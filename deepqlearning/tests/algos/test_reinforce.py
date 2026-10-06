# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for REINFORCE: return computation, baselines, masking, and that updates move the policy."""

import unittest

import numpy as np
import torch

from deepqlearning.algos.base import StepBatch
from deepqlearning.algos.reinforce import ReinforceAgent

OBS_SIZE = 6
ACTION_SIZE = 4


def _agent(**overrides) -> ReinforceAgent:
    config = {"batch_episodes": 1, "verbose": False}
    config.update(overrides)
    return ReinforceAgent(OBS_SIZE, ACTION_SIZE, config)


def _feed_episode(agent, rewards, legal=None, env_id=0):
    """Hand the agent one complete episode of ``len(rewards)`` steps."""
    legal = legal if legal is not None else list(range(ACTION_SIZE))
    for t, reward in enumerate(rewards):
        done = t == len(rewards) - 1
        agent.observe(
            StepBatch(
                obs=np.random.rand(1, OBS_SIZE).astype(np.float32),
                actions=np.array([t % ACTION_SIZE]),
                rewards=np.array([reward]),
                next_obs=np.random.rand(1, OBS_SIZE).astype(np.float32),
                terminated=np.array([done]),
                truncated=np.array([False]),
                legal=[legal],
                next_legal=[legal],
                env_ids=np.array([env_id]),
            )
        )


class TestDiscountedReturns(unittest.TestCase):
    def test_reward_to_go_matches_hand_computation(self):
        agent = _agent(gamma=0.5)
        # Rewards 1, 2, 3 with gamma 0.5:
        #   G_2 = 3
        #   G_1 = 2 + 0.5*3   = 3.5
        #   G_0 = 1 + 0.5*3.5 = 2.75
        self.assertEqual(agent._discounted_returns([1.0, 2.0, 3.0]), [2.75, 3.5, 3.0])

    def test_undiscounted_returns_are_suffix_sums(self):
        agent = _agent(gamma=1.0)
        self.assertEqual(agent._discounted_returns([1.0, 2.0, 3.0]), [6.0, 5.0, 3.0])


class TestBaselines(unittest.TestCase):
    def test_unknown_baseline_is_rejected(self):
        with self.assertRaises(ValueError):
            _agent(baseline="magic")

    def test_value_baseline_adds_a_value_head(self):
        self.assertIsNotNone(_agent(baseline="value").policy.value_head)
        self.assertIsNone(_agent(baseline="none").policy.value_head)

    def test_running_mean_baseline_tracks_observed_returns(self):
        agent = _agent(baseline="mean", gamma=1.0, normalize_returns=False)
        # The first batch is scored against a zero baseline, then the mean is folded in.
        self.assertEqual(agent._update_return_mean(np.array([2.0, 4.0], dtype=np.float32)), 0.0)
        self.assertAlmostEqual(agent._return_mean, 3.0, places=6)
        self.assertAlmostEqual(agent._update_return_mean(np.array([3.0], dtype=np.float32)), 3.0, places=6)
        self.assertAlmostEqual(agent._return_mean, 3.0, places=6)


class TestActionMasking(unittest.TestCase):
    def test_sampling_never_picks_an_illegal_action(self):
        torch.manual_seed(0)
        agent = _agent()
        legal = [1, 3]
        obs = np.random.rand(500, OBS_SIZE).astype(np.float32)
        actions = agent.act(obs, [legal] * 500, training=True).actions
        self.assertEqual(set(actions.tolist()) - set(legal), set())

    def test_greedy_action_is_legal_and_deterministic(self):
        agent = _agent()
        obs = np.random.rand(1, OBS_SIZE).astype(np.float32)
        picks = {int(agent.act(obs, [[2]], training=False).actions[0]) for _ in range(10)}
        self.assertEqual(picks, {2})


class TestUpdate(unittest.TestCase):
    def test_update_waits_for_the_configured_episode_count(self):
        agent = _agent(batch_episodes=2)
        _feed_episode(agent, [1.0, 1.0])
        self.assertIsNone(agent.update())
        _feed_episode(agent, [1.0, 1.0])
        self.assertIsNotNone(agent.update())

    def test_gradient_step_changes_policy_parameters(self):
        torch.manual_seed(0)
        agent = _agent(batch_episodes=1, learning_rate=0.1)
        before = [p.detach().clone() for p in agent.policy.parameters()]
        _feed_episode(agent, [1.0, 2.0, 3.0])
        metrics = agent.update()
        self.assertIsNotNone(metrics)
        self.assertTrue(np.isfinite(metrics["loss"]))
        after = list(agent.policy.parameters())
        self.assertTrue(any(not torch.allclose(a, b) for a, b in zip(before, after)))

    def test_entropy_is_finite_under_masking(self):
        # Illegal actions carry a large finite logit rather than -inf, so entropy stays defined.
        torch.manual_seed(0)
        agent = _agent(batch_episodes=1, entropy_coef=1.0)
        _feed_episode(agent, [1.0, 1.0], legal=[0, 2])
        metrics = agent.update()
        self.assertTrue(np.isfinite(metrics["entropy"]))

    def test_entropy_coefficient_anneals_to_its_floor(self):
        agent = _agent(entropy_coef=0.02, entropy_coef_final=0.0)
        agent.anneal(0.5)
        self.assertAlmostEqual(agent.entropy_coef, 0.01, places=6)
        agent.anneal(1.0)
        self.assertAlmostEqual(agent.entropy_coef, 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
