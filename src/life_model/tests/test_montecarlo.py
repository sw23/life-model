# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the Monte Carlo runner and result API."""

import unittest

from ..account.bank import BankAccount
from ..config.financial_config import FinancialConfig
from ..model import LifeModel
from ..montecarlo import MonteCarlo, MonteCarloResult
from ..people.family import Family
from ..people.person import Person, Spending


def _build_trial(seed: int) -> LifeModel:
    """Top-level (picklable) factory: a stochastic-economy model with an interest-bearing bank.

    The bank's interest defers to the economy's (stochastic) cash yield, so the collected
    ``Bank Balance`` varies from trial to trial and reflects the random draws.
    """
    cfg = FinancialConfig()
    cfg.apply_scenario(
        "mc", {"economy": {"mode": "stochastic", "stochastic": {"cash_yield_mean": 3.0, "cash_yield_vol": 2.0}}}
    )
    model = LifeModel(start_year=2026, end_year=2035, config=cfg, seed=seed)
    family = Family(model)
    person = Person(family, "A", 30, 65, Spending(model, base=0))
    BankAccount(person, "Bank", balance=10000)
    return model


class TestMonteCarlo(unittest.TestCase):
    def test_runs_all_trials(self):
        result = MonteCarlo(_build_trial, n=20, seed=42, workers=1).run()
        self.assertIsInstance(result, MonteCarloResult)
        self.assertEqual(result.num_trials, 20)
        self.assertEqual(result.years[0], 2026)
        self.assertEqual(result.years[-1], 2035)

    def test_reproducible_under_master_seed(self):
        a = MonteCarlo(_build_trial, n=15, seed=99, workers=1).run()
        b = MonteCarlo(_build_trial, n=15, seed=99, workers=1).run()
        self.assertTrue(a.percentiles("Bank Balance").equals(b.percentiles("Bank Balance")))
        # A different master seed yields different draws.
        c = MonteCarlo(_build_trial, n=15, seed=1234, workers=1).run()
        self.assertFalse(a.mean("Bank Balance").equals(c.mean("Bank Balance")))

    def test_percentiles_shape_and_order(self):
        result = MonteCarlo(_build_trial, n=30, seed=7, workers=1).run()
        frame = result.percentiles("Bank Balance", [10, 50, 90])
        self.assertEqual(list(frame.columns), ["p10", "p50", "p90"])
        self.assertEqual(len(frame), len(result.years))
        # Percentiles are monotone non-decreasing across the requested levels.
        self.assertTrue((frame["p10"] <= frame["p50"]).all())
        self.assertTrue((frame["p50"] <= frame["p90"]).all())

    def test_success_rate(self):
        result = MonteCarlo(_build_trial, n=25, seed=3, workers=1).run()
        # Interest is floored at zero, so the bank balance never drops below its opening value.
        rate = result.success_rate(lambda row: row["Bank Balance"] >= 10000)
        self.assertEqual(rate, 1.0)
        rate_impossible = result.success_rate(lambda row: row["Bank Balance"] < 0)
        self.assertEqual(rate_impossible, 0.0)

    def test_unknown_column_raises(self):
        result = MonteCarlo(_build_trial, n=3, seed=1, workers=1).run()
        with self.assertRaises(KeyError):
            result.percentiles("Not A Column")

    def test_picklability_detection(self):
        self.assertTrue(MonteCarlo(_build_trial, n=1)._factory_is_picklable())
        self.assertFalse(MonteCarlo(lambda seed: _build_trial(seed), n=1)._factory_is_picklable())

    def test_invalid_n(self):
        with self.assertRaises(ValueError):
            MonteCarlo(_build_trial, n=0)


if __name__ == "__main__":
    unittest.main()
