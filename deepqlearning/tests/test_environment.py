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


if __name__ == "__main__":
    unittest.main()
