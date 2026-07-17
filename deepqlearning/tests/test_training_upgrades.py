# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the training upgrades: PER, n-step returns, batched action selection,
and vectorized-collection reproducibility."""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent import (  # noqa: E402
    Experience,
    FinancialDQNAgent,
    NStepAccumulator,
    PrioritizedReplayBuffer,
)
from environment import FinancialLifeEnv  # noqa: E402
from vector_trainer import make_vector_env  # noqa: E402


class TestPrioritizedReplayBuffer(unittest.TestCase):
    def _fill(self, buf, n):
        for i in range(n):
            buf.push(np.zeros(4, np.float32), i % 3, float(i), np.zeros(4, np.float32), False, [0, 1, 2], [0, 1, 2])

    def test_sample_returns_indices_and_weights(self):
        buf = PrioritizedReplayBuffer(capacity=50, alpha=0.6)
        self._fill(buf, 40)
        experiences, indices, weights = buf.sample(8, beta=0.4)
        self.assertEqual(len(experiences), 8)
        self.assertEqual(len(indices), 8)
        self.assertEqual(weights.shape, (8,))
        self.assertTrue(np.all(weights <= 1.0 + 1e-6))
        self.assertTrue(np.all(weights > 0))

    def test_capacity_is_a_ring_buffer(self):
        buf = PrioritizedReplayBuffer(capacity=5)
        self._fill(buf, 12)
        self.assertEqual(len(buf), 5)

    def test_priority_update_biases_sampling(self):
        # Give one index a huge priority; it should be sampled far more than uniform.
        buf = PrioritizedReplayBuffer(capacity=100, alpha=1.0)
        self._fill(buf, 100)
        np.random.seed(0)
        buf.update_priorities(np.array([7]), np.array([1000.0]))
        _, indices, _ = buf.sample(500, beta=0.4)
        frac = np.mean(indices == 7)
        self.assertGreater(frac, 0.05)  # >> uniform 1/100


class TestNStepAccumulator(unittest.TestCase):
    def test_nstep_reward_and_discount(self):
        acc = NStepAccumulator(n_step=3, gamma=0.5)
        emitted = []
        s = [np.array([float(i)], np.float32) for i in range(6)]
        rewards = [1.0, 2.0, 3.0, 4.0, 5.0]
        for t in range(5):
            done = t == 4
            out = acc.push(s[t], t, rewards[t], [0], s[t + 1], [0], done)
            emitted.extend(out)

        # First full 3-step transition: 1 + 0.5*2 + 0.25*3 = 2.75, discount 0.5**3.
        first = emitted[0]
        self.assertAlmostEqual(first.reward, 2.75)
        self.assertAlmostEqual(first.discount, 0.125)
        self.assertFalse(first.done)
        # Every start index eventually produces exactly one transition (5 steps -> 5 transitions).
        self.assertEqual(len(emitted), 5)
        # The tail transitions from the flush are marked done.
        self.assertTrue(emitted[-1].done)
        self.assertAlmostEqual(emitted[-1].reward, 5.0)
        self.assertAlmostEqual(emitted[-1].discount, 0.5)

    def test_one_step_recovers_vanilla(self):
        acc = NStepAccumulator(n_step=1, gamma=0.9)
        out = acc.push(np.zeros(1, np.float32), 0, 2.0, [0], np.zeros(1, np.float32), [0], done=False)
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0].reward, 2.0)
        self.assertAlmostEqual(out[0].discount, 0.9)

    def test_emits_are_experiences(self):
        acc = NStepAccumulator(n_step=2, gamma=1.0)
        out = acc.push(np.zeros(1, np.float32), 0, 1.0, [0], np.zeros(1, np.float32), [0], done=True)
        self.assertIsInstance(out[0], Experience)


class TestBatchedActionSelection(unittest.TestCase):
    def test_batch_actions_are_legal(self):
        env = FinancialLifeEnv()
        agent = FinancialDQNAgent(env.observation_space.shape[0], env.action_space.n, {"min_replay_size": 8})
        agent.epsilon = 0.0
        states = np.stack([env._get_observation() for _ in range(4)])
        legal_lists = [env.get_legal_actions() for _ in range(4)]
        actions = agent.select_actions_batch(states, legal_lists, training=False)
        self.assertEqual(len(actions), 4)
        for a, legal in zip(actions, legal_lists):
            self.assertIn(a, legal)


class TestVectorizedReproducibility(unittest.TestCase):
    def test_same_base_seed_reproduces_per_env_streams(self):
        # Per-env seeds derived from a base seed must reproduce identical reward streams under
        # a fixed action policy (acceptance).
        def collect(base):
            venv = make_vector_env({}, num_envs=4, backend="sync")
            no_op = venv.single_action_space.n - 1
            venv.reset(seed=[base + i for i in range(4)])
            streams = []
            for _ in range(30):
                _, rewards, _, _, _ = venv.step(np.array([no_op] * 4))
                streams.append(np.asarray(rewards).round(6).tolist())
            venv.close()
            return streams

        self.assertEqual(collect(100), collect(100))


if __name__ == "__main__":
    unittest.main()
