# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..account.job401k import Job401kAccount
from ..config.financial_config import FinancialConfig
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..tax.federal import FilingStatus
from ..work.job import Job, Salary

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    """Fresh FinancialConfig loaded from the frozen test fixture."""
    return FinancialConfig(config_file=TEST_CONFIG)


class TestFamilyAggregation(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(start_year=2020, end_year=2020)
        self.family = Family(self.model)
        self.a = Person(self.family, "Ada", age=40, retirement_age=70, spending=Spending(self.model, base=15000))
        self.b = Person(self.family, "Ben", age=42, retirement_age=70, spending=Spending(self.model, base=5000))

    def test_bank_account_balance_sums_members(self):
        BankAccount(self.a, "Bank A", balance=1000, interest_rate=0)
        BankAccount(self.b, "Bank B", balance=2500, interest_rate=0)
        self.assertEqual(self.family.bank_account_balance, 3500)

    def test_combined_spending_sums_members(self):
        self.assertEqual(self.family.combined_spending, 20000)

    def test_getitem_by_member_name(self):
        self.assertIs(self.family["Ada"], self.a)
        self.assertIs(self.family["Ben"], self.b)

    def test_empty_family_defaults_to_single(self):
        empty = Family(self.model)
        self.assertEqual(empty.filing_status, FilingStatus.SINGLE)


class TestFamilyMarriedFilingStatus(unittest.TestCase):
    def test_marriage_sets_joint_filing_status(self):
        model = LifeModel(start_year=2020, end_year=2020)
        family = Family(model)
        a = Person(family, "Ada", age=40, retirement_age=70, spending=Spending(model, base=0))
        b = Person(family, "Ben", age=40, retirement_age=70, spending=Spending(model, base=0))
        a.get_married(b)
        self.assertEqual(family.filing_status, FilingStatus.MARRIED_FILING_JOINTLY)

    def test_federal_deductions_use_joint_standard_deduction(self):
        model = LifeModel(start_year=2020, end_year=2020, config=_fixture_config())
        family = Family(model)
        a = Person(family, "Ada", age=40, retirement_age=70, spending=Spending(model, base=0))
        b = Person(family, "Ben", age=40, retirement_age=70, spending=Spending(model, base=0))
        a.get_married(b)
        # Fixture MFJ standard deduction is $20k, exceeding zero itemized deductions.
        self.assertEqual(family.federal_deductions, 20000)


class TestFamilyStepSettlesJointTaxes(unittest.TestCase):
    def test_two_earner_couple_pays_combined_federal_tax_once(self):
        model = LifeModel(start_year=2020, end_year=2020, config=_fixture_config())
        family = Family(model)
        a = Person(family, "Ada", age=40, retirement_age=70, spending=Spending(model, base=0))
        b = Person(family, "Ben", age=40, retirement_age=70, spending=Spending(model, base=0))
        a.get_married(b)
        for p in (a, b):
            BankAccount(p, "Bank", balance=100000, interest_rate=0)
        Job(a, "Co", "Dev", Salary(model=model, base=50000))
        Job(b, "Co", "Dev", Salary(model=model, base=50000))

        model.step()

        # Combined $100k, MFJ standard deduction $20k -> $80k taxable, all in the 10% bracket.
        total_federal = sum(p.stat_taxes_paid_federal for p in (a, b))
        self.assertAlmostEqual(total_federal, 8000, places=2)


class TestFamilyMoneyFlow(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(start_year=2020, end_year=2020)
        self.family = Family(self.model)
        self.a = Person(self.family, "Ada", age=40, retirement_age=70, spending=Spending(self.model, base=10000))
        self.b = Person(self.family, "Ben", age=41, retirement_age=70, spending=Spending(self.model, base=5000))
        self.a.get_married(self.b)

    def test_combined_taxable_income_sums_members(self):
        self.a.income.add_wages(ordinary_amount=60000, fica_wages=60000)
        self.b.income.add_wages(ordinary_amount=40000, fica_wages=40000)
        self.assertEqual(self.family.combined_taxable_income, 100000)

    def test_debt_sums_members(self):
        self.assertEqual(self.family.debt, 0)

    def test_withdraw_from_pretax_401ks_spans_members(self):
        job_a = Job(self.a, "Co", "Dev", Salary(model=self.model, base=0))
        Job401kAccount(job=job_a, pretax_balance=8000, average_growth=0)
        job_b = Job(self.b, "Co", "Dev", Salary(model=self.model, base=0))
        Job401kAccount(job=job_b, pretax_balance=8000, average_growth=0)
        # Request more than one member holds so the withdrawal spills to the second.
        remaining = self.family.withdraw_from_pretax_401ks(12000)
        self.assertAlmostEqual(remaining, 0, delta=1e-6)

    def test_pay_bills_draws_down_bank(self):
        BankAccount(self.a, "Bank", balance=20000, interest_rate=0)
        remaining = self.family.pay_bills(5000)
        self.assertEqual(remaining, 0)
        self.assertEqual(self.a.bank_account_balance, 15000)


if __name__ == "__main__":
    unittest.main()
