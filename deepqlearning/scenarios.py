# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Episode scenario definitions and domain randomization (Plan 18 D6).

Each named household scenario carries a *point* household (the legacy deterministic
configuration — used exactly when randomization is off) and the spreads for drawing a
randomized household around it. :class:`EpisodeSampler` performs the draw using the
environment's Gymnasium ``np_random`` generator, so the same reset seed always produces the
same household and therefore the same trajectory.

Randomized quantities: start age, retirement age, salary, starting bank balance, spending
(as a fraction of salary), and gender. A scenario may also carry a list of named economy
scenarios (see ``life_model.config.scenarios``) to sample per episode as a curriculum knob.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import numpy as np

from life_model.people.person import GenderAtBirth


@dataclass(frozen=True)
class HouseholdScenario:
    """A named household scenario: a legacy point household plus randomization spreads."""

    #: The exact household used when randomization is off (the legacy point scenario).
    point: Dict[str, Any]
    #: Genders drawn from (uniformly) when randomizing.
    genders: Tuple[GenderAtBirth, ...] = (GenderAtBirth.MALE, GenderAtBirth.FEMALE)
    #: +/- years around the point start age (inclusive uniform integer draw).
    start_age_spread: int = 3
    #: +/- years around the point retirement age (inclusive uniform integer draw).
    retirement_age_spread: int = 3
    #: Multiplicative uniform range applied to the point salary.
    salary_factor_range: Tuple[float, float] = (0.7, 1.3)
    #: Multiplicative uniform range applied to the point bank balance.
    bank_factor_range: Tuple[float, float] = (0.25, 1.75)
    #: Multiplicative uniform range applied to the point spending/salary fraction.
    spending_factor_range: Tuple[float, float] = (0.85, 1.15)
    #: Named economy scenarios to draw from per episode (None = the env's configured economy).
    #: Empty means the economy is never sampled here.
    economy_scenarios: Tuple[Optional[str], ...] = field(default=())


# The four point scenarios previously hardcoded in FinancialLifeEnvGenerator, now the
# distribution anchors. Point values must stay exactly equal to the legacy configurations so
# that randomize=False reproduces the historical fixed households.
HOUSEHOLD_SCENARIOS: Dict[str, HouseholdScenario] = {
    "basic": HouseholdScenario(
        point={
            "person_start_age": 25,
            "person_retirement_age": 65,
            "person_gender": GenderAtBirth.MALE,
            "initial_salary": 50000,
            "initial_bank_balance": 10000,
            "initial_spending": 30000,
        },
    ),
    "high_earner": HouseholdScenario(
        point={
            "person_start_age": 30,
            "person_retirement_age": 65,
            "person_gender": GenderAtBirth.MALE,
            "initial_salary": 120000,
            "initial_bank_balance": 50000,
            "initial_spending": 60000,
        },
    ),
    "low_earner": HouseholdScenario(
        point={
            "person_start_age": 22,
            "person_retirement_age": 65,
            "person_gender": GenderAtBirth.FEMALE,
            "initial_salary": 30000,
            "initial_bank_balance": 2000,
            "initial_spending": 25000,
        },
    ),
    "mid_career": HouseholdScenario(
        point={
            "person_start_age": 35,
            "person_retirement_age": 62,
            "person_gender": GenderAtBirth.FEMALE,
            "initial_salary": 80000,
            "initial_bank_balance": 30000,
            "initial_spending": 50000,
        },
    ),
}


class EpisodeSampler:
    """Draws randomized episode households from a named scenario's distributions.

    All randomness comes from the ``np.random.Generator`` passed to :meth:`sample` (the env's
    ``np_random``), so a given reset seed reproduces the same household exactly.
    """

    def __init__(self, scenario: str = "basic"):
        if scenario not in HOUSEHOLD_SCENARIOS:
            raise KeyError(f"Unknown household scenario {scenario!r}; expected one of {list(HOUSEHOLD_SCENARIOS)}")
        self.scenario_name = scenario
        self.scenario = HOUSEHOLD_SCENARIOS[scenario]

    def point_household(self) -> Dict[str, Any]:
        """The scenario's exact legacy point household (used when randomization is off)."""
        return dict(self.scenario.point)

    def sample(self, rng: np.random.Generator) -> Dict[str, Any]:
        """Draw one randomized household around the scenario's point values."""
        s = self.scenario
        p = s.point

        start_age = int(
            rng.integers(p["person_start_age"] - s.start_age_spread, p["person_start_age"] + s.start_age_spread + 1)
        )
        retirement_age = int(
            rng.integers(
                p["person_retirement_age"] - s.retirement_age_spread,
                p["person_retirement_age"] + s.retirement_age_spread + 1,
            )
        )
        # A retirement age at least a decade out keeps every episode a meaningful planning task.
        retirement_age = max(retirement_age, start_age + 10)

        salary = float(p["initial_salary"] * rng.uniform(*s.salary_factor_range))
        bank_balance = float(p["initial_bank_balance"] * rng.uniform(*s.bank_factor_range))
        spending_fraction = (p["initial_spending"] / p["initial_salary"]) * rng.uniform(*s.spending_factor_range)
        spending = float(salary * spending_fraction)
        gender = s.genders[int(rng.integers(0, len(s.genders)))]

        household: Dict[str, Any] = {
            "person_start_age": start_age,
            "person_retirement_age": retirement_age,
            "person_gender": gender,
            "initial_salary": round(salary, 2),
            "initial_bank_balance": round(bank_balance, 2),
            "initial_spending": round(spending, 2),
        }
        if s.economy_scenarios:
            choice = s.economy_scenarios[int(rng.integers(0, len(s.economy_scenarios)))]
            household["economy_scenario"] = choice
        return household
