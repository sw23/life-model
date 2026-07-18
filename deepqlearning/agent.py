# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import json
import os
import random
from collections import deque, namedtuple
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from environment import OBS_VERSION, FinancialLifeEnv

# Identifies the checkpoint format: reward shaping, observation layout, action space, and tensor
# layout. A checkpoint whose version differs from the code refuses to load rather than silently
# misaligning its weights against a different observation/action space (see ``load_model``).
MODEL_VERSION = 4

# Experience tuple for the replay buffer. ``legal_actions`` is the legal action list for ``state``
# and ``next_legal_actions`` is the list for ``next_state`` (needed to mask bootstrapped targets).
# ``reward`` is the (possibly n-step) discounted reward and ``discount`` is the discount applied to
# the bootstrapped next-state value: ``gamma`` for a 1-step transition, ``gamma**n`` for an n-step
# one. ``discount`` defaults to ``None`` (interpreted as plain ``gamma``) so callers/tests that
# build 7-field experiences keep working.
Experience = namedtuple(
    "Experience",
    ["state", "action", "reward", "next_state", "done", "legal_actions", "next_legal_actions", "discount"],
)
Experience.__new__.__defaults__ = (None,)


class DQNNetwork(nn.Module):
    """Deep Q-Network for financial decision making"""

    def __init__(self, state_size: int, action_size: int, hidden_sizes: Optional[List[int]] = None):
        super(DQNNetwork, self).__init__()
        if hidden_sizes is None:
            hidden_sizes = [512, 256, 128]

        self.state_size = state_size
        self.action_size = action_size

        # Build the network
        layers = []
        input_size = state_size

        for hidden_size in hidden_sizes:
            layers.append(nn.Linear(input_size, hidden_size))
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(0.1))
            input_size = hidden_size

        # Output layer
        layers.append(nn.Linear(input_size, action_size))

        self.network = nn.Sequential(*layers)

        # Initialize weights
        self.apply(self._init_weights)

    def _init_weights(self, module):
        """Initialize network weights"""
        if isinstance(module, nn.Linear):
            torch.nn.init.xavier_uniform_(module.weight)
            module.bias.data.fill_(0.01)

    def forward(self, state):
        """Forward pass through the network"""
        return self.network(state)


class DuelingDQN(nn.Module):
    """Dueling DQN architecture for better value estimation"""

    def __init__(self, state_size: int, action_size: int, hidden_sizes: Optional[List[int]] = None):
        super(DuelingDQN, self).__init__()
        if hidden_sizes is None:
            hidden_sizes = [512, 256]

        self.state_size = state_size
        self.action_size = action_size

        # Shared feature extraction layers
        self.feature_layers = nn.Sequential(
            nn.Linear(state_size, hidden_sizes[0]),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_sizes[0], hidden_sizes[1]),
            nn.ReLU(),
            nn.Dropout(0.1),
        )

        # Value stream
        self.value_stream = nn.Sequential(nn.Linear(hidden_sizes[1], 128), nn.ReLU(), nn.Linear(128, 1))

        # Advantage stream
        self.advantage_stream = nn.Sequential(nn.Linear(hidden_sizes[1], 128), nn.ReLU(), nn.Linear(128, action_size))

        self.apply(self._init_weights)

    def _init_weights(self, module):
        if isinstance(module, nn.Linear):
            torch.nn.init.xavier_uniform_(module.weight)
            module.bias.data.fill_(0.01)

    def forward(self, state):
        features = self.feature_layers(state)

        value = self.value_stream(features)
        advantage = self.advantage_stream(features)

        # Combine value and advantage: Q(s,a) = V(s) + A(s,a) - mean(A(s,a))
        q_value = value + advantage - advantage.mean(dim=1, keepdim=True)

        return q_value


class ReplayBuffer:
    """Uniform experience replay buffer for training stability."""

    def __init__(self, capacity: int):
        self.buffer = deque(maxlen=capacity)

    def push(self, *args):
        """Add experience to buffer"""
        self.buffer.append(Experience(*args))

    def sample(self, batch_size: int) -> List[Experience]:
        """Sample random batch from buffer"""
        return random.sample(self.buffer, batch_size)

    def __len__(self):
        return len(self.buffer)


class PrioritizedReplayBuffer:
    """Proportional prioritized experience replay (Schaul et al. 2016).

    Transitions are sampled with probability proportional to ``priority**alpha``
    (priority = last-seen TD error), and the resulting bias is corrected with importance-sampling
    weights ``(N * P(i))**(-beta)`` normalized by their max. New transitions enter at the current
    max priority so they are seen at least once; :meth:`update_priorities` refreshes priorities
    after each gradient step.
    """

    def __init__(self, capacity: int, alpha: float = 0.6, epsilon: float = 1e-6):
        self.capacity = capacity
        self.alpha = alpha
        self.epsilon = epsilon
        self.buffer: List[Experience] = []
        self.priorities = np.zeros(capacity, dtype=np.float64)
        self.pos = 0

    def push(self, *args):
        max_prio = self.priorities[: len(self.buffer)].max() if self.buffer else 1.0
        if len(self.buffer) < self.capacity:
            self.buffer.append(Experience(*args))
        else:
            self.buffer[self.pos] = Experience(*args)
        self.priorities[self.pos] = max_prio
        self.pos = (self.pos + 1) % self.capacity

    def sample(self, batch_size: int, beta: float = 0.4):
        """Return ``(experiences, indices, is_weights)``."""
        size = len(self.buffer)
        prios = self.priorities[:size] ** self.alpha
        probs = prios / prios.sum()
        indices = np.random.choice(size, batch_size, p=probs)
        experiences = [self.buffer[i] for i in indices]
        weights = (size * probs[indices]) ** (-beta)
        weights = weights / weights.max()
        return experiences, indices, weights.astype(np.float32)

    def update_priorities(self, indices: np.ndarray, td_errors: np.ndarray):
        for idx, err in zip(indices, td_errors):
            self.priorities[idx] = abs(float(err)) + self.epsilon

    def __len__(self):
        return len(self.buffer)


class NStepAccumulator:
    """Builds n-step transitions for a single episode stream.

    Push each ``(state, action, reward, legal_actions)`` as it happens; :meth:`push` emits the
    finalized n-step transitions that are ready (their ``next_state`` is now known). On episode end,
    :meth:`flush` emits the truncated-horizon transitions for the tail of the episode. Each emitted
    transition carries ``reward = sum_{k} gamma**k r_{t+k}`` and ``discount = gamma**steps`` so the
    learner bootstraps with the correct horizon.
    """

    def __init__(self, n_step: int, gamma: float):
        self.n_step = max(1, int(n_step))
        self.gamma = gamma
        self._items: deque = deque()

    def _make(self, upto: int, next_state, next_legal_actions, done) -> Experience:
        """Build the transition starting at the oldest item, spanning ``upto`` rewards."""
        state, action, _, legal = self._items[0]
        reward = 0.0
        for k in range(upto):
            reward += (self.gamma**k) * self._items[k][2]
        discount = self.gamma**upto
        return Experience(state, action, float(reward), next_state, done, legal, next_legal_actions, discount)

    def push(self, state, action, reward, legal_actions, next_state, next_legal_actions, done):
        """Record a step and return a list of finalized n-step transitions (possibly empty)."""
        self._items.append((state, action, float(reward), list(legal_actions)))
        emitted: List[Experience] = []
        if done:
            emitted.extend(self.flush(next_state, next_legal_actions))
        elif len(self._items) >= self.n_step:
            emitted.append(self._make(self.n_step, next_state, next_legal_actions, done=False))
            self._items.popleft()
        return emitted

    def flush(self, next_state, next_legal_actions) -> List[Experience]:
        """Emit truncated transitions for every remaining start index at episode end."""
        emitted: List[Experience] = []
        while self._items:
            emitted.append(self._make(len(self._items), next_state, next_legal_actions, done=True))
            self._items.popleft()
        return emitted


class FinancialDQNAgent:
    """Deep Q-Network agent for financial decision making"""

    def __init__(self, state_size: int, action_size: int, config: Optional[Dict] = None):

        # Default configuration
        self.config = {
            "learning_rate": 1e-4,
            "batch_size": 64,
            "gamma": 0.99,
            "epsilon_start": 1.0,
            "epsilon_end": 0.01,
            # Fraction of total episodes over which epsilon decays linearly to its floor. Decaying
            # per-episode (not per gradient step) keeps exploration alive across training.
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
        }

        if config:
            self.config.update(config)

        self.state_size = state_size
        self.action_size = action_size
        self.device = self._select_device(self.config.get("device"))

        # Initialize networks
        if self.config["use_dueling"]:
            self.q_network = DuelingDQN(state_size, action_size, self.config["hidden_sizes"]).to(self.device)
            self.target_network = DuelingDQN(state_size, action_size, self.config["hidden_sizes"]).to(self.device)
        else:
            self.q_network = DQNNetwork(state_size, action_size, self.config["hidden_sizes"]).to(self.device)
            self.target_network = DQNNetwork(state_size, action_size, self.config["hidden_sizes"]).to(self.device)

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
        self.steps_done = 0
        self.training_losses = []
        self.episode_rewards = []

        print(f"Initialized DQN Agent on {self.device}")
        print(f"Network architecture: {self.config['hidden_sizes']}")
        print(f"Using Dueling DQN: {self.config['use_dueling']}")
        print(f"Using Double DQN: {self.config['use_double_dqn']}")
        print(f"Using Prioritized Replay: {self.use_per}, n-step: {self.config['n_step']}")

    @staticmethod
    def _select_device(preference: Optional[str] = None) -> torch.device:
        """Pick a compute device: CUDA when available, otherwise CPU. Apple MPS (Metal) is used
        only when explicitly requested (``preference="mps"``).

        ``preference`` may force a specific backend (``"cuda"``, ``"mps"``, ``"cpu"``); an
        unavailable choice falls back to CPU. MPS is opt-in (never auto-selected) because for this
        workload the per-step cost is dominated by the CPU-bound ``life_model`` simulation and the
        network is small, so MPS typically performs worse than CPU for single-env training — the
        vectorized trainer's environment parallelism is the larger lever.
        """
        if preference:
            pref = preference.lower()
            if pref == "cuda" and torch.cuda.is_available():
                return torch.device("cuda")
            if pref == "mps" and torch.backends.mps.is_available():
                return torch.device("mps")
            return torch.device("cpu")
        if torch.cuda.is_available():
            return torch.device("cuda")
        return torch.device("cpu")

    def _per_beta(self) -> float:
        """Current PER importance-sampling exponent, annealed from ``per_beta_start`` to 1.0."""
        start = self.config["per_beta_start"]
        frac = min(1.0, self.steps_done / max(1, self.config["per_beta_steps"]))
        return start + (1.0 - start) * frac

    def _legal_mask(self, legal_actions_batch: List[List[int]]) -> torch.Tensor:
        """Build an additive mask (0 for legal, -inf for illegal) for a batch of legal-action lists."""
        mask = torch.full((len(legal_actions_batch), self.action_size), float("-inf"), device=self.device)
        for i, legal in enumerate(legal_actions_batch):
            if legal:
                mask[i, legal] = 0.0
            else:
                # No legal actions recorded: don't mask anything (avoids an all -inf row).
                mask[i, :] = 0.0
        return mask

    def select_action(self, state: np.ndarray, legal_actions: List[int], training: bool = True) -> int:
        """Select an action using an epsilon-greedy policy over the legal actions."""

        if training and random.random() < self.epsilon:
            # Random action from legal actions
            return random.choice(legal_actions)

        # Greedy action, computed deterministically (eval mode disables dropout).
        was_training = self.q_network.training
        self.q_network.eval()
        with torch.no_grad():
            state_tensor = torch.tensor(state, dtype=torch.float32).unsqueeze(0).to(self.device)
            q_values = self.q_network(state_tensor)
            masked_q_values = q_values + self._legal_mask([legal_actions])
            action = int(masked_q_values.argmax().item())
        if was_training:
            self.q_network.train()
        return action

    def select_actions_batch(
        self, states: np.ndarray, legal_actions_batch: List[List[int]], training: bool = True
    ) -> List[int]:
        """Epsilon-greedy action selection for a batch of states (vectorized collection).

        Each row independently explores with probability ``epsilon`` (a random legal action) or
        exploits (masked greedy). One batched forward pass serves all envs.
        """
        n = len(legal_actions_batch)
        was_training = self.q_network.training
        self.q_network.eval()
        with torch.no_grad():
            state_tensor = torch.tensor(np.asarray(states), dtype=torch.float32).to(self.device)
            q_values = self.q_network(state_tensor) + self._legal_mask(legal_actions_batch)
            greedy = q_values.argmax(dim=1).tolist()
        if was_training:
            self.q_network.train()

        actions: List[int] = []
        for i in range(n):
            legal = legal_actions_batch[i]
            if training and legal and random.random() < self.epsilon:
                actions.append(random.choice(legal))
            else:
                actions.append(int(greedy[i]))
        return actions

    def store_experience(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
        legal_actions: List[int],
        next_legal_actions: List[int],
        discount: Optional[float] = None,
    ):
        """Store an experience in the replay buffer.

        ``discount`` is the discount to apply to the bootstrapped next-state value (``gamma`` for a
        1-step transition, ``gamma**n`` for n-step). ``None`` (the default) is interpreted as plain
        ``gamma`` at training time, so existing 1-step callers are unaffected.
        """
        self.replay_buffer.push(
            state, action, float(reward), next_state, done, list(legal_actions), list(next_legal_actions), discount
        )

    def store_prebuilt(self, experience: Experience):
        """Store an already-built :class:`Experience` (e.g. from :class:`NStepAccumulator`)."""
        self.replay_buffer.push(*experience)

    def train(self) -> Optional[float]:
        """Train the agent on a batch of experiences.

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

        return loss_value

    def update_epsilon(self, episode: int, num_episodes: int):
        """Linearly decay epsilon over the first ``epsilon_decay_fraction`` of episodes.

        Called once per episode (not per gradient step) so exploration lasts across training
        rather than collapsing in the first few episodes.
        """
        start = self.config["epsilon_start"]
        end = self.config["epsilon_end"]
        decay_episodes = max(1, int(num_episodes * self.config["epsilon_decay_fraction"]))
        progress = min(1.0, episode / decay_episodes)
        self.epsilon = start + (end - start) * progress

    def _history_path(self, filepath: str) -> str:
        """Path of the JSON sidecar holding non-tensor training history for ``filepath``."""
        return os.path.splitext(filepath)[0] + ".history.json"

    def save_model(self, filepath: str):
        """Save the model.

        The ``.pt`` file holds only tensors and simple scalars so it can be reloaded with
        ``torch.load(..., weights_only=True)`` under modern PyTorch defaults. Non-tensor training
        history (losses, rewards, config) is written to a JSON sidecar next to it.
        """
        checkpoint = {
            "model_version": MODEL_VERSION,
            "obs_version": OBS_VERSION,
            "q_network_state_dict": self.q_network.state_dict(),
            "target_network_state_dict": self.target_network.state_dict(),
            "optimizer_state_dict": self.optimizer.state_dict(),
            "epsilon": float(self.epsilon),
            "steps_done": int(self.steps_done),
        }
        torch.save(checkpoint, filepath)

        history = {
            "model_version": MODEL_VERSION,
            "obs_version": OBS_VERSION,
            "config": self.config,
            "training_losses": [float(x) for x in self.training_losses],
            "episode_rewards": [float(x) for x in self.episode_rewards],
        }
        with open(self._history_path(filepath), "w") as f:
            json.dump(history, f)

        print(f"Model saved to {filepath}")

    def load_model(self, filepath: str):
        """Load the model saved by :meth:`save_model` (tensor-only ``.pt`` + JSON sidecar).

        Raises:
            ValueError: If the checkpoint's ``model_version`` or ``obs_version`` does not match
                the current code. A checkpoint's weights are tied to a specific observation layout
                and action space, so a version mismatch would silently misalign them — failing
                loudly here is the guard.
        """
        if not os.path.exists(filepath):
            print(f"Model file {filepath} not found")
            return

        checkpoint = torch.load(filepath, map_location=self.device, weights_only=True)

        version = checkpoint.get("model_version")
        obs_version = checkpoint.get("obs_version")
        if version != MODEL_VERSION or obs_version != OBS_VERSION:
            raise ValueError(
                f"Checkpoint {filepath!r} has model_version={version}, obs_version={obs_version}, but this "
                f"code is model_version={MODEL_VERSION}, obs_version={OBS_VERSION}. A checkpoint is tied to a "
                "specific observation layout and action space, so a mismatched checkpoint cannot be loaded — "
                "retrain, or check out the code version that produced the checkpoint."
            )

        self.q_network.load_state_dict(checkpoint["q_network_state_dict"])
        self.target_network.load_state_dict(checkpoint["target_network_state_dict"])
        self.target_network.eval()
        self.optimizer.load_state_dict(checkpoint["optimizer_state_dict"])

        self.epsilon = float(checkpoint.get("epsilon", self.config["epsilon_end"]))
        self.steps_done = int(checkpoint.get("steps_done", 0))

        history_path = self._history_path(filepath)
        if os.path.exists(history_path):
            with open(history_path) as f:
                history = json.load(f)
            self.training_losses = history.get("training_losses", [])
            self.episode_rewards = history.get("episode_rewards", [])

        print(f"Model loaded from {filepath}")
        print(f"Training steps: {self.steps_done}, Epsilon: {self.epsilon:.4f}")


@dataclass
class RolloutResult:
    """Outcome of a single episode rollout."""

    total_reward: float
    steps: int
    terminated: bool
    truncated: bool
    final_info: Dict
    trajectory: List[Dict] = field(default_factory=list)


def rollout(
    env: FinancialLifeEnv,
    agent: FinancialDQNAgent,
    training: bool = False,
    seed: Optional[int] = None,
    collect_trajectory: bool = False,
) -> RolloutResult:
    """Run one episode. The single episode loop used by training, evaluation, and analysis.

    The action space is fully discrete: the policy's chosen index carries both the action
    type and the amount bucket, so there is no separate amount to fill in. When
    ``training`` is True, experiences are stored and a gradient step is taken each step.
    """
    state, info = env.reset(seed=seed)
    total_reward = 0.0
    steps = 0
    terminated = False
    truncated = False
    trajectory: List[Dict] = []
    # N-step accumulator for the training path. n_step=1 recovers 1-step DQN.
    nstep = NStepAccumulator(agent.config.get("n_step", 1), agent.config["gamma"]) if training else None

    while True:
        legal_actions = env.get_legal_actions()
        action = agent.select_action(state, legal_actions, training=training)

        next_state, reward, terminated, truncated, info = env.step(action)
        done = terminated or truncated
        total_reward += reward

        if training:
            next_legal_actions = env.get_legal_actions()
            for exp in nstep.push(state, action, reward, legal_actions, next_state, next_legal_actions, done):
                agent.store_prebuilt(exp)
            agent.train()

        if collect_trajectory:
            trajectory.append(
                {
                    "age": info.get("age"),
                    "net_worth": info.get("net_worth"),
                    "bank_balance": info.get("bank_balance"),
                    "action_type": info.get("action_type"),
                    "action_amount": info.get("action_amount"),
                }
            )

        state = next_state
        steps += 1
        if done:
            break

    return RolloutResult(float(total_reward), steps, bool(terminated), bool(truncated), info, trajectory)


class FinancialDQNTrainer:
    """Trainer for the financial DQN agent"""

    def __init__(self, env: FinancialLifeEnv, agent: FinancialDQNAgent, config: Optional[Dict] = None):

        self.env = env
        self.agent = agent

        # Training configuration
        self.config = {
            "num_episodes": 1000,
            "save_freq": 100,
            "eval_freq": 50,
            "eval_episodes": 10,
            "print_freq": 10,
            "model_save_path": "financial_dqn_model.pt",
            # Base seed for training episodes; each episode uses base_seed + episode for
            # reproducibility. Set to None for nondeterministic training.
            "base_seed": None,
        }

        if config:
            self.config.update(config)

        self.episode_rewards = []
        self.eval_rewards = []
        self.training_metrics = {"avg_reward": [], "avg_net_worth": [], "success_rate": [], "avg_retirement_age": []}

    def _episode_seed(self, episode: int) -> Optional[int]:
        base = self.config.get("base_seed")
        return None if base is None else base + episode

    def train(self):
        """Train the agent"""
        num_episodes = self.config["num_episodes"]
        print(f"Starting training for {num_episodes} episodes")
        print(f"Environment: {type(self.env).__name__}")
        print(f"Action space size: {self.env.action_space.n}")
        print(f"State space size: {self.env.observation_space.shape[0]}")

        for episode in range(num_episodes):
            result = rollout(self.env, self.agent, training=True, seed=self._episode_seed(episode))
            self.episode_rewards.append(result.total_reward)
            self.agent.episode_rewards.append(result.total_reward)

            # Decay exploration once per episode
            self.agent.update_epsilon(episode, num_episodes)

            # Print progress
            if episode % self.config["print_freq"] == 0:
                avg_reward = np.mean(self.episode_rewards[-100:])
                print(
                    f"Episode {episode:4d}, "
                    f"Reward: {result.total_reward:8.2f}, "
                    f"Avg Reward (100): {avg_reward:8.2f}, "
                    f"Epsilon: {self.agent.epsilon:.4f}"
                )

            # Evaluate agent
            if episode % self.config["eval_freq"] == 0 and episode > 0:
                eval_reward = self._evaluate_agent()
                self.eval_rewards.append(eval_reward)
                print(f"Evaluation at episode {episode}: {eval_reward:.2f}")

            # Save model
            if episode % self.config["save_freq"] == 0 and episode > 0:
                self.agent.save_model(self.config["model_save_path"])

        # Final save
        self.agent.save_model(self.config["model_save_path"])
        print("Training completed!")

    def _evaluate_agent(self) -> float:
        """Evaluate agent performance (greedy policy, no exploration/training)."""
        eval_rewards = []
        natural_deaths = 0
        bankruptcies = 0
        successful_completions = 0
        ages_at_end = []

        for i in range(self.config["eval_episodes"]):
            result = rollout(self.env, self.agent, training=False, seed=self._episode_seed(1_000_000 + i))
            eval_rewards.append(result.total_reward)

            if result.final_info.get("died_from_natural_causes"):
                natural_deaths += 1
            elif result.final_info.get("net_worth", 0) < self.env.BANKRUPTCY_THRESHOLD:
                bankruptcies += 1
            else:
                # Reached the horizon or maximum age while solvent.
                successful_completions += 1

            ages_at_end.append(result.final_info.get("age", 0))

        avg_age = np.mean(ages_at_end) if ages_at_end else 0.0
        print(
            f"  Eval Summary: Natural deaths: {natural_deaths}/{self.config['eval_episodes']}, "
            f"Bankruptcies: {bankruptcies}/{self.config['eval_episodes']}, "
            f"Successful completions: {successful_completions}/{self.config['eval_episodes']}, "
            f"Avg age at end: {avg_age:.1f}"
        )

        return float(np.mean(eval_rewards))

    def get_training_stats(self) -> Dict:
        """Get training statistics"""
        return {
            "episode_rewards": self.episode_rewards,
            "eval_rewards": self.eval_rewards,
            "training_losses": self.agent.training_losses,
            "total_episodes": len(self.episode_rewards),
            "total_steps": self.agent.steps_done,
        }
