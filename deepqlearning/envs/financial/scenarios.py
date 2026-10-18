# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Episode scenario definitions and domain randomization.

Each named household scenario carries a *point* household (the deterministic
configuration — used exactly when randomization is off) and the spreads for drawing a
randomized household around it. :class:`EpisodeSampler` performs the draw using the
environment's Gymnasium ``np_random`` generator, so the same reset seed always produces the
same household and therefore the same trajectory.

Randomized quantities: start age, retirement age, salary, starting bank balance, spending
(as a fraction of salary), gender, an employer 401k match, and starting invested balances. A
scenario may also carry a list of named economy scenarios (see ``life_model.config.scenarios``) to
sample per episode as a curriculum knob.

Starting invested balances are age-calibrated: total retirement savings is a multiple of salary
that follows the common "1x by 30, 3x by 40, 6x by 50, 8x by 60" planner benchmark
(:data:`SAVINGS_BENCHMARK`), scaled by a per-household factor drawn below 1 on average (most
households sit under the benchmark). A 50-year-old therefore arrives with a 401k, not only cash.
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from life_model.config.financial_config import FinancialConfig, default_financial_config
from life_model.insurance.social_security import get_max_delayed_retirement_credit_age, get_min_early_retirement_age
from life_model.people.person import GenderAtBirth
from life_model.spec import HouseholdSpec

#: Person id of the RL agent in the household spec.
AGENT_ID = "rl_agent"

#: Earliest year-of-age-62 SSA publishes bend points for; households turning 62 before it get no
#: Social Security (only artificial test households with start ages near 119 reach that).
FIRST_BEND_POINT_YEAR = 1979

#: The ``FinancialLifeEnv`` defaults of the env config keys that describe the household's
#: *construction* (read by :func:`household_spec`; a test keeps them equal to the env's defaults).
#: The episode's policy knobs (retirement spending ratio, savings boost, employer match, bequest tax
#: rate) are applied by the environment itself and are not part of the spec.
SPEC_ENV_DEFAULTS: dict[str, Any] = {
    "start_year": 2025,
    "person_max_age": 119,
    "account_growth": None,
    "spending_growth": None,
    "salary_growth": None,
    "social_security": True,
    "career_start_age": 22,
}
SPEC_ENV_KEYS = tuple(SPEC_ENV_DEFAULTS)

#: Retirement savings as a multiple of salary by age: the planner benchmark the starting balances
#: are calibrated to (linear between knots, 0 at the start of a career, flat after 67).
SAVINGS_BENCHMARK: tuple[tuple[int, float], ...] = ((22, 0.0), (30, 1.0), (40, 3.0), (50, 6.0), (60, 8.0), (67, 10.0))

#: Employer match offers drawn per household: (rate per deferred dollar, cap as a share of pay).
#: (0, 0) is "no match"; it appears twice so about a quarter of households have none.
MATCH_OFFERS: tuple[tuple[float, float], ...] = (
    (0.0, 0.0),
    (0.0, 0.0),
    (0.5, 0.06),
    (0.5, 0.06),
    (1.0, 0.03),
    (1.0, 0.04),
    (1.0, 0.06),
    (0.5, 0.04),
)


def savings_benchmark_multiple(age: float) -> float:
    """Benchmark retirement savings, as a multiple of salary, for someone of ``age``."""
    ages = [a for a, _ in SAVINGS_BENCHMARK]
    multiples = [m for _, m in SAVINGS_BENCHMARK]
    return float(np.interp(age, ages, multiples))


@dataclass(frozen=True)
class HouseholdScenario:
    """A named household scenario: a fixed point household plus randomization spreads."""

    #: The exact household used when randomization is off (the fixed point scenario).
    point: dict[str, Any]
    #: Genders drawn from (uniformly) when randomizing.
    genders: tuple[GenderAtBirth, ...] = (GenderAtBirth.MALE, GenderAtBirth.FEMALE)
    #: +/- years around the point start age (inclusive uniform integer draw).
    start_age_spread: int = 3
    #: +/- years around the point retirement age (inclusive uniform integer draw).
    retirement_age_spread: int = 3
    #: Multiplicative uniform range applied to the point salary.
    salary_factor_range: tuple[float, float] = (0.7, 1.3)
    #: Multiplicative uniform range applied to the point bank balance.
    bank_factor_range: tuple[float, float] = (0.25, 1.75)
    #: Multiplicative uniform range applied to the point spending/salary fraction.
    spending_factor_range: tuple[float, float] = (0.85, 1.15)
    #: Named economy scenarios to draw from per episode (None = the env's configured economy).
    #: Empty means the economy is never sampled here.
    economy_scenarios: tuple[str | None, ...] = field(default=())
    #: Uniform range of the household's savings relative to the age benchmark (see
    #: :func:`savings_benchmark_multiple`); below 1 on average.
    savings_factor_range: tuple[float, float] = (0.2, 1.3)
    #: Uniform range of retirement spending as a share of working spending.
    retirement_spending_ratio_range: tuple[float, float] = (0.7, 0.9)
    #: Uniform range of the Roth share of the starting 401k balance.
    roth_share_range: tuple[float, float] = (0.0, 0.35)
    #: Uniform range of the taxable brokerage balance as a share of the starting 401k balance.
    brokerage_share_range: tuple[float, float] = (0.0, 0.3)


# The four point household scenarios that anchor the randomization distributions. With
# randomization off, ``randomize=False`` reproduces these exact point households, so the point
# values are the fixed, deterministic configurations.
HOUSEHOLD_SCENARIOS: dict[str, HouseholdScenario] = {
    "basic": HouseholdScenario(
        point={
            "person_start_age": 25,
            "person_retirement_age": 65,
            "person_gender": GenderAtBirth.MALE,
            "initial_salary": 50000,
            "initial_bank_balance": 10000,
            "initial_spending": 30000,
            "employer_match_rate": 0.5,
            "employer_match_cap": 0.06,
            "initial_401k_pretax": 8000,
            "initial_401k_roth": 2000,
            "initial_brokerage": 0,
            "retirement_spending_ratio": 0.8,
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
            "employer_match_rate": 1.0,
            "employer_match_cap": 0.04,
            "initial_401k_pretax": 80000,
            "initial_401k_roth": 20000,
            "initial_brokerage": 20000,
            "retirement_spending_ratio": 0.8,
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
            "employer_match_rate": 0.0,
            "employer_match_cap": 0.0,
            "initial_401k_pretax": 0,
            "initial_401k_roth": 0,
            "initial_brokerage": 0,
            "retirement_spending_ratio": 0.8,
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
            "employer_match_rate": 0.5,
            "employer_match_cap": 0.06,
            "initial_401k_pretax": 120000,
            "initial_401k_roth": 20000,
            "initial_brokerage": 15000,
            "retirement_spending_ratio": 0.8,
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

    def sample_spec(self, rng: np.random.Generator, env_config: dict[str, Any]) -> HouseholdSpec:
        """Draw one randomized household (as :meth:`sample`) and return it as a ``HouseholdSpec``.

        ``env_config`` supplies the env-level construction settings (:data:`SPEC_ENV_KEYS`) and the
        defaults for household fields the draw does not set (e.g. ``children_ages``).
        """
        return household_spec({**env_config, **self.sample(rng)}, env_config)

    def point_household(self) -> dict[str, Any]:
        """The scenario's exact fixed point household (used when randomization is off)."""
        return dict(self.scenario.point)

    def sample(self, rng: np.random.Generator) -> dict[str, Any]:
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

        household: dict[str, Any] = {
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

        # Drawn after every pre-existing draw so the households above are unchanged by them.
        match_rate, match_cap = MATCH_OFFERS[int(rng.integers(0, len(MATCH_OFFERS)))]
        retirement_savings = salary * savings_benchmark_multiple(start_age) * rng.uniform(*s.savings_factor_range)
        roth_share = rng.uniform(*s.roth_share_range)
        brokerage_share = rng.uniform(*s.brokerage_share_range)
        retirement_spending_ratio = rng.uniform(*s.retirement_spending_ratio_range)
        household.update(
            {
                "employer_match_rate": match_rate,
                "employer_match_cap": match_cap,
                "initial_401k_pretax": round(retirement_savings * (1 - roth_share), 2),
                "initial_401k_roth": round(retirement_savings * roth_share, 2),
                "initial_brokerage": round(retirement_savings * brokerage_share, 2),
                "retirement_spending_ratio": round(retirement_spending_ratio, 2),
            }
        )
        return household


def ss_claim_age(household: dict[str, Any], config: FinancialConfig | None = None) -> int:
    """The Social Security claiming age for ``household``: ``ss_claim_age`` if set, else the
    retirement age, clipped to the claiming window (62-70 in the packaged config)."""
    config = config or default_financial_config()
    low = get_min_early_retirement_age(config)
    high = get_max_delayed_retirement_credit_age(config)
    claim = household.get("ss_claim_age")
    if claim is None:
        claim = household["person_retirement_age"]
    return int(min(max(int(claim), low), high))


def _growth(value: float | None) -> float | str:
    return "economy" if value is None else float(value)


def household_spec(
    household: dict[str, Any], env_config: dict[str, Any] | None = None, *, config: FinancialConfig | None = None
) -> HouseholdSpec:
    """The ``HouseholdSpec`` of one RL episode household.

    The household is a single earner with one of every account the agent can act on: a checking
    account, a job with a 401k, a brokerage account, a traditional and a Roth IRA and an HSA, plus
    the optional children, healthcare costs and Social Security. ``household`` holds the episode's
    resolved household values (``person_start_age``, ``initial_salary``, ...); ``env_config`` the
    env-level construction settings (:data:`SPEC_ENV_KEYS`, defaulting to the env's defaults);
    ``config`` the financial config used
    to clip the Social Security claiming age (the packaged defaults when None).

    Social Security uses a synthesized earnings record (``assumed_career_start_age``): a flat real
    career at the current salary since ``career_start_age``, indexed by the average wage index.
    The named economy scenario is recorded in ``meta.scenario``; the environment applies it itself
    (as a stochastic overlay), so it builds with ``apply_economy=False``.
    """
    env_config = {**SPEC_ENV_DEFAULTS, **(env_config or {})}
    start_year = int(env_config["start_year"])
    start_age = int(household["person_start_age"])
    gender = household["person_gender"]
    person: dict[str, Any] = {
        "id": AGENT_ID,
        "name": "RL_Agent",
        "age": start_age,
        "gender": gender.value if isinstance(gender, GenderAtBirth) else str(gender).lower(),
        "retirement_age": household["person_retirement_age"],
        "mortality": "stochastic",
        "spending": {
            "amount_annual": household["initial_spending"],
            "growth_pct": _growth(env_config.get("spending_growth")),
        },
        "jobs": [
            {
                "id": "job",
                "company": "Company",
                "role": "Employee",
                "salary_annual": household["initial_salary"],
                "raise_pct": _growth(env_config.get("salary_growth")),
                "bonus_pct": 1,
            }
        ],
        "accounts": [
            {
                "kind": "bank",
                "id": "bank",
                "company": "Bank",
                "type": "Checking",
                "balance": household["initial_bank_balance"],
                "interest_pct": 0.5,
            },
            {
                "kind": "401k",
                "id": "401k",
                "job": "job",
                "pretax_balance": float(household.get("initial_401k_pretax") or 0.0),
                "roth_balance": float(household.get("initial_401k_roth") or 0.0),
                "growth_pct": _growth(env_config.get("account_growth")),
            },
            {
                "kind": "brokerage",
                "id": "brokerage",
                "company": "Brokerage",
                "balance": float(household.get("initial_brokerage") or 0.0),
            },
            {"kind": "traditional_ira", "id": "traditional_ira"},
            {"kind": "roth_ira", "id": "roth_ira"},
            {"kind": "hsa", "id": "hsa", "coverage": "individual"},
        ],
        # Zero-padded ids keep the children in the order given (the builder sorts by id).
        "children": [
            {"id": f"child{i + 1:02d}", "name": f"Child{i + 1}", "birth_year": start_year - int(age)}
            for i, age in enumerate(household.get("children_ages", ()) or ())
        ],
    }
    if household.get("models_healthcare", False):
        person["healthcare"] = {"medical_costs": True, "medicare": True}
    turned_62 = start_year - start_age + 62
    if env_config.get("social_security", True) and turned_62 >= FIRST_BEND_POINT_YEAR:
        person["social_security"] = {
            "claim_age": ss_claim_age(household, config),
            "assumed_career_start_age": int(env_config["career_start_age"]),
        }
    max_steps = int(env_config["person_max_age"]) - start_age
    return HouseholdSpec.model_validate(
        {
            "meta": {
                "name": f"RL household ({env_config.get('household_scenario', 'custom')})",
                "start_year": start_year,
                "end_year": start_year + max_steps,
                "scenario": household.get("economy_scenario"),
            },
            "people": [person],
        }
    )
