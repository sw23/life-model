# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Slow training smoke test (Plan 19 D6).

The default CI training path is only the 10-episode notebook fast-path. This ``slow``-marked test
runs ~150 episodes on a fixed seed and asserts the bar that is *reliably* achievable at that scale
and robust across platforms/torch builds:

* training runs end to end without diverging (every recorded eval return is finite), and
* the final greedy agent beats the ``do_nothing`` and ``save_25_percent`` baselines on shared
  held-out seeds.

An earlier version also asserted that eval return "improves over the first third" of training.
That bar was dropped: at 150 episodes the eval trajectory on ``retirement_security`` is dominated
by episode-to-episode variance (a single early eval can already sit near the run's peak), so the
first-vs-last comparison flakes across platforms without indicating a real regression. The genuine
"the agent learned a good policy" claim is documented by the committed local/manual protocol run
(deepqlearning/reports/), which uses far more than 150 episodes — it is *not* asserted here.

Run with::

    pytest -m slow deepqlearning/tests/test_training_smoke_slow.py
"""

import os
import random
import sys
import tempfile
import unittest

import numpy as np
import pytest
import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent import FinancialDQNAgent, FinancialDQNTrainer, rollout  # noqa: E402
from baselines import BASELINES, evaluate_baseline  # noqa: E402
from environment import FinancialLifeEnv  # noqa: E402


@pytest.mark.slow
class TestTrainingSmokeSlow(unittest.TestCase):
    def test_150_episodes_train_cleanly_and_beat_weak_baselines(self):
        random.seed(0)
        np.random.seed(0)
        torch.manual_seed(0)

        env = FinancialLifeEnv()  # default preset = retirement_security
        agent = FinancialDQNAgent(
            env.observation_space.shape[0],
            env.action_space.n,
            {
                "min_replay_size": 300,
                "batch_size": 64,
                "learning_rate": 5e-4,
                "epsilon_end": 0.05,
                "n_step": 3,
                "use_prioritized_replay": True,
            },
        )
        trainer = FinancialDQNTrainer(
            env,
            agent,
            {
                "num_episodes": 150,
                "eval_freq": 25,
                "eval_episodes": 8,
                "save_freq": 100000,
                "print_freq": 100000,
                "base_seed": 0,
                "model_save_path": os.path.join(tempfile.mkdtemp(), "smoke.pt"),
            },
        )
        trainer.train()

        # Training ran end to end without diverging: every recorded eval return is finite.
        evals = trainer.eval_rewards
        self.assertGreaterEqual(len(evals), 3)
        self.assertTrue(all(np.isfinite(evals)), f"non-finite eval return (training diverged): {evals}")

        # Final greedy agent beats the weak baselines on shared held-out seeds.
        eval_seeds = [2_000_000 + i for i in range(10)]
        agent.epsilon = 0.0
        agent_score = float(np.mean([rollout(env, agent, training=False, seed=s).total_reward for s in eval_seeds]))
        do_nothing = evaluate_baseline(env, BASELINES["do_nothing"], eval_seeds)
        save_25 = evaluate_baseline(env, BASELINES["save_25_percent"], eval_seeds)
        self.assertGreaterEqual(agent_score, do_nothing)
        self.assertGreaterEqual(agent_score, save_25)


if __name__ == "__main__":
    unittest.main()
