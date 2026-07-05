# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Un-mocked unit tests for the state and FICA tax functions.

These exercise the real tax math (no mocking) against the frozen fixture config so the numbers
stay stable across annual data refreshes.
"""

import unittest
from pathlib import Path

from ..config.financial_config import FinancialConfig
from ..tax.federal import FilingStatus
from ..tax.fica import medicare_tax, social_security_tax
from ..tax.state import get_state_tax_rate, state_income_tax

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    return FinancialConfig(config_file=TEST_CONFIG)


class TestStateIncomeTax(unittest.TestCase):
    def setUp(self):
        self.config = _fixture_config()

    def test_flat_rate_applied(self):
        # Fixture state rate is 5%.
        self.assertEqual(get_state_tax_rate(self.config), 5.0)
        self.assertAlmostEqual(state_income_tax(100000, self.config), 5000, places=6)

    def test_zero_income_zero_tax(self):
        self.assertEqual(state_income_tax(0, self.config), 0)

    def test_defaults_to_global_config_when_none(self):
        # Exercises the global-config resolution path (config omitted).
        rate = get_state_tax_rate()
        self.assertAlmostEqual(state_income_tax(100000), 100000 * rate / 100, places=6)


class TestSocialSecurityTax(unittest.TestCase):
    def setUp(self):
        self.config = _fixture_config()

    def test_below_cap_taxed_on_full_income(self):
        # Fixture SS rate 6.2%, wage base $110k.
        self.assertAlmostEqual(social_security_tax(50000, self.config), 50000 * 0.062, places=6)

    def test_above_cap_taxed_on_wage_base_only(self):
        self.assertAlmostEqual(social_security_tax(200000, self.config), 110000 * 0.062, places=6)


class TestMedicareTax(unittest.TestCase):
    def setUp(self):
        self.config = _fixture_config()

    def test_base_rate_below_threshold(self):
        # Fixture medicare rate 1.45%, single additional-rate threshold $200k.
        self.assertAlmostEqual(medicare_tax(100000, FilingStatus.SINGLE, self.config), 100000 * 0.0145, places=6)

    def test_additional_rate_applies_above_threshold(self):
        # $250k single: 1.45% on all + 0.9% on the $50k above the $200k threshold.
        expected = 250000 * 0.0145 + 50000 * 0.009
        self.assertAlmostEqual(medicare_tax(250000, FilingStatus.SINGLE, self.config), expected, places=6)

    def test_joint_threshold_is_higher(self):
        # Fixture MFJ threshold is $250k; $250k income incurs no additional medicare tax jointly.
        self.assertAlmostEqual(
            medicare_tax(250000, FilingStatus.MARRIED_FILING_JOINTLY, self.config), 250000 * 0.0145, places=6
        )


if __name__ == "__main__":
    unittest.main()
