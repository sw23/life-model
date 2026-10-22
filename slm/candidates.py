# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Executable plans and reference policies.

This is the bridge from a decision *name* to something the simulator can run: an env config (a
plan's savings and claiming levers change the household the env builds) plus a per-year policy
(its routing and drawdown levers). Two kinds of name resolve here:

* **plans** (:mod:`slm.strategies`) — what the adviser recommends; and
* **reference policies** — the RL planner heuristics (contribution waterfall, age glide, emergency
  fund first, 4% drawdown). They are not answers the adviser can give; the eval harness scores them
  on the same seeds as the bar a recommendation should clear.

A plan executes several money moves a year (a 401k deferral split, the overflow to brokerage, a
bracket-filling withdrawal) through the env's own action executor, so each move obeys the same
legality, 402(g), employer-match, and tax rules as an RL action; the policy then returns
``NO_ACTION`` for the year.

**Policy vectors.** With ``action_space="factored"`` a candidate runs on the RL env's
standing-policy space instead: :func:`plan_policy_vector` writes the plan in that vocabulary (a
401(k) rate per bucket, an IRA / HSA choice, a sweep, a withdrawal order, a claim, a Roth
conversion) and :func:`candidate_policy` returns the action vector each decision. The flat path is
the default, and the committed SLM data and reports were generated on it.

**Teacher gating:** no trained RL policy is a candidate. Per the committed protocol reports no
learned policy cleared the pre-registered bar, so distilling from one would silently cap the
student.

Imports the RL package, so the repo root must be on ``sys.path`` (the SLM test conftest arranges
this, mirroring ``deepqlearning/tests/conftest.py``).
"""

from collections.abc import Callable

import numpy as np

from deepqlearning.envs.financial.actions import ActionType, _remaining_401k_deferral_room
from deepqlearning.envs.financial.environment import FinancialLifeEnv
from deepqlearning.envs.financial.policies import SLOT_BY_NAME
from deepqlearning.evaluation.baselines import (
    _NO_ACTION,
    FACTORED_BASELINES,
    BaselinePolicy,
    _legal_vector,
    affordable_401k_rate,
    age_glide_policy,
    contribution_waterfall_policy,
    emergency_fund_first_policy,
    four_percent_drawdown_policy,
)
from life_model.config.financial_config import default_financial_config
from life_model.insurance.social_security import (
    get_max_delayed_retirement_credit_age,
    get_min_early_retirement_age,
    get_normal_retirement_age,
)

from .strategies import Plan

#: Months of spending kept in cash before any savings are invested.
CASH_RESERVE_MONTHS = 3
#: The bracket whose top edge the split-routing and bracket-fill levers aim at (federal rate, %).
TARGET_BRACKET_RATE = 12

#: Reference policies (RL planner heuristics): scored by the eval as the bar, never recommended.
REFERENCE_POLICIES: dict[str, BaselinePolicy] = {
    "contribution_waterfall": contribution_waterfall_policy,
    "age_glide": age_glide_policy,
    "emergency_fund_first": emergency_fund_first_policy,
    "four_percent_drawdown": four_percent_drawdown_policy,
}


def _bracket_top(env: FinancialLifeEnv, rate: int = TARGET_BRACKET_RATE) -> float:
    """Gross ordinary income at the top of the ``rate``% federal bracket this year (single filer)."""
    params = env.model.tax_params_for_year(env.model.year)
    upper = next(up for _low, up, r in params.tax_brackets.single if r == rate)
    return upper + params.standard_deduction.single


def _execute(env: FinancialLifeEnv, action_type: ActionType, amount: float) -> None:
    if amount > 1.0:
        env.action_executor.execute_action(env.person, action_type, amount=amount)


def _working_year(env: FinancialLifeEnv, plan: Plan) -> None:
    """Invest cash above the reserve: 401k deferral per the routing lever, the rest to brokerage."""
    person = env.person
    reserve = person.spending.get_yearly_spending() * CASH_RESERVE_MONTHS / 12.0
    investable = person.bank_account_balance - reserve
    if investable <= 0:
        return
    deferral = min(investable, _remaining_401k_deferral_room(person))
    if plan.routing == "pretax":
        pretax = deferral
    elif plan.routing == "roth":
        pretax = 0.0
    else:  # split: pre-tax the income above the target bracket's top edge, Roth the rest
        wages = sum(job.salary.base + job.salary.bonus for job in person.jobs if not job.retired)
        pretax = min(deferral, max(0.0, wages - _bracket_top(env)))
    _execute(env, ActionType.TRANSFER_BANK_TO_401K_PRETAX, pretax)
    _execute(env, ActionType.TRANSFER_BANK_TO_401K_ROTH, deferral - pretax)
    _execute(env, ActionType.TRANSFER_BANK_TO_BROKERAGE, person.bank_account_balance - reserve)


def _retired_year(env: FinancialLifeEnv, plan: Plan) -> None:
    """Bracket fill: draw pre-tax savings up to the target bracket's top (taxed at <= its rate)."""
    if plan.drawdown != "bracketfill":
        return
    features = env._compute_observation_features()
    deflator = env.model.economy.cumulative_inflation(env.model.year)
    # Ordinary income already coming this year: the RMD (real $M -> nominal $) plus the taxable
    # share (at most 85%) of Social Security once it is being paid. (Retired: no wages.)
    ss = env.social_security
    claiming = ss is not None and env.model.year >= ss.withdrawal_start_year
    already = features["projected_rmd"] * 1_000_000.0 * deflator
    already += 0.85 * env._ss_annual_benefit() if claiming else 0.0
    fill = max(0.0, _bracket_top(env) - already)
    available = sum(acc.pretax_balance for acc in env.person.all_retirement_accounts)
    _execute(env, ActionType.WITHDRAW_401K_PRETAX, min(fill, available))
    # Cash beyond a year of spending is invested rather than left in the bank.
    _execute(
        env,
        ActionType.TRANSFER_BANK_TO_BROKERAGE,
        env.person.bank_account_balance - env.person.spending.get_yearly_spending(),
    )


def plan_policy(plan: Plan) -> BaselinePolicy:
    """The per-year policy realizing ``plan``'s routing and drawdown levers."""

    def policy(env: FinancialLifeEnv) -> int:
        if env.person.is_retired:
            _retired_year(env, plan)
        else:
            _working_year(env, plan)
        return _NO_ACTION

    policy.__name__ = f"plan_{plan.name}"
    return policy


def claim_age_for(plan: Plan, retirement_age: int) -> int:
    """The Social Security claiming age ``plan`` implies for someone retiring at ``retirement_age``.

    Claiming is never before retirement (the earnings test is not modeled, so claiming while working
    would be free money), and always within the 62-70 window.
    """
    cfg = default_financial_config()
    low, high = get_min_early_retirement_age(cfg), get_max_delayed_retirement_credit_age(cfg)
    target = {
        "claimret": retirement_age,
        "claimfra": max(retirement_age, get_normal_retirement_age(cfg)),
        "claim70": high,
    }[plan.claim]
    claim = max(target, low)
    if retirement_age <= high:
        claim = max(claim, retirement_age)
    return int(min(claim, high))


def candidate_household(name: str, household: dict) -> dict:
    """The household config a candidate runs on (a plan's savings/claim levers applied)."""
    plan = Plan.parse(name)
    if plan is None:
        return dict(household)
    return {
        **household,
        "savings_boost_pct": plan.savings_boost_pct,
        "ss_claim_age": claim_age_for(plan, int(household["person_retirement_age"])),
    }


#: Action spaces a candidate can run on (see the module docstring).
CANDIDATE_ACTION_SPACES = ("flat", "factored")

_RATE_VALUES = SLOT_BY_NAME["pretax_401k_rate"].values  # "0", "3", "6", "10", "15", "max"


def _rate_pct(env: FinancialLifeEnv, value: str) -> float:
    """A 401(k) rate value as a percent of this year's pay ("max": the 402(g) limit's share)."""
    if value != "max":
        return float(value)
    person = env.person
    pay = sum(job.salary.base for job in person.jobs if not job.retired)
    limit = env.model.year_config.get_job_401k_contrib_limit(person.age_in(env.model.year))
    return 100.0 * limit / pay if pay > 0 else 0.0


def _split_rates(env: FinancialLifeEnv, total: str) -> tuple[str, str]:
    """``(pretax, roth)`` rate values for the ``split`` routing: pre-tax on pay above the target
    bracket's top edge (the smallest step covering it), Roth for the rest of ``total``."""
    person = env.person
    wages = sum(job.salary.base + job.salary.bonus for job in person.jobs if not job.retired)
    if wages <= 0 or total == "0":
        return "0", "0"
    total_pct = _rate_pct(env, total)
    needed = max(0.0, wages - _bracket_top(env)) / wages * 100.0
    pretax = next((v for v in _RATE_VALUES if _rate_pct(env, v) >= needed), "max")
    if _rate_pct(env, pretax) >= total_pct:
        return total, "0"
    left = total_pct - _rate_pct(env, pretax)
    roth = "0"
    for value in _RATE_VALUES:
        if _rate_pct(env, value) <= left + 1e-9:
            roth = value
    return pretax, roth


def plan_policy_vector(plan: Plan, env: FinancialLifeEnv) -> dict[str, str]:
    """``plan`` in the RL env's standing-policy vocabulary (``envs/financial/policies.py``) at the
    env's current state: ``{slot: value}`` for the slots the plan sets.

    * **routing** — while working, the 401(k) deferral at the highest rate take-home pay carries
      (``evaluation.baselines.affordable_401k_rate``): all pre-tax, all Roth, or ``split`` (pre-tax on
      pay above the 12% bracket's top, Roth for the rest); savings beyond it are swept to the
      brokerage (``sweep_to_brokerage``; the sweep keeps six months of spending, the flat plan three).
    * **claim** — claiming at the plan's age is applied by the policy (the household carries the age).
    * **drawdown** — ``conventional`` keeps the default withdrawal order; ``bracketfill`` becomes a
      standing Roth conversion to the top of the 12% bracket once retired (the factored analog of
      drawing pre-tax money up to that edge: the bracket is filled by converting, not withdrawing).
    * **savings** — the savings boost is a household lever (``candidate_household``), the same in
      both spaces.
    """
    vector: dict[str, str] = {"sweep_policy": "sweep_to_brokerage", "withdrawal_order": "default"}
    working = not env.person.is_retired and not env.person.is_deceased
    if working:
        total = affordable_401k_rate(env)
        if plan.routing == "pretax":
            pretax, roth = total, "0"
        elif plan.routing == "roth":
            pretax, roth = "0", total
        else:
            pretax, roth = _split_rates(env, total)
        vector.update({"pretax_401k_rate": pretax, "roth_401k_rate": roth})
        vector["roth_conversion"] = "none"
    else:
        vector["roth_conversion"] = "to_bracket_12" if plan.drawdown == "bracketfill" else "none"
    return vector


def plan_factored_policy(plan: Plan) -> Callable[[FinancialLifeEnv], np.ndarray]:
    """The per-decision factored policy realizing ``plan`` (a ``MultiDiscrete`` action each step)."""

    def policy(env: FinancialLifeEnv) -> np.ndarray:
        return _legal_vector(env, plan_policy_vector(plan, env))

    policy.__name__ = f"plan_{plan.name}_factored"
    return policy


def candidate_policy(name: str, *, action_space: str = "flat") -> Callable[[FinancialLifeEnv], int]:
    """The per-decision policy for a plan or reference-policy name.

    ``action_space="factored"`` returns the plan's (or reference heuristic's) standing-policy version,
    for an env built with ``action_space="factored"``; the default is the flat-space policy.
    """
    if action_space not in CANDIDATE_ACTION_SPACES:
        raise ValueError(f"action_space must be one of {CANDIDATE_ACTION_SPACES}, got {action_space!r}")
    plan = Plan.parse(name)
    factored = action_space == "factored"
    if plan is not None:
        return plan_factored_policy(plan) if factored else plan_policy(plan)
    if name in REFERENCE_POLICIES:
        return FACTORED_BASELINES[name] if factored else REFERENCE_POLICIES[name]
    raise KeyError(f"unknown candidate {name!r}")
