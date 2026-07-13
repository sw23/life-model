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

from actions import ActionType, encode_flat_action  # noqa: E402
from agent import FinancialDQNAgent, FinancialDQNTrainer, rollout  # noqa: E402
from baselines import (  # noqa: E402
    BASELINES,
    PLANNER_BASELINES,
    collect_teacher_experiences,
    evaluate_all_baselines,
    evaluate_baseline,
)
from environment import FinancialLifeEnv  # noqa: E402

_NO_ACTION = encode_flat_action(ActionType.NO_ACTION)


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


class TestPlannerBaselines(unittest.TestCase):
    """Plan 19 D2: the planner-grade baselines that define the 'intelligent' bar."""

    def test_all_planner_baselines_registered(self):
        for name in PLANNER_BASELINES:
            self.assertIn(name, BASELINES)

    def test_each_baseline_only_emits_legal_actions_on_50_seeds(self):
        # Acceptance criterion: each heuristic runs legally to episode end on 50 random seeds.
        env = FinancialLifeEnv()
        for name in PLANNER_BASELINES:
            policy = BASELINES[name]
            for seed in range(50):
                env.reset(seed=seed)
                steps = 0
                while True:
                    legal = set(env.get_legal_actions())
                    action = policy(env)
                    self.assertIn(action, legal, f"{name} emitted illegal action {action} at seed {seed}")
                    _, _, terminated, truncated, _ = env.step(action)
                    steps += 1
                    if terminated or truncated:
                        break
                self.assertGreater(steps, 0)

    def test_each_baseline_is_deterministic_per_seed(self):
        env = FinancialLifeEnv()
        seeds = [11, 12, 13]
        for name in PLANNER_BASELINES:
            a = evaluate_baseline(env, BASELINES[name], seeds)
            b = evaluate_baseline(env, BASELINES[name], seeds)
            self.assertAlmostEqual(a, b, msg=f"{name} not deterministic per seed")

    def test_planner_baselines_beat_do_nothing_on_default_objective(self):
        # A sanity check that the bar is meaningful: the contribution waterfall should not be worse
        # than doing nothing under the default (retirement_security) objective.
        env = FinancialLifeEnv()
        seeds = list(range(20))
        scores = evaluate_all_baselines(env, seeds)
        self.assertGreaterEqual(scores["contribution_waterfall"], scores["do_nothing"] - 1e-6)

    def test_teacher_experiences_have_expected_shape(self):
        env = FinancialLifeEnv()
        transitions = collect_teacher_experiences(env, BASELINES["contribution_waterfall"], seeds=[1, 2])
        self.assertGreater(len(transitions), 0)
        state, action, reward, next_state, done, legal, next_legal = transitions[0]
        self.assertEqual(state.shape, (env.observation_space.shape[0],))
        self.assertIn(action, range(env.action_space.n))
        self.assertIs(type(reward), float)
        self.assertIsInstance(done, bool)
        self.assertIsInstance(legal, list)
        self.assertIsInstance(next_legal, list)


class TestAgentBeatsDoNothing(unittest.TestCase):
    def test_trained_agent_beats_do_nothing(self):
        # Fully seed the stack so the outcome is deterministic and non-flaky.
        random.seed(0)
        np.random.seed(0)
        torch.manual_seed(0)

        env = FinancialLifeEnv()
        state_size = env.observation_space.shape[0]
        action_size = env.action_space.n
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
