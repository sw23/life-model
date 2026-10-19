# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Scripted baseline policies for the financial life environment.

These non-learning policies give the RL agent something to beat. The simple ones
(``do_nothing``, ``always_max_401k``, ``save_25_percent``) double as regression detectors — an
agent that cannot beat "do nothing" on the same seeds is a sign the environment or agent is
broken. The **planner-grade** policies (plus ``always_max_401k``, the strongest scripted
policy) are the real bar: they encode strategies a human advisor would recognize — a tax-advantaged contribution waterfall, an age-based savings
glide path, a 4%-rule retirement drawdown with Roth-last ordering, and an emergency-fund-first
rule. "Intelligent" is defined as beating *these* on the default objective.

Every policy is a pure function of the environment's current state and returns a **legal** flat
action index (or ``NO_ACTION``, which is always legal), so a policy never desyncs from the action
mask. Being a deterministic function of the seeded state, each policy is reproducible per seed.

**Factored space.** :data:`FACTORED_BASELINES` expresses the same heuristics, under the
same names, as standing-policy vectors (``envs/financial/policies.py``), so an agent trained on the
factored space is compared with like: e.g. ``always_max_401k`` sets the pre-tax deferral to the
highest rate the household's take-home pay can carry, ``four_percent_drawdown`` draws taxable, then
pre-tax, then Roth (``withdrawal_order=brokerage_first``) once retired. Every factored baseline claims
Social Security at the household's configured claiming age (what the flat env does on its own), so
the two spaces differ only in how savings and drawdown are expressed. :func:`baselines_for` picks
the right set for an environment.

The planner policies are also usable as curriculum teachers: :func:`collect_teacher_experiences`
runs them to produce transitions that can warm-start the replay buffer, kept
behind an off-by-default trainer flag.
"""

from collections.abc import Callable

import numpy as np

from ..envs.financial.actions import ActionType, encode_flat_action
from ..envs.financial.environment import FinancialLifeEnv
from ..envs.financial.policies import SLOT_BY_NAME, SLOTS, encode_policy_action
from ..envs.financial.scenarios import ss_claim_age

# A baseline policy maps the environment's current state to a flat discrete action index
# (the index carries both the action type and the amount bucket).
BaselinePolicy = Callable[[FinancialLifeEnv], int]

_NO_ACTION = encode_flat_action(ActionType.NO_ACTION)

# Months of spending a household keeps as a cash buffer before investing (emergency_fund_first and
# the waterfall's minimum reserve).
_EMERGENCY_FUND_MONTHS = 6
_WATERFALL_RESERVE_MONTHS = 3


def _first_legal(env: FinancialLifeEnv, candidates: list[int]) -> int:
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
# Simple baselines (regression detectors, not the real bar).
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
# Planner-grade baselines. These are the bar the RL agent must beat.
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
    ladder: list[int] = []
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
    age = env.decision_age
    bucket = next(frac for threshold, frac in _GLIDE_STEPS if age < threshold)
    return _first_legal(env, [encode_flat_action(ActionType.TRANSFER_BANK_TO_401K_PRETAX, bucket)])


# Retirement drawdown ordering: taxable/tax-deferred first, Roth last, matching the
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


BASELINES: dict[str, BaselinePolicy] = {
    "do_nothing": do_nothing_policy,
    "always_max_401k": always_max_401k_policy,
    "save_25_percent": save_25_percent_policy,
    "contribution_waterfall": contribution_waterfall_policy,
    "age_glide": age_glide_policy,
    "four_percent_drawdown": four_percent_drawdown_policy,
    "emergency_fund_first": emergency_fund_first_policy,
}

# The policies that define the "intelligent" bar: the planner-grade heuristics plus
# ``always_max_401k``, which scored at least as well as every planner heuristic in the committed
# reports — a bar that excludes the best scripted policy certifies nothing. The other simple
# policies stay in BASELINES as regression detectors.
PLANNER_BASELINES = (
    "always_max_401k",
    "contribution_waterfall",
    "age_glide",
    "four_percent_drawdown",
    "emergency_fund_first",
)


# ---------------------------------------------------------------------------
# The same heuristics in the factored (standing-policy) action space.
# ---------------------------------------------------------------------------

#: A factored baseline maps the env's state to a MultiDiscrete action vector.
FactoredPolicy = Callable[[FinancialLifeEnv], np.ndarray]

# Pre-tax 401(k) rates of the factored space, lowest first ("max" is the 402(g) limit).
_RATE_STEPS = (0.0, 3.0, 6.0, 10.0, 15.0)
_AGE_GLIDE_RATES = ((35, "6"), (45, "10"), (55, "15"), (200, "max"))


def _legal_vector(env: FinancialLifeEnv, changes: dict[str, str]) -> np.ndarray:
    """The action setting ``changes`` (slot -> value), dropping any value illegal now (that slot then
    keeps its standing value), and claiming Social Security at the household's claiming age."""
    masks = env.legal_slot_masks()
    standing = env.policy_vector()
    wanted = dict(changes)
    if _claim_due(env):
        wanted["claim_social_security"] = "now"
    legal: dict[str, str] = {}
    for i, slot in enumerate(SLOTS):
        value = wanted.get(slot.name)
        if value is None or (value == standing.get(slot.name) and slot.name != "spending_adjust"):
            continue
        if masks[i][slot.index(value)]:
            legal[slot.name] = value
    return encode_policy_action(legal)


def _claim_due(env: FinancialLifeEnv) -> bool:
    """Whether the household's configured claiming age (the flat env's automatic claim) has come."""
    ss = env.person.social_security
    if ss is None or ss.is_claiming or env.person.is_deceased:
        return False
    return env.person.age_years_fractional >= ss_claim_age(env.episode_household, env.model.config)


def _take_home_surplus(env: FinancialLifeEnv) -> float:
    """Pay left after spending and an estimate of the year's income and payroll taxes (0 when
    retired): what payroll deferrals can absorb without the waterfall tapping savings."""
    person = env.person
    pay = sum(job.salary.base for job in person.jobs if not job.retired)
    if pay <= 0:
        return 0.0
    params = env.model.tax_params_for_year(env.model.year)
    taxable = max(0.0, pay - params.standard_deduction.single)
    tax = 0.0
    for lower, upper, rate in params.tax_brackets.single:
        if taxable <= lower:
            break
        tax += (min(taxable, upper) - lower) * rate / 100.0
    fica = 0.0765 * pay
    return pay - person.spending.get_yearly_spending() - tax - fica


def affordable_401k_rate(env: FinancialLifeEnv) -> str:
    """The highest pre-tax 401(k) rate value (``"0"`` ... ``"15"``, ``"max"``) whose yearly deferral the
    household's take-home surplus covers (conservatively: the deferral's own tax saving is ignored)."""
    person = env.person
    pay = sum(job.salary.base for job in person.jobs if not job.retired)
    if pay <= 0:
        return "0"
    spare = _take_home_surplus(env)
    limit = env.model.year_config.get_job_401k_contrib_limit(person.age_in(env.model.year))
    if spare >= limit:
        return "max"
    best = "0"
    for rate in _RATE_STEPS:
        if pay * rate / 100.0 <= spare:
            best = f"{rate:g}"
    return best


def _working(env: FinancialLifeEnv) -> bool:
    return not env.person.is_retired and not env.person.is_deceased


def factored_do_nothing_policy(env: FinancialLifeEnv) -> np.ndarray:
    """Keep every standing policy (claims Social Security at the household's age, as the flat env does)."""
    return _legal_vector(env, {})


def factored_always_max_401k_policy(env: FinancialLifeEnv) -> np.ndarray:
    """Defer the most the take-home pay carries to the pre-tax 401(k) (the 402(g) limit when it can)."""
    if not _working(env):
        return _legal_vector(env, {})
    return _legal_vector(env, {"pretax_401k_rate": affordable_401k_rate(env)})


def factored_save_25_percent_policy(env: FinancialLifeEnv) -> np.ndarray:
    """Sweep surplus cash (above six months of spending) to the brokerage every year."""
    return _legal_vector(env, {"sweep_policy": "sweep_to_brokerage"})


def factored_contribution_waterfall_policy(env: FinancialLifeEnv) -> np.ndarray:
    """HSA and IRA to their limits, the pre-tax 401(k) at the affordable rate, the rest swept to the
    brokerage; contributions stop at retirement (the env drops them)."""
    if not _working(env):
        return _legal_vector(env, {"sweep_policy": "sweep_to_brokerage"})
    return _legal_vector(
        env,
        {
            "hsa_contribution": "max",
            "ira_contribution": "traditional_max",
            "pretax_401k_rate": affordable_401k_rate(env),
            "sweep_policy": "sweep_to_brokerage",
        },
    )


def factored_age_glide_policy(env: FinancialLifeEnv) -> np.ndarray:
    """Pre-tax 401(k) rate stepping up with age (6% under 35, 10% to 45, 15% to 55, then the limit),
    capped at what take-home pay carries."""
    if not _working(env):
        return _legal_vector(env, {})
    age = env.decision_age
    target = next(rate for threshold, rate in _AGE_GLIDE_RATES if age < threshold)
    affordable = affordable_401k_rate(env)
    order = SLOT_BY_NAME["pretax_401k_rate"].values
    rate = target if order.index(target) <= order.index(affordable) else affordable
    return _legal_vector(env, {"pretax_401k_rate": rate})


def factored_four_percent_drawdown_policy(env: FinancialLifeEnv) -> np.ndarray:
    """Accumulate in the pre-tax 401(k) while working; once retired draw taxable, then pre-tax, then
    Roth savings (``brokerage_first``: Roth last)."""
    if not _working(env):
        return _legal_vector(env, {"withdrawal_order": "brokerage_first"})
    return _legal_vector(env, {"pretax_401k_rate": affordable_401k_rate(env)})


def factored_emergency_fund_first_policy(env: FinancialLifeEnv) -> np.ndarray:
    """Below six months of cash, no bank-funded saving (IRA off, cash held; payroll 401(k) at 3%);
    above it, the contribution waterfall."""
    if not _working(env):
        return _legal_vector(env, {"sweep_policy": "sweep_to_brokerage"})
    if _months_of_cash(env) < _EMERGENCY_FUND_MONTHS:
        return _legal_vector(env, {"ira_contribution": "none", "sweep_policy": "hold_cash", "pretax_401k_rate": "3"})
    return factored_contribution_waterfall_policy(env)


FACTORED_BASELINES: dict[str, FactoredPolicy] = {
    "do_nothing": factored_do_nothing_policy,
    "always_max_401k": factored_always_max_401k_policy,
    "save_25_percent": factored_save_25_percent_policy,
    "contribution_waterfall": factored_contribution_waterfall_policy,
    "age_glide": factored_age_glide_policy,
    "four_percent_drawdown": factored_four_percent_drawdown_policy,
    "emergency_fund_first": factored_emergency_fund_first_policy,
}


def baselines_for(env_or_config) -> dict[str, Callable]:
    """The baseline set matching an env (or an env config): :data:`FACTORED_BASELINES` for
    ``action_space="factored"``, else :data:`BASELINES`."""
    if isinstance(env_or_config, dict):
        factored = env_or_config.get("action_space", "flat") == "factored"
    else:
        factored = bool(getattr(getattr(env_or_config, "unwrapped", env_or_config), "factored", False))
    return dict(FACTORED_BASELINES if factored else BASELINES)


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


def evaluate_baseline(env: FinancialLifeEnv, policy: BaselinePolicy, seeds: list[int]) -> float:
    """Average reward of ``policy`` over the given seeds."""
    return float(np.mean([run_baseline_episode(env, policy, seed) for seed in seeds]))


def evaluate_all_baselines(env: FinancialLifeEnv, seeds: list[int]) -> dict[str, float]:
    """Average reward for every named baseline (in the env's action space) over the given seeds."""
    return {name: evaluate_baseline(env, policy, seeds) for name, policy in baselines_for(env).items()}


def collect_teacher_experiences(
    env: FinancialLifeEnv,
    policy: BaselinePolicy,
    seeds: list[int],
    max_per_seed: int | None = None,
) -> list[tuple]:
    """Roll a teacher ``policy`` and return replay transitions for warm-starting.

    Each transition is ``(state, action, reward, next_state, done, legal_actions,
    next_legal_actions)`` — the exact tuple ``DQNAgent.store_experience`` expects — so a
    trainer can seed the buffer with expert trajectories. Off by default (imitation can bias the
    policy); the trainer exposes it behind a flag and the eval report compares with/without.
    """
    transitions: list[tuple] = []
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
