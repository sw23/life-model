# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Scripted baseline policies for the financial life environment.

These non-learning policies give the RL agent something to beat. An agent that cannot beat
"do nothing" on the same seeds is a sign the environment or agent is broken, so the baselines
double as regression detectors.
"""

from typing import Callable, Dict, List, Tuple

import numpy as np
from actions import ActionType
from environment import FinancialLifeEnv

# A baseline policy maps the environment's current state to an
# ``(action_type_index, amount_percentage)`` pair.
BaselinePolicy = Callable[[FinancialLifeEnv], Tuple[int, float]]


def _index(action_type: ActionType) -> int:
    return list(ActionType).index(action_type)


def do_nothing_policy(env: FinancialLifeEnv) -> Tuple[int, float]:
    """Never take a financial action."""
    return _index(ActionType.NO_ACTION), 0.0


def always_max_401k_policy(env: FinancialLifeEnv) -> Tuple[int, float]:
    """Contribute as much as allowed to the pre-tax 401k every year."""
    legal = env.get_legal_actions()
    idx = _index(ActionType.TRANSFER_BANK_TO_401K_PRETAX)
    if idx in legal:
        return idx, 1.0
    return _index(ActionType.NO_ACTION), 0.0


def save_20_percent_policy(env: FinancialLifeEnv) -> Tuple[int, float]:
    """Move roughly 20% of the bank balance into the brokerage each year."""
    legal = env.get_legal_actions()
    idx = _index(ActionType.TRANSFER_BANK_TO_BROKERAGE)
    if idx in legal:
        return idx, 0.2
    return _index(ActionType.NO_ACTION), 0.0


BASELINES: Dict[str, BaselinePolicy] = {
    "do_nothing": do_nothing_policy,
    "always_max_401k": always_max_401k_policy,
    "save_20_percent": save_20_percent_policy,
}


def run_baseline_episode(env: FinancialLifeEnv, policy: BaselinePolicy, seed: int) -> float:
    """Run one episode under ``policy`` and return the total reward."""
    env.reset(seed=seed)
    total_reward = 0.0
    while True:
        action_idx, pct = policy(env)
        action = {"action_type": action_idx, "amount_percentage": np.array([pct], dtype=np.float32)}
        _, reward, terminated, truncated, _ = env.step(action)
        total_reward += reward
        if terminated or truncated:
            break
    return float(total_reward)


def evaluate_baseline(env: FinancialLifeEnv, policy: BaselinePolicy, seeds: List[int]) -> float:
    """Average reward of ``policy`` over the given seeds."""
    return float(np.mean([run_baseline_episode(env, policy, seed) for seed in seeds]))


def evaluate_all_baselines(env: FinancialLifeEnv, seeds: List[int]) -> Dict[str, float]:
    """Average reward for every named baseline over the given seeds."""
    return {name: evaluate_baseline(env, policy, seeds) for name, policy in BASELINES.items()}
