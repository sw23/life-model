# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Checkpoint round trips and the version gates that stop a mismatched checkpoint from loading."""

import os
import tempfile
import unittest

import numpy as np
import torch

from deepqlearning.algos.dqn import MODEL_VERSION, DQNAgent
from deepqlearning.algos.ppo import PPOAgent
from deepqlearning.algos.reinforce import ReinforceAgent
from deepqlearning.envs.financial.environment import OBS_VERSION

# A locally trained checkpoint, exercised read-only when present. Checkpoints are not committed
# (see .gitignore), so this is a local-developer check that skips in CI rather than a hard gate.
# ``financial_basic_dqn.pt`` is what ``python -m deepqlearning.train`` writes (outputs are keyed
# ``{env}_{algo}``); ``financial_dqn_basic.pt`` is the name the pre-refactor trainer used, kept so an
# older local checkpoint still proves the refactor did not break loading.
_MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "models")
_LOCAL_MODEL = next(
    (
        path
        for path in (
            os.path.join(_MODELS_DIR, "financial_basic_dqn.pt"),
            os.path.join(_MODELS_DIR, "financial_dqn_basic.pt"),
        )
        if os.path.exists(path)
    ),
    None,
)


def _make_agent(**overrides):
    config = {
        "min_replay_size": 8,
        "batch_size": 4,
        "replay_buffer_size": 1000,
        "obs_version": OBS_VERSION,
        "verbose": False,
    }
    config.update(overrides)
    return DQNAgent(20, 16, config)


class TestDQNCheckpointRoundTrip(unittest.TestCase):
    def test_round_trip_with_weights_only(self):
        agent = _make_agent()
        # Populate some training state.
        for i in range(20):
            agent.store_experience(np.random.rand(20), i % 16, 1.0, np.random.rand(20), False, [0, 1], [0, 1])
        agent.update()
        agent.episode_rewards.append(1.23)

        path = os.path.join(tempfile.mkdtemp(), "ckpt.pt")
        agent.save(path)

        # torch.load(weights_only=True) is the default on modern torch; loading must not need any
        # environment-variable escape hatch.
        loaded = torch.load(path, weights_only=True)
        self.assertEqual(loaded["model_version"], MODEL_VERSION)

        agent2 = _make_agent()
        agent2.load(path)
        sd1, sd2 = agent.q_network.state_dict(), agent2.q_network.state_dict()
        self.assertTrue(all(torch.allclose(sd1[k], sd2[k]) for k in sd1))
        self.assertEqual(agent2.episode_rewards, agent.episode_rewards)

    def test_version_mismatch_refuses_to_load(self):
        # The observation layout / action space changed, so a checkpoint from another
        # version must fail loudly with a clear message instead of loading misaligned weights.
        agent = _make_agent()
        path = os.path.join(tempfile.mkdtemp(), "ckpt.pt")
        agent.save(path)
        # Tamper the version in the checkpoint.
        ckpt = torch.load(path, weights_only=True)
        ckpt["model_version"] = MODEL_VERSION + 99
        torch.save(ckpt, path)

        agent2 = _make_agent()
        with self.assertRaises(ValueError) as ctx:
            agent2.load(path)
        self.assertIn("model_version", str(ctx.exception))

    def test_missing_obs_version_refuses_to_load(self):
        # A checkpoint predating observation versioning has no obs_version key at all — an agent
        # that pins an obs_version must also refuse it.
        agent = _make_agent()
        path = os.path.join(tempfile.mkdtemp(), "ckpt.pt")
        agent.save(path)
        ckpt = torch.load(path, weights_only=True)
        del ckpt["obs_version"]
        torch.save(ckpt, path)

        agent2 = _make_agent()
        with self.assertRaises(ValueError):
            agent2.load(path)

    def test_unversioned_agent_skips_the_obs_version_gate(self):
        # An environment with no observation-layout version leaves the gate
        # off, so the checkpoint's obs_version is not compared.
        agent = _make_agent(obs_version=None)
        path = os.path.join(tempfile.mkdtemp(), "ckpt.pt")
        agent.save(path)
        _make_agent(obs_version=None).load(path)

    @unittest.skipUnless(_LOCAL_MODEL, "no locally trained checkpoint to load")
    def test_locally_trained_checkpoint_still_loads(self):
        from deepqlearning.envs.financial.environment import FinancialLifeEnv

        env = FinancialLifeEnv()
        agent = DQNAgent(env.observation_space, env.action_space, {"obs_version": OBS_VERSION, "verbose": False})
        agent.load(_LOCAL_MODEL)
        action = agent.select_action(env._get_observation(), env.get_legal_actions(), training=False)
        self.assertIn(action, env.get_legal_actions())


class TestPolicyAlgorithmCheckpoints(unittest.TestCase):
    def _round_trip(self, factory):
        agent = factory()
        path = os.path.join(tempfile.mkdtemp(), "ckpt.pt")
        agent.save(path)
        restored = factory()
        restored.load(path)
        sd1 = agent.policy.state_dict()
        sd2 = restored.policy.state_dict()
        self.assertTrue(all(torch.allclose(sd1[k], sd2[k]) for k in sd1))
        return path

    def test_reinforce_round_trip(self):
        self._round_trip(lambda: ReinforceAgent(8, 4, {"verbose": False}))

    def test_ppo_round_trip(self):
        self._round_trip(lambda: PPOAgent(8, 4, {"verbose": False}))

    def test_algo_mismatch_refuses_to_load(self):
        path = self._round_trip(lambda: PPOAgent(8, 4, {"verbose": False}))
        with self.assertRaises(ValueError) as ctx:
            ReinforceAgent(8, 4, {"verbose": False}).load(path)
        self.assertIn("ppo", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
