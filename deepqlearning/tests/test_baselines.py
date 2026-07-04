# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for scripted baselines and that a trained agent beats the do-nothing baseline."""

import os
import random
import sys
import tempfile
import unittest

import numpy as np
import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent import FinancialDQNAgent, FinancialDQNTrainer, rollout  # noqa: E402
from baselines import BASELINES, evaluate_all_baselines, evaluate_baseline  # noqa: E402
from environment import FinancialLifeEnv  # noqa: E402


class TestBaselines(unittest.TestCase):
    def test_baselines_produce_finite_scores(self):
        env = FinancialLifeEnv()
        seeds = [i for i in range(5)]
        scores = evaluate_all_baselines(env, seeds)
        self.assertEqual(set(scores), set(BASELINES))
        for score in scores.values():
            self.assertTrue(np.isfinite(score))

    def test_baseline_is_deterministic_for_seeds(self):
        env = FinancialLifeEnv()
        seeds = [1, 2, 3]
        a = evaluate_baseline(env, BASELINES["do_nothing"], seeds)
        b = evaluate_baseline(env, BASELINES["do_nothing"], seeds)
        self.assertAlmostEqual(a, b)


class TestAgentBeatsDoNothing(unittest.TestCase):
    def test_trained_agent_beats_do_nothing(self):
        # Fully seed the stack so the outcome is deterministic and non-flaky.
        random.seed(0)
        np.random.seed(0)
        torch.manual_seed(0)

        env = FinancialLifeEnv()
        state_size = env.observation_space.shape[0]
        action_size = env.action_space["action_type"].n
        agent = FinancialDQNAgent(
            state_size,
            action_size,
            {"min_replay_size": 200, "batch_size": 32, "learning_rate": 1e-3, "epsilon_end": 0.05},
        )
        trainer = FinancialDQNTrainer(
            env,
            agent,
            {
                "num_episodes": 120,
                "eval_freq": 10000,
                "save_freq": 10000,
                "print_freq": 10000,
                "base_seed": 0,
                "model_save_path": os.path.join(tempfile.mkdtemp(), "m.pt"),
            },
        )
        trainer.train()

        eval_seeds = [2_000_000 + i for i in range(10)]
        agent.epsilon = 0.0
        agent_score = float(np.mean([rollout(env, agent, training=False, seed=s).total_reward for s in eval_seeds]))
        do_nothing_score = evaluate_baseline(env, BASELINES["do_nothing"], eval_seeds)

        self.assertGreaterEqual(agent_score, do_nothing_score)


if __name__ == "__main__":
    unittest.main()
