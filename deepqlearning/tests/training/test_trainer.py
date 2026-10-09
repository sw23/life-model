# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the vectorized trainer: reproducibility, action legality, and autoreset bookkeeping."""

import os
import tempfile
import unittest

import numpy as np
import torch

from deepqlearning.algos.dqn import DQNAgent
from deepqlearning.algos.ppo import PPOAgent
from deepqlearning.envs.financial.environment import OBS_SPEC, FinancialLifeEnv
from deepqlearning.envs.registry import make_vector_env
from deepqlearning.training.trainer import Trainer

OBS_DIM = len(OBS_SPEC)

# A ten-year horizon, so episodes end (and autoreset) many times within a short run.
_SHORT_EPISODES = {"person_start_age": 25, "person_max_age": 35}


class TestVectorizedReproducibility(unittest.TestCase):
    def test_same_base_seed_reproduces_per_env_streams(self):
        # Per-env seeds derived from a base seed must reproduce identical reward streams under
        # a fixed action policy (acceptance).
        def collect(base):
            venv = make_vector_env("financial", {}, num_envs=4, backend="sync")
            no_op = venv.single_action_space.n - 1
            venv.reset(seed=[base + i for i in range(4)])
            streams = []
            for _ in range(30):
                _, rewards, _, _, _ = venv.step(np.array([no_op] * 4))
                streams.append(np.asarray(rewards).round(6).tolist())
            venv.close()
            return streams

        self.assertEqual(collect(100), collect(100))


class TestBatchedActionLegality(unittest.TestCase):
    def test_batch_actions_are_legal_in_the_financial_env(self):
        env = FinancialLifeEnv()
        agent = DQNAgent(env.observation_space, env.action_space, {"min_replay_size": 8, "verbose": False})
        agent.epsilon = 0.0
        states = np.stack([env._get_observation() for _ in range(4)])
        legal_lists = [env.get_legal_actions() for _ in range(4)]
        actions = agent.act(states, legal_lists, training=False).actions
        self.assertEqual(len(actions), 4)
        for action, legal in zip(actions, legal_lists):
            self.assertIn(int(action), legal)


class TestTrainerLoop(unittest.TestCase):
    def test_ppo_runs_over_two_financial_envs(self):
        # Exercises the collect -> observe -> update loop and the NEXT_STEP autoreset bookkeeping
        # end to end. Short-horizon episodes make autoresets happen many times in 200 steps.
        torch.manual_seed(0)
        algo = PPOAgent(OBS_DIM, 52, {"n_steps": 16, "num_envs": 2, "epochs": 2, "minibatches": 2, "verbose": False})
        trainer = Trainer(
            algo,
            "financial",
            _SHORT_EPISODES,
            {
                "num_envs": 2,
                "total_env_steps": 200,
                "eval_freq_steps": 1_000_000,  # no eval inside this short run
                "print_freq_steps": 1_000_000,
                "model_save_path": os.path.join(tempfile.mkdtemp(), "ppo.pt"),
            },
        )
        stats = trainer.train()

        self.assertGreaterEqual(stats["collected_env_steps"], 200)
        self.assertGreater(stats["episodes"], 0)
        self.assertTrue(all(np.isfinite(r) for r in trainer.episode_rewards))
        self.assertTrue(all(np.isfinite(loss) for loss in algo.training_losses))

    def test_dqn_runs_over_two_financial_envs(self):
        torch.manual_seed(0)
        algo = DQNAgent(
            OBS_DIM,
            52,
            {
                "hidden_sizes": [32, 32],
                "min_replay_size": 32,
                "batch_size": 16,
                "n_step": 1,
                "use_prioritized_replay": False,
                "verbose": False,
            },
        )
        trainer = Trainer(
            algo,
            "financial",
            _SHORT_EPISODES,
            {
                "num_envs": 2,
                "total_env_steps": 200,
                "eval_freq_steps": 1_000_000,
                "print_freq_steps": 1_000_000,
                "model_save_path": os.path.join(tempfile.mkdtemp(), "dqn.pt"),
            },
        )
        stats = trainer.train()
        self.assertGreaterEqual(stats["collected_env_steps"], 200)
        self.assertGreater(len(algo.replay_buffer), 0)

    def test_unknown_lr_schedule_is_rejected(self):
        algo = DQNAgent(OBS_DIM, 52, {"verbose": False})
        with self.assertRaises(ValueError):
            Trainer(algo, "financial", {}, {"lr_schedule": "exponential"})


if __name__ == "__main__":
    unittest.main()


class TestTrainerKeepsBestCheckpoint(unittest.TestCase):
    def test_best_weights_are_restored_after_training(self):
        """Eval peaks in the first round then declines: train() must return the peak weights."""
        torch.manual_seed(0)
        algo = DQNAgent(
            OBS_DIM,
            52,
            {
                "hidden_sizes": [32, 32],
                "min_replay_size": 32,
                "batch_size": 16,
                "n_step": 1,
                "use_prioritized_replay": False,
                "verbose": False,
            },
        )
        trainer = Trainer(
            algo,
            "financial",
            _SHORT_EPISODES,
            {
                "num_envs": 2,
                "total_env_steps": 400,
                "eval_freq_steps": 100,
                "print_freq_steps": 1_000_000,
                "early_stop_patience": 100,
                "model_save_path": os.path.join(tempfile.mkdtemp(), "dqn.pt"),
            },
        )
        scores = iter([10.0, 1.0, 1.0, 1.0, 1.0, 1.0])
        trainer._evaluate = lambda: next(scores)
        saved = {}
        original_save = algo.save

        def recording_save(path):
            saved["weights"] = {k: v.clone() for k, v in algo.q_network.state_dict().items()}
            original_save(path)

        algo.save = recording_save
        trainer.train()

        final = algo.q_network.state_dict()
        self.assertTrue(all(torch.equal(final[k], saved["weights"][k]) for k in final))
