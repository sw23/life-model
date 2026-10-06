# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the optional legal-action mask protocol."""

import unittest

import gymnasium as gym
import numpy as np

from deepqlearning.envs.masks import legal_actions_of, masks_from_vector_info
from deepqlearning.envs.registry import make_env


class _MaskedEnv:
    """Minimal stand-in exposing the method form of the mask protocol."""

    def __init__(self, legal):
        self._legal = legal
        self.action_space = gym.spaces.Discrete(5)

    def get_legal_actions(self):
        return list(self._legal)


class _PlainEnv:
    def __init__(self):
        self.action_space = gym.spaces.Discrete(5)


class TestLegalActionsFallbackChain(unittest.TestCase):
    def test_info_mask_wins(self):
        env = _MaskedEnv([0, 1])
        info = {"legal_mask": np.array([False, False, True, False, True])}
        self.assertEqual(legal_actions_of(env, info), [2, 4])

    def test_falls_back_to_the_env_method(self):
        self.assertEqual(legal_actions_of(_MaskedEnv([1, 3]), {}), [1, 3])

    def test_env_without_a_mask_offers_every_action(self):
        self.assertEqual(legal_actions_of(_PlainEnv(), {}), [0, 1, 2, 3, 4])

    def test_financial_env_info_mask_matches_its_method(self):
        env = make_env("financial")
        _, info = env.reset(seed=0)
        self.assertEqual(legal_actions_of(env, info), sorted(env.get_legal_actions()))


class TestVectorInfoMasks(unittest.TestCase):
    def test_rows_are_decoded_per_env(self):
        info = {"legal_mask": np.array([[True, False, True], [False, True, False]])}
        self.assertEqual(masks_from_vector_info(info, 2, 3), [[0, 2], [1]])

    def test_missing_mask_yields_every_action(self):
        self.assertEqual(masks_from_vector_info({}, 2, 3), [[0, 1, 2], [0, 1, 2]])


if __name__ == "__main__":
    unittest.main()
