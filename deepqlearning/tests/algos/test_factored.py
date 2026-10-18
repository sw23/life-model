# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Factored (MultiDiscrete) action spaces: the factored categorical heads of PPO and REINFORCE, and
DQN's refusal (it trains through ``FlattenPolicies`` instead)."""

import unittest

import gymnasium as gym
import numpy as np
import torch
from gymnasium import spaces

from deepqlearning.algos.base import FactoredCategorical, StepBatch, distribution_mode
from deepqlearning.algos.dqn import DQNAgent
from deepqlearning.algos.ppo import PPOAgent
from deepqlearning.algos.reinforce import ReinforceAgent
from deepqlearning.training.rollout import rollout

NVEC = (3, 2, 4)
OBS = spaces.Box(low=-1.0, high=1.0, shape=(4,), dtype=np.float32)


class SlotMatchEnv(gym.Env):
    """A one-step-per-episode toy: reward is the number of slots set to their target value
    (targets ``(2, 1, 3)``); value 1 of slot 2 is masked off. Value 0 of every slot is its no-op,
    the convention ``FlattenPolicies`` relies on."""

    TARGET = (2, 1, 3)

    def __init__(self, horizon: int = 4):
        self.action_space = spaces.MultiDiscrete(NVEC)
        self.observation_space = OBS
        self.horizon = horizon
        self.t = 0

    def _mask(self):
        mask = np.ones(sum(NVEC), dtype=bool)
        mask[3 + 2 + 1] = False  # slot 2 value 1
        return mask

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.t = 0
        return np.zeros(4, dtype=np.float32), {"legal_mask": self._mask()}

    def step(self, action):
        action = np.asarray(action)
        assert action[2] != 1, "masked value chosen"
        reward = float(sum(int(a == t) for a, t in zip(action, self.TARGET)))
        self.t += 1
        return np.zeros(4, dtype=np.float32), reward, False, self.t >= self.horizon, {"legal_mask": self._mask()}


class TestFactoredCategorical(unittest.TestCase):
    def test_log_prob_and_entropy_are_slot_sums_and_masks_apply_per_slot(self):
        torch.manual_seed(0)
        logits = torch.randn(2, sum(NVEC))
        legal = [list(range(sum(NVEC))), [0, 2, 3, 6, 7, 8]]  # row 1: slot0 {0,2}, slot1 {0}, slot2 {1,2,3}
        dist = FactoredCategorical(logits, legal, NVEC)
        samples = torch.stack([dist.sample() for _ in range(200)])
        self.assertTrue(set(samples[:, 1, 0].tolist()) <= {0, 2})
        self.assertEqual(set(samples[:, 1, 1].tolist()), {0})
        self.assertTrue(set(samples[:, 1, 2].tolist()) <= {1, 2, 3})
        actions = torch.tensor([[1, 0, 2], [2, 0, 3]])
        expected = sum(d.log_prob(actions[:, i]) for i, d in enumerate(dist.dists))
        torch.testing.assert_close(dist.log_prob(actions), expected)
        torch.testing.assert_close(dist.entropy(), sum(d.entropy() for d in dist.dists))
        self.assertEqual(tuple(distribution_mode(dist).shape), (2, 3))

    def test_a_slot_with_nothing_published_stays_unmasked(self):
        dist = FactoredCategorical(torch.zeros(1, sum(NVEC)), [[0, 1, 2, 3]], NVEC)  # slot 2 unpublished
        self.assertTrue(torch.allclose(dist.dists[2].probs, torch.full((1, 4), 0.25)))


class TestAlgorithmsOnMultiDiscrete(unittest.TestCase):
    def test_ppo_and_reinforce_act_with_vectors(self):
        for cls, config in (
            (PPOAgent, {"n_steps": 8, "num_envs": 1, "verbose": False}),
            (ReinforceAgent, {"batch_episodes": 2, "verbose": False}),
        ):
            with self.subTest(algo=cls.name):
                agent = cls(OBS, spaces.MultiDiscrete(NVEC), config)
                self.assertEqual(agent.action_nvec, NVEC)
                self.assertEqual(agent.action_size, sum(NVEC))
                action = agent.select_action(np.zeros(4, dtype=np.float32), list(range(sum(NVEC))))
                self.assertEqual(action.shape, (3,))

    def test_ppo_learns_the_target_vector(self):
        torch.manual_seed(0)
        np.random.seed(0)
        env = SlotMatchEnv()
        agent = PPOAgent(
            OBS,
            env.action_space,
            {
                "n_steps": 32,
                "num_envs": 1,
                "epochs": 4,
                "minibatches": 2,
                "learning_rate": 3e-2,
                "gamma": 0.0,
                "verbose": False,
            },
        )
        for episode in range(300):
            rollout(env, agent, training=True, seed=episode)
        greedy = agent.select_action(np.zeros(4, dtype=np.float32), np.nonzero(env._mask())[0].tolist())
        self.assertEqual(tuple(int(a) for a in greedy), SlotMatchEnv.TARGET)

    def test_reinforce_updates_on_vectors(self):
        torch.manual_seed(0)
        env = SlotMatchEnv()
        agent = ReinforceAgent(OBS, env.action_space, {"batch_episodes": 2, "verbose": False})
        for episode in range(4):
            rollout(env, agent, training=True, seed=episode)
        self.assertGreaterEqual(agent.steps_done, 1)

    def test_ppo_observe_keeps_vector_actions(self):
        agent = PPOAgent(OBS, spaces.MultiDiscrete(NVEC), {"n_steps": 2, "num_envs": 1, "verbose": False})
        legal = [list(range(sum(NVEC)))]
        obs = np.zeros((1, 4), dtype=np.float32)
        for _ in range(2):
            result = agent.act(obs, legal)
            agent.observe(
                StepBatch(
                    obs=obs,
                    actions=result.actions,
                    rewards=np.array([1.0]),
                    next_obs=obs,
                    terminated=np.array([False]),
                    truncated=np.array([False]),
                    legal=legal,
                    next_legal=legal,
                    env_ids=np.array([0]),
                    extras=result.extras,
                )
            )
        self.assertIsNotNone(agent.update())

    def test_dqn_refuses_multidiscrete_and_points_at_the_wrapper(self):
        with self.assertRaisesRegex(TypeError, "FlattenPolicies"):
            DQNAgent(OBS, spaces.MultiDiscrete(NVEC), {"verbose": False})


if __name__ == "__main__":
    unittest.main()
