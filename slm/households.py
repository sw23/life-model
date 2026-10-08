# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Household distributions for adviser data (SLM-only; the RL scenarios are untouched).

The adviser's households start from the RL environment's four point scenarios and widen them in
the ways the decision data needs:

* **Older households.** The RL scenarios start everyone at 19-38, where drawdown and glide-path
  levers barely matter. ``late_career`` and ``pre_retiree`` add households in their late 40s to
  60s with larger cash savings, so every lever on the menu faces a household it can help.
* **Economy variety.** Each household draws a named economy (about half the stochastic baseline,
  the rest boom / high-inflation / deflation / conservative / aggressive). ``recession`` is never
  drawn: the eval harness holds it out as its out-of-distribution condition.
* **Retirement-income context.** Every household carries Social Security (claimed at its
  retirement age, clipped to 62-70), an employer match offer, and age-calibrated starting 401k /
  brokerage balances (drawn by the RL ``EpisodeSampler``). Without them a 57-year-old retired on a
  decade of bank savings and no benefit, and almost every older household was insolvent under
  every lever.
* **Budgeted children and healthcare.** Children are part of the household's spending, not a cost stacked on top
  of a childless budget. The sampled spending is the household's *total* outlay; the starting
  child costs are carved out of it (the rest is base spending), and the draw keeps at most as many
  children as fit in half the budget. Stacking them made over a third of households insolvent under
  every strategy, which leaves the label with nothing to learn.
"""

from dataclasses import replace

import numpy as np

from deepqlearning.envs.financial.scenarios import HOUSEHOLD_SCENARIOS, EpisodeSampler, HouseholdScenario
from life_model.config.financial_config import default_financial_config
from life_model.dependents.child import Child
from life_model.insurance.social_security import get_max_delayed_retirement_credit_age, get_min_early_retirement_age
from life_model.people.person import GenderAtBirth

# Named economies drawn per household; None is the stochastic baseline. "recession" is held out
# for evaluation (AdviserEvaluator.held_out_scenario) and must not appear here.
TRAIN_ECONOMIES: tuple[str | None, ...] = (
    None,
    None,
    None,
    None,
    None,
    "boom",
    "high_inflation",
    "deflation",
    "conservative",
    "aggressive",
)

# Children never take more than this share of the household's total spending at the start year.
MAX_CHILD_SHARE_OF_SPENDING = 0.5

# The RL low_earner point spends 83% of gross pay; with taxes and the medical cost budgeted inside
# spending that leaves nothing to save, and three quarters of its households were insolvent under
# every lever (labels with nothing to learn). The adviser's low earner spends 75% of gross instead.
_LOW_EARNER_SPENDING = 22500

SLM_SCENARIOS: dict[str, HouseholdScenario] = {
    **{name: replace(s, economy_scenarios=TRAIN_ECONOMIES) for name, s in HOUSEHOLD_SCENARIOS.items()},
    "low_earner": replace(
        HOUSEHOLD_SCENARIOS["low_earner"],
        point={**HOUSEHOLD_SCENARIOS["low_earner"].point, "initial_spending": _LOW_EARNER_SPENDING},
        economy_scenarios=TRAIN_ECONOMIES,
    ),
    "late_career": HouseholdScenario(
        point={
            "person_start_age": 50,
            "person_retirement_age": 65,
            "person_gender": GenderAtBirth.FEMALE,
            "initial_salary": 95000,
            "initial_bank_balance": 30000,
            "initial_spending": 57000,
            "employer_match_rate": 0.5,
            "employer_match_cap": 0.06,
            "initial_401k_pretax": 340000,
            "initial_401k_roth": 60000,
            "initial_brokerage": 50000,
            "retirement_spending_ratio": 0.8,
        },
        start_age_spread=4,
        economy_scenarios=TRAIN_ECONOMIES,
    ),
    "pre_retiree": HouseholdScenario(
        point={
            "person_start_age": 57,
            "person_retirement_age": 67,
            "person_gender": GenderAtBirth.MALE,
            "initial_salary": 85000,
            "initial_bank_balance": 40000,
            "initial_spending": 55000,
            "employer_match_rate": 0.5,
            "employer_match_cap": 0.06,
            "initial_401k_pretax": 450000,
            "initial_401k_roth": 60000,
            "initial_brokerage": 80000,
            "retirement_spending_ratio": 0.8,
        },
        retirement_age_spread=2,
        economy_scenarios=TRAIN_ECONOMIES,
    ),
}


class _ScenarioSampler(EpisodeSampler):
    """EpisodeSampler over an SLM scenario definition (the RL sampler looks names up itself)."""

    def __init__(self, name: str):
        if name not in SLM_SCENARIOS:
            raise KeyError(f"Unknown household scenario {name!r}; expected one of {list(SLM_SCENARIOS)}")
        self.scenario_name = name
        self.scenario = SLM_SCENARIOS[name]


def _starting_child_cost(age: int) -> float:
    """Start-year cost of a child of ``age`` (the simulator's age bands, before inflation)."""
    cfg = default_financial_config().dependents
    if age >= cfg.adult_age:
        return 0.0
    return cfg.childcare_annual_cost if age < Child.CHILDCARE_END_AGE else cfg.school_age_annual_cost


def _starting_medical_cost(age: int) -> float:
    """Start-year out-of-pocket medical cost for a person of ``age`` (the simulator's age bands)."""
    for band in default_financial_config().healthcare.medical_cost_bands:
        if age <= band.max_age:
            return float(band.annual_cost)
    return 0.0


def _add_children_and_healthcare(rng: np.random.Generator, household: dict) -> dict:
    """Draw 0-3 children inside the household's budget and price healthcare (deterministic under ``rng``).

    Like the children, the start-year medical cost is carved out of the sampled spending rather
    than stacked on it: the sampled spending is the household's total outlay.
    """
    start_age = int(household["person_start_age"])
    # Dependents are plausible for the person's age: none before 20, under-18s only.
    max_child_age = min(17, start_age - 20)
    children: list[int] = []
    if max_child_age >= 0:
        num_children = int(rng.integers(0, 4))
        children = sorted(int(rng.integers(0, max_child_age + 1)) for _ in range(num_children))
    total_spending = float(household["initial_spending"])
    # Drop the costliest (youngest) children until what remains fits the budget share.
    while children and sum(map(_starting_child_cost, children)) > MAX_CHILD_SHARE_OF_SPENDING * total_spending:
        children.pop(0)
    household["children_ages"] = children
    medical = _starting_medical_cost(start_age)
    household["initial_spending"] = round(total_spending - sum(map(_starting_child_cost, children)) - medical, 2)
    household["models_healthcare"] = True
    return household


def resolved_ss_claim_age(household: dict) -> int:
    """The Social Security claiming age the env uses for ``household`` (its retirement age clipped
    to the claiming window, unless the household sets ``ss_claim_age``)."""
    cfg = default_financial_config()
    claim = household.get("ss_claim_age")
    if claim is None:
        claim = household["person_retirement_age"]
    return int(min(max(int(claim), get_min_early_retirement_age(cfg)), get_max_delayed_retirement_credit_age(cfg)))


def sample_households(scenarios: list[str], n_per_scenario: int, generation_seed: int) -> list[tuple[str, dict, int]]:
    """Draw every household sequentially from one seeded RNG (scenario-major, deterministic)."""
    rng = np.random.default_rng(generation_seed)
    items: list[tuple[str, dict, int]] = []
    index = 0
    for scenario in scenarios:
        sampler = _ScenarioSampler(scenario)
        for _ in range(n_per_scenario):
            items.append((scenario, _add_children_and_healthcare(rng, sampler.sample(rng)), index))
            index += 1
    return items
