# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Vectorized data collection and training upgrades (Plan 19 D4).

The legacy trainer collected from a single sequential environment. This module drives ``N`` envs
through :mod:`gymnasium.vector` (``Sync`` by default for deterministic n-step/masking; ``Async``
for throughput) feeding one shared learner, and adds the rest of the D4 stack:

* **Prioritized replay + n-step returns** — supplied by :class:`FinancialDQNAgent` /
  :class:`NStepAccumulator`; this trainer just routes per-env transitions into them.
* **Learning-rate schedule** — optional cosine / step decay on the agent's optimizer.
* **Early stopping** — halts when greedy eval return plateaus, keeping the best checkpoint.

Gymnasium 1.x uses ``AutoresetMode.NEXT_STEP``: the step that ends an episode returns its terminal
transition, and the *following* step is an autoreset whose action is ignored and whose reward is 0.
The collector tracks a per-env "awaiting reset" flag so those reset steps are not stored as
transitions and the n-step accumulator is flushed exactly at episode boundaries.

Per-env seeds are derived from a base seed, so a collection run is reproducible.
"""

import time
from typing import Dict, List, Optional

import gymnasium as gym
import numpy as np
import torch
from agent import FinancialDQNAgent, NStepAccumulator, rollout
from environment import FinancialLifeEnv


class _EnvFactory:
    """Picklable env factory (needed for the Async/spawn backend)."""

    def __init__(self, config: Optional[Dict]):
        self.config = dict(config or {})

    def __call__(self) -> FinancialLifeEnv:
        return FinancialLifeEnv(self.config)


def make_vector_env(env_config: Optional[Dict], num_envs: int, backend: str = "sync") -> gym.vector.VectorEnv:
    """Build a gymnasium vector env of ``num_envs`` ``FinancialLifeEnv`` instances."""
    fns = [_EnvFactory(env_config) for _ in range(num_envs)]
    if backend == "async":
        return gym.vector.AsyncVectorEnv(fns)
    return gym.vector.SyncVectorEnv(fns)


def _masks_from_info(info: Dict, num_envs: int, action_size: int) -> List[List[int]]:
    """Extract per-env legal-action lists from the vector info's ``legal_mask`` array."""
    masks = info.get("legal_mask")
    result: List[List[int]] = []
    for i in range(num_envs):
        row = masks[i] if masks is not None and masks[i] is not None else None
        if row is None:
            result.append(list(range(action_size)))
        else:
            result.append(np.nonzero(row)[0].tolist())
    return result


class VectorizedTrainer:
    """Trains a :class:`FinancialDQNAgent` from vectorized collection with the D4 upgrades."""

    def __init__(self, agent: FinancialDQNAgent, env_config: Optional[Dict] = None, config: Optional[Dict] = None):
        self.agent = agent
        self.env_config = dict(env_config or {})

        self.config = {
            "num_envs": 8,
            "backend": "sync",  # "sync" (deterministic) or "async" (throughput)
            "total_env_steps": 200_000,  # collection budget across all envs
            "train_per_step": 1,  # gradient steps per vectorized collection step
            "base_seed": 0,
            "eval_freq_steps": 5_000,  # greedy eval cadence (in collected env steps)
            "eval_episodes": 10,
            "eval_seed_base": 1_000_000,
            "early_stop_patience": 8,  # eval rounds without improvement before stopping
            "lr_schedule": None,  # None | "cosine" | "step"
            "lr_step_size": 20_000,
            "lr_gamma": 0.5,
            "model_save_path": "financial_dqn_vector.pt",
            "print_freq_steps": 5_000,
            # Optional TensorBoard logging dir (Plan 19 D4/D5). Uses torch.utils.tensorboard, which
            # ships with torch; behind a soft import so the trainer runs fine without TensorBoard.
            "tensorboard_logdir": None,
        }
        if config:
            self.config.update(config)

        self.writer = self._make_tensorboard_writer()
        self.scheduler = self._make_scheduler()
        self.episode_rewards: List[float] = []
        self.eval_rewards: List[float] = []
        self.best_eval = -float("inf")
        self._collected_steps = 0

    def _make_tensorboard_writer(self):
        logdir = self.config["tensorboard_logdir"]
        if not logdir:
            return None
        try:
            from torch.utils.tensorboard import SummaryWriter
        except ImportError:
            print("TensorBoard requested but torch.utils.tensorboard is unavailable; continuing without it.")
            return None
        print(f"TensorBoard logging to {logdir}")
        return SummaryWriter(log_dir=logdir)

    def _make_scheduler(self):
        sched = self.config["lr_schedule"]
        if sched == "cosine":
            t_max = max(1, self.config["total_env_steps"] // max(1, self.config["train_per_step"]))
            return torch.optim.lr_scheduler.CosineAnnealingLR(self.agent.optimizer, T_max=t_max)
        if sched == "step":
            return torch.optim.lr_scheduler.StepLR(
                self.agent.optimizer, step_size=self.config["lr_step_size"], gamma=self.config["lr_gamma"]
            )
        return None

    def _evaluate(self) -> float:
        """Greedy eval on held-out seeds (single env; no exploration/training)."""
        env = FinancialLifeEnv(self.env_config)
        old_eps = self.agent.epsilon
        self.agent.epsilon = 0.0
        rewards = [
            rollout(env, self.agent, training=False, seed=self.config["eval_seed_base"] + i).total_reward
            for i in range(self.config["eval_episodes"])
        ]
        self.agent.epsilon = old_eps
        return float(np.mean(rewards))

    def update_epsilon(self, frac: float):
        """Linear epsilon decay over the first ``epsilon_decay_fraction`` of the step budget."""
        start = self.agent.config["epsilon_start"]
        end = self.agent.config["epsilon_end"]
        decay = max(1e-9, self.agent.config["epsilon_decay_fraction"])
        progress = min(1.0, frac / decay)
        self.agent.epsilon = start + (end - start) * progress

    def train(self) -> Dict:
        """Run vectorized collection + training until the step budget or early stop. Returns stats."""
        num_envs = self.config["num_envs"]
        action_size = self.agent.action_size
        gamma = self.agent.config["gamma"]
        n_step = self.agent.config.get("n_step", 1)
        total_steps = self.config["total_env_steps"]

        venv = make_vector_env(self.env_config, num_envs, self.config["backend"])
        seeds = [self.config["base_seed"] + i for i in range(num_envs)]
        states, info = venv.reset(seed=seeds)
        legal = _masks_from_info(info, num_envs, action_size)

        accumulators = [NStepAccumulator(n_step, gamma) for _ in range(num_envs)]
        awaiting_reset = [False] * num_envs
        ep_returns = [0.0] * num_envs
        rounds_without_improve = 0
        last_eval_at = 0
        last_print_at = 0
        start_time = time.perf_counter()

        try:
            while self._collected_steps < total_steps:
                self.update_epsilon(self._collected_steps / max(1, total_steps))
                actions = self.agent.select_actions_batch(states, legal, training=True)
                next_states, rewards, terminated, truncated, info = venv.step(np.asarray(actions))
                next_legal = _masks_from_info(info, num_envs, action_size)

                for i in range(num_envs):
                    if awaiting_reset[i]:
                        # NEXT_STEP autoreset: this step's obs is the new episode's start; the
                        # action/reward are placeholders and must not be stored.
                        awaiting_reset[i] = False
                        ep_returns[i] = 0.0
                        continue
                    done = bool(terminated[i] or truncated[i])
                    ep_returns[i] += float(rewards[i])
                    for exp in accumulators[i].push(
                        states[i], actions[i], float(rewards[i]), legal[i], next_states[i], next_legal[i], done
                    ):
                        self.agent.store_prebuilt(exp)
                    if done:
                        self.episode_rewards.append(ep_returns[i])
                        self.agent.episode_rewards.append(ep_returns[i])
                        awaiting_reset[i] = True

                did_grad_step = False
                for _ in range(self.config["train_per_step"]):
                    if self.agent.train() is not None:
                        did_grad_step = True
                if self.scheduler is not None and did_grad_step:
                    self.scheduler.step()

                states, legal = next_states, next_legal
                self._collected_steps += num_envs

                if self._collected_steps - last_print_at >= self.config["print_freq_steps"]:
                    last_print_at = self._collected_steps
                    recent = np.mean(self.episode_rewards[-50:]) if self.episode_rewards else float("nan")
                    rate = self._collected_steps / (time.perf_counter() - start_time)
                    print(
                        f"steps {self._collected_steps:>8d} | eps {self.agent.epsilon:.3f} | "
                        f"recent_return {recent:8.2f} | {rate:7.0f} env-steps/s"
                    )
                    if self.writer is not None:
                        self.writer.add_scalar("train/recent_return", recent, self._collected_steps)
                        self.writer.add_scalar("train/epsilon", self.agent.epsilon, self._collected_steps)
                        if self.agent.training_losses:
                            self.writer.add_scalar("train/loss", self.agent.training_losses[-1], self._collected_steps)

                if self._collected_steps - last_eval_at >= self.config["eval_freq_steps"]:
                    last_eval_at = self._collected_steps
                    eval_reward = self._evaluate()
                    self.eval_rewards.append(eval_reward)
                    print(f"  [eval @ {self._collected_steps} steps] greedy return {eval_reward:.2f}")
                    if self.writer is not None:
                        self.writer.add_scalar("eval/greedy_return", eval_reward, self._collected_steps)
                    if eval_reward > self.best_eval + 1e-6:
                        self.best_eval = eval_reward
                        rounds_without_improve = 0
                        self.agent.save_model(self.config["model_save_path"])
                    else:
                        rounds_without_improve += 1
                        if rounds_without_improve >= self.config["early_stop_patience"]:
                            print(f"  early stopping: no eval improvement in {rounds_without_improve} rounds")
                            break
        finally:
            venv.close()
            if self.writer is not None:
                self.writer.close()

        return {
            "collected_env_steps": self._collected_steps,
            "episodes": len(self.episode_rewards),
            "best_eval_return": self.best_eval,
            "eval_rewards": self.eval_rewards,
            "elapsed_sec": time.perf_counter() - start_time,
        }
