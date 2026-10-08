# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Named economy scenarios layered on the stochastic economy (economy_overlay.py)."""

import unittest

from deepqlearning.envs.financial.economy_overlay import ScenarioOverlay
from deepqlearning.envs.financial.environment import FinancialLifeEnv
from life_model.config.financial_config import FinancialConfig

_NO_ACTION = 51


def _rates(env, years):
    economy = env.model.economy
    return [economy.inflation(y) for y in years], [economy.equity_return(y) for y in years]


class TestScenarioOverlay(unittest.TestCase):
    def setUp(self):
        self.stochastic = FinancialConfig().model.economy.stochastic

    def test_level_shift_applies_only_inside_regime(self):
        overlay = ScenarioOverlay.from_scenario({"mode": "fixed", "inflation": 8.0}, self.stochastic, 2025, 10)
        shift = 8.0 - self.stochastic.inflation_mean
        base = {"inflation": 3.0, "equity_return": 7.0, "cash_yield": 1.0}
        self.assertAlmostEqual(overlay.adjust(2025, base)["inflation"], 3.0 + shift)
        self.assertAlmostEqual(overlay.adjust(2034, base)["inflation"], 3.0 + shift)
        self.assertAlmostEqual(overlay.adjust(2035, base)["inflation"], 3.0)
        self.assertEqual(overlay.adjust(2025, base)["equity_return"], 7.0)

    def test_path_replaces_listed_years_only(self):
        overlay = ScenarioOverlay.from_scenario(
            {"mode": "path", "paths": {"equity_return": {2027: -12.0}}}, self.stochastic, 2025, 10
        )
        base = {"inflation": 3.0, "equity_return": 9.0, "cash_yield": 1.0}
        self.assertEqual(overlay.adjust(2027, base)["equity_return"], -12.0)
        self.assertEqual(overlay.adjust(2028, base)["equity_return"], 9.0)

    def test_cash_yield_floored(self):
        overlay = ScenarioOverlay.from_scenario({"cash_yield": -10.0}, self.stochastic, 2025, 10)
        self.assertEqual(overlay.adjust(2025, {"cash_yield": 1.0})["cash_yield"], 0.0)


class TestEnvScenarioOverlay(unittest.TestCase):
    def test_recession_keeps_the_economy_stochastic(self):
        env = FinancialLifeEnv({"economy_scenario": "recession"})
        env.reset(seed=0)
        self.assertEqual(env.model.config.economy.mode, "stochastic")
        for _ in range(4):
            env.step(_NO_ACTION)
        economy = env.model.economy
        self.assertEqual(economy.equity_return(2027), -12.0)
        self.assertEqual(economy.equity_return(2028), -4.0)

    def test_recession_trials_differ_outside_the_shock(self):
        a = FinancialLifeEnv({"economy_scenario": "recession"})
        b = FinancialLifeEnv({"economy_scenario": "recession"})
        a.reset(seed=1)
        b.reset(seed=2)
        for _ in range(8):
            a.step(_NO_ACTION)
            b.step(_NO_ACTION)
        self.assertEqual(a.model.economy.equity_return(2027), b.model.economy.equity_return(2027))
        self.assertNotEqual(a.model.economy.equity_return(2031), b.model.economy.equity_return(2031))

    def test_high_inflation_is_a_regime_not_forever(self):
        env = FinancialLifeEnv({"economy_scenario": "high_inflation"})
        env.reset(seed=3)
        for _ in range(30):
            env.step(_NO_ACTION)
        economy = env.model.economy
        regime = [economy.inflation(y) for y in range(2025, 2035)]
        after = [economy.inflation(y) for y in range(2035, 2054)]
        self.assertGreater(sum(regime) / len(regime), sum(after) / len(after) + 2.0)
        self.assertEqual(env.model.config.economy.mode, "stochastic")

    def test_non_economy_overrides_still_apply(self):
        env = FinancialLifeEnv({"economy_scenario": "high_inflation"})
        env.reset(seed=0)
        self.assertEqual(env.model.config.debt.credit_card.default_interest_rate, 25.0)

    def test_fixed_mode_keeps_core_semantics(self):
        env = FinancialLifeEnv({"economy_scenario": "high_inflation", "economy_mode": "fixed"})
        env.reset(seed=0)
        self.assertEqual(env.model.config.economy.mode, "fixed")
        self.assertEqual(env.model.economy.inflation(2040), 8.0)

    def test_same_seed_reproducible(self):
        a = FinancialLifeEnv({"economy_scenario": "boom"})
        b = FinancialLifeEnv({"economy_scenario": "boom"})
        a.reset(seed=9)
        b.reset(seed=9)
        for _ in range(6):
            a.step(_NO_ACTION)
            b.step(_NO_ACTION)
        self.assertEqual(_rates(a, range(2025, 2031)), _rates(b, range(2025, 2031)))


if __name__ == "__main__":
    unittest.main()
