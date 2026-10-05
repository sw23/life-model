# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Unit tests for the DQN agent: masking, epsilon schedule, replay, and rollout determinism."""

import unittest

import numpy as np

from deepqlearning.algos.base import StepBatch
from deepqlearning.algos.dqn import DQNAgent
from deepqlearning.algos.replay import Experience, ReplayBuffer
from deepqlearning.envs.financial.environment import FinancialLifeEnv
from deepqlearning.training.rollout import rollout


def _make_agent(**overrides):
    config = {"min_replay_size": 8, "batch_size": 4, "replay_buffer_size": 1000, "verbose": False}
    config.update(overrides)
    return DQNAgent(20, 16, config)


class TestEpsilonSchedule(unittest.TestCase):
    def test_epsilon_decays_over_training_not_per_step(self):
        agent = _make_agent(epsilon_start=1.0, epsilon_end=0.01, epsilon_decay_fraction=0.5)
        # Floor should be reached at ~50% of training, not within the first few percent.
        agent.anneal(0.10)
        self.assertGreater(agent.epsilon, 0.5)
        agent.anneal(0.50)
        self.assertAlmostEqual(agent.epsilon, 0.01, places=6)

    def test_epsilon_floor_reached_no_earlier_than_the_decay_fraction(self):
        agent = _make_agent(epsilon_start=1.0, epsilon_end=0.01, epsilon_decay_fraction=0.6)
        agent.anneal(0.4)
        self.assertGreater(agent.epsilon, 0.01 + 1e-6)


class TestActionMasking(unittest.TestCase):
    def test_select_action_only_returns_legal_actions(self):
        agent = _make_agent()
        agent.epsilon = 0.0  # force greedy
        state = np.zeros(20, dtype=np.float32)
        legal = [2, 5, 9]
        for _ in range(20):
            self.assertIn(agent.select_action(state, legal, training=False), legal)

    def test_batch_actions_are_legal(self):
        agent = _make_agent()
        agent.epsilon = 0.0
        states = np.random.rand(4, 20).astype(np.float32)
        legal_lists = [[0, 1], [3], [2, 5, 9], list(range(16))]
        actions = agent.act(states, legal_lists, training=False).actions
        self.assertEqual(len(actions), 4)
        for action, legal in zip(actions, legal_lists):
            self.assertIn(int(action), legal)

    def test_update_masks_illegal_next_actions(self):
        # A gradient step with next_legal_actions stored should run without error and produce a
        # finite loss even when only a subset of next actions is legal.
        agent = _make_agent()
        for i in range(20):
            s = np.random.rand(20).astype(np.float32)
            ns = np.random.rand(20).astype(np.float32)
            agent.store_experience(s, i % 16, 1.0, ns, False, [0, 1, 2], [3, 4])
        metrics = agent.update()
        self.assertIsNotNone(metrics)
        self.assertTrue(np.isfinite(metrics["loss"]))


class TestReplayBuffer(unittest.TestCase):
    def test_capacity_and_sampling(self):
        buf = ReplayBuffer(capacity=3)
        for i in range(5):
            buf.push(i, i, float(i), i, False, [0], [0])
        self.assertEqual(len(buf), 3)  # oldest evicted
        sample = buf.sample(2)
        self.assertEqual(len(sample), 2)
        self.assertIsInstance(sample[0], Experience)

    def test_store_experience_records_next_legal_actions(self):
        agent = _make_agent()
        agent.store_experience(np.zeros(20), 0, 1.0, np.zeros(20), False, [0, 1], [2, 3])
        exp = agent.replay_buffer.buffer[-1]
        self.assertEqual(exp.next_legal_actions, [2, 3])


class TestObserveAccumulatesPerEnvStream(unittest.TestCase):
    def test_n_step_accumulation_is_keyed_by_env_id(self):
        # Two interleaved streams must not contaminate each other's n-step returns: with n_step=2
        # and gamma=1, each stream's emitted transition sums only its own two rewards.
        agent = _make_agent(n_step=2, gamma=1.0, use_prioritized_replay=False)
        for reward_pair in ([1.0, 10.0], [2.0, 20.0]):
            agent.observe(
                StepBatch(
                    obs=np.zeros((2, 20), dtype=np.float32),
                    actions=np.array([0, 1]),
                    rewards=np.array(reward_pair),
                    next_obs=np.zeros((2, 20), dtype=np.float32),
                    terminated=np.array([False, False]),
                    truncated=np.array([False, False]),
                    legal=[[0, 1], [0, 1]],
                    next_legal=[[0, 1], [0, 1]],
                    env_ids=np.array([0, 1]),
                )
            )
        rewards = sorted(exp.reward for exp in agent.replay_buffer.buffer)
        self.assertEqual(rewards, [3.0, 30.0])


class TestEvalModeDeterminism(unittest.TestCase):
    def test_greedy_selection_is_deterministic_despite_dropout(self):
        agent = _make_agent()
        agent.epsilon = 0.0
        state = np.random.rand(20).astype(np.float32)
        legal = list(range(16))
        picks = {agent.select_action(state, legal, training=False) for _ in range(10)}
        self.assertEqual(len(picks), 1)  # dropout disabled at inference -> deterministic


class TestRolloutAndEval(unittest.TestCase):
    def test_rollout_is_deterministic_for_a_seed(self):
        env = FinancialLifeEnv()
        agent = DQNAgent(
            env.observation_space,
            env.action_space,
            {"min_replay_size": 8, "batch_size": 4, "replay_buffer_size": 1000, "verbose": False},
        )
        agent.epsilon = 0.0
        r1 = rollout(env, agent, training=False, seed=5)
        r2 = rollout(env, agent, training=False, seed=5)
        self.assertAlmostEqual(r1.total_reward, r2.total_reward)
        self.assertEqual(r1.steps, r2.steps)


if __name__ == "__main__":
    unittest.main()
