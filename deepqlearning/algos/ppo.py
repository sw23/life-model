# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Proximal Policy Optimization with generalized advantage estimation.

PPO collects a fixed rollout (``n_steps`` transitions per environment stream), estimates
advantages with GAE(lambda), then takes several passes of minibatch gradient steps over that same
rollout before throwing it away. Reusing the data is what makes PPO sample-efficient compared with
REINFORCE; the clipped surrogate objective is what keeps that reuse from walking the policy too far
from the one the data was collected under.

Two details that are easy to get wrong and are pinned by tests:

* **Truncation is not termination.** When an episode is cut off by a time limit the value of the
  next state is still real future reward, so the advantage bootstraps through it. When the episode
  genuinely ends there is no future, so the bootstrap term is zeroed.
* **Masked logits are re-applied at update time.** The importance ratio compares the *current*
  policy against the behavior policy on the same masked distribution; scoring the stored actions
  against unmasked logits would produce ratios the behavior policy could never have generated.
"""

from collections.abc import Iterable, Sequence

import numpy as np
import torch
from torch import nn, optim

from .base import ActResult, Algorithm, StepBatch, masked_categorical
from .networks import build_encoder


class ActorCritic(nn.Module):
    """Shared encoder feeding a policy-logit head and a state-value head."""

    def __init__(self, obs_space, action_size: int, hidden_sizes=None):
        super().__init__()
        self.encoder = build_encoder(obs_space, hidden_sizes)
        self.policy_head = nn.Linear(self.encoder.output_dim, action_size)
        self.value_head = nn.Linear(self.encoder.output_dim, 1)

    def forward(self, obs: torch.Tensor):
        features = self.encoder(obs)
        return self.policy_head(features), self.value_head(features).squeeze(-1)


class RolloutBuffer:
    """Fixed-size on-policy storage, kept as one ordered segment per environment stream.

    Storage is per stream rather than a flat ``(n_steps, num_envs)`` array because autoreset steps
    are dropped from the incoming batches, so streams do not advance in lockstep. GAE only needs
    each stream's transitions in time order, which this preserves.
    """

    def __init__(self, n_steps: int, num_envs: int):
        self.capacity = max(1, int(n_steps) * max(1, int(num_envs)))
        self._streams: dict[int, list[dict]] = {}
        self._size = 0

    def resize(self, n_steps: int, num_envs: int) -> None:
        """Re-target the buffer for a different stream count, discarding anything held."""
        self.capacity = max(1, int(n_steps) * max(1, int(num_envs)))
        self.clear()

    def add(self, env_id: int, transition: dict) -> None:
        self._streams.setdefault(int(env_id), []).append(transition)
        self._size += 1

    def ready(self) -> bool:
        return self._size >= self.capacity

    def clear(self) -> None:
        self._streams = {}
        self._size = 0

    def streams(self) -> Iterable[list[dict]]:
        """Each stream's transitions, in the order they were collected."""
        return [stream for stream in self._streams.values() if stream]

    def __len__(self) -> int:
        return self._size


def compute_gae(
    rewards: np.ndarray,
    values: np.ndarray,
    next_values: np.ndarray,
    terminated: np.ndarray,
    truncated: np.ndarray,
    gamma: float,
    gae_lambda: float,
) -> np.ndarray:
    """Generalized advantage estimates for one contiguous stream of transitions.

    ``delta_t = r_t + gamma * V(s_{t+1}) * (1 - terminated_t) - V(s_t)`` and
    ``A_t = delta_t + gamma * lambda * (1 - done_t) * A_{t+1}``. Termination zeroes the bootstrap
    (no future exists); truncation keeps it (the future exists, the rollout just stopped looking).
    Both end the recursion, since the next transition belongs to a different episode.
    """
    n = len(rewards)
    advantages = np.zeros(n, dtype=np.float64)
    running = 0.0
    for t in range(n - 1, -1, -1):
        not_terminal = 0.0 if terminated[t] else 1.0
        not_done = 0.0 if (terminated[t] or truncated[t]) else 1.0
        delta = rewards[t] + gamma * next_values[t] * not_terminal - values[t]
        running = delta + gamma * gae_lambda * not_done * running
        advantages[t] = running
    return advantages


def clipped_surrogate(ratio: torch.Tensor, advantages: torch.Tensor, clip_range: float) -> torch.Tensor:
    """PPO's clipped policy loss (negated objective, so it is minimized).

    Taking the *minimum* of the unclipped and clipped terms makes the bound pessimistic in both
    directions: it removes the incentive to push the ratio further than ``1 +/- clip_range`` when
    the advantage is positive, and equally when it is negative.
    """
    unclipped = ratio * advantages
    clipped = torch.clamp(ratio, 1.0 - clip_range, 1.0 + clip_range) * advantages
    return -torch.min(unclipped, clipped).mean()


class PPOAgent(Algorithm):
    """Clipped-surrogate PPO over a discrete action space, with optional legal-action masking."""

    on_policy = True
    name = "ppo"

    @staticmethod
    def default_config() -> dict:
        return {
            "learning_rate": 3e-4,
            "gamma": 0.99,
            "gae_lambda": 0.95,
            "clip_range": 0.2,
            # Transitions collected per environment stream before each update.
            "n_steps": 128,
            "num_envs": 1,
            "epochs": 4,
            "minibatches": 4,
            "value_coef": 0.5,
            "entropy_coef": 0.01,
            "entropy_coef_final": 0.0,
            "max_grad_norm": 0.5,
            "normalize_advantage": True,
            "hidden_sizes": [64, 64],
            "verbose": True,
        }

    def __init__(self, obs_space, action_space, config: dict | None = None):
        super().__init__(obs_space, action_space, config)

        self.policy = ActorCritic(self.obs_space, self.action_size, self.config["hidden_sizes"]).to(self.device)
        self.optimizer = optim.Adam(self.policy.parameters(), lr=self.config["learning_rate"])
        self.buffer = RolloutBuffer(self.config["n_steps"], self.config["num_envs"])
        self.entropy_coef = float(self.config["entropy_coef"])

        if self.config["verbose"]:
            print(
                f"Initialized PPO on {self.device} (n_steps={self.config['n_steps']} x "
                f"{self.config['num_envs']} envs, epochs={self.config['epochs']}, "
                f"clip={self.config['clip_range']})"
            )

    def on_env_count(self, num_envs: int) -> None:
        """Resize the rollout to the trainer's actual stream count."""
        if num_envs != self.config["num_envs"]:
            self.config["num_envs"] = int(num_envs)
            self.buffer.resize(self.config["n_steps"], num_envs)

    def _to_tensor(self, obs) -> torch.Tensor:
        return torch.as_tensor(np.asarray(obs), dtype=torch.float32, device=self.device)

    # --- acting ------------------------------------------------------------------------------

    def act(self, obs: np.ndarray, legal: Sequence[Sequence[int]], training: bool = True) -> ActResult:
        """Sample from the masked policy (mode when evaluating), returning log-prob and value.

        The log-probability and value are handed back through ``extras`` because the update needs
        the values *this* policy produced at collection time, which cannot be recovered once the
        weights have moved.
        """
        with torch.no_grad():
            logits, values = self.policy(self._to_tensor(obs))
            dist = masked_categorical(logits, legal)
            actions = dist.sample() if training else dist.probs.argmax(dim=1)
            log_probs = dist.log_prob(actions)
        return ActResult(
            actions.cpu().numpy().astype(np.int64),
            {"log_prob": log_probs.cpu().numpy(), "value": values.cpu().numpy()},
        )

    # --- storing -----------------------------------------------------------------------------

    def observe(self, batch: StepBatch) -> None:
        """Append each row to its stream's rollout segment."""
        log_probs = batch.extras.get("log_prob")
        values = batch.extras.get("value")
        if log_probs is None or values is None:
            raise ValueError("PPO needs the 'log_prob' and 'value' extras from act() in the observed batch")
        for i in range(len(batch)):
            self.buffer.add(
                int(batch.env_ids[i]),
                {
                    "obs": np.asarray(batch.obs[i]),
                    "next_obs": np.asarray(batch.next_obs[i]),
                    "action": int(batch.actions[i]),
                    "reward": float(batch.rewards[i]),
                    "terminated": bool(batch.terminated[i]),
                    "truncated": bool(batch.truncated[i]),
                    "legal": list(batch.legal[i]),
                    "log_prob": float(log_probs[i]),
                    "value": float(values[i]),
                },
            )

    # --- learning ----------------------------------------------------------------------------

    def _next_values(self, transitions: list[dict]) -> np.ndarray:
        """Value of each transition's successor state, in one batched forward pass."""
        with torch.no_grad():
            _, values = self.policy(self._to_tensor(np.stack([t["next_obs"] for t in transitions])))
        return values.cpu().numpy()

    def _prepare_batch(self):
        """Flatten the rollout into tensors, computing GAE advantages per stream."""
        streams = list(self.buffer.streams())
        flat = [t for stream in streams for t in stream]
        next_values = self._next_values(flat)

        advantages: list[np.ndarray] = []
        offset = 0
        for stream in streams:
            size = len(stream)
            advantages.append(
                compute_gae(
                    rewards=np.array([t["reward"] for t in stream], dtype=np.float64),
                    values=np.array([t["value"] for t in stream], dtype=np.float64),
                    next_values=next_values[offset : offset + size].astype(np.float64),
                    terminated=np.array([t["terminated"] for t in stream], dtype=bool),
                    truncated=np.array([t["truncated"] for t in stream], dtype=bool),
                    gamma=self.config["gamma"],
                    gae_lambda=self.config["gae_lambda"],
                )
            )
            offset += size

        advantage_array = np.concatenate(advantages) if advantages else np.zeros(0)
        values_array = np.array([t["value"] for t in flat], dtype=np.float64)
        return {
            "obs": self._to_tensor(np.stack([t["obs"] for t in flat])),
            "actions": torch.as_tensor(np.array([t["action"] for t in flat], dtype=np.int64), device=self.device),
            "old_log_probs": torch.as_tensor(
                np.array([t["log_prob"] for t in flat], dtype=np.float32), device=self.device
            ),
            "advantages": torch.as_tensor(advantage_array.astype(np.float32), device=self.device),
            # The value target is the advantage plus the value the critic predicted at collection
            # time — the lambda-return, consistent with the advantages just computed.
            "returns": torch.as_tensor((advantage_array + values_array).astype(np.float32), device=self.device),
            "legal": [t["legal"] for t in flat],
        }

    def update(self) -> dict[str, float] | None:
        """Run the clipped-surrogate epochs once a full rollout is collected, then drop it."""
        if not self.buffer.ready():
            return None

        data = self._prepare_batch()
        self.buffer.clear()

        n = len(data["actions"])
        advantages = data["advantages"]
        if self.config["normalize_advantage"] and n > 1:
            advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        clip_range = float(self.config["clip_range"])
        minibatch_size = max(1, n // max(1, int(self.config["minibatches"])))
        totals = {"policy_loss": 0.0, "value_loss": 0.0, "entropy": 0.0, "clip_fraction": 0.0, "loss": 0.0}
        n_updates = 0

        for _ in range(int(self.config["epochs"])):
            order = torch.randperm(n, device=self.device)
            for start in range(0, n, minibatch_size):
                index = order[start : start + minibatch_size]
                index_list = index.tolist()
                logits, values = self.policy(data["obs"][index])
                dist = masked_categorical(logits, [data["legal"][i] for i in index_list])
                log_probs = dist.log_prob(data["actions"][index])
                entropy = dist.entropy().mean()

                ratio = torch.exp(log_probs - data["old_log_probs"][index])
                policy_loss = clipped_surrogate(ratio, advantages[index], clip_range)
                value_loss = nn.functional.mse_loss(values, data["returns"][index])
                loss = policy_loss + self.config["value_coef"] * value_loss - self.entropy_coef * entropy

                self.optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.policy.parameters(), self.config["max_grad_norm"])
                self.optimizer.step()

                with torch.no_grad():
                    clip_fraction = float(((ratio - 1.0).abs() > clip_range).float().mean().item())
                totals["policy_loss"] += float(policy_loss.item())
                totals["value_loss"] += float(value_loss.item())
                totals["entropy"] += float(entropy.item())
                totals["clip_fraction"] += clip_fraction
                totals["loss"] += float(loss.item())
                n_updates += 1

        self.steps_done += 1
        metrics = {key: value / max(1, n_updates) for key, value in totals.items()}
        metrics["transitions"] = float(n)
        self.training_losses.append(metrics["loss"])
        return metrics

    def anneal(self, progress: float) -> None:
        """Interpolate the entropy bonus from its start value to its floor over training."""
        start = float(self.config["entropy_coef"])
        end = float(self.config["entropy_coef_final"])
        self.entropy_coef = start + (end - start) * min(1.0, max(0.0, progress))

    # --- checkpointing -----------------------------------------------------------------------

    def checkpoint_state(self) -> dict:
        return {
            "policy_state_dict": self.policy.state_dict(),
            "optimizer_state_dict": self.optimizer.state_dict(),
            "steps_done": int(self.steps_done),
        }

    def restore_checkpoint(self, checkpoint: dict) -> None:
        self.policy.load_state_dict(checkpoint["policy_state_dict"])
        self.optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
        self.steps_done = int(checkpoint.get("steps_done", 0))
