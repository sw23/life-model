# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Unit tests for the DQN agent: masking, epsilon schedule, replay, and checkpointing."""

import os
import sys
import tempfile
import unittest

import numpy as np
import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent import MODEL_VERSION, Experience, FinancialDQNAgent, ReplayBuffer, rollout  # noqa: E402
from environment import FinancialLifeEnv  # noqa: E402


def _make_agent(**overrides):
    config = {"min_replay_size": 8, "batch_size": 4, "replay_buffer_size": 1000}
    config.update(overrides)
    return FinancialDQNAgent(state_size=20, action_size=16, config=config)


class TestEpsilonSchedule(unittest.TestCase):
    def test_epsilon_decays_per_episode_not_per_step(self):
        agent = _make_agent(epsilon_start=1.0, epsilon_end=0.01, epsilon_decay_fraction=0.5)
        num_episodes = 100
        # Floor should be reached at ~50% of episodes, not within the first few.
        agent.update_epsilon(10, num_episodes)
        self.assertGreater(agent.epsilon, 0.5)
        agent.update_epsilon(50, num_episodes)
        self.assertAlmostEqual(agent.epsilon, 0.01, places=6)

    def test_epsilon_floor_reached_no_earlier_than_half(self):
        agent = _make_agent(epsilon_start=1.0, epsilon_end=0.01, epsilon_decay_fraction=0.6)
        num_episodes = 200
        agent.update_epsilon(int(num_episodes * 0.4), num_episodes)
        self.assertGreater(agent.epsilon, 0.01 + 1e-6)


class TestActionMasking(unittest.TestCase):
    def test_select_action_only_returns_legal_actions(self):
        agent = _make_agent()
        agent.epsilon = 0.0  # force greedy
        state = np.zeros(20, dtype=np.float32)
        legal = [2, 5, 9]
        for _ in range(20):
            self.assertIn(agent.select_action(state, legal, training=False), legal)

    def test_train_masks_illegal_next_actions(self):
        # A gradient step with next_legal_actions stored should run without error and produce a
        # finite loss even when only a subset of next actions is legal.
        agent = _make_agent()
        for i in range(20):
            s = np.random.rand(20).astype(np.float32)
            ns = np.random.rand(20).astype(np.float32)
            agent.store_experience(s, i % 16, 1.0, ns, False, [0, 1, 2], [3, 4])
        loss = agent.train()
        self.assertIsNotNone(loss)
        self.assertTrue(np.isfinite(loss))


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


class TestEvalModeDeterminism(unittest.TestCase):
    def test_greedy_selection_is_deterministic_despite_dropout(self):
        agent = _make_agent()
        agent.epsilon = 0.0
        state = np.random.rand(20).astype(np.float32)
        legal = list(range(16))
        picks = {agent.select_action(state, legal, training=False) for _ in range(10)}
        self.assertEqual(len(picks), 1)  # dropout disabled at inference -> deterministic


class TestCheckpointRoundTrip(unittest.TestCase):
    def test_round_trip_with_weights_only(self):
        agent = _make_agent()
        # Populate some training state.
        for i in range(20):
            agent.store_experience(np.random.rand(20), i % 16, 1.0, np.random.rand(20), False, [0, 1], [0, 1])
        agent.train()
        agent.episode_rewards.append(1.23)

        path = os.path.join(tempfile.mkdtemp(), "ckpt.pt")
        agent.save_model(path)

        # torch.load(weights_only=True) is the default on modern torch; loading must not need any
        # environment-variable escape hatch.
        loaded = torch.load(path, weights_only=True)
        self.assertEqual(loaded["model_version"], MODEL_VERSION)

        agent2 = _make_agent()
        agent2.load_model(path)
        sd1, sd2 = agent.q_network.state_dict(), agent2.q_network.state_dict()
        self.assertTrue(all(torch.allclose(sd1[k], sd2[k]) for k in sd1))
        self.assertEqual(agent2.episode_rewards, agent.episode_rewards)

    def test_version_mismatch_refuses_to_load(self):
        # Plan 18: the observation layout / action space changed, so a checkpoint from another
        # version must fail loudly with a clear message instead of loading misaligned weights.
        agent = _make_agent()
        path = os.path.join(tempfile.mkdtemp(), "ckpt.pt")
        agent.save_model(path)
        # Tamper the version in the checkpoint.
        ckpt = torch.load(path, weights_only=True)
        ckpt["model_version"] = MODEL_VERSION + 99
        torch.save(ckpt, path)

        agent2 = _make_agent()
        with self.assertRaises(ValueError) as ctx:
            agent2.load_model(path)
        self.assertIn("model_version", str(ctx.exception))

    def test_missing_obs_version_refuses_to_load(self):
        # A pre-Plan-18 checkpoint has no obs_version key at all — it must also refuse.
        agent = _make_agent()
        path = os.path.join(tempfile.mkdtemp(), "ckpt.pt")
        agent.save_model(path)
        ckpt = torch.load(path, weights_only=True)
        del ckpt["obs_version"]
        torch.save(ckpt, path)

        agent2 = _make_agent()
        with self.assertRaises(ValueError):
            agent2.load_model(path)


class TestRolloutAndEval(unittest.TestCase):
    def test_rollout_is_deterministic_for_a_seed(self):
        env = FinancialLifeEnv()
        agent = FinancialDQNAgent(
            state_size=env.observation_space.shape[0],
            action_size=env.action_space["action_type"].n,
            config={"min_replay_size": 8, "batch_size": 4, "replay_buffer_size": 1000},
        )
        agent.epsilon = 0.0
        r1 = rollout(env, agent, training=False, seed=5)
        r2 = rollout(env, agent, training=False, seed=5)
        self.assertAlmostEqual(r1.total_reward, r2.total_reward)
        self.assertEqual(r1.steps, r2.steps)


if __name__ == "__main__":
    unittest.main()
