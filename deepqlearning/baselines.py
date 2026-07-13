# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Scripted baseline policies for the financial life environment.

These non-learning policies give the RL agent something to beat. An agent that cannot beat
"do nothing" on the same seeds is a sign the environment or agent is broken, so the baselines
double as regression detectors.
"""

from typing import Callable, Dict, List

import numpy as np
from actions import ActionType, encode_flat_action
from environment import FinancialLifeEnv

# A baseline policy maps the environment's current state to a flat discrete action index
# (Plan 18 D5: the index carries both the action type and the amount bucket).
BaselinePolicy = Callable[[FinancialLifeEnv], int]

_NO_ACTION = encode_flat_action(ActionType.NO_ACTION)


def do_nothing_policy(env: FinancialLifeEnv) -> int:
    """Never take a financial action."""
    return _NO_ACTION


def always_max_401k_policy(env: FinancialLifeEnv) -> int:
    """Contribute as much as allowed to the pre-tax 401k every year (the 100% bucket)."""
    action = encode_flat_action(ActionType.TRANSFER_BANK_TO_401K_PRETAX, 1.00)
    if action in env.get_legal_actions():
        return action
    return _NO_ACTION


def save_25_percent_policy(env: FinancialLifeEnv) -> int:
    """Move a quarter of the bank balance into the brokerage each year (the 25% bucket)."""
    action = encode_flat_action(ActionType.TRANSFER_BANK_TO_BROKERAGE, 0.25)
    if action in env.get_legal_actions():
        return action
    return _NO_ACTION


BASELINES: Dict[str, BaselinePolicy] = {
    "do_nothing": do_nothing_policy,
    "always_max_401k": always_max_401k_policy,
    "save_25_percent": save_25_percent_policy,
}


def run_baseline_episode(env: FinancialLifeEnv, policy: BaselinePolicy, seed: int) -> float:
    """Run one episode under ``policy`` and return the total reward."""
    env.reset(seed=seed)
    total_reward = 0.0
    while True:
        action = policy(env)
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
