# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Pooling per-seed protocol reports into one verdict."""

import unittest

import numpy as np

from deepqlearning.evaluation.pool_seeds import _t_interval, pool_reports


def _report(agent_returns, bar_returns=(1.0, 1.0, 1.0, 1.0)):
    def stats(returns):
        return {"mean_return": float(np.mean(returns)), "returns": list(returns)}

    cond = {"agent": stats(agent_returns), "always_max_401k": stats(bar_returns), "age_glide": stats([0.0] * 4)}
    return {"reward_preset": "retirement_security", "master_seed": 1, "n_eval": 4, "conditions": {"train": cond}}


class TestPoolSeeds(unittest.TestCase):
    def test_t_interval(self):
        mean, _low, high = _t_interval(np.array([1.0, 2.0, 3.0]))
        self.assertAlmostEqual(mean, 2.0)
        self.assertAlmostEqual(high - mean, 4.303 * 1.0 / np.sqrt(3), places=6)
        self.assertEqual(_t_interval(np.array([5.0]))[1], float("-inf"))

    def test_consistent_winner_is_intelligent(self):
        reports = [_report([2.0, 2.1, 1.9, 2.0]), _report([1.8, 1.9, 2.0, 2.1]), _report([2.2, 2.0, 2.1, 1.9])]
        pooled = pool_reports(reports)
        train = pooled["conditions"]["train"]
        self.assertEqual(train["best_in_bar"], "always_max_401k")
        self.assertEqual(train["runs_beating_best_on_mean"], 3)
        self.assertTrue(pooled["verdict_intelligent_pooled"])

    def test_one_lucky_seed_is_not_intelligent(self):
        reports = [_report([5.0] * 4), _report([0.9] * 4), _report([1.0] * 4)]
        self.assertFalse(pool_reports(reports)["verdict_intelligent_pooled"])

    def test_mismatched_reports_rejected(self):
        a, b = _report([1.0] * 4), _report([1.0] * 4)
        b["n_eval"] = 5
        with self.assertRaises(ValueError):
            pool_reports([a, b])


if __name__ == "__main__":
    unittest.main()
