# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the ``healthcare`` config section (Plan 15, Task 1)."""

import unittest
from pathlib import Path

from ..config.financial_config import FinancialConfig


class TestHealthcareConfig(unittest.TestCase):
    def test_packaged_defaults_load_healthcare(self):
        """The packaged YAML loads and exposes a populated healthcare section."""
        cfg = FinancialConfig()
        hc = cfg.healthcare
        self.assertGreater(len(hc.medical_cost_bands), 0)
        self.assertEqual(hc.medicare.eligibility_age, 65)
        # Real 2026 CMS Part B standard premium and Part D national base premium.
        self.assertEqual(hc.medicare.part_b_base_monthly_premium, 202.90)
        self.assertEqual(hc.medicare.part_d_base_monthly_premium, 34.50)
        self.assertEqual(len(hc.medicare.irmaa_tiers), 6)
        self.assertEqual(hc.long_term_care.start_age, 65)
        self.assertEqual(hc.funeral_cost, 8300)
        self.assertEqual(hc.medical_deduction_agi_floor, 7.5)

    def test_fixture_config_without_healthcare_section_uses_defaults(self):
        """A config file with no healthcare section still loads (all fields default)."""
        fixture = Path(__file__).parent / "fixtures" / "test_config.yaml"
        cfg = FinancialConfig(config_file=str(fixture))
        # No healthcare section in the fixture: defaults apply.
        self.assertEqual(cfg.healthcare.medicare.eligibility_age, 65)
        self.assertGreater(cfg.healthcare.long_term_care.annual_cost, 0)

    def test_irmaa_tiers_are_monotonic(self):
        """IRMAA MAGI thresholds and premiums increase tier over tier."""
        tiers = FinancialConfig().healthcare.medicare.irmaa_tiers
        for lower, higher in zip(tiers, tiers[1:]):
            self.assertLess(lower.magi_min_single, higher.magi_min_single)
            self.assertLess(lower.magi_min_married_filing_jointly, higher.magi_min_married_filing_jointly)
            self.assertLessEqual(lower.part_b_monthly, higher.part_b_monthly)
            self.assertLessEqual(lower.part_d_monthly_surcharge, higher.part_d_monthly_surcharge)

    def test_healthcare_scenario_override(self):
        """Healthcare values can be overridden via a scenario (deep-merge + revalidate)."""
        cfg = FinancialConfig()
        cfg.apply_scenario("test", {"healthcare": {"funeral_cost": 12345}})
        self.assertEqual(cfg.healthcare.funeral_cost, 12345)


if __name__ == "__main__":
    unittest.main()
