# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Retirement-income fidelity: Social Security, the employer match, and starting balances."""

import unittest

import numpy as np

from deepqlearning.envs.financial.actions import ActionType, EmployerMatch, encode_flat_action
from deepqlearning.envs.financial.environment import OBS_SPEC, FinancialLifeEnv, FinancialLifeEnvGenerator
from deepqlearning.envs.financial.scenarios import (
    MATCH_OFFERS,
    EpisodeSampler,
    savings_benchmark_multiple,
)
from life_model.insurance.social_security import get_avg_wage_index

_NO_ACTION = encode_flat_action(ActionType.NO_ACTION)
_MAX_PRETAX = encode_flat_action(ActionType.TRANSFER_BANK_TO_401K_PRETAX, 1.00)
_MAX_ROTH = encode_flat_action(ActionType.TRANSFER_BANK_TO_401K_ROTH, 1.00)


def _env(**config) -> FinancialLifeEnv:
    base = {"economy_mode": "fixed"}
    base.update(config)
    return FinancialLifeEnv(base)


class TestSocialSecurity(unittest.TestCase):
    def test_attached_by_default_and_claimed_at_retirement_age(self):
        env = _env(person_start_age=30, person_retirement_age=66)
        self.assertIsNotNone(env.person.social_security)
        self.assertEqual(env.person.social_security.withdrawal_start_age, 66)

    def test_claim_age_clipped_to_window(self):
        self.assertEqual(_env(person_start_age=40, person_retirement_age=55).social_security.withdrawal_start_age, 62)
        self.assertEqual(_env(person_start_age=40, person_retirement_age=75).social_security.withdrawal_start_age, 70)
        self.assertEqual(_env(person_start_age=40, ss_claim_age=68).social_security.withdrawal_start_age, 68)

    def test_can_be_disabled(self):
        env = _env(social_security=False)
        self.assertIsNone(env.person.social_security)
        self.assertEqual(env._compute_observation_features()["ss_annual_benefit"], 0.0)

    def test_synthetic_history_covers_years_worked(self):
        env = _env(person_start_age=40, initial_salary=60000)
        history = env.person.social_security.income_history
        self.assertEqual(len(history), 40 - 22)
        self.assertEqual(history[-1].year, env.config["start_year"] - 1)
        # Earlier years are smaller (indexed back by the average wage index).
        self.assertLess(history[0].amount, history[-1].amount)

    def test_retiree_with_no_assets_lives_on_benefits(self):
        # A 67-year-old with a $60k career, no savings, and $20k of spending stays solvent: the
        # benefit (~$26k/yr for that record) covers the spending.
        env = _env(
            person_start_age=67,
            person_retirement_age=67,
            initial_salary=60000,
            initial_bank_balance=0,
            initial_spending=20000,
        )
        benefit = env._ss_annual_benefit()
        self.assertGreater(benefit, 20000)
        self.assertLess(benefit, 40000)
        for _ in range(5):
            _, _, terminated, _, info = env.step(_NO_ACTION)
            if terminated:
                break
            self.assertFalse(info["bankrupt"])
        self.assertGreater(env.person.bank_account_balance, 0)

    def test_benefit_feature_matches_pia(self):
        env = _env(person_start_age=50, initial_salary=80000)
        features = env._compute_observation_features()
        # Before 60 the PIA is in age-60 wage-indexed dollars; the feature restates it in current
        # dollars by the average-wage-index ratio.
        config, economy = env.model.config, env.model.economy
        year, age_60_year = env.model.year, env.person.get_year_at_age(60)
        to_now = get_avg_wage_index(year, config, economy=economy) / get_avg_wage_index(
            age_60_year, config, economy=economy
        )
        expected = env.person.social_security.get_pia() * 12 * to_now / 100_000.0
        self.assertAlmostEqual(features["ss_annual_benefit"], expected, places=6)
        self.assertAlmostEqual(features["years_to_ss_claim"], (65 - 50) / 50.0)


class TestEmployerMatch(unittest.TestCase):
    def _matched_env(self, rate=0.5, cap=0.06, **config):
        return _env(
            employer_match_rate=rate,
            employer_match_cap=cap,
            initial_bank_balance=40000,
            initial_salary=100000,
            **config,
        )

    def test_match_is_rate_times_capped_deferral(self):
        env = self._matched_env()
        result = env.action_executor.execute_action(env.person, ActionType.TRANSFER_BANK_TO_401K_PRETAX, amount=10000)
        # Pay is salary + 1% bonus; 6% of $101k = $6,060 of matched deferral, at 50 cents/dollar.
        self.assertAlmostEqual(result.employer_match, 0.5 * 0.06 * 101000)
        self.assertAlmostEqual(env.job401k.pretax_balance, 10000 + 0.5 * 0.06 * 101000)

    def test_small_deferral_matched_in_full(self):
        env = self._matched_env()
        result = env.action_executor.execute_action(env.person, ActionType.TRANSFER_BANK_TO_401K_PRETAX, amount=2000)
        self.assertAlmostEqual(result.employer_match, 1000)

    def test_second_deferral_only_matched_up_to_cap(self):
        env = self._matched_env()
        first = env.action_executor.execute_action(env.person, ActionType.TRANSFER_BANK_TO_401K_PRETAX, amount=4000)
        second = env.action_executor.execute_action(env.person, ActionType.TRANSFER_BANK_TO_401K_ROTH, amount=4000)
        self.assertAlmostEqual(first.employer_match + second.employer_match, 0.5 * 0.06 * 101000)

    def test_roth_deferral_match_lands_pretax(self):
        env = self._matched_env()
        env.action_executor.execute_action(env.person, ActionType.TRANSFER_BANK_TO_401K_ROTH, amount=2000)
        self.assertAlmostEqual(env.job401k.roth_balance, 2000)
        self.assertAlmostEqual(env.job401k.pretax_balance, 1000)

    def test_no_match_without_offer_or_for_other_accounts(self):
        env = _env(initial_bank_balance=40000)
        result = env.action_executor.execute_action(env.person, ActionType.TRANSFER_BANK_TO_401K_PRETAX, amount=5000)
        self.assertEqual(result.employer_match, 0.0)
        env = self._matched_env()
        result = env.action_executor.execute_action(env.person, ActionType.TRANSFER_BANK_TO_BROKERAGE, amount=5000)
        self.assertEqual(result.employer_match, 0.0)

    def test_match_resets_each_year(self):
        env = self._matched_env()
        env.step(_MAX_PRETAX)
        balance_after_year_one = env.job401k.pretax_balance
        result = env.action_executor.execute_action(env.person, ActionType.TRANSFER_BANK_TO_401K_PRETAX, amount=2000)
        self.assertAlmostEqual(result.employer_match, 1000)
        self.assertGreater(env.job401k.pretax_balance, balance_after_year_one)

    def test_max_match(self):
        self.assertAlmostEqual(EmployerMatch(1.0, 0.04).max_match(100000), 4000)
        self.assertEqual(EmployerMatch().max_match(100000), 0.0)


class TestStartingBalancesAndGrowth(unittest.TestCase):
    def test_point_household_balances_seeded(self):
        env = FinancialLifeEnvGenerator.create_scenario_env("mid_career")
        env.reset(seed=0)
        self.assertEqual(env.job401k.pretax_balance, 120000)
        self.assertEqual(env.job401k.roth_balance, 20000)
        self.assertEqual(env.brokerage.balance, 15000)
        self.assertEqual(env.employer_match, EmployerMatch(0.5, 0.06))

    def test_401k_follows_the_economy_by_default(self):
        env = FinancialLifeEnv({"economy_mode": "stochastic"})
        env.reset(seed=3)
        rates = set()
        for _ in range(5):
            rates.add(round(env.job401k.growth_rate, 6))
            env.step(_NO_ACTION)
        self.assertGreater(len(rates), 1)

    def test_spending_follows_inflation_by_default(self):
        env = FinancialLifeEnv({"economy_mode": "stochastic"})
        env.reset(seed=3)
        self.assertEqual(env.person.spending.yearly_increase, env.model.economy.inflation(env.model.year))

    def test_new_observation_features_declared(self):
        names = [name for name, _, _ in OBS_SPEC]
        for feature in ("ss_annual_benefit", "years_to_ss_claim", "employer_match_rate", "employer_match_cap"):
            self.assertIn(feature, names)


class TestSampledRetirementContext(unittest.TestCase):
    def test_benchmark_is_monotone_and_anchored(self):
        self.assertEqual(savings_benchmark_multiple(22), 0.0)
        self.assertAlmostEqual(savings_benchmark_multiple(40), 3.0)
        ages = range(18, 80)
        values = [savings_benchmark_multiple(a) for a in ages]
        self.assertEqual(values, sorted(values))

    def test_balances_scale_with_age(self):
        young = [EpisodeSampler("basic").sample(np.random.default_rng(i)) for i in range(40)]
        older = [EpisodeSampler("mid_career").sample(np.random.default_rng(i)) for i in range(40)]

        def mean_multiple(hs):
            return np.mean([(h["initial_401k_pretax"] + h["initial_401k_roth"]) / h["initial_salary"] for h in hs])

        self.assertLess(mean_multiple(young), mean_multiple(older))

    def test_match_drawn_from_offers(self):
        for i in range(30):
            h = EpisodeSampler("high_earner").sample(np.random.default_rng(i))
            self.assertIn((h["employer_match_rate"], h["employer_match_cap"]), MATCH_OFFERS)
            self.assertGreaterEqual(h["initial_brokerage"], 0.0)


if __name__ == "__main__":
    unittest.main()
