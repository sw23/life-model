# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the policy-analysis artifacts: they generate headlessly."""

import os
import tempfile
import unittest

import matplotlib

from deepqlearning.algos.dqn import DQNAgent
from deepqlearning.envs.financial.environment import FinancialLifeEnv
from deepqlearning.evaluation.analyze_policy import analyze


class TestAnalyzePolicy(unittest.TestCase):
    def test_artifacts_generate_headlessly(self):
        # analyze_policy forces the Agg backend, so importing it must leave us headless-capable.
        self.assertEqual(matplotlib.get_backend().lower(), "agg")

        env = FinancialLifeEnv()
        agent = DQNAgent(env.observation_space, env.action_space, {"min_replay_size": 8, "verbose": False})

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
