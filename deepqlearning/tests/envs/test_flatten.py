# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""``FlattenPolicies``: the Discrete views (joint enumeration, sequential sub-steps) DQN trains on."""

import unittest
import warnings

import numpy as np
from gymnasium import spaces

from deepqlearning.algos.dqn import DQNAgent
from deepqlearning.envs.financial.flatten import (
    FlattenPolicies,
    compose_action,
    resolve_mode,
    sequential_pairs,
)
from deepqlearning.envs.financial.policies import NVEC
from deepqlearning.envs.registry import make_env
from deepqlearning.evaluation.protocol import run_policy_episode
from deepqlearning.tests.algos.test_factored import SlotMatchEnv
from deepqlearning.training.rollout import rollout


class RecordingEnv(SlotMatchEnv):
    def __init__(self):
        super().__init__(horizon=3)
        self.actions = []

    def step(self, action):
        self.actions.append(np.asarray(action).tolist())
        return super().step(action)


class TestModes(unittest.TestCase):
    def test_auto_picks_joint_only_for_small_spaces(self):
        self.assertEqual(resolve_mode("auto", (3, 2, 4)), "joint")
        self.assertEqual(resolve_mode("auto", NVEC), "sequential")  # 2,540,160 joint actions
        self.assertEqual(resolve_mode("auto", (3, 2, 4), max_joint=10), "sequential")
        with self.assertRaises(ValueError):
            resolve_mode("pairs", NVEC)

    def test_rejects_a_discrete_env(self):
        with self.assertRaises(TypeError):
            FlattenPolicies(make_env("financial:basic", {}))


class TestJoint(unittest.TestCase):
    def test_joint_index_decodes_and_masks(self):
        env = FlattenPolicies(RecordingEnv(), "joint")
        self.assertEqual(env.action_space, spaces.Discrete(24))
        _, info = env.reset(seed=0)
        mask = info["legal_mask"]
        self.assertEqual(mask.shape, (24,))
        for index in range(24):
            self.assertEqual(bool(mask[index]), env.decode(index)[2] != 1)
        target = int(np.ravel_multi_index(SlotMatchEnv.TARGET, (3, 2, 4)))
        _, reward, *_ = env.step(target)
        self.assertEqual(reward, 3.0)
        self.assertEqual(env.unwrapped.actions[-1], list(SlotMatchEnv.TARGET))


class TestSequential(unittest.TestCase):
    def test_stage_then_commit(self):
        env = FlattenPolicies(RecordingEnv(), "sequential", max_changes=3)
        pairs = sequential_pairs((3, 2, 4))
        self.assertEqual(env.action_space, spaces.Discrete(1 + 2 + 1 + 3))
        obs, info = env.reset(seed=0)
        self.assertEqual(obs.shape, (4 + 2 * 3 + 1,))
        stage = pairs.index((0, 2)) + 1
        obs, reward, terminated, truncated, info = env.step(stage)
        self.assertEqual((reward, terminated, truncated, info["decision_substep"]), (0.0, False, False, True))
        self.assertEqual(env.unwrapped.actions, [])
        # The staged slot's pairs are masked; commit stays legal.
        self.assertTrue(info["legal_mask"][0])
        self.assertFalse(info["legal_mask"][pairs.index((0, 1)) + 1])
        self.assertEqual(obs[4], 1.0)  # slot 0 staged at its last value
        _, reward, *_ = env.step(0)
        self.assertEqual(env.unwrapped.actions, [[2, 0, 0]])

    def test_the_cap_commits_automatically(self):
        env = FlattenPolicies(RecordingEnv(), "sequential", max_changes=2)
        pairs = sequential_pairs((3, 2, 4))
        env.reset(seed=0)
        env.step(pairs.index((1, 1)) + 1)
        _, reward, *_, info = env.step(pairs.index((2, 3)) + 1)
        self.assertFalse(info["decision_substep"])
        self.assertEqual(env.unwrapped.actions, [[0, 1, 3]])
        self.assertEqual(reward, 2.0)

    def test_compose_action_replays_the_staging(self):
        choices = iter([3, 1, 0])  # stage (1, 1), then (0, 1), then commit
        vector = compose_action(lambda obs, legal: next(choices), np.zeros(4), np.ones(9, dtype=bool), (3, 2, 4))
        self.assertEqual(vector.tolist(), [1, 1, 0])


class TestDQNThroughTheWrapper(unittest.TestCase):
    def test_dqn_trains_on_the_factored_financial_env_and_scores_on_the_raw_env(self):
        env = make_env(
            "financial:basic", {"action_space": "factored", "flatten_policies": "auto", "economy_mode": "fixed"}
        )
        self.assertIsInstance(env, FlattenPolicies)
        self.assertEqual(env.action_space, spaces.Discrete(1 + sum(n - 1 for n in NVEC)))
        agent = DQNAgent(
            env.observation_space,
            env.action_space,
            {"min_replay_size": 16, "batch_size": 8, "hidden_sizes": [32, 32], "verbose": False, "device": "cpu"},
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for episode in range(2):
                rollout(env, agent, training=True, seed=episode)
            self.assertGreater(agent.steps_done, 0)
            outcome = run_policy_episode(env.unwrapped, env.agent_policy(agent), seed=7)
        self.assertGreater(outcome.steps, 0)


if __name__ == "__main__":
    unittest.main()
