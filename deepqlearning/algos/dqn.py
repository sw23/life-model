# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Deep Q-Network with dueling heads, double-Q targets, prioritized replay, and n-step returns.

Off-policy: collected transitions stay useful after the policy changes, so :meth:`DQNAgent.update`
takes a gradient step on every collection step once the replay buffer has warmed up.

Per-environment n-step accumulation lives inside :meth:`DQNAgent.observe`, keyed by the
:attr:`~deepqlearning.algos.base.StepBatch.env_ids` of the incoming batch, so a trainer only has to
report what happened and never has to know that the algorithm buffers multi-step returns.
"""

import json
import os
import pickle
import random
from typing import Dict, Optional, Sequence

import numpy as np
import torch
import torch.optim as optim

from .base import ActResult, Algorithm, StepBatch, legal_mask_tensor
from .networks import build_q_network
from .replay import Experience, NStepAccumulator, PrioritizedReplayBuffer, ReplayBuffer

# Identifies the checkpoint format: reward shaping, observation layout, action space, and tensor
# layout. A checkpoint whose version differs from the code refuses to load rather than silently
# misaligning its weights against a different observation/action space (see ``load``).
MODEL_VERSION = 4


class DQNAgent(Algorithm):
    """Deep Q-Network agent over a discrete action space with optional legal-action masking."""

    on_policy = False
    name = "dqn"

    @staticmethod
    def default_config() -> Dict:
        return {
            "learning_rate": 1e-4,
            "batch_size": 64,
            "gamma": 0.99,
            "epsilon_start": 1.0,
            "epsilon_end": 0.01,
            # Fraction of training over which epsilon decays linearly to its floor. Decaying
            # against overall progress (not per gradient step) keeps exploration alive.
            "epsilon_decay_fraction": 0.6,
            "target_update_freq": 100,
            "replay_buffer_size": 100000,
            "min_replay_size": 1000,
            "hidden_sizes": [512, 256, 128],
            "use_dueling": True,
            "use_double_dqn": True,
            # Prioritized experience replay. When True the
            # agent uses a PrioritizedReplayBuffer with proportional sampling and IS-weight
            # correction; alpha controls prioritization strength, beta (annealed to 1 over
            # per_beta_steps gradient steps) controls the IS correction.
            "use_prioritized_replay": True,
            "per_alpha": 0.6,
            "per_beta_start": 0.4,
            "per_beta_steps": 100000,
            # N-step returns. n_step=1 recovers vanilla 1-step DQN.
            "n_step": 3,
            # Observation-layout version this checkpoint is tied to. An environment that versions
            # its observation layout (the financial env) passes its OBS_VERSION so a checkpoint
            # trained against a different layout is refused; ``None`` disables the check for
            # environments that have no such notion.
            "obs_version": None,
            # Emit the one-time architecture summary when the agent is constructed.
            "verbose": True,
        }

    def __init__(self, obs_space, action_space, config: Optional[Dict] = None):
        super().__init__(obs_space, action_space, config)

        self.obs_version = self.config["obs_version"]

        # Initialize networks
        dueling = bool(self.config["use_dueling"])
        hidden_sizes = self.config["hidden_sizes"]
        self.q_network = build_q_network(self.obs_space, self.action_size, hidden_sizes, dueling).to(self.device)
        self.target_network = build_q_network(self.obs_space, self.action_size, hidden_sizes, dueling).to(self.device)

        # Copy weights to target network; the target net is never trained, so keep it in eval mode
        # permanently (its dropout must not perturb bootstrapped targets).
        self.target_network.load_state_dict(self.q_network.state_dict())
        self.target_network.eval()

        # Optimizer
        self.optimizer = optim.Adam(self.q_network.parameters(), lr=self.config["learning_rate"])

        # Replay buffer: prioritized or uniform.
        self.use_per = bool(self.config["use_prioritized_replay"])
        if self.use_per:
            self.replay_buffer = PrioritizedReplayBuffer(
                self.config["replay_buffer_size"], alpha=self.config["per_alpha"]
            )
        else:
            self.replay_buffer = ReplayBuffer(self.config["replay_buffer_size"])

        # Training state
        self.epsilon = self.config["epsilon_start"]
        # One n-step accumulator per environment stream, created on first sight of that stream.
        self._accumulators: Dict[int, NStepAccumulator] = {}

        if self.config["verbose"]:
            print(f"Initialized DQN Agent on {self.device}")
            print(f"Network architecture: {self.config['hidden_sizes']}")
            print(f"Using Dueling DQN: {self.config['use_dueling']}")
            print(f"Using Double DQN: {self.config['use_double_dqn']}")
            print(f"Using Prioritized Replay: {self.use_per}, n-step: {self.config['n_step']}")

    def _per_beta(self) -> float:
        """Current PER importance-sampling exponent, annealed from ``per_beta_start`` to 1.0."""
        start = self.config["per_beta_start"]
        frac = min(1.0, self.steps_done / max(1, self.config["per_beta_steps"]))
        return start + (1.0 - start) * frac

    def _legal_mask(self, legal_actions_batch) -> torch.Tensor:
        """Additive mask (0 for legal, -inf for illegal) for a batch of legal-action lists."""
        return legal_mask_tensor(legal_actions_batch, self.action_size, self.device)

    # --- acting ------------------------------------------------------------------------------

    def act(self, obs: np.ndarray, legal: Sequence[Sequence[int]], training: bool = True) -> ActResult:
        """Epsilon-greedy action selection over the legal actions, for a batch of observations.

        Each row independently explores with probability ``epsilon`` (a random legal action) or
        exploits (masked greedy). One batched forward pass serves all rows, computed in eval mode
        so dropout cannot make the greedy choice nondeterministic.
        """
        was_training = self.q_network.training
        self.q_network.eval()
        with torch.no_grad():
            state_tensor = torch.tensor(np.asarray(obs), dtype=torch.float32).to(self.device)
            q_values = self.q_network(state_tensor) + self._legal_mask(legal)
            greedy = q_values.argmax(dim=1).tolist()
        if was_training:
            self.q_network.train()

        actions = []
        for i, row in enumerate(legal):
            if training and len(row) and random.random() < self.epsilon:
                actions.append(int(random.choice(list(row))))
            else:
                actions.append(int(greedy[i]))
        return ActResult(np.asarray(actions, dtype=np.int64))

    # --- storing -----------------------------------------------------------------------------

    def store_experience(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
        legal_actions,
        next_legal_actions,
        discount: Optional[float] = None,
    ):
        """Store a single transition directly in the replay buffer, bypassing n-step accumulation.

        ``discount`` is the discount to apply to the bootstrapped next-state value (``gamma`` for a
        1-step transition, ``gamma**n`` for n-step). ``None`` (the default) is interpreted as plain
        ``gamma`` at training time.
        """
        self.replay_buffer.push(
            state, action, float(reward), next_state, done, list(legal_actions), list(next_legal_actions), discount
        )

    def store_prebuilt(self, experience: Experience):
        """Store an already-built :class:`Experience` (e.g. from :class:`NStepAccumulator`)."""
        self.replay_buffer.push(*experience)

    def observe(self, batch: StepBatch) -> None:
        """Route each row through its environment stream's n-step accumulator into replay."""
        gamma = self.config["gamma"]
        n_step = self.config.get("n_step", 1)
        for i in range(len(batch)):
            env_id = int(batch.env_ids[i])
            accumulator = self._accumulators.get(env_id)
            if accumulator is None:
                accumulator = self._accumulators[env_id] = NStepAccumulator(n_step, gamma)
            done = bool(batch.terminated[i] or batch.truncated[i])
            for experience in accumulator.push(
                batch.obs[i],
                int(batch.actions[i]),
                float(batch.rewards[i]),
                batch.legal[i],
                batch.next_obs[i],
                batch.next_legal[i],
                done,
            ):
                self.store_prebuilt(experience)

    # --- learning ----------------------------------------------------------------------------

    def update(self) -> Optional[Dict[str, float]]:
        """One gradient step on a replay batch, or ``None`` while the buffer is still warming up.

        Supports prioritized replay (importance-sampling-weighted loss + priority updates from the
        TD errors) and per-transition discounts (``gamma**n`` for n-step returns). A ``None``
        discount is treated as plain ``gamma``.
        """

        if len(self.replay_buffer) < self.config["min_replay_size"]:
            return None

        # Sample batch (prioritized returns indices + IS weights; uniform returns a plain list).
        if self.use_per:
            experiences, indices, is_weights = self.replay_buffer.sample(
                self.config["batch_size"], beta=self._per_beta()
            )
            weights = torch.tensor(is_weights, dtype=torch.float32, device=self.device).unsqueeze(1)
        else:
            experiences = self.replay_buffer.sample(self.config["batch_size"])
            indices, weights = None, None
        batch = Experience(*zip(*experiences))

        # Convert to tensors
        gamma = self.config["gamma"]
        discounts = [gamma if d is None else float(d) for d in batch.discount]
        state_batch = torch.tensor(np.array(batch.state), dtype=torch.float32).to(self.device)
        action_batch = torch.tensor(batch.action, dtype=torch.long).to(self.device)
        reward_batch = torch.tensor(batch.reward, dtype=torch.float32).to(self.device)
        discount_batch = torch.tensor(discounts, dtype=torch.float32).to(self.device)
        next_state_batch = torch.tensor(np.array(batch.next_state), dtype=torch.float32).to(self.device)
        done_batch = torch.tensor([bool(d) for d in batch.done], dtype=torch.bool).to(self.device)
        next_legal_mask = self._legal_mask(list(batch.next_legal_actions))

        # Current Q values (train mode so dropout regularizes the online network)
        self.q_network.train()
        current_q_values = self.q_network(state_batch).gather(1, action_batch.unsqueeze(1))

        # Next Q values (targets computed deterministically and masked to legal next actions)
        with torch.no_grad():
            if self.config["use_double_dqn"]:
                # Double DQN: online net selects the (legal) action, target net evaluates it.
                was_training = self.q_network.training
                self.q_network.eval()
                online_next_q = self.q_network(next_state_batch) + next_legal_mask
                if was_training:
                    self.q_network.train()
                next_actions = online_next_q.argmax(1)
                target_next_q = self.target_network(next_state_batch) + next_legal_mask
                next_q_values = target_next_q.gather(1, next_actions.unsqueeze(1))
            else:
                # Standard DQN: max over legal next actions using the target net.
                target_next_q = self.target_network(next_state_batch) + next_legal_mask
                next_q_values = target_next_q.max(1)[0].unsqueeze(1)

            # Target uses the per-transition discount (gamma**n for n-step).
            target_q_values = reward_batch.unsqueeze(1)
            target_q_values = target_q_values + discount_batch.unsqueeze(1) * next_q_values * ~done_batch.unsqueeze(1)

        # Loss: TD error, IS-weighted under PER.
        td_errors = current_q_values - target_q_values
        if self.use_per:
            loss = (weights * td_errors.pow(2)).mean()
        else:
            loss = td_errors.pow(2).mean()

        # Optimize
        self.optimizer.zero_grad()
        loss.backward()

        # Gradient clipping
        torch.nn.utils.clip_grad_norm_(self.q_network.parameters(), 1.0)

        self.optimizer.step()

        # Refresh priorities from the fresh TD errors.
        if self.use_per:
            self.replay_buffer.update_priorities(indices, td_errors.detach().squeeze(1).cpu().numpy())

        # Update target network
        if self.steps_done % self.config["target_update_freq"] == 0:
            self.target_network.load_state_dict(self.q_network.state_dict())
            self.target_network.eval()

        self.steps_done += 1
        loss_value = float(loss.item())
        self.training_losses.append(loss_value)

        return {"loss": loss_value}

    def anneal(self, progress: float) -> None:
        """Linearly decay epsilon over the first ``epsilon_decay_fraction`` of training.

        ``progress`` is overall training progress in ``[0, 1]`` (fraction of the episode count or
        of the env-step budget), so exploration lasts across training rather than collapsing in the
        first few episodes.
        """
        start = self.config["epsilon_start"]
        end = self.config["epsilon_end"]
        decay = max(1e-9, self.config["epsilon_decay_fraction"])
        self.epsilon = start + (end - start) * min(1.0, progress / decay)

    # --- checkpointing -----------------------------------------------------------------------

    def save(self, filepath) -> None:
        """Save the model.

        The ``.pt`` file holds only tensors and simple scalars so it can be reloaded with
        ``torch.load(..., weights_only=True)`` under modern PyTorch defaults. Non-tensor training
        history (losses, rewards, config) is written to a JSON sidecar next to it.
        """
        filepath = str(filepath)
        checkpoint = {
            "model_version": MODEL_VERSION,
            "obs_version": self.obs_version,
            "q_network_state_dict": self.q_network.state_dict(),
            "target_network_state_dict": self.target_network.state_dict(),
            "optimizer_state_dict": self.optimizer.state_dict(),
            "epsilon": float(self.epsilon),
            "steps_done": int(self.steps_done),
        }
        torch.save(checkpoint, filepath)

        history = {
            "model_version": MODEL_VERSION,
            "obs_version": self.obs_version,
            "config": self.config,
            "training_losses": [float(x) for x in self.training_losses],
            "episode_rewards": [float(x) for x in self.episode_rewards],
        }
        with open(self.history_path(filepath), "w") as f:
            json.dump(history, f)

        print(f"Model saved to {filepath}")

    def load(self, filepath) -> None:
        """Load the model saved by :meth:`save` (tensor-only ``.pt`` + JSON sidecar).

        Checkpoints written before the tensor-only split are pickled Python objects; they are
        accepted only if their state-dict shapes still match the current network, since they carry
        no version metadata to check.

        Raises:
            ValueError: If the checkpoint's ``model_version`` or ``obs_version`` does not match
                the current code. A checkpoint's weights are tied to a specific observation layout
                and action space, so a version mismatch would silently misalign them — failing
                loudly here is the guard.
        """
        filepath = str(filepath)
        if not os.path.exists(filepath):
            print(f"Model file {filepath} not found")
            return

        try:
            checkpoint = torch.load(filepath, map_location=self.device, weights_only=True)
            legacy_checkpoint = False
        except pickle.UnpicklingError:
            checkpoint = torch.load(filepath, map_location=self.device, weights_only=False)
            legacy_checkpoint = True

        version = checkpoint.get("model_version")
        obs_version = checkpoint.get("obs_version")
        if legacy_checkpoint:
            current_q = self.q_network.state_dict()
            loaded_q = checkpoint.get("q_network_state_dict", {})
            shape_mismatch = any(
                key not in current_q or current_q[key].shape != value.shape for key, value in loaded_q.items()
            ) or len(current_q) != len(loaded_q)
            if shape_mismatch:
                raise ValueError(
                    f"Legacy checkpoint {filepath!r} does not match the current network layout and cannot be loaded. "
                    "Retrain, or check out the code version that produced the checkpoint."
                )
            print(
                f"Loading legacy checkpoint {filepath} without version metadata; "
                "state-dict shapes match the current model."
            )
        elif version != MODEL_VERSION or (self.obs_version is not None and obs_version != self.obs_version):
            raise ValueError(
                f"Checkpoint {filepath!r} has model_version={version}, obs_version={obs_version}, but this "
                f"code is model_version={MODEL_VERSION}, obs_version={self.obs_version}. A checkpoint is tied to a "
                "specific observation layout and action space, so a mismatched checkpoint cannot be loaded — "
                "retrain, or check out the code version that produced the checkpoint."
            )

        self.q_network.load_state_dict(checkpoint["q_network_state_dict"])
        self.target_network.load_state_dict(checkpoint["target_network_state_dict"])
        self.target_network.eval()
        self.optimizer.load_state_dict(checkpoint["optimizer_state_dict"])

        self.epsilon = float(checkpoint.get("epsilon", self.config["epsilon_end"]))
        self.steps_done = int(checkpoint.get("steps_done", 0))

        history_path = self.history_path(filepath)
        if os.path.exists(history_path):
            with open(history_path) as f:
                history = json.load(f)
            self.training_losses = history.get("training_losses", [])
            self.episode_rewards = history.get("episode_rewards", [])
        elif legacy_checkpoint:
            self.training_losses = checkpoint.get("training_losses", [])
            self.episode_rewards = checkpoint.get("episode_rewards", [])

        print(f"Model loaded from {filepath}")
        print(f"Training steps: {self.steps_done}, Epsilon: {self.epsilon:.4f}")
