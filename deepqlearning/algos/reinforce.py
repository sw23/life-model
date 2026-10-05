# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""REINFORCE: Monte-Carlo policy gradient.

The simplest policy-gradient method and the useful floor to compare PPO against. The gradient is
``E[ grad log pi(a|s) * (G_t - b(s)) ]`` where ``G_t`` is the discounted return from step ``t`` to
the end of the episode — so nothing can be learned until an episode finishes, and the update
consumes whole episodes.

Three baselines are available, trading variance against complexity:

* ``"none"`` — raw returns; unbiased but high variance,
* ``"mean"`` — a running mean of returns seen so far; the cheapest useful variance reduction,
* ``"value"`` — a learned state-value head trained on the observed returns (an actor-critic
  baseline), the lowest variance of the three.

Episodes cut short by a time limit are treated the same as terminated ones: with no value function
in the ``none``/``mean`` configurations there is nothing to bootstrap the remainder from, so the
truncated return is used as-is.
"""

from typing import Dict, List, Optional, Sequence

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

from .base import ActResult, Algorithm, StepBatch, masked_categorical
from .networks import build_encoder

BASELINES = ("none", "mean", "value")


class PolicyNetwork(nn.Module):
    """Shared encoder feeding a policy-logit head and (optionally) a state-value head."""

    def __init__(self, obs_space, action_size: int, hidden_sizes=None, with_value: bool = False):
        super(PolicyNetwork, self).__init__()
        self.encoder = build_encoder(obs_space, hidden_sizes)
        self.policy_head = nn.Linear(self.encoder.output_dim, action_size)
        self.value_head = nn.Linear(self.encoder.output_dim, 1) if with_value else None

    def forward(self, obs: torch.Tensor):
        """Return ``(logits, values)``; ``values`` is ``None`` when there is no value head."""
        features = self.encoder(obs)
        values = self.value_head(features).squeeze(-1) if self.value_head is not None else None
        return self.policy_head(features), values


class ReinforceAgent(Algorithm):
    """Monte-Carlo policy gradient over a discrete action space, with optional legal-action masking."""

    on_policy = True
    name = "reinforce"

    @staticmethod
    def default_config() -> Dict:
        return {
            "learning_rate": 1e-3,
            "gamma": 0.99,
            "hidden_sizes": [64, 64],
            # Entropy bonus, annealed linearly from entropy_coef to entropy_coef_final over
            # training so exploration fades as the policy sharpens.
            "entropy_coef": 0.01,
            "entropy_coef_final": 0.0,
            "baseline": "mean",
            "value_coef": 0.5,
            # Completed episodes collected before each gradient step.
            "batch_episodes": 8,
            # Standardize the advantages within the batch (scale-free step sizes).
            "normalize_returns": True,
            "max_grad_norm": 0.5,
            "verbose": True,
        }

    def __init__(self, obs_space, action_space, config: Optional[Dict] = None):
        super().__init__(obs_space, action_space, config)

        baseline = self.config["baseline"]
        if baseline not in BASELINES:
            raise ValueError(f"Unknown baseline {baseline!r}; expected one of {BASELINES}")
        self.baseline = baseline

        self.policy = PolicyNetwork(
            self.obs_space, self.action_size, self.config["hidden_sizes"], with_value=(baseline == "value")
        ).to(self.device)
        self.optimizer = optim.Adam(self.policy.parameters(), lr=self.config["learning_rate"])

        self.entropy_coef = float(self.config["entropy_coef"])
        # Running mean of episode returns, used by the "mean" baseline.
        self._return_mean = 0.0
        self._return_count = 0

        # In-progress trace per environment stream, and the completed episodes awaiting an update.
        self._traces: Dict[int, List[Dict]] = {}
        self._completed: List[List[Dict]] = []

        if self.config["verbose"]:
            print(f"Initialized REINFORCE on {self.device} (baseline={baseline}, hidden={self.config['hidden_sizes']})")

    # --- acting ------------------------------------------------------------------------------

    def act(self, obs: np.ndarray, legal: Sequence[Sequence[int]], training: bool = True) -> ActResult:
        """Sample from the masked policy while training; take its mode when evaluating."""
        with torch.no_grad():
            logits, _ = self.policy(self._to_tensor(obs))
            dist = masked_categorical(logits, legal)
            actions = dist.sample() if training else dist.probs.argmax(dim=1)
        return ActResult(actions.cpu().numpy().astype(np.int64))

    def _to_tensor(self, obs: np.ndarray) -> torch.Tensor:
        return torch.as_tensor(np.asarray(obs), dtype=torch.float32, device=self.device)

    # --- storing -----------------------------------------------------------------------------

    def observe(self, batch: StepBatch) -> None:
        """Append each row to its stream's trace, banking the trace when the episode ends."""
        for i in range(len(batch)):
            env_id = int(batch.env_ids[i])
            trace = self._traces.setdefault(env_id, [])
            trace.append(
                {
                    "obs": np.asarray(batch.obs[i]),
                    "action": int(batch.actions[i]),
                    "reward": float(batch.rewards[i]),
                    "legal": list(batch.legal[i]),
                }
            )
            if bool(batch.terminated[i] or batch.truncated[i]):
                self._completed.append(trace)
                self._traces[env_id] = []

    def _discounted_returns(self, rewards: Sequence[float]) -> List[float]:
        """Reward-to-go for each step: ``G_t = r_t + gamma * G_{t+1}``."""
        gamma = self.config["gamma"]
        returns: List[float] = [0.0] * len(rewards)
        running = 0.0
        for t in range(len(rewards) - 1, -1, -1):
            running = float(rewards[t]) + gamma * running
            returns[t] = running
        return returns

    # --- learning ----------------------------------------------------------------------------

    def update(self) -> Optional[Dict[str, float]]:
        """Take one policy-gradient step once ``batch_episodes`` episodes have completed."""
        if len(self._completed) < self.config["batch_episodes"]:
            return None

        episodes, self._completed = self._completed, []
        obs = np.stack([step["obs"] for episode in episodes for step in episode])
        actions = np.array([step["action"] for episode in episodes for step in episode], dtype=np.int64)
        legal = [step["legal"] for episode in episodes for step in episode]
        returns = np.array(
            [g for episode in episodes for g in self._discounted_returns([step["reward"] for step in episode])],
            dtype=np.float32,
        )

        obs_t = self._to_tensor(obs)
        actions_t = torch.as_tensor(actions, device=self.device)
        returns_t = torch.as_tensor(returns, dtype=torch.float32, device=self.device)

        logits, values = self.policy(obs_t)
        dist = masked_categorical(logits, legal)
        log_probs = dist.log_prob(actions_t)
        entropy = dist.entropy().mean()

        value_loss = torch.zeros((), device=self.device)
        if self.baseline == "value":
            advantages = returns_t - values.detach()
            value_loss = nn.functional.mse_loss(values, returns_t)
        elif self.baseline == "mean":
            advantages = returns_t - self._update_return_mean(returns)
        else:
            advantages = returns_t

        if self.config["normalize_returns"] and advantages.numel() > 1:
            advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        policy_loss = -(log_probs * advantages).mean()
        loss = policy_loss + self.config["value_coef"] * value_loss - self.entropy_coef * entropy

        self.optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.policy.parameters(), self.config["max_grad_norm"])
        self.optimizer.step()

        self.steps_done += 1
        loss_value = float(loss.item())
        self.training_losses.append(loss_value)
        return {
            "loss": loss_value,
            "policy_loss": float(policy_loss.item()),
            "value_loss": float(value_loss.item()),
            "entropy": float(entropy.item()),
            "episodes": float(len(episodes)),
        }

    def _update_return_mean(self, returns: np.ndarray) -> float:
        """Fold this batch's returns into the running mean and return the pre-update baseline."""
        baseline = self._return_mean
        count = self._return_count + returns.size
        self._return_mean += float(returns.sum() - returns.size * self._return_mean) / max(count, 1)
        self._return_count = count
        return baseline

    def anneal(self, progress: float) -> None:
        """Interpolate the entropy bonus from its start value to its floor over training."""
        start = float(self.config["entropy_coef"])
        end = float(self.config["entropy_coef_final"])
        self.entropy_coef = start + (end - start) * min(1.0, max(0.0, progress))

    # --- checkpointing -----------------------------------------------------------------------

    def checkpoint_state(self) -> Dict:
        return {
            "policy_state_dict": self.policy.state_dict(),
            "optimizer_state_dict": self.optimizer.state_dict(),
            "steps_done": int(self.steps_done),
            "return_mean": float(self._return_mean),
            "return_count": int(self._return_count),
        }

    def restore_checkpoint(self, checkpoint: Dict) -> None:
        self.policy.load_state_dict(checkpoint["policy_state_dict"])
        self.optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
        self.steps_done = int(checkpoint.get("steps_done", 0))
        self._return_mean = float(checkpoint.get("return_mean", 0.0))
        self._return_count = int(checkpoint.get("return_count", 0))
