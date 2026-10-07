# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Teacher warm-start of the DQN replay buffer (Plan 19 D2)."""

import unittest

from deepqlearning.algos.dqn import DQNAgent
from deepqlearning.algos.reinforce import ReinforceAgent
from deepqlearning.envs.financial.environment import FinancialLifeEnv
from deepqlearning.training.warm_start import warm_start_replay


class TestWarmStart(unittest.TestCase):
    def test_teacher_transitions_fill_the_replay_buffer(self):
        env = FinancialLifeEnv()
        agent = DQNAgent(env.observation_space, env.action_space, {"verbose": False})
        stored = warm_start_replay(agent, env, "contribution_waterfall", num_seeds=2)
        self.assertGreater(stored, 0)
        self.assertEqual(len(agent.replay_buffer), stored)

    def test_rejects_unknown_teacher_and_on_policy_agents(self):
        env = FinancialLifeEnv()
        agent = DQNAgent(env.observation_space, env.action_space, {"verbose": False})
        with self.assertRaises(ValueError):
            warm_start_replay(agent, env, "not_a_policy", num_seeds=1)
        reinforce = ReinforceAgent(env.observation_space.shape[0], env.action_space.n, {"verbose": False})
        with self.assertRaises(TypeError):
            warm_start_replay(reinforce, env, "do_nothing", num_seeds=1)


if __name__ == "__main__":
    unittest.main()
