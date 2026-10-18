# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The decision interval (Plan 32 D9): an env step simulates a year, a quarter or a month."""

import unittest
import warnings
from unittest import mock

import numpy as np

from deepqlearning.envs.financial.actions import ActionType, encode_flat_action
from deepqlearning.envs.financial.environment import OBS_SPEC, FinancialLifeEnv, FinancialLifeEnvGenerator
from deepqlearning.envs.financial.policies import encode_policy_action, no_change_vector
from deepqlearning.envs.financial.rewards import consumption_utility, step_reward
from deepqlearning.evaluation.baselines import do_nothing_policy, factored_do_nothing_policy

_NO_ACTION = encode_flat_action(ActionType.NO_ACTION)


def _episode(env, policy, seed, options=None):
    """(rewards, observations, infos) of one episode under ``policy``."""
    obs, info = env.reset(seed=seed, options=options)
    rewards, observations, infos = [], [obs], [info]
    done = False
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        while not done:
            obs, reward, terminated, truncated, info = env.step(policy(env))
            rewards.append(reward)
            observations.append(obs)
            infos.append(info)
            done = terminated or truncated
    return rewards, observations, infos


class TestYearReproducesTheAnnualEpisode(unittest.TestCase):
    def test_episode_length_is_one_step_per_year(self):
        env = FinancialLifeEnvGenerator.create_scenario_env("basic")
        self.assertEqual(env.max_steps, 119 - 25)
        quarterly = FinancialLifeEnvGenerator.create_scenario_env("basic", {"decision_interval": "quarter"})
        self.assertEqual(quarterly.max_steps, 4 * (119 - 25))
        monthly = FinancialLifeEnvGenerator.create_scenario_env("basic", {"decision_interval": "month"})
        self.assertEqual(monthly.max_steps, 12 * (119 - 25))

    def test_twelve_monthly_steps_are_step_year(self):
        """The yearly env is the pre-Plan-32-task-5 env: driving the model with ``step_year`` instead of
        twelve ``step`` calls changes nothing (rewards, observations, episode length)."""
        rng = np.random.default_rng(3)

        def policy(env):
            return int(rng.choice(env.get_legal_actions())) if rng.random() < 0.5 else _NO_ACTION

        env = FinancialLifeEnvGenerator.create_scenario_env("mid_career")
        rewards, observations, _ = _episode(env, policy, seed=11, options={"randomize": True})

        def step_year(self):
            self.model.step_year()
            return 12

        rng = np.random.default_rng(3)
        twin = FinancialLifeEnvGenerator.create_scenario_env("mid_career")
        with mock.patch.object(FinancialLifeEnv, "_simulate_interval", step_year):
            twin_rewards, twin_observations, _ = _episode(twin, policy, seed=11, options={"randomize": True})
        self.assertEqual(rewards, twin_rewards)
        for a, b in zip(observations, twin_observations):
            np.testing.assert_array_equal(a, b)

    def test_yearly_reward_is_the_annual_utility(self):
        env = FinancialLifeEnvGenerator.create_scenario_env("basic", {"economy_mode": "fixed"})
        env.reset(seed=0)
        _, reward, terminated, truncated, _ = env.step(_NO_ACTION)
        self.assertFalse(terminated or truncated)
        expected = consumption_utility(
            env.person.spending.get_yearly_spending(),
            env.model.economy.cumulative_inflation(env.model.year),
            env.reward_config,
        )
        self.assertEqual(reward, expected)

    def test_factored_no_change_reproduces_the_flat_no_action_episode(self):
        """Keeping every standing policy (and claiming at the household's age) is exactly the flat
        env's no-op: same rewards, same length."""
        flat = FinancialLifeEnvGenerator.create_scenario_env("high_earner")
        factored = FinancialLifeEnvGenerator.create_scenario_env("high_earner", {"action_space": "factored"})
        flat_rewards, _, flat_infos = _episode(flat, do_nothing_policy, seed=5)
        factored_rewards, _, factored_infos = _episode(factored, factored_do_nothing_policy, seed=5)
        self.assertEqual(len(flat_rewards), len(factored_rewards))
        np.testing.assert_allclose(factored_rewards, flat_rewards, rtol=0, atol=1e-9)
        self.assertEqual(flat_infos[-1]["age"], factored_infos[-1]["age"])


class TestSubYearIntervals(unittest.TestCase):
    def _quarterly(self, **config):
        base = {"decision_interval": "quarter", "action_space": "factored", "economy_mode": "fixed"}
        base.update(config)
        env = FinancialLifeEnvGenerator.create_scenario_env("basic", base)
        env.reset(seed=0)
        return env

    def test_timing_features(self):
        env = self._quarterly()
        names = [name for name, _, _ in OBS_SPEC]
        month_i, next_i = names.index("month_of_year"), names.index("months_to_next_decision")
        seen = []
        obs = env._get_observation()
        for _ in range(5):
            seen.append((round(float(obs[month_i]), 4), round(float(obs[next_i]), 4), env.model.month))
            obs, *_ = env.step(no_change_vector())
        self.assertEqual(seen, [(0.0, 0.25, 1), (0.25, 0.25, 4), (0.5, 0.25, 7), (0.75, 0.25, 10), (0.0, 0.25, 1)])
        yearly = FinancialLifeEnvGenerator.create_scenario_env("basic")
        features = yearly._compute_observation_features()
        self.assertEqual((features["month_of_year"], features["months_to_next_decision"]), (0.0, 1.0))

    def test_reward_accumulates_a_quarter_of_the_years_utility(self):
        """Each quarterly step earns a quarter of the annual utility of the spending rate in force at
        its end (read from Spending, so the December tax settlement and the year-end flow-stat reset
        inside the fourth quarter cannot distort it), deflated to the start of the next month."""
        env = self._quarterly()
        for quarter in range(8):
            _, reward, terminated, truncated, _ = env.step(no_change_vector())
            self.assertFalse(terminated or truncated)
            deflator = env.model.economy.cumulative_inflation(
                env.model.year, env.model.month if env.model.month > 1 else None
            )
            expected = 0.25 * consumption_utility(env.spending_rate(), deflator, env.reward_config)
            self.assertAlmostEqual(reward, expected, places=12, msg=f"quarter {quarter}")
        # Four quarters at a constant real spending rate earn about one year's utility.
        yearly = FinancialLifeEnvGenerator.create_scenario_env(
            "basic", {"action_space": "factored", "economy_mode": "fixed"}
        )
        yearly.reset(seed=0)
        _, annual, *_ = yearly.step(no_change_vector())
        quarterly = self._quarterly()
        total = sum(quarterly.step(no_change_vector())[1] for _ in range(4))
        self.assertAlmostEqual(total, annual, delta=0.02 * abs(annual))

    def test_mid_year_rate_ignores_one_time_expenses_paid_so_far(self):
        """Medical costs are one-time expenses; the consumption rate a quarterly step is scored on is
        the spending rate in force, not how much of the year's one-time spending has been paid."""
        env = self._quarterly(models_healthcare=True)
        env.step(no_change_vector())
        spending = env.person.spending
        spending.add_expense(5_000, category="medical")
        self.assertGreater(spending.get_yearly_spending(), spending.base)
        self.assertEqual(env.spending_rate(), spending.base)

    def test_period_fraction_scales_only_the_consumption_term(self):
        config = FinancialLifeEnv().reward_config
        full = step_reward(
            nominal_consumption=40_000,
            deflator=1.1,
            config=config,
            terminal=True,
            nominal_terminal_net_worth=5e5,
            ruined=False,
        )
        quarter = step_reward(
            nominal_consumption=40_000,
            deflator=1.1,
            config=config,
            terminal=True,
            nominal_terminal_net_worth=5e5,
            ruined=False,
            period_fraction=0.25,
        )
        consumption = consumption_utility(40_000, 1.1, config)
        self.assertAlmostEqual(full - quarter, 0.75 * consumption)

    def test_taxes_settle_inside_the_december_quarter(self):
        """The year's return is filed in the fourth quarter's December, from the whole year's income."""
        env = self._quarterly()
        year = env.model.year
        env.step(encode_policy_action({"pretax_401k_rate": "6"}))
        for _ in range(2):
            env.step(no_change_vector())
        self.assertEqual(env.model.tax_returns.for_year(year), [])
        env.step(no_change_vector())
        (tax_return,) = env.model.tax_returns.for_year(year)
        self.assertEqual(env.model.year, year + 1)
        # The pre-tax deferral of every month (set at the first decision) left the year's W-2 wages.
        self.assertAlmostEqual(tax_return.wages, env.job.salary.base * 0.94, delta=0.03 * env.job.salary.base)

    def test_decision_age_advances_monthly(self):
        env = FinancialLifeEnvGenerator.create_scenario_env(
            "basic", {"decision_interval": "month", "economy_mode": "fixed"}
        )
        env.reset(seed=0)
        ages = []
        for _ in range(13):
            env.step(_NO_ACTION)
            ages.append(env.decision_age)
        # January births: 25 through December, 26 once the next January has been simulated.
        self.assertEqual(ages, [25] * 12 + [26])

    def test_flat_actions_at_quarterly_decisions(self):
        env = FinancialLifeEnvGenerator.create_scenario_env(
            "basic", {"decision_interval": "quarter", "checks": "strict", "economy_mode": "fixed"}
        )
        env.reset(seed=0)
        rng = np.random.default_rng(0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for _ in range(12):
                _, _, terminated, truncated, _ = env.step(int(rng.choice(env.get_legal_actions())))
                if terminated or truncated:
                    break
        self.assertEqual(env.model.invariant_violations, [])


if __name__ == "__main__":
    unittest.main()
