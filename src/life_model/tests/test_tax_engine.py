# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Regression tests for Plan 05 — tax engine correctness.

Each test targets a specific tax bug catalogued in plans/05-tax-engine.md. Dollar
assertions read the frozen fixture config (fixtures/test_config.yaml), never live-year
defaults, so they stay stable across annual data refreshes.
"""

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..account.job401k import Job401kAccount
from ..config.financial_config import FinancialConfig
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..tax.federal import FilingStatus, federal_income_tax
from ..work.job import Job, Salary

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    """Fresh FinancialConfig loaded from the frozen test fixture."""
    return FinancialConfig(config_file=TEST_CONFIG)


class TestBracketMath(unittest.TestCase):
    """Item 4: brackets are half-open and computed marginally with no boundary gaps."""

    def setUp(self):
        self.config = _fixture_config()

    def test_no_boundary_gap(self):
        # Fixture: 10% to $40,000 then 25%. Income sitting in the boundary "gap" the old
        # [start, end] rows left ($40,000 -> $40,001) must be taxed marginally, not skipped.
        # $40,000 @ 10% = $4,000; the extra $0.50 @ 25% = $0.125.
        tax = federal_income_tax(40000.50, FilingStatus.SINGLE, self.config)
        self.assertAlmostEqual(tax, 4000.125, places=4)

    def test_marginal_is_not_rounded(self):
        # Item 4 / Plan 04 D3: no premature round() to the dollar.
        tax = federal_income_tax(40010.40, FilingStatus.SINGLE, self.config)
        # $40,000 @ 10% + $10.40 @ 25% = 4000 + 2.60 = 4002.60
        self.assertAlmostEqual(tax, 4002.60, places=4)

    def test_exact_boundary(self):
        # Income exactly at the threshold stays fully in the lower bracket.
        self.assertAlmostEqual(federal_income_tax(40000, FilingStatus.SINGLE, self.config), 4000.0, places=6)

    def test_zero_and_negative(self):
        self.assertEqual(federal_income_tax(0, FilingStatus.SINGLE, self.config), 0)
        self.assertEqual(federal_income_tax(-100, FilingStatus.SINGLE, self.config), 0)

    def test_mfj_brackets(self):
        # MFJ fixture: 10% to $80,000 then 25%. $100,000 -> 8000 + 5000 = 13000.
        tax = federal_income_tax(100000, FilingStatus.MARRIED_FILING_JOINTLY, self.config)
        self.assertAlmostEqual(tax, 13000.0, places=6)


if __name__ == "__main__":
    unittest.main()
