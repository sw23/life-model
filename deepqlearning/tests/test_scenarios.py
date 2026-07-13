# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for domain randomization: EpisodeSampler and reset(options=...) (Plan 18 D6)."""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from environment import FinancialLifeEnv, FinancialLifeEnvGenerator  # noqa: E402
from scenarios import HOUSEHOLD_SCENARIOS, EpisodeSampler  # noqa: E402


def _trajectory(env, seed, options=None, steps=20):
    """Observations and rewards from a fixed random-legal-action policy."""
    obs, _ = env.reset(seed=seed, options=options)
    trace = [obs.tolist()]
    rng = np.random.RandomState(seed)
    for _ in range(steps):
        legal = env.get_legal_actions()
        obs, reward, terminated, truncated, _ = env.step(int(rng.choice(legal)))
        trace.append(obs.tolist() + [reward])
        if terminated or truncated:
            break
    return trace


class TestEpisodeSampler(unittest.TestCase):
    def test_unknown_scenario_rejected(self):
        with self.assertRaises(KeyError):
            EpisodeSampler("bogus")

    def test_point_household_matches_scenario_definition(self):
        for name, scenario in HOUSEHOLD_SCENARIOS.items():
            self.assertEqual(EpisodeSampler(name).point_household(), scenario.point)

    def test_sample_is_deterministic_per_rng_seed(self):
        sampler = EpisodeSampler("basic")
        a = sampler.sample(np.random.default_rng(9))
        b = sampler.sample(np.random.default_rng(9))
        self.assertEqual(a, b)

    def test_samples_vary_across_seeds(self):
        sampler = EpisodeSampler("basic")
        households = [sampler.sample(np.random.default_rng(i)) for i in range(10)]
        salaries = {h["initial_salary"] for h in households}
        self.assertGreater(len(salaries), 1)

    def test_sampled_household_is_coherent(self):
        sampler = EpisodeSampler("mid_career")
        for i in range(50):
            h = sampler.sample(np.random.default_rng(i))
            self.assertGreaterEqual(h["person_retirement_age"], h["person_start_age"] + 10)
            self.assertGreater(h["initial_salary"], 0)
            self.assertGreater(h["initial_spending"], 0)
            self.assertGreaterEqual(h["initial_bank_balance"], 0)


class TestResetOptions(unittest.TestCase):
    def test_default_reset_reproduces_fixed_household(self):
        # Plan 18 D6 acceptance: randomize=False (or no options) reproduces the legacy point
        # household exactly.
        env = FinancialLifeEnv()
        env.reset(seed=0)
        self.assertEqual(env.person.age, 25)
        self.assertEqual(env.person.retirement_age, 65)
        self.assertEqual(env.job.salary.base, 50000)
        self.assertEqual(env.person.bank_account_balance, 10000)
        self.assertEqual(env.person.spending.base, 30000)

    def test_randomize_false_trajectory_identical_to_no_options(self):
        env = FinancialLifeEnv()
        a = _trajectory(env, seed=3, options=None)
        b = _trajectory(env, seed=3, options={"randomize": False})
        self.assertEqual(a, b)

    def test_scenario_option_uses_point_household(self):
        env = FinancialLifeEnv()
        env.reset(seed=0, options={"scenario": "high_earner"})
        point = HOUSEHOLD_SCENARIOS["high_earner"].point
        self.assertEqual(env.person.age, point["person_start_age"])
        self.assertEqual(env.job.salary.base, point["initial_salary"])
        self.assertEqual(env.person.bank_account_balance, point["initial_bank_balance"])

    def test_randomized_household_same_seed_identical(self):
        env = FinancialLifeEnv()
        options = {"randomize": True}
        env.reset(seed=42, options=options)
        first = dict(env.episode_household)
        env.reset(seed=42, options=options)
        self.assertEqual(env.episode_household, first)

    def test_randomized_households_vary_across_seeds(self):
        env = FinancialLifeEnv()
        salaries = set()
        for seed in range(8):
            env.reset(seed=seed, options={"randomize": True})
            salaries.add(env.episode_household["initial_salary"])
        self.assertGreater(len(salaries), 1)

    def test_full_stack_determinism_same_seed_identical_trajectories(self):
        # Acceptance criterion: same seed -> identical trajectories under stochastic economy +
        # stochastic mortality + randomized households.
        env1 = FinancialLifeEnv()
        env2 = FinancialLifeEnv()
        options = {"randomize": True, "scenario": "basic"}
        a = _trajectory(env1, seed=17, options=options, steps=40)
        b = _trajectory(env2, seed=17, options=options, steps=40)
        self.assertEqual(a, b)

    def test_generator_point_configs_come_from_scenarios(self):
        env = FinancialLifeEnvGenerator.create_low_earner_env()
        point = HOUSEHOLD_SCENARIOS["low_earner"].point
        self.assertEqual(env.config["initial_salary"], point["initial_salary"])
        self.assertEqual(env.config["household_scenario"], "low_earner")


if __name__ == "__main__":
    unittest.main()
