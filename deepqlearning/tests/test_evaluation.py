# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the statistical evaluation protocol (Plan 19 D3)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from baselines import BASELINES  # noqa: E402
from environment import FinancialLifeEnv  # noqa: E402
from evaluation import EvalProtocol, format_comparison_table, run_policy_episode, spawn_seeds  # noqa: E402

_REQUIRED_STAT_KEYS = {
    "n",
    "mean_return",
    "ci_low",
    "ci_high",
    "ruin_rate",
    "success_rate",
    "net_worth_p10",
    "net_worth_p50",
    "net_worth_p90",
    "mean_steps",
}


class TestSeedSpawning(unittest.TestCase):
    def test_reproducible_and_disjoint(self):
        a = spawn_seeds(42, 10)
        b = spawn_seeds(42, 10)
        self.assertEqual(a, b)
        both = spawn_seeds(7, 20)
        train, held = both[:10], both[10:]
        self.assertEqual(len(set(train) & set(held)), 0)


class TestRunPolicyEpisode(unittest.TestCase):
    def test_outcome_fields_present(self):
        env = FinancialLifeEnv()
        outcome = run_policy_episode(env, BASELINES["contribution_waterfall"], seed=1)
        self.assertGreater(outcome.steps, 0)
        self.assertIsInstance(outcome.ruined, bool)
        self.assertIsInstance(outcome.success, bool)
        self.assertIs(type(outcome.total_reward), float)


class TestEvalProtocol(unittest.TestCase):
    def _protocol(self, **overrides):
        kwargs = dict(n_eval=4, master_seed=123, bootstrap_resamples=200, held_out_scenario="recession")
        kwargs.update(overrides)
        return EvalProtocol(**kwargs)

    def test_report_has_all_conditions_and_stat_keys(self):
        report = self._protocol().run()
        self.assertIn("train", report["conditions"])
        self.assertIn("held_out_seeds", report["conditions"])
        self.assertIn("held_out_scenario", report["conditions"])
        # Every baseline appears in every condition with the full stat set.
        for cond in report["conditions"].values():
            self.assertEqual(set(cond), set(BASELINES))
            for stats in cond.values():
                self.assertEqual(set(stats), _REQUIRED_STAT_KEYS)

    def test_report_records_reward_config(self):
        report = self._protocol(reward_preset="retirement_security").run()
        self.assertEqual(report["reward_preset"], "retirement_security")
        self.assertEqual(report["reward_config"]["name"], "retirement_security")

    def test_held_out_scenario_can_be_disabled(self):
        report = self._protocol(held_out_scenario=None).run()
        self.assertNotIn("held_out_scenario", report["conditions"])

    def test_reproducible_under_master_seed(self):
        r1 = self._protocol().run()
        r2 = self._protocol().run()
        self.assertEqual(
            r1["conditions"]["train"]["do_nothing"]["mean_return"],
            r2["conditions"]["train"]["do_nothing"]["mean_return"],
        )

    def test_agent_verdict_and_table(self):
        # A stub agent that always no-ops exercises the agent path and intelligence verdict.
        no_op = FinancialLifeEnv().action_space.n - 1  # NO_ACTION is the last flat index

        class StubAgent:
            def select_action(self, state, legal_actions, training=False):
                return no_op if no_op in legal_actions else legal_actions[0]

        report = self._protocol().run(agent=StubAgent())
        self.assertIn("agent", report["conditions"]["train"])
        self.assertIn("intelligent", report)
        v = report["intelligent"]
        self.assertIn("verdict_intelligent", v)
        self.assertIn("best_heuristic", v)
        # The always-no-op stub cannot beat the planner heuristics.
        self.assertFalse(v["verdict_intelligent"])
        table = format_comparison_table(report)
        self.assertIn("[train]", table)
        self.assertIn("INTELLIGENT", table)


if __name__ == "__main__":
    unittest.main()
