# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Scripted baseline policies for the financial life environment.

These non-learning policies give the RL agent something to beat. The simple ones
(``do_nothing``, ``always_max_401k``, ``save_25_percent``) double as regression detectors — an
agent that cannot beat "do nothing" on the same seeds is a sign the environment or agent is
broken. The **planner-grade** policies (Plan 19 D2) are the real bar: they encode strategies a
human advisor would recognize — a tax-advantaged contribution waterfall, an age-based savings
glide path, a 4%-rule retirement drawdown with Roth-last ordering, and an emergency-fund-first
rule. "Intelligent" is defined (D3) as beating *these* on the default objective.

Every policy is a pure function of the environment's current state and returns a **legal** flat
action index (or ``NO_ACTION``, which is always legal), so a policy never desyncs from the action
mask. Being a deterministic function of the seeded state, each policy is reproducible per seed.

The planner policies are also usable as curriculum teachers: :func:`collect_teacher_experiences`
runs them to produce transitions that can warm-start the replay buffer (Plan 19 D2/D4), kept
behind an off-by-default trainer flag.
"""

from typing import Callable, Dict, List, Optional

import numpy as np
from actions import ActionType, encode_flat_action
from environment import FinancialLifeEnv

# A baseline policy maps the environment's current state to a flat discrete action index
# (Plan 18 D5: the index carries both the action type and the amount bucket).
BaselinePolicy = Callable[[FinancialLifeEnv], int]

_NO_ACTION = encode_flat_action(ActionType.NO_ACTION)

# Months of spending a household keeps as a cash buffer before investing (emergency_fund_first and
# the waterfall's minimum reserve).
_EMERGENCY_FUND_MONTHS = 6
_WATERFALL_RESERVE_MONTHS = 3


def _first_legal(env: FinancialLifeEnv, candidates: List[int]) -> int:
    """Return the first candidate action that is currently legal, else ``NO_ACTION``."""
    legal = set(env.get_legal_actions())
    for action in candidates:
        if action in legal:
            return action
    return _NO_ACTION


def _months_of_cash(env: FinancialLifeEnv) -> float:
    """Bank balance expressed in months of current annual spending."""
    annual_spending = env.person.spending.get_yearly_spending()
    monthly = max(annual_spending, 1.0) / 12.0
    return env.person.bank_account_balance / monthly


# ---------------------------------------------------------------------------
# Simple baselines (kept from Plan 18; regression detectors, not the real bar).
# ---------------------------------------------------------------------------


def do_nothing_policy(env: FinancialLifeEnv) -> int:
    """Never take a financial action."""
    return _NO_ACTION


def always_max_401k_policy(env: FinancialLifeEnv) -> int:
    """Contribute as much as allowed to the pre-tax 401k every year (the 100% bucket)."""
    return _first_legal(env, [encode_flat_action(ActionType.TRANSFER_BANK_TO_401K_PRETAX, 1.00)])


def save_25_percent_policy(env: FinancialLifeEnv) -> int:
    """Move a quarter of the bank balance into the brokerage each year (the 25% bucket)."""
    return _first_legal(env, [encode_flat_action(ActionType.TRANSFER_BANK_TO_BROKERAGE, 0.25)])


# ---------------------------------------------------------------------------
# Planner-grade baselines (Plan 19 D2). These are the bar the RL agent must beat.
# ---------------------------------------------------------------------------


def contribution_waterfall_policy(env: FinancialLifeEnv) -> int:
    """Tax-advantaged contribution waterfall while working.

    Advisor logic: fund the accounts with scarce, use-it-or-lose-it annual contribution room
    first (HSA, then traditional IRA — gated by the observed room fractions), then route the
    remaining savings to the pre-tax 401k, and finally to a taxable brokerage. (HSA/IRA are
    filled ahead of the 401k because the action layer caps only those accounts' annual room, so
    filling them first is what makes the waterfall actually cascade; the 401k then absorbs the
    rest.) A ~3-month cash reserve is kept before any investing, and nothing is contributed once
    retired (no earned income to defer).
    """
    if env.person.is_retired:
        return _NO_ACTION
    if _months_of_cash(env) < _WATERFALL_RESERVE_MONTHS:
        return _NO_ACTION

    features = env._compute_observation_features()
    ladder: List[int] = []
    if features["hsa_room_fraction"] > 0.01:
        ladder.append(encode_flat_action(ActionType.TRANSFER_BANK_TO_HSA, 0.50))
    if features["ira_room_fraction"] > 0.01:
        ladder.append(encode_flat_action(ActionType.TRANSFER_BANK_TO_IRA_TRADITIONAL, 0.50))
    ladder.append(encode_flat_action(ActionType.TRANSFER_BANK_TO_401K_PRETAX, 0.50))
    ladder.append(encode_flat_action(ActionType.TRANSFER_BANK_TO_BROKERAGE, 0.50))
    return _first_legal(env, ladder)


# Savings-rate glide path: contribution bucket (fraction of investable bank balance) steps up with
# age, mirroring the advice to save more as income rises and the horizon shortens.
_GLIDE_STEPS = ((35, 0.10), (45, 0.25), (55, 0.50), (200, 1.00))


def age_glide_policy(env: FinancialLifeEnv) -> int:
    """Age-based savings glide path: contribute a rising fraction of the bank balance to the
    pre-tax 401k as the person ages (10% under 35, up to 100% at 55+). No contributions once
    retired."""
    if env.person.is_retired:
        return _NO_ACTION
    age = env.person.age
    bucket = next(frac for threshold, frac in _GLIDE_STEPS if age < threshold)
    return _first_legal(env, [encode_flat_action(ActionType.TRANSFER_BANK_TO_401K_PRETAX, bucket)])


# Retirement drawdown ordering (Plan 19 D2): taxable/tax-deferred first, Roth last, matching the
# PaymentService withdrawal priorities so Roth compounding is preserved longest.
_DRAWDOWN_ORDER = (
    ActionType.WITHDRAW_BROKERAGE,
    ActionType.WITHDRAW_401K_PRETAX,
    ActionType.WITHDRAW_IRA_TRADITIONAL,
    ActionType.WITHDRAW_HSA,
    ActionType.WITHDRAW_401K_ROTH,
    ActionType.WITHDRAW_IRA_ROTH,
)


def four_percent_drawdown_policy(env: FinancialLifeEnv) -> int:
    """Accumulate to a nest egg while working, then draw it down in retirement.

    While working: build the nest egg by contributing half the bank balance to the pre-tax 401k.
    Once retired: withdraw from the portfolio each year (the smallest 10% bucket approximates the
    4% rule under the discretized action space), drawing taxable and tax-deferred accounts before
    Roth (Roth-last ordering, matching ``PaymentService`` priorities). Falls back to no action if
    nothing is drawable."""
    if not env.person.is_retired:
        return _first_legal(env, [encode_flat_action(ActionType.TRANSFER_BANK_TO_401K_PRETAX, 0.50)])
    candidates = [encode_flat_action(action_type, 0.10) for action_type in _DRAWDOWN_ORDER]
    return _first_legal(env, candidates)


def emergency_fund_first_policy(env: FinancialLifeEnv) -> int:
    """Fill a 6-month cash buffer before investing, then invest the surplus.

    Below a 6-month cash cushion, let cash accumulate (no action). Above it, invest via the same
    tax-advantaged waterfall so the cushion is protected first. No contributions once retired."""
    if env.person.is_retired:
        return _NO_ACTION
    if _months_of_cash(env) < _EMERGENCY_FUND_MONTHS:
        return _NO_ACTION
    return contribution_waterfall_policy(env)


BASELINES: Dict[str, BaselinePolicy] = {
    "do_nothing": do_nothing_policy,
    "always_max_401k": always_max_401k_policy,
    "save_25_percent": save_25_percent_policy,
    "contribution_waterfall": contribution_waterfall_policy,
    "age_glide": age_glide_policy,
    "four_percent_drawdown": four_percent_drawdown_policy,
    "emergency_fund_first": emergency_fund_first_policy,
}

# The planner-grade policies that define the "intelligent" bar (D3). The simple policies stay in
# BASELINES as regression detectors but are not part of the bar.
PLANNER_BASELINES = (
    "contribution_waterfall",
    "age_glide",
    "four_percent_drawdown",
    "emergency_fund_first",
)


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


def collect_teacher_experiences(
    env: FinancialLifeEnv,
    policy: BaselinePolicy,
    seeds: List[int],
    max_per_seed: Optional[int] = None,
) -> List[tuple]:
    """Roll a teacher ``policy`` and return replay transitions for warm-starting (Plan 19 D2/D4).

    Each transition is ``(state, action, reward, next_state, done, legal_actions,
    next_legal_actions)`` — the exact tuple ``FinancialDQNAgent.store_experience`` expects — so a
    trainer can seed the buffer with expert trajectories. Off by default (imitation can bias the
    policy); the trainer exposes it behind a flag and the eval report compares with/without.
    """
    transitions: List[tuple] = []
    for seed in seeds:
        state, _ = env.reset(seed=seed)
        steps = 0
        while True:
            legal_actions = env.get_legal_actions()
            action = policy(env)
            next_state, reward, terminated, truncated, _ = env.step(action)
            done = terminated or truncated
            next_legal_actions = env.get_legal_actions()
            transitions.append((state, action, float(reward), next_state, done, legal_actions, next_legal_actions))
            state = next_state
            steps += 1
            if done or (max_per_seed is not None and steps >= max_per_seed):
                break
    return transitions
