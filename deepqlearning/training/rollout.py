# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The single-episode loop shared by training, evaluation, and policy analysis."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from ..algos.base import Algorithm, StepBatch
from ..envs.masks import legal_actions_of


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
    env,
    algo: Algorithm,
    training: bool = False,
    seed: Optional[int] = None,
    collect_trajectory: bool = False,
) -> RolloutResult:
    """Run one episode.

    The action space is fully discrete: the policy's chosen index carries everything the
    environment needs, so there is no separate amount or parameter to fill in. When ``training`` is
    True the transition is handed to the algorithm and an update is attempted each step — the
    algorithm decides whether that update actually does anything.

    ``collect_trajectory`` records the financial-environment fields the policy-analysis artifacts
    read; environments that do not publish them simply record ``None``.
    """
    state, info = env.reset(seed=seed)
    action_size = int(env.action_space.n)
    if training:
        algo.on_env_count(1)

    total_reward = 0.0
    steps = 0
    terminated = False
    truncated = False
    trajectory: List[Dict] = []
    legal_actions = legal_actions_of(env, info, action_size)

    while True:
        obs_batch = np.expand_dims(np.asarray(state), 0)
        act_result = algo.act(obs_batch, [legal_actions], training=training)
        action = int(act_result.actions[0])

        next_state, reward, terminated, truncated, info = env.step(action)
        done = terminated or truncated
        total_reward += reward
        next_legal_actions = legal_actions_of(env, info, action_size)

        if training:
            algo.observe(
                StepBatch(
                    obs=obs_batch,
                    actions=act_result.actions,
                    rewards=np.array([reward], dtype=np.float64),
                    next_obs=np.expand_dims(np.asarray(next_state), 0),
                    terminated=np.array([terminated], dtype=bool),
                    truncated=np.array([truncated], dtype=bool),
                    legal=[legal_actions],
                    next_legal=[next_legal_actions],
                    env_ids=np.array([0], dtype=np.int64),
                    extras=act_result.extras,
                )
            )
            algo.update()

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
        legal_actions = next_legal_actions
        steps += 1
        if done:
            break

    return RolloutResult(float(total_reward), steps, bool(terminated), bool(truncated), info, trajectory)
