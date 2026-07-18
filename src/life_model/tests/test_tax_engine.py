# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Regression tests for tax engine correctness.

Each test targets a specific tax-engine bug. Dollar
assertions read the frozen fixture config (fixtures/test_config.yaml), never live-year
defaults, so they stay stable across annual data refreshes.
"""

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..account.job401k import Job401kAccount
from ..charity.daf import DonorAdvisedFund
from ..charity.donation import Donation
from ..config.financial_config import FinancialConfig
from ..housing.home import Home, HomeExpenses, Mortgage
from ..limits import required_min_distrib, rmd_start_age
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
    """Brackets are half-open and computed marginally with no boundary gaps."""

    def setUp(self):
        self.config = _fixture_config()

    def test_no_boundary_gap(self):
        # Fixture: 10% to $40,000 then 25%. Income sitting in the boundary "gap" the old
        # [start, end] rows left ($40,000 -> $40,001) must be taxed marginally, not skipped.
        # $40,000 @ 10% = $4,000; the extra $0.50 @ 25% = $0.125.
        tax = federal_income_tax(40000.50, FilingStatus.SINGLE, self.config)
        self.assertAlmostEqual(tax, 4000.125, places=4)

    def test_marginal_is_not_rounded(self):
        # No premature round() to the dollar.
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


class TestFicaPerPerson(unittest.TestCase):
    """Bugs 1-3: FICA is a per-person payroll tax on wages only."""

    def test_retiree_401k_distribution_pays_no_fica(self):
        # A retiree living on 401k distributions has no wages, so owes zero FICA.
        model = LifeModel(start_year=2020, end_year=2020, config=_fixture_config())
        family = Family(model)
        person = Person(family, "Retired R", age=65, retirement_age=60, spending=Spending(model, base=30000))
        BankAccount(person, "Bank", balance=0, interest_rate=0)
        job = Job(person, "Old Co", "Retiree", Salary(model=model, base=0))
        Job401kAccount(job=job, pretax_balance=500000, average_growth=0)

        model.step()

        # The distribution funded the year's spending as ordinary income, but no payroll tax.
        self.assertGreater(person.stat_taxes_paid_federal, 0)
        self.assertEqual(person.stat_taxes_paid_ss, 0)
        self.assertEqual(person.stat_taxes_paid_medicare, 0)

    def test_worker_pretax_deferral_still_pays_fica_on_full_gross(self):
        # Pre-tax 401k deferrals reduce income tax but are still FICA wages.
        model = LifeModel(start_year=2020, end_year=2020, config=_fixture_config())
        family = Family(model)
        person = Person(family, "Saver S", age=40, retirement_age=70, spending=Spending(model, base=0))
        BankAccount(person, "Bank", balance=0, interest_rate=0)
        job = Job(person, "Co", "Dev", Salary(model=model, base=100000))
        # Defer 20% ($20k) pre-tax.
        Job401kAccount(job=job, pretax_contrib_percent=20, average_growth=0)

        model.step()

        # FICA base is the full $100k gross (SS at 6.2%), not the $80k after deferral.
        self.assertAlmostEqual(person.stat_taxes_paid_ss, 100000 * 0.062, places=2)
        self.assertAlmostEqual(person.stat_taxes_paid_medicare, 100000 * 0.0145, places=2)

    def test_two_earner_mfj_each_under_cap_pays_ss_on_both_salaries(self):
        # The Social Security wage cap is per person, not on combined MFJ wages.
        # Fixture wage base is $110k; two earners at $70k and $80k are both under it.
        model = LifeModel(start_year=2020, end_year=2020, config=_fixture_config())
        family = Family(model)
        b = Person(family, "Spouse B", age=40, retirement_age=70, spending=Spending(model, base=0))
        c = Person(family, "Spouse C", age=40, retirement_age=70, spending=Spending(model, base=0))
        b.get_married(c)
        for p in (b, c):
            BankAccount(p, "Bank", balance=100000, interest_rate=0)
        Job(b, "Co", "Dev", Salary(model=model, base=70000))
        Job(c, "Co", "Dev", Salary(model=model, base=80000))

        model.step()

        # Combined SS = 6.2% of both full salaries (neither capped): 150000 * 0.062.
        total_ss = sum(p.stat_taxes_paid_ss for p in (b, c))
        self.assertAlmostEqual(total_ss, 150000 * 0.062, places=2)


class TestWithdrawalSizing(unittest.TestCase):
    """Pre-tax withdrawals are sized by a fixed-point solve, not a max-rate buffer."""

    def test_fifty_k_net_need_no_over_withdrawal(self):
        # A retiree needs $50k of spending funded entirely from a pre-tax 401k, with an empty
        # bank account. The solver must withdraw just enough to cover the $50k plus the tax the
        # withdrawal triggers — leaving no meaningful buffer behind.
        model = LifeModel(start_year=2020, end_year=2020, config=_fixture_config())
        family = Family(model)
        person = Person(family, "Retiree", age=65, retirement_age=60, spending=Spending(model, base=50000))
        BankAccount(person, "Bank", balance=0, interest_rate=0)
        job = Job(person, "Old Co", "Retiree", Salary(model=model, base=0))
        Job401kAccount(job=job, pretax_balance=1000000, average_growth=0)

        model.step()

        # The $50k spending was fully covered from the 401k and created no debt.
        self.assertEqual(person.stat_money_spent, 50000)
        self.assertEqual(person.debt, 0)
        # No max-rate over-buffer: at most ~$1 of excess is left in the bank after settlement.
        self.assertLessEqual(person.bank_account_balance, 1.0)
        # The bank actually received at least the $50k net need (before it was spent).
        withdrawn = 1000000 - job.retirement_account.pretax_balance
        self.assertGreaterEqual(withdrawn, 50000 - 1.0)


class TestDeductionTiming(unittest.TestCase):
    """Bugs 5-6: charitable deductions must reduce taxes and only when cash actually leaves."""

    def _federal_tax_with_donation(self, donation_amount: float) -> float:
        model = LifeModel(start_year=2020, end_year=2020, config=_fixture_config())
        family = Family(model)
        person = Person(family, "Giver", age=40, retirement_age=70, spending=Spending(model, base=0))
        BankAccount(person, "Bank", balance=50000, interest_rate=0)
        Job(person, "Co", "Dev", Salary(model=model, base=100000))
        if donation_amount > 0:
            Donation(person, "Charity", annual_amount=donation_amount)
        model.step()
        return person.stat_taxes_paid_federal

    def test_recurring_donation_reduces_federal_tax(self):
        # A donation made this year must be deductible this year. Itemizing $30k (vs the
        # $10k fixture standard deduction) lowers taxable income by $20k -> $5k less tax at 25%.
        # DEFAULT (5%) state income tax now also enters SALT. Only the itemizing
        # (donation) case includes it: state tax = 5% of the $70k post-charity AGI = $3,500, adding
        # $3,500 * 25% = $875 of federal savings. Total delta = $5,000 + $875 = $5,875.
        tax_without = self._federal_tax_with_donation(0)
        tax_with = self._federal_tax_with_donation(30000)
        self.assertLess(tax_with, tax_without)
        self.assertAlmostEqual(tax_without - tax_with, 5875.0, places=2)

    def test_daf_deposit_creates_no_deduction(self):
        # A bare deposit (no cash leaving the person) is not a deductible contribution.
        model = LifeModel(start_year=2020, end_year=2020, config=_fixture_config())
        family = Family(model)
        person = Person(family, "DAF Owner", age=40, retirement_age=70, spending=Spending(model, base=0))
        BankAccount(person, "Bank", balance=100000, interest_rate=0)
        daf = DonorAdvisedFund(person, "Fund", balance=0)

        daf.deposit(10000)
        self.assertEqual(daf.stat_contributions_this_year, 0)

        daf.contribute(10000)
        self.assertEqual(daf.stat_contributions_this_year, 10000)


def _add_home(person, loan_amount=300000, rate=5.0, property_tax_percent=1.0, purchase_price=400000):
    mortgage = Mortgage(loan_amount=loan_amount, start_date=2020, length_years=30, yearly_interest_rate=rate)
    expenses = HomeExpenses(
        model=person.model,
        property_tax_percent=property_tax_percent,
        home_insurance_percent=0.0,
        maintenance_amount=0,
        maintenance_increase=0.0,
        improvement_amount=0,
        improvement_increase=0.0,
        hoa_amount=0,
        hoa_increase=0.0,
    )
    return Home(
        person=person,
        name="House",
        purchase_price=purchase_price,
        value_yearly_increase=0.0,
        down_payment=100000,
        mortgage=mortgage,
        expenses=expenses,
    )


class TestHousingDeductions(unittest.TestCase):
    """Mortgage interest uses pre-payment interest with a $750k cap; property tax is SALT."""

    def test_interest_recorded_before_payment(self):
        mortgage = Mortgage(loan_amount=300000, start_date=2020, length_years=30, yearly_interest_rate=5.0)
        # A full year of simple interest on the starting principal is $15,000.
        self.assertAlmostEqual(mortgage.get_interest_for_year(), 15000.0, places=2)
        mortgage.make_yearly_payment(mortgage.monthly_payment)
        # interest_paid_this_year is the interest actually charged across the 12 monthly periods:
        # close to a full year's interest, and the deduction reads this (not the smaller
        # post-payment annual figure).
        self.assertGreater(mortgage.interest_paid_this_year, 14000.0)
        self.assertLessEqual(mortgage.interest_paid_this_year, 15000.0)
        self.assertLess(mortgage.get_interest_for_year(), 15000.0)

    def test_mortgage_interest_and_property_tax_deductible(self):
        model = LifeModel(start_year=2020, end_year=2020, config=_fixture_config())
        family = Family(model)
        person = Person(family, "Owner", age=40, retirement_age=70, spending=Spending(model, base=0))
        home = _add_home(person, loan_amount=300000, rate=5.0, property_tax_percent=1.0)

        # Full pre-payment interest ($15k, loan under the $750k cap) plus property tax
        # (home value $400k * 1% = $4k, under the SALT cap) are itemized.
        expected = 15000.0 + 4000.0
        self.assertAlmostEqual(person.total_itemized_deductions, expected, places=2)
        self.assertAlmostEqual(home.property_tax_for_year, 4000.0, places=2)

    def test_acquisition_debt_cap_limits_interest(self):
        model = LifeModel(start_year=2020, end_year=2020, config=_fixture_config())
        family = Family(model)
        person = Person(family, "Jumbo", age=40, retirement_age=70, spending=Spending(model, base=0))
        # $1.5M loan: only the interest on the first $750k of acquisition debt is deductible (half).
        _add_home(person, loan_amount=1500000, rate=5.0, property_tax_percent=0.0, purchase_price=1600000)

        full_interest = 1500000 * 0.05
        self.assertAlmostEqual(person.total_itemized_deductions, full_interest * (750000 / 1500000), places=2)


class TestRmdStartAge(unittest.TestCase):
    """RMD start-age gate and a clamped, IndexError-free table lookup."""

    def setUp(self):
        # Fixture RMD table: ages 72-75 with periods 25/24/23/22.
        self.config = _fixture_config()

    def test_no_distribution_before_start_age(self):
        self.assertEqual(required_min_distrib(72, 100000, config=self.config, start_age=73), 0)

    def test_distribution_at_start_age(self):
        # $240,000 / 24.0 (age-73 period) = $10,000.
        self.assertAlmostEqual(required_min_distrib(73, 240000, config=self.config, start_age=73), 10000.0, places=2)

    def test_fractional_age_does_not_raise(self):
        # A non-integer age must clamp to int(age) instead of failing an exact-match lookup.
        self.assertAlmostEqual(required_min_distrib(73.5, 240000, config=self.config, start_age=73), 10000.0, places=2)

    def test_age_beyond_table_clamps_to_last_row(self):
        # $220,000 / 22.0 (last, age-75 period) = $10,000.
        self.assertAlmostEqual(required_min_distrib(130, 220000, config=self.config, start_age=73), 10000.0, places=2)

    def test_secure_20_start_age(self):
        # Born 1960 or later start at 75; earlier cohorts use the year-indexed base (fixture: 72).
        self.assertEqual(rmd_start_age(1965), 75)
        self.assertEqual(rmd_start_age(1959, config=self.config, year=2020), 72)


if __name__ == "__main__":
    unittest.main()
