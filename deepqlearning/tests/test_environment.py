# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Unit tests for the Gymnasium environment API, seeding, and reward semantics."""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from actions import ActionType  # noqa: E402
from environment import FinancialLifeEnv  # noqa: E402


def _no_action(env):
    return {
        "action_type": list(ActionType).index(ActionType.NO_ACTION),
        "amount_percentage": np.array([0.0], dtype=np.float32),
    }


class TestGymnasiumAPI(unittest.TestCase):
    def test_passes_env_checker(self):
        from gymnasium.utils.env_checker import check_env

        check_env(FinancialLifeEnv(), skip_render_check=True)

    def test_reset_returns_obs_and_info(self):
        env = FinancialLifeEnv()
        obs, info = env.reset(seed=0)
        self.assertEqual(obs.shape, (env.observation_space.shape[0],))
        self.assertIsInstance(info, dict)

    def test_step_returns_five_tuple(self):
        env = FinancialLifeEnv()
        env.reset(seed=0)
        result = env.step(_no_action(env))
        self.assertEqual(len(result), 5)
        obs, reward, terminated, truncated, info = result
        self.assertIsInstance(reward, float)
        self.assertIsInstance(terminated, bool)
        self.assertIsInstance(truncated, bool)

    def test_retirement_accounts_exist_after_reset(self):
        env = FinancialLifeEnv()
        env.reset(seed=0)
        self.assertEqual(len(env.person.all_retirement_accounts), 1)


class TestSeedingDeterminism(unittest.TestCase):
    def test_same_seed_reproduces_trajectory(self):
        def run(seed):
            env = FinancialLifeEnv()
            env.reset(seed=seed)
            rewards = []
            rng = np.random.RandomState(seed)
            for _ in range(30):
                legal = env.get_legal_actions()
                idx = int(rng.choice(legal))
                _, r, term, trunc, _ = env.step(
                    {"action_type": idx, "amount_percentage": np.array([0.1], dtype=np.float32)}
                )
                rewards.append(r)
                if term or trunc:
                    break
            return rewards

        self.assertEqual(run(7), run(7))

    def test_previous_net_worth_reset_between_episodes(self):
        # A fresh episode must not compute its first reward against the last episode's net worth.
        env = FinancialLifeEnv()
        env.reset(seed=1)
        # Drive net worth up materially.
        for _ in range(20):
            env.step(_no_action(env))
        high_net_worth = env._calculate_net_worth()

        env.reset(seed=1)
        self.assertEqual(env.previous_net_worth, env.initial_net_worth)
        self.assertNotAlmostEqual(env.previous_net_worth, high_net_worth)


class TestRewardSemantics(unittest.TestCase):
    def test_bankruptcy_penalty_threshold_matches_termination(self):
        env = FinancialLifeEnv()
        # Penalty and termination use the same single threshold constant.
        self.assertEqual(env.BANKRUPTCY_THRESHOLD, -100000)

    def test_no_farmable_early_retirement_bonus(self):
        # Decreasing spending must not manufacture reward via a pre-retirement bonus.
        env = FinancialLifeEnv()
        self.assertNotIn("early_retirement_bonus", env.config["reward_weights"])

    def test_terminated_on_max_age(self):
        env = FinancialLifeEnv({"person_start_age": 118, "person_max_age": 119})
        env.reset(seed=0)
        # One step takes the person to max age -> terminated.
        _, _, terminated, truncated, _ = env.step(_no_action(env))
        self.assertTrue(terminated or truncated)


class TestModelNativeMortality(unittest.TestCase):
    """Plan 18 D2: death is decided by the model (Person mortality machinery), not the env."""

    def test_person_uses_stochastic_mortality(self):
        from life_model.people.person import MortalityMode

        env = FinancialLifeEnv()
        env.reset(seed=0)
        self.assertEqual(env.person.mortality_mode, MortalityMode.STOCHASTIC)
        self.assertEqual(env.person.gender, env.config["person_gender"])

    def test_death_in_sim_triggers_estate_flow(self):
        # Start very old so death occurs within a few steps; the death must run the model's
        # die() machinery, which logs the death and the estate settlement on the event log.
        env = FinancialLifeEnv({"person_start_age": 105})
        env.reset(seed=3)
        terminated = False
        for _ in range(20):
            _, _, terminated, truncated, info = env.step(_no_action(env))
            if terminated or truncated:
                break
        self.assertTrue(terminated)
        self.assertTrue(env.person.is_deceased)
        self.assertTrue(info["died_from_natural_causes"])
        messages = [event.message for event in env.model.event_log.list]
        self.assertTrue(any("died at age" in m for m in messages), messages)
        self.assertTrue(any("estate" in m.lower() for m in messages), messages)
        # The estate value at death was captured for the terminal reward.
        self.assertIsNotNone(info["estate_value_at_death"])

    def test_death_reward_uses_estate_value_not_dissolved_net_worth(self):
        # Dying with money must not produce a huge negative net-worth-drop reward.
        env = FinancialLifeEnv({"person_start_age": 105, "initial_bank_balance": 500000})
        env.reset(seed=3)
        rewards = []
        for _ in range(20):
            _, r, terminated, truncated, _ = env.step(_no_action(env))
            rewards.append(r)
            if terminated or truncated:
                break
        self.assertTrue(env.person.is_deceased)
        # The terminal step must not be dominated by an artificial ~-$500k net worth collapse
        # (which would be a reward of about -5.0 before other terms).
        self.assertGreater(rewards[-1], -4.0)


class TestStochasticEconomy(unittest.TestCase):
    """Plan 18 D3: the economy is stochastic by default, seeded, and observable."""

    def test_default_mode_is_stochastic(self):
        env = FinancialLifeEnv()
        env.reset(seed=0)
        self.assertEqual(env.model.config.economy.mode, "stochastic")

    def test_fixed_mode_knob_for_unit_tests(self):
        env = FinancialLifeEnv({"economy_mode": "fixed"})
        env.reset(seed=0)
        self.assertEqual(env.model.config.economy.mode, "fixed")

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            FinancialLifeEnv({"economy_mode": "bogus"})

    def test_economy_scenario_applies(self):
        env = FinancialLifeEnv({"economy_scenario": "recession"})
        env.reset(seed=0)
        # The recession scenario switches the economy to path mode with drawdown years.
        self.assertEqual(env.model.config.economy.mode, "path")

    def test_stochastic_returns_vary_across_years(self):
        env = FinancialLifeEnv()
        env.reset(seed=0)
        observed = set()
        for _ in range(10):
            _, _, term, trunc, _ = env.step(_no_action(env))
            observed.add(round(env._compute_observation_features()["equity_return"], 6))
            if term or trunc:
                break
        self.assertGreater(len(observed), 1, "stochastic equity returns should differ across years")

    def test_stochastic_mode_reproducible_under_seed(self):
        def run(seed):
            env = FinancialLifeEnv()
            obs, _ = env.reset(seed=seed)
            trace = [obs.tolist()]
            for _ in range(15):
                obs, r, term, trunc, _ = env.step(_no_action(env))
                trace.append(obs.tolist() + [r])
                if term or trunc:
                    break
            return trace

        self.assertEqual(run(11), run(11))


class TestObservationV2(unittest.TestCase):
    """Plan 18 D4: observation features are hand-checkable, bounded, and decision-relevant."""

    def _fixed_env(self, config=None):
        cfg = {"economy_mode": "fixed"}
        if config:
            cfg.update(config)
        env = FinancialLifeEnv(cfg)
        env.reset(seed=0)
        return env

    def test_observation_within_declared_bounds(self):
        env = FinancialLifeEnv()
        obs, _ = env.reset(seed=4)
        self.assertTrue(env.observation_space.contains(obs))
        for _ in range(25):
            obs, _, term, trunc, _ = env.step(_no_action(env))
            self.assertTrue(env.observation_space.contains(obs))
            if term or trunc:
                break

    def test_reset_features_match_hand_computed_values(self):
        env = self._fixed_env()
        f = env._compute_observation_features()
        self.assertAlmostEqual(f["age"], 25 / 100.0)
        self.assertAlmostEqual(f["years_to_retirement"], 40 / 50.0)
        self.assertEqual(f["is_retired"], 0.0)
        self.assertAlmostEqual(f["life_progress"], 0.0)
        self.assertAlmostEqual(f["bank_balance"], 10000 / 1e6)
        self.assertAlmostEqual(f["annual_income"], 50000 / 1e6)
        self.assertAlmostEqual(f["annual_spending"], 30000 / 1e6)
        self.assertAlmostEqual(f["savings_rate"], (50000 - 30000) / 50000)
        self.assertAlmostEqual(f["emergency_fund_years"], 10000 / 30000)
        self.assertAlmostEqual(f["years_to_59_5"], (59.5 - 25) / 35.0)
        self.assertAlmostEqual(f["log_deflator"], 0.0)  # deflator is 1.0 at reset
        self.assertAlmostEqual(f["ira_room_fraction"], 1.0)
        self.assertAlmostEqual(f["hsa_room_fraction"], 1.0)
        self.assertAlmostEqual(f["projected_rmd"], 0.0)
        # Fixed-economy constants are observed at reset (no realized year yet).
        econ = env.model.config.economy
        self.assertAlmostEqual(f["inflation"], econ.inflation / 100.0)
        self.assertAlmostEqual(f["equity_return"], econ.equity_return / 100.0)
        self.assertAlmostEqual(f["bond_return"], econ.bond_return / 100.0)

    def test_bracket_features_match_hand_computed_values(self):
        env = self._fixed_env()
        params = env.model.tax_params_for_year(env.model.year)
        taxable = max(0.0, 50000 - params.standard_deduction.single)
        expected_edge, expected_rate = None, None
        for _lower, upper, rate in params.tax_brackets.single:
            if taxable < upper:
                expected_edge, expected_rate = upper - taxable, rate / 100.0
                break
        f = env._compute_observation_features()
        self.assertAlmostEqual(f["marginal_rate"], expected_rate)
        self.assertAlmostEqual(f["bracket_headroom"], expected_edge / 1e5)
        self.assertAlmostEqual(f["projected_taxable_income"], 50000 / 1e6)

    def test_debt_feature_reads_real_debt_not_dead_attribute(self):
        # Acceptance criterion: a household with a car loan shows nonzero observed debt, and no
        # feature reads the hard-zero person.debt.
        from life_model.debt.car_loan import CarLoan

        env = self._fixed_env()
        self.assertAlmostEqual(env._compute_observation_features()["debt"], 0.0)
        CarLoan(person=env.person, loan_amount=30000, length_years=5, yearly_interest_rate=6.0, name="Car")
        f = env._compute_observation_features()
        self.assertAlmostEqual(f["debt"], 30000 / 1e6)
        self.assertGreater(f["debt_to_income"], 0.0)

    def test_projected_rmd_appears_at_rmd_age(self):
        # An old person with a pre-tax balance must observe a nonzero upcoming RMD.
        env = self._fixed_env({"person_start_age": 80})
        env.job401k.pretax_balance = 500000.0
        f = env._compute_observation_features()
        self.assertGreater(f["projected_rmd"], 0.0)
        self.assertAlmostEqual(f["years_to_rmd_start"], 0.0)

    def test_real_dollar_features_are_deflated(self):
        # Under stochastic inflation the deflator grows; nominal balances are divided by it.
        env = FinancialLifeEnv()
        env.reset(seed=2)
        for _ in range(10):
            _, _, term, trunc, _ = env.step(_no_action(env))
            if term or trunc:
                break
        deflator = env.model.economy.cumulative_inflation(env.model.year)
        f = env._compute_observation_features()
        self.assertAlmostEqual(f["bank_balance"], env.person.bank_account_balance / deflator / 1e6, places=6)
        self.assertAlmostEqual(f["log_deflator"], float(np.log(deflator)), places=6)


if __name__ == "__main__":
    unittest.main()
