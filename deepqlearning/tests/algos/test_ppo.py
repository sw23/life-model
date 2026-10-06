# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for PPO: GAE, the clipped surrogate, rollout readiness, minibatching, and masking."""

import unittest

import numpy as np
import torch

from deepqlearning.algos.base import StepBatch, masked_categorical
from deepqlearning.algos.ppo import PPOAgent, RolloutBuffer, clipped_surrogate

OBS_SIZE = 5
ACTION_SIZE = 4
GAMMA = 0.9
LAMBDA = 0.8


def _agent(**overrides) -> PPOAgent:
    config = {"n_steps": 4, "num_envs": 1, "verbose": False}
    config.update(overrides)
    return PPOAgent(OBS_SIZE, ACTION_SIZE, config)


def _feed(agent, n_steps, terminated=None, truncated=None, env_id=0, legal=None):
    """Push ``n_steps`` transitions for one environment stream through the collection path."""
    legal = legal if legal is not None else list(range(ACTION_SIZE))
    for t in range(n_steps):
        obs = np.random.rand(1, OBS_SIZE).astype(np.float32)
        act_result = agent.act(obs, [legal], training=True)
        agent.observe(
            StepBatch(
                obs=obs,
                actions=act_result.actions,
                rewards=np.array([1.0]),
                next_obs=np.random.rand(1, OBS_SIZE).astype(np.float32),
                terminated=np.array([bool(terminated[t]) if terminated else False]),
                truncated=np.array([bool(truncated[t]) if truncated else False]),
                legal=[legal],
                next_legal=[legal],
                env_ids=np.array([env_id]),
                extras=act_result.extras,
            )
        )


class TestGAE(unittest.TestCase):
    """A fixed 4-step sequence with hand-computed advantages."""

    rewards = np.array([1.0, 1.0, 1.0, 1.0])
    values = np.array([0.5, 0.5, 0.5, 0.5])
    next_values = np.array([0.5, 0.5, 0.5, 2.0])

    def _gae(self, terminated, truncated):
        from deepqlearning.algos.ppo import compute_gae

        return compute_gae(
            self.rewards,
            self.values,
            self.next_values,
            np.array(terminated),
            np.array(truncated),
            GAMMA,
            LAMBDA,
        )

    def test_termination_zeroes_the_bootstrap(self):
        # delta_3 = 1 + 0.9*2.0*0 - 0.5 = 0.5  (no future exists past a terminal state)
        # delta_2 = 1 + 0.9*0.5   - 0.5 = 0.95, A_2 = 0.95 + 0.72*0.5 = 1.31
        advantages = self._gae([False, False, False, True], [False] * 4)
        self.assertAlmostEqual(advantages[3], 0.5, places=6)
        self.assertAlmostEqual(advantages[2], 1.31, places=6)
        self.assertAlmostEqual(advantages[1], 0.95 + 0.72 * 1.31, places=6)
        self.assertAlmostEqual(advantages[0], 0.95 + 0.72 * (0.95 + 0.72 * 1.31), places=6)

    def test_truncation_bootstraps_through_the_cutoff(self):
        # delta_3 = 1 + 0.9*2.0 - 0.5 = 2.3 — the future is real, the rollout just stopped looking.
        advantages = self._gae([False] * 4, [False, False, False, True])
        self.assertAlmostEqual(advantages[3], 2.3, places=6)
        self.assertAlmostEqual(advantages[2], 0.95 + 0.72 * 2.3, places=6)

    def test_episode_boundary_stops_the_recursion(self):
        # A terminal at t=1 must not let t=2's advantage leak backwards into t=1 and t=0.
        advantages = self._gae([False, True, False, True], [False] * 4)
        self.assertAlmostEqual(advantages[1], 0.5, places=6)
        self.assertAlmostEqual(advantages[0], 0.95 + 0.72 * 0.5, places=6)


class TestClippedSurrogate(unittest.TestCase):
    def test_ratio_above_the_band_is_clipped(self):
        loss = clipped_surrogate(torch.tensor([1.5]), torch.tensor([2.0]), 0.2)
        self.assertAlmostEqual(float(loss), -(1.2 * 2.0), places=6)

    def test_ratio_below_the_band_is_clipped_for_negative_advantage(self):
        loss = clipped_surrogate(torch.tensor([0.5]), torch.tensor([-2.0]), 0.2)
        self.assertAlmostEqual(float(loss), 0.8 * 2.0, places=6)

    def test_ratio_inside_the_band_is_untouched(self):
        loss = clipped_surrogate(torch.tensor([1.1]), torch.tensor([2.0]), 0.2)
        self.assertAlmostEqual(float(loss), -(1.1 * 2.0), places=6)


class TestRolloutBuffer(unittest.TestCase):
    def test_capacity_is_steps_times_envs(self):
        buffer = RolloutBuffer(n_steps=3, num_envs=4)
        self.assertEqual(buffer.capacity, 12)
        buffer.resize(n_steps=5, num_envs=2)
        self.assertEqual(buffer.capacity, 10)

    def test_update_refuses_until_the_rollout_is_full(self):
        agent = _agent(n_steps=4, num_envs=1)
        _feed(agent, 3)
        self.assertIsNone(agent.update())
        self.assertEqual(len(agent.buffer), 3)
        _feed(agent, 1)
        self.assertIsNotNone(agent.update())
        # The rollout is on-policy, so it is discarded once consumed.
        self.assertEqual(len(agent.buffer), 0)

    def test_env_count_resizes_the_rollout(self):
        agent = _agent(n_steps=4, num_envs=1)
        agent.on_env_count(3)
        self.assertEqual(agent.buffer.capacity, 12)


class TestUpdate(unittest.TestCase):
    def test_minibatch_epochs_take_the_expected_number_of_gradient_steps(self):
        torch.manual_seed(0)
        agent = _agent(n_steps=8, num_envs=1, epochs=3, minibatches=2)
        _feed(agent, 8)

        steps = []
        real_step = agent.optimizer.step
        agent.optimizer.step = lambda *a, **kw: (steps.append(1), real_step(*a, **kw))[1]
        agent.update()
        # 3 epochs x (8 transitions / 4-sample minibatches) = 6 gradient steps.
        self.assertEqual(len(steps), 6)

    def test_metrics_are_finite(self):
        torch.manual_seed(0)
        agent = _agent(n_steps=8, num_envs=1)
        _feed(agent, 8)
        metrics = agent.update()
        for key in ("loss", "policy_loss", "value_loss", "entropy", "clip_fraction"):
            self.assertTrue(np.isfinite(metrics[key]), key)

    def test_observe_requires_the_act_extras(self):
        agent = _agent()
        with self.assertRaises(ValueError):
            agent.observe(
                StepBatch(
                    obs=np.zeros((1, OBS_SIZE), dtype=np.float32),
                    actions=np.array([0]),
                    rewards=np.array([0.0]),
                    next_obs=np.zeros((1, OBS_SIZE), dtype=np.float32),
                    terminated=np.array([False]),
                    truncated=np.array([False]),
                    legal=[[0, 1]],
                    next_legal=[[0, 1]],
                    env_ids=np.array([0]),
                )
            )


class TestMaskedCategorical(unittest.TestCase):
    def test_illegal_actions_get_zero_probability(self):
        logits = torch.tensor([[3.0, 1.0, 2.0, 0.5]])
        dist = masked_categorical(logits, [[1, 3]])
        probs = dist.probs[0]
        self.assertEqual(float(probs[0]), 0.0)
        self.assertEqual(float(probs[2]), 0.0)
        self.assertAlmostEqual(float(probs[1] + probs[3]), 1.0, places=5)
        self.assertTrue(torch.isfinite(dist.entropy()).all())

    def test_empty_mask_leaves_every_action_available(self):
        dist = masked_categorical(torch.zeros((1, ACTION_SIZE)), [[]])
        self.assertTrue(torch.all(dist.probs > 0))


if __name__ == "__main__":
    unittest.main()
