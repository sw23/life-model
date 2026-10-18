# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The RL household is built through life_model.spec without changing a single number.

Plan 25 routed the environment's household construction through the declarative spec builder and
deleted the hand-written constructor calls. This test keeps a verbatim copy of the pre-spec
construction code (``_legacy_populate``) and swaps it in for the builder, then plays the same seeded
episodes both ways and requires bit-identical observations, rewards, info and model stats. It runs
side by side in one process, so it does not depend on platform floating-point details.
"""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import numpy as np

from deepqlearning.envs.financial import environment
from deepqlearning.envs.financial.actions import ActionType, decode_flat_action
from deepqlearning.envs.financial.environment import FinancialLifeEnv, FinancialLifeEnvGenerator
from deepqlearning.envs.financial.scenarios import (
    AGENT_ID,
    HOUSEHOLD_SCENARIOS,
    SPEC_ENV_DEFAULTS,
    EpisodeSampler,
    household_spec,
)
from life_model.account.bank import BankAccount
from life_model.account.brokerage import BrokerageAccount
from life_model.account.hsa import HealthSavingsAccount, HSAType
from life_model.account.job401k import Job401kAccount
from life_model.account.roth_IRA import RothIRA
from life_model.account.traditional_IRA import TraditionalIRA
from life_model.dependents.child import Child
from life_model.healthcare.medical_costs import MedicalCosts
from life_model.healthcare.medicare import Medicare
from life_model.insurance.social_security import (
    SocialSecurity,
    get_avg_wage_index,
    get_max_delayed_retirement_credit_age,
    get_min_early_retirement_age,
)
from life_model.model import LifeModel
from life_model.people.family import Family
from life_model.people.person import MortalityMode, Person, Spending
from life_model.spec import validate_spec
from life_model.work.job import Job, Salary

STATS = LifeModel.STATS + LifeModel.EXTRA_STATS


def _legacy_populate(env: FinancialLifeEnv):
    """The pre-spec construction code of ``FinancialLifeEnv.reset``, verbatim, as a populate_model stand-in."""

    def populate(model, spec, check=False):
        household: dict[str, Any] = env.episode_household
        config = env.config
        family = Family(model)
        person = Person(
            family=family,
            name="RL_Agent",
            age=household["person_start_age"],
            retirement_age=household["person_retirement_age"],
            spending=Spending(
                model=model, base=household["initial_spending"], yearly_increase=config["spending_growth"]
            ),
            gender=household["person_gender"],
            mortality_mode=MortalityMode.STOCHASTIC,
        )
        items: dict[str, Any] = {}
        items["bank"] = BankAccount(
            owner=person, company="Bank", type="Checking", balance=household["initial_bank_balance"], interest_rate=0.5
        )
        items["job"] = Job(
            owner=person,
            company="Company",
            role="Employee",
            salary=Salary(
                model=model, base=household["initial_salary"], yearly_increase=config["salary_growth"], yearly_bonus=1
            ),
        )
        items["401k"] = Job401kAccount(
            job=items["job"],
            pretax_balance=float(household.get("initial_401k_pretax") or 0.0),
            roth_balance=float(household.get("initial_401k_roth") or 0.0),
            average_growth=config["account_growth"],
        )
        items["brokerage"] = BrokerageAccount(
            person=person, company="Brokerage", balance=float(household.get("initial_brokerage") or 0.0)
        )
        items["traditional_ira"] = TraditionalIRA(person=person)
        items["roth_ira"] = RothIRA(person=person)
        items["hsa"] = HealthSavingsAccount(person=person, hsa_type=HSAType.INDIVIDUAL)
        for i, age in enumerate(household.get("children_ages", ()) or ()):
            Child(person, f"Child{i + 1}", model.start_year - int(age))
        if household.get("models_healthcare", False):
            MedicalCosts(person)
            Medicare(person)
        turned_62 = config["start_year"] - int(household["person_start_age"]) + 62
        if config["social_security"] and turned_62 >= 1979:
            low = get_min_early_retirement_age(model.config)
            high = get_max_delayed_retirement_credit_age(model.config)
            claim = household.get("ss_claim_age")
            if claim is None:
                claim = household["person_retirement_age"]
            start_year = config["start_year"]
            years_worked = max(0, int(household["person_start_age"]) - int(config["career_start_age"]))
            salary = float(household["initial_salary"])
            awi_now = get_avg_wage_index(start_year, model.config, economy=model.economy)
            history = []
            for year in range(max(start_year - years_worked, 1978), start_year):
                wage = salary * get_avg_wage_index(year, model.config, economy=model.economy) / awi_now
                cap = model.config_for_year(year).tax.fica.social_security_max_income
                history.append((year, round(min(wage, cap), 2)))
            SocialSecurity(person, withdrawal_start_age=int(min(max(int(claim), low), high)), income_history=history)
        return SimpleNamespace(family=family, people={AGENT_ID: person}, items=items)

    return populate


def _episode(env: FinancialLifeEnv, seed: int | None, options: dict | None, noop: bool, steps: int = 200) -> list:
    obs, info = env.reset(seed=seed, options=options)
    trace: list = [obs.tobytes(), info["net_worth"]]
    noop_index = next(i for i in range(env.action_space.n) if decode_flat_action(i).action_type == ActionType.NO_ACTION)
    for t in range(steps):
        legal = env.get_legal_actions()
        action = noop_index if noop else legal[(t * 7 + 3) % len(legal)]
        obs, reward, terminated, truncated, info = env.step(action)
        stats = tuple(stat.model_reporter(env.model) for stat in STATS)
        trace.append((obs.tobytes(), reward, terminated, truncated, info["net_worth"], info["age"], stats))
        if terminated or truncated:
            break
    return trace


CASES: list[tuple[str, Any, int, dict | None]] = [
    ("default", lambda: FinancialLifeEnv(), 0, None),
    *[
        (f"named-{name}", lambda name=name: FinancialLifeEnvGenerator.create_scenario_env(name), 1, None)
        for name in HOUSEHOLD_SCENARIOS
    ],
    *[
        (
            f"randomized-{name}",
            lambda name=name: FinancialLifeEnvGenerator.create_scenario_env(name),
            2,
            {"randomize": True},
        )
        for name in HOUSEHOLD_SCENARIOS
    ],
    (
        "children-healthcare-fixed-economy",
        lambda: FinancialLifeEnv(
            {
                "children_ages": (3, 10, 1),
                "models_healthcare": True,
                "economy_mode": "fixed",
                "account_growth": 6.0,
                "spending_growth": 2.0,
                "salary_growth": 3.0,
            }
        ),
        4,
        None,
    ),
    ("recession-overlay", lambda: FinancialLifeEnv({"economy_scenario": "recession"}), 5, None),
    (
        "recession-replaces-economy",
        lambda: FinancialLifeEnv({"economy_scenario": "recession", "scenario_overlay": False}),
        6,
        None,
    ),
    ("no-social-security", lambda: FinancialLifeEnv({"social_security": False, "savings_boost_pct": 5.0}), 7, None),
    (
        "late-claim-with-balances",
        lambda: FinancialLifeEnv(
            {
                "ss_claim_age": 70,
                "person_start_age": 55,
                "initial_401k_pretax": 300000,
                "initial_brokerage": 50000,
                "employer_match_rate": 0.5,
                "employer_match_cap": 0.06,
            }
        ),
        8,
        None,
    ),
    ("artificial-old-start", lambda: FinancialLifeEnv({"person_start_age": 117}), 9, None),
]


class TestHouseholdSpecParity(unittest.TestCase):
    def test_spec_built_episodes_match_the_legacy_construction(self):
        for name, make, seed, options in CASES:
            for noop in (False, True):
                with self.subTest(case=name, noop=noop):
                    new_env = make()
                    new = _episode(new_env, seed, options, noop)
                    new_autoreset = _episode(new_env, None, options, noop, steps=15)
                    legacy_env = make()
                    with mock.patch.object(environment, "populate_model", _legacy_populate(legacy_env)):
                        legacy = _episode(legacy_env, seed, options, noop)
                        legacy_autoreset = _episode(legacy_env, None, options, noop, steps=15)
                    self.assertEqual(len(new), len(legacy))
                    self.assertEqual(new, legacy)
                    self.assertEqual(new_autoreset, legacy_autoreset)

    def test_episode_spec_describes_the_built_household(self):
        env = FinancialLifeEnvGenerator.create_scenario_env(
            "mid_career", {"children_ages": (4,), "models_healthcare": True}
        )
        env.reset(seed=3)
        spec = env.episode_spec
        (person,) = spec.people
        self.assertEqual(person.age, env.person.age)
        self.assertEqual(
            [a.kind for a in person.accounts], ["bank", "401k", "brokerage", "traditional_ira", "roth_ira", "hsa"]
        )
        self.assertEqual(person.social_security.assumed_career_start_age, 22)
        self.assertEqual(spec.meta.end_year, env.model.end_year)
        self.assertIs(env.model.household.people[AGENT_ID], env.person)

    def test_sampled_households_validate_cleanly(self):
        env_config = FinancialLifeEnv().config
        for name in HOUSEHOLD_SCENARIOS:
            sampler = EpisodeSampler(name)
            rng = np.random.default_rng(0)
            for _ in range(20):
                with self.subTest(scenario=name):
                    self.assertEqual(validate_spec(sampler.sample_spec(rng, env_config)), [])
            point = household_spec({**env_config, **sampler.point_household()}, env_config)
            self.assertEqual(validate_spec(point), [])

    def test_spec_env_defaults_match_the_environment(self):
        env_config = FinancialLifeEnv().config
        self.assertEqual({key: env_config[key] for key in SPEC_ENV_DEFAULTS}, SPEC_ENV_DEFAULTS)

    def test_sample_spec_matches_sample(self):
        env_config = FinancialLifeEnv().config
        sampler = EpisodeSampler("basic")
        household = sampler.sample(np.random.default_rng(5))
        spec = sampler.sample_spec(np.random.default_rng(5), env_config)
        self.assertEqual(spec.people[0].jobs[0].salary_annual, household["initial_salary"])
        self.assertEqual(spec.people[0].age, household["person_start_age"])


if __name__ == "__main__":
    unittest.main()
