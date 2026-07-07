# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the credits stage (TaxesDue.credits) and the Child Tax Credit.

Dollar assertions use the frozen fixture config: ctc_per_child 2000, ctc_refundable_max 1500,
phase-out starts 200k single / 400k MFJ, rate 5% ($50 per $1,000 or fraction thereof), two-bracket
10%/25% federal tax with a $10k/$20k standard deduction, 5% state tax.
"""

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..config.financial_config import FinancialConfig
from ..dependents.child import Child
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..tax.credits import child_tax_credit
from ..tax.federal import FilingStatus
from ..tax.tax import TaxesDue, compute_taxes
from ..work.job import Job, Salary

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    return FinancialConfig(config_file=TEST_CONFIG)


class TestTaxesDueCredits(unittest.TestCase):
    def test_total_subtracts_credits(self):
        taxes = TaxesDue(federal=5000, state=1000, ss=500, medicare=100, credits=2000)
        self.assertEqual(taxes.total, 4600)

    def test_credits_default_zero_back_compat(self):
        taxes = TaxesDue(federal=5000, state=1000, ss=500, medicare=100)
        self.assertEqual(taxes.credits, 0.0)
        self.assertEqual(taxes.total, 6600)

    def test_compute_taxes_credits_kwarg_defaults_zero(self):
        cfg = _fixture_config()
        base = compute_taxes(50000, 10000, FilingStatus.SINGLE, [50000], cfg)
        credited = compute_taxes(50000, 10000, FilingStatus.SINGLE, [50000], cfg, credits=1000)
        self.assertEqual(base.credits, 0.0)
        self.assertEqual(credited.credits, 1000)
        self.assertEqual(credited.total, base.total - 1000)

    def test_refundable_credit_can_make_total_negative(self):
        taxes = TaxesDue(federal=0, state=0, ss=0, medicare=0, credits=1500)
        self.assertEqual(taxes.total, -1500)


class TestChildTaxCreditFunction(unittest.TestCase):
    """Pure phase-out math (fixture: 2000/child, 1500 refundable cap, 5% per $1,000)."""

    def setUp(self):
        self.cfg = _fixture_config()

    def test_full_credit_below_phaseout(self):
        credit = child_tax_credit(2, 100000, 20000, FilingStatus.MARRIED_FILING_JOINTLY, self.cfg)
        self.assertEqual(credit, 4000)

    def test_no_children_no_credit(self):
        self.assertEqual(child_tax_credit(0, 100000, 20000, FilingStatus.SINGLE, self.cfg), 0.0)

    def test_phaseout_reduces_credit(self):
        # MFJ, MAGI 405,000: excess 5,000 -> reduction 5% * 5,000 = 250.
        credit = child_tax_credit(1, 405000, 50000, FilingStatus.MARRIED_FILING_JOINTLY, self.cfg)
        self.assertEqual(credit, 1750)

    def test_phaseout_rounds_excess_up_to_1000(self):
        # Excess of $1 counts as a full $1,000 step ($50 reduction).
        credit = child_tax_credit(1, 400001, 50000, FilingStatus.MARRIED_FILING_JOINTLY, self.cfg)
        self.assertEqual(credit, 1950)

    def test_fully_phased_out(self):
        # Excess 40,000 -> reduction 2,000 wipes out one child's credit.
        credit = child_tax_credit(1, 440000, 50000, FilingStatus.MARRIED_FILING_JOINTLY, self.cfg)
        self.assertEqual(credit, 0.0)

    def test_single_threshold_used_for_single_filer(self):
        # Single, MAGI 205,000: excess 5,000 -> reduction 250.
        credit = child_tax_credit(1, 205000, 50000, FilingStatus.SINGLE, self.cfg)
        self.assertEqual(credit, 1750)

    def test_nonrefundable_clamped_at_liability_plus_refundable_cap(self):
        # Zero federal liability: only the refundable portion (1500/child) survives.
        credit = child_tax_credit(1, 50000, 0, FilingStatus.SINGLE, self.cfg)
        self.assertEqual(credit, 1500)

    def test_partial_liability_plus_refundable(self):
        # Liability 300: 300 nonrefundable + min(1700 rest, 1500 cap) = 1800.
        credit = child_tax_credit(1, 50000, 300, FilingStatus.SINGLE, self.cfg)
        self.assertEqual(credit, 1800)

    def test_refundable_cap_scales_per_child(self):
        # Two children, zero liability: 2 x 1500 refundable.
        credit = child_tax_credit(2, 50000, 0, FilingStatus.SINGLE, self.cfg)
        self.assertEqual(credit, 3000)


class TestTaxUnitCTCWiring(unittest.TestCase):
    """The CTC lands in TaxUnit.get_income_taxes_due and reduces settled taxes."""

    def _run_year(self, with_child):
        model = LifeModel(start_year=2026, end_year=2026, config=_fixture_config())
        parent = Person(Family(model), "Parent", age=35, retirement_age=70, spending=Spending(model, base=0))
        BankAccount(parent, "Bank", balance=100000, interest_rate=0)
        Job(parent, "Co", "Dev", Salary(model=model, base=80000, yearly_increase=0, yearly_bonus=0))
        if with_child:
            Child(parent, "Kid", birth_year=2020)  # age 6 in 2026 -> qualifying
        model.step()
        return model, parent

    def test_ctc_reduces_taxes_by_exactly_per_child_amount(self):
        _, without = self._run_year(with_child=False)
        _, with_kid = self._run_year(with_child=True)
        # Same income, well below phase-out and liability > 2000: taxes drop by exactly 2000.
        self.assertAlmostEqual(without.stat_taxes_paid - with_kid.stat_taxes_paid, 2000, places=2)

    def test_unborn_and_adult_children_do_not_qualify(self):
        model = LifeModel(start_year=2026, end_year=2026, config=_fixture_config())
        parent = Person(Family(model), "Parent", age=45, retirement_age=70, spending=Spending(model, base=0))
        BankAccount(parent, "Bank", balance=100000, interest_rate=0)
        Job(parent, "Co", "Dev", Salary(model=model, base=80000, yearly_increase=0, yearly_bonus=0))
        Child(parent, "Unborn", birth_year=2030)  # negative age
        Child(parent, "Grown", birth_year=2000)  # age 26
        model.step()
        taxes = model.datacollector.get_model_vars_dataframe().iloc[-1]["Taxes"]

        model2, parent2 = LifeModel(start_year=2026, end_year=2026, config=_fixture_config()), None
        parent2 = Person(Family(model2), "Parent", age=45, retirement_age=70, spending=Spending(model2, base=0))
        BankAccount(parent2, "Bank", balance=100000, interest_rate=0)
        Job(parent2, "Co", "Dev", Salary(model=model2, base=80000, yearly_increase=0, yearly_bonus=0))
        model2.step()
        taxes_no_children = model2.datacollector.get_model_vars_dataframe().iloc[-1]["Taxes"]

        self.assertAlmostEqual(taxes, taxes_no_children, places=2)


class TestZeroChildrenGoldenFrame(unittest.TestCase):
    """Models with no children must produce byte-identical frames to the pre-credit code path."""

    @staticmethod
    def _frame():
        model = LifeModel(start_year=2026, end_year=2035, config=_fixture_config())
        family = Family(model)
        person = Person(family, "A", 30, 65, Spending(model, base=20000, yearly_increase=2.0))
        BankAccount(person, "Bank", interest_rate=0.0)
        Job(person, "Co", "Dev", Salary(model=model, base=80000, yearly_increase=2.0))
        model.run()
        return model.datacollector.get_model_vars_dataframe()

    def test_no_children_frames_are_stable(self):
        first = self._frame()
        second = self._frame()
        self.assertTrue(first.equals(second))
        # Credits must be exactly zero-effect: taxes match the credit-free computation.
        cfg = _fixture_config()
        taxes = compute_taxes(80000, 10000, FilingStatus.SINGLE, [80000], cfg)
        self.assertAlmostEqual(first.iloc[0]["Taxes"], round(taxes.total), delta=1.0)


if __name__ == "__main__":
    unittest.main()
