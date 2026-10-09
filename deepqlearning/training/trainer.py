# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Vectorized collection loop with a step budget.

Drives ``N`` copies of a registered environment through :mod:`gymnasium.vector` (``Sync`` by
default for deterministic ordering; ``Async`` for throughput) feeding one shared learner, and adds
the surrounding training machinery:

* **Learning-rate schedule** — optional cosine / step decay on the algorithm's optimizer.
* **Early stopping** — halts when greedy eval return plateaus, keeping the best checkpoint.
* **TensorBoard logging** — behind a soft import, so the trainer runs fine without it.

Gymnasium 1.x uses ``AutoresetMode.NEXT_STEP``: the step that ends an episode returns its terminal
transition, and the *following* step is an autoreset whose action is ignored and whose reward is 0.
The collector tracks a per-env "awaiting reset" flag and drops those reset steps from the batch
handed to the algorithm, so they are never learned from and per-stream bookkeeping (n-step
accumulation, rollout segments) sees clean episode boundaries.

Per-env seeds are derived from a base seed, so a collection run is reproducible. The loop is
algorithm-agnostic: it calls ``observe`` then ``update`` every step, and an algorithm that is not
ready to learn simply returns ``None``.
"""

import time

import numpy as np
import torch

from ..algos.base import Algorithm, StepBatch
from ..envs.masks import masks_from_vector_info
from ..envs.registry import make_env, make_vector_env
from .rollout import rollout


class Trainer:
    """Trains an algorithm from vectorized collection until a step budget or an early stop."""

    def __init__(
        self,
        algo: Algorithm,
        env_name: str = "financial",
        env_config: dict | None = None,
        config: dict | None = None,
    ):
        self.algo = algo
        self.env_name = env_name
        self.env_config = dict(env_config or {})

        self.config = {
            "num_envs": 8,
            "backend": "sync",  # "sync" (deterministic) or "async" (throughput)
            "total_env_steps": 200_000,  # collection budget across all envs
            "train_per_step": 1,  # update attempts per vectorized collection step
            "base_seed": 0,
            "eval_freq_steps": 5_000,  # greedy eval cadence (in collected env steps)
            "eval_episodes": 10,
            "eval_seed_base": 1_000_000,
            "early_stop_patience": 8,  # eval rounds without improvement before stopping
            "lr_schedule": None,  # None | "cosine" | "step"
            "lr_step_size": 20_000,
            "lr_gamma": 0.5,
            "model_save_path": "model.pt",
            "print_freq_steps": 5_000,
            # Optional TensorBoard logging dir. Uses torch.utils.tensorboard, which
            # ships with torch; behind a soft import so the trainer runs fine without TensorBoard.
            "tensorboard_logdir": None,
        }
        if config:
            self.config.update(config)

        self.writer = self._make_tensorboard_writer()
        self.scheduler = self._make_scheduler()
        self.episode_rewards: list[float] = []
        self.eval_rewards: list[float] = []
        self.best_eval = -float("inf")
        # True once training has moved past the last saved best checkpoint.
        self._best_is_stale = False
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
        optimizer = getattr(self.algo, "optimizer", None)
        if sched is None or optimizer is None:
            return None
        if sched == "cosine":
            t_max = max(1, self.config["total_env_steps"] // max(1, self.config["train_per_step"]))
            return torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=t_max)
        if sched == "step":
            return torch.optim.lr_scheduler.StepLR(
                optimizer, step_size=self.config["lr_step_size"], gamma=self.config["lr_gamma"]
            )
        raise ValueError(f"Unknown lr_schedule {sched!r}; expected None, 'cosine', or 'step'")

    def _evaluate(self) -> float:
        """Mean greedy return on held-out seeds (single env; no exploration, no learning)."""
        env = make_env(self.env_name, self.env_config)
        try:
            rewards = [
                rollout(env, self.algo, training=False, seed=self.config["eval_seed_base"] + i).total_reward
                for i in range(self.config["eval_episodes"])
            ]
        finally:
            env.close()
        return float(np.mean(rewards))

    def train(self) -> dict:
        """Run vectorized collection + training until the step budget or early stop. Returns stats."""
        num_envs = self.config["num_envs"]
        action_size = self.algo.action_size
        total_steps = self.config["total_env_steps"]
        self.algo.on_env_count(num_envs)

        venv = make_vector_env(self.env_name, self.env_config, num_envs, self.config["backend"])
        seeds = [self.config["base_seed"] + i for i in range(num_envs)]
        states, info = venv.reset(seed=seeds)
        legal = masks_from_vector_info(info, num_envs, action_size)

        awaiting_reset = [False] * num_envs
        ep_returns = [0.0] * num_envs
        rounds_without_improve = 0
        last_eval_at = 0
        last_print_at = 0
        start_time = time.perf_counter()

        try:
            while self._collected_steps < total_steps:
                self.algo.anneal(self._collected_steps / max(1, total_steps))
                act_result = self.algo.act(states, legal, training=True)
                actions = act_result.actions
                next_states, rewards, terminated, truncated, info = venv.step(np.asarray(actions))
                next_legal = masks_from_vector_info(info, num_envs, action_size)

                # NEXT_STEP autoreset: an env flagged as awaiting reset just returned the first
                # observation of its next episode; its action/reward are placeholders, so the row
                # is dropped instead of being learned from.
                active = []
                for i in range(num_envs):
                    if awaiting_reset[i]:
                        awaiting_reset[i] = False
                        ep_returns[i] = 0.0
                        continue
                    active.append(i)
                    ep_returns[i] += float(rewards[i])
                    if bool(terminated[i] or truncated[i]):
                        self.episode_rewards.append(ep_returns[i])
                        self.algo.episode_rewards.append(ep_returns[i])
                        awaiting_reset[i] = True

                if active:
                    self.algo.observe(
                        StepBatch(
                            obs=np.asarray(states)[active],
                            actions=np.asarray(actions)[active],
                            rewards=np.asarray(rewards, dtype=np.float64)[active],
                            next_obs=np.asarray(next_states)[active],
                            terminated=np.asarray(terminated, dtype=bool)[active],
                            truncated=np.asarray(truncated, dtype=bool)[active],
                            legal=[legal[i] for i in active],
                            next_legal=[next_legal[i] for i in active],
                            env_ids=np.asarray(active, dtype=np.int64),
                            extras={key: np.asarray(value)[active] for key, value in act_result.extras.items()},
                        )
                    )

                did_grad_step = False
                for _ in range(self.config["train_per_step"]):
                    if self.algo.update() is not None:
                        did_grad_step = True
                if self.scheduler is not None and did_grad_step:
                    self.scheduler.step()

                states, legal = next_states, next_legal
                self._collected_steps += num_envs

                if self._collected_steps - last_print_at >= self.config["print_freq_steps"]:
                    last_print_at = self._collected_steps
                    recent = np.mean(self.episode_rewards[-50:]) if self.episode_rewards else float("nan")
                    rate = self._collected_steps / (time.perf_counter() - start_time)
                    print(f"steps {self._collected_steps:>8d} | recent_return {recent:8.2f} | {rate:7.0f} env-steps/s")
                    if self.writer is not None:
                        self.writer.add_scalar("train/recent_return", recent, self._collected_steps)
                        if self.algo.training_losses:
                            self.writer.add_scalar("train/loss", self.algo.training_losses[-1], self._collected_steps)

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
                        self.algo.save(self.config["model_save_path"])
                        self._best_is_stale = False
                    else:
                        rounds_without_improve += 1
                        self._best_is_stale = True
                        if rounds_without_improve >= self.config["early_stop_patience"]:
                            print(f"  early stopping: no eval improvement in {rounds_without_improve} rounds")
                            break
        finally:
            venv.close()
            if self.writer is not None:
                self.writer.close()

        # Hand back the best policy, not the last one: the final weights can be well past the eval
        # peak (early stopping fires only after ``early_stop_patience`` non-improving rounds), and
        # callers evaluate whatever weights the algorithm holds when train() returns.
        if self.best_eval > -float("inf") and self._best_is_stale:
            self.algo.load(self.config["model_save_path"])

        return {
            "collected_env_steps": self._collected_steps,
            "episodes": len(self.episode_rewards),
            "best_eval_return": self.best_eval,
            "eval_rewards": self.eval_rewards,
            "elapsed_sec": time.perf_counter() - start_time,
        }
