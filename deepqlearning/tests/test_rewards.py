# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Pure unit tests for the utility-based reward.

Properties covered: CRRA monotonicity and concavity, the log branch at gamma==1, deflation
correctness, ruin alignment / terminal-branch selection, and — the float-type regression — that every
returned value is a genuine Python float, not an ``np.float64``.
"""

import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rewards import (  # noqa: E402
    DEFAULT_PRESET,
    REWARD_PRESETS,
    RewardConfig,
    bequest_utility,
    consumption_utility,
    crra_utility,
    get_reward_config,
    step_reward,
)


def _cfg(**overrides) -> RewardConfig:
    base = dict(
        name="test",
        crra_gamma=2.0,
        consumption_weight=1.0,
        consumption_scale=10_000.0,
        consumption_floor=1_000.0,
        bequest_weight=1.0,
        bequest_gamma=1.5,
        bequest_scale=100_000.0,
        ruin_penalty=-50.0,
    )
    base.update(overrides)
    return RewardConfig(**base)


class TestCRRA(unittest.TestCase):
    def test_gamma_one_is_log(self):
        for x in (0.5, 1.0, 3.0, 25.0):
            self.assertAlmostEqual(crra_utility(x, 1.0), math.log(x))

    def test_gamma_not_one_formula(self):
        # gamma=2 -> (x^-1 - 1)/(-1) = 1 - 1/x
        for x in (0.5, 2.0, 10.0):
            self.assertAlmostEqual(crra_utility(x, 2.0), 1.0 - 1.0 / x)

    def test_monotonic_increasing(self):
        for gamma in (0.0, 0.5, 1.0, 2.0, 4.0):
            xs = [0.1, 0.5, 1.0, 2.0, 5.0, 20.0]
            vals = [crra_utility(x, gamma) for x in xs]
            for a, b in zip(vals, vals[1:]):
                self.assertLess(a, b, f"gamma={gamma} not increasing")

    def test_concave_diminishing_returns(self):
        for gamma in (0.5, 1.0, 2.0, 4.0):
            # Equal-size steps in x produce shrinking utility increments (strict concavity).
            u1 = crra_utility(1.0, gamma)
            u2 = crra_utility(2.0, gamma)
            u3 = crra_utility(3.0, gamma)
            self.assertGreater(u2 - u1, u3 - u2, f"gamma={gamma} not concave")

    def test_nonpositive_rejected(self):
        with self.assertRaises(ValueError):
            crra_utility(0.0, 2.0)
        with self.assertRaises(ValueError):
            crra_utility(-1.0, 1.0)

    def test_returns_python_float(self):
        self.assertIs(type(crra_utility(3.0, 2.0)), float)
        self.assertIs(type(crra_utility(3.0, 1.0)), float)


class TestConsumptionUtility(unittest.TestCase):
    def test_more_consumption_is_better(self):
        cfg = _cfg()
        u_low = consumption_utility(20_000, 1.0, cfg)
        u_high = consumption_utility(60_000, 1.0, cfg)
        self.assertLess(u_low, u_high)

    def test_deflation_reduces_real_utility(self):
        # Same nominal consumption but a higher price level -> less real consumption -> less utility.
        cfg = _cfg()
        u_no_inflation = consumption_utility(50_000, 1.0, cfg)
        u_inflated = consumption_utility(50_000, 2.0, cfg)
        self.assertLess(u_inflated, u_no_inflation)
        # Deflating nominal by the same factor recovers the real-terms equivalence.
        self.assertAlmostEqual(
            consumption_utility(100_000, 2.0, cfg),
            consumption_utility(50_000, 1.0, cfg),
        )

    def test_floor_prevents_blowup(self):
        cfg = _cfg(crra_gamma=1.0)  # log would be -inf at 0
        val = consumption_utility(0.0, 1.0, cfg)
        self.assertTrue(math.isfinite(val))

    def test_weight_scales_term(self):
        base = _cfg(consumption_weight=1.0)
        doubled = _cfg(consumption_weight=2.0)
        self.assertAlmostEqual(
            2.0 * consumption_utility(50_000, 1.0, base),
            consumption_utility(50_000, 1.0, doubled),
        )

    def test_returns_python_float(self):
        self.assertIs(type(consumption_utility(np.float64(50_000), np.float64(1.0), _cfg())), float)


class TestBequestUtility(unittest.TestCase):
    def test_more_wealth_is_better(self):
        cfg = _cfg()
        self.assertLess(bequest_utility(100_000, 1.0, cfg), bequest_utility(500_000, 1.0, cfg))

    def test_zero_estate_is_zero_bequest(self):
        # Warm-glow form: a zero estate yields exactly zero bequest utility, finite at any gamma.
        for gamma in (1.0, 1.5, 2.0):
            self.assertAlmostEqual(bequest_utility(0.0, 1.0, _cfg(bequest_gamma=gamma)), 0.0)

    def test_deflation_reduces_bequest(self):
        cfg = _cfg()
        self.assertLess(bequest_utility(500_000, 3.0, cfg), bequest_utility(500_000, 1.0, cfg))

    def test_returns_python_float(self):
        self.assertIs(type(bequest_utility(np.float64(250_000), np.float64(1.0), _cfg())), float)


class TestStepReward(unittest.TestCase):
    def test_nonterminal_is_consumption_only(self):
        cfg = _cfg()
        r = step_reward(
            nominal_consumption=40_000,
            deflator=1.0,
            config=cfg,
            terminal=False,
            nominal_terminal_net_worth=1_000_000,
            ruined=False,
        )
        self.assertAlmostEqual(r, consumption_utility(40_000, 1.0, cfg))

    def test_terminal_solvent_adds_bequest(self):
        cfg = _cfg()
        r = step_reward(
            nominal_consumption=40_000,
            deflator=1.0,
            config=cfg,
            terminal=True,
            nominal_terminal_net_worth=800_000,
            ruined=False,
        )
        expected = consumption_utility(40_000, 1.0, cfg) + bequest_utility(800_000, 1.0, cfg)
        self.assertAlmostEqual(r, expected)

    def test_terminal_ruined_applies_penalty_not_bequest(self):
        cfg = _cfg()
        r = step_reward(
            nominal_consumption=40_000,
            deflator=1.0,
            config=cfg,
            terminal=True,
            nominal_terminal_net_worth=-50_000,
            ruined=True,
        )
        expected = consumption_utility(40_000, 1.0, cfg) + cfg.ruin_penalty
        self.assertAlmostEqual(r, expected)
        # Ruin must be materially worse than a solvent terminal step, so bankruptcy is deterred.
        solvent = step_reward(
            nominal_consumption=40_000,
            deflator=1.0,
            config=cfg,
            terminal=True,
            nominal_terminal_net_worth=500_000,
            ruined=False,
        )
        self.assertLess(r, solvent)

    def test_returns_python_float(self):
        cfg = _cfg()
        for terminal, ruined in ((False, False), (True, False), (True, True)):
            r = step_reward(
                nominal_consumption=np.float64(40_000),
                deflator=np.float64(1.2),
                config=cfg,
                terminal=terminal,
                nominal_terminal_net_worth=np.float64(500_000),
                ruined=ruined,
            )
            self.assertIs(type(r), float, f"terminal={terminal} ruined={ruined} leaked non-float")


class TestPresets(unittest.TestCase):
    def test_default_preset_exists_and_is_retirement_security(self):
        self.assertEqual(DEFAULT_PRESET, "retirement_security")
        self.assertIn(DEFAULT_PRESET, REWARD_PRESETS)

    def test_get_reward_config_roundtrip(self):
        for name, cfg in REWARD_PRESETS.items():
            self.assertIs(get_reward_config(name), cfg)

    def test_unknown_preset_raises(self):
        with self.assertRaises(KeyError):
            get_reward_config("does_not_exist")

    def test_wealth_max_is_bequest_dominant(self):
        # In wealth_max the terminal bequest utility should dwarf a single year's consumption
        # utility, so the objective approximates accumulation.
        cfg = REWARD_PRESETS["wealth_max"]
        one_year = consumption_utility(40_000, 1.0, cfg)
        bequest = bequest_utility(1_000_000, 1.0, cfg)
        self.assertGreater(bequest, 5 * one_year)


if __name__ == "__main__":
    unittest.main()
