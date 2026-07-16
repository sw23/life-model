# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the policy-analysis artifacts (Plan 19 D5): they generate headlessly."""

import os
import sys
import tempfile
import unittest

import matplotlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent import FinancialDQNAgent  # noqa: E402
from analyze_policy import analyze  # noqa: E402
from environment import FinancialLifeEnv  # noqa: E402


class TestAnalyzePolicy(unittest.TestCase):
    def test_artifacts_generate_headlessly(self):
        # analyze_policy forces the Agg backend, so importing it must leave us headless-capable.
        self.assertEqual(matplotlib.get_backend().lower(), "agg")

        env = FinancialLifeEnv()
        agent = FinancialDQNAgent(env.observation_space.shape[0], env.action_space.n, {"min_replay_size": 8})
        agent.epsilon = 0.0

        out_dir = tempfile.mkdtemp()
        manifest = analyze(agent, {}, out_dir, n_episodes=4)

        for name in (
            "policy_heatmap.png",
            "contribution_schedule.png",
            "lifetime_trace.png",
            "lifetime_trace.json",
            "analysis_manifest.json",
        ):
            path = os.path.join(out_dir, name)
            self.assertTrue(os.path.exists(path), f"missing artifact {name}")
            self.assertGreater(os.path.getsize(path), 0)

        self.assertIn("heatmap", manifest)
        self.assertIn("schedule", manifest)
        self.assertIn("categories", manifest["heatmap"])
        self.assertEqual(len(manifest["schedule"]["ages"]), len(manifest["schedule"]["avg_contribution"]))


if __name__ == "__main__":
    unittest.main()
