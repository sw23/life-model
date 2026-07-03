# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Regression tests for Plan 04 — core simulation engine correctness.

Each test targets a specific money-flow bug catalogued in plans/04-core-engine-correctness.md.
Dollar assertions are derived from the library's own tax/housing helpers (not hardcoded
constants) so they remain valid as financial data is refreshed.
"""

import unittest

from ..account.bank import BankAccount
from ..housing.home import Home, HomeExpenses, Mortgage
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..people.tax_unit import TaxUnit
from ..tax.federal import FilingStatus, federal_standard_deduction
from ..tax.tax import get_income_taxes_due
from ..work.job import Job, Salary


def _make_home(person, purchase_price=400000, mortgage_rate=4.5, appreciation=0.0):
    mortgage = Mortgage(loan_amount=300000, start_date=2020, length_years=30, yearly_interest_rate=mortgage_rate)
    expenses = HomeExpenses(
        model=person.model,
        property_tax_percent=1.0,
        home_insurance_percent=0.0,
        maintenance_amount=1000,
        maintenance_increase=0.0,
        improvement_amount=0,
        improvement_increase=0.0,
        hoa_amount=0,
        hoa_increase=0.0,
    )
    return Home(
        person=person,
        name="Test House",
        purchase_price=purchase_price,
        value_yearly_increase=appreciation,
        down_payment=100000,
        mortgage=mortgage,
        expenses=expenses,
    )


class TestDataCollectorTiming(unittest.TestCase):
    """Bug 5 / D4: collect after stages; row Year=Y holds year-Y flows; final year collected."""

    def test_year_semantics_and_flows(self):
        model = LifeModel(start_year=2020, end_year=2022)
        family = Family(model)
        person = Person(family, "Ann", age=40, retirement_age=70, spending=Spending(model, 0))
        BankAccount(person, "Bank", balance=0, interest_rate=0)
        Job(person, "Co", "Dev", Salary(model=model, base=40000))

        model.run()

        # Inclusive year range: 2020..2022 -> 3 simulated years
        self.assertEqual(model.simulated_years, [2020, 2021, 2022])
        df = model.datacollector.get_model_vars_dataframe()
        self.assertEqual(len(df), 3)
        # First row is year 2020 and already contains that year's income (not an all-zero row).
        self.assertEqual(df.iloc[0]["Year"], 2020)
        self.assertEqual(df.iloc[0]["Income"], 40000)
        # Final simulated year is present.
        self.assertEqual(df.iloc[-1]["Year"], 2022)


class TestSpendingTiming(unittest.TestCase):
    """Bug 3: one-time expenses are spent (not wiped) and the yearly increase applies a year late."""

    def test_one_time_expense_spent_and_increase_deferred(self):
        model = LifeModel(start_year=2020, end_year=2022)
        family = Family(model)
        spending = Spending(model, base=10000, yearly_increase=10)
        person = Person(family, "Bo", age=40, retirement_age=70, spending=spending)
        BankAccount(person, "Bank", balance=1_000_000, interest_rate=0)

        spending.add_expense(5000)  # added before the sim runs
        model.step()  # year 1
        self.assertEqual(person.stat_money_spent, 15000)  # base + one-time, increase not yet applied

        model.step()  # year 2
        self.assertEqual(person.stat_money_spent, 11000)  # base grew 10%, one-time cleared


class TestRetirementCrossing(unittest.TestCase):
    """Bug 4: non-integer retirement age must still trigger retirement (crossing detection)."""

    def test_non_integer_retirement_age_triggers(self):
        model = LifeModel(start_year=2020, end_year=2030)
        family = Family(model)
        person = Person(family, "Cy", age=64, retirement_age=65.5, spending=Spending(model, 0))
        BankAccount(person, "Bank", balance=100000, interest_rate=0)
        job = Job(person, "Co", "Dev", Salary(model=model, base=50000))

        model.step()  # age 65 -> below 65.5, still working
        self.assertEqual(person.age, 65)
        self.assertFalse(job.retired)

        model.step()  # age 66 -> crosses 65.5, retires
        self.assertEqual(person.age, 66)
        self.assertTrue(job.retired)


class TestMarriedHousing(unittest.TestCase):
    """Bug 1: married couples must actually pay housing; a mortgage only amortizes when cash is paid."""

    def test_married_couple_pays_housing_and_amortizes_with_cash(self):
        model = LifeModel(start_year=2020, end_year=2021)
        family = Family(model)
        a = Person(family, "Dana", age=40, retirement_age=70, spending=Spending(model, 0))
        b = Person(family, "Evan", age=40, retirement_age=70, spending=Spending(model, 0))
        a.get_married(b)
        bank = BankAccount(a, "Bank", balance=1_000_000, interest_rate=0)
        home = _make_home(a)

        # Capture the year's housing figures before the step (no income -> no taxes).
        interest = home.mortgage.get_interest_for_year()
        mortgage_payment = home.mortgage.get_payment_due_for_year()
        home_expenses = home.expenses.get_yearly_spending()
        total_housing = mortgage_payment + home_expenses
        principal_before = home.mortgage.principal
        bank_before = bank.balance

        model.step()

        # Cash actually left the bank for the full housing cost.
        self.assertAlmostEqual(bank.balance, bank_before - total_housing, places=2)
        # Mortgage principal dropped only by the principal portion (payment - interest).
        self.assertAlmostEqual(home.mortgage.principal, principal_before - (mortgage_payment - interest), places=2)


class TestFamilyDebtPaidOnce(unittest.TestCase):
    """Bug 2: a family member's debt must be paid exactly once, not doubled."""

    def test_member_debt_paid_once(self):
        model = LifeModel(start_year=2020, end_year=2021)
        family = Family(model)
        a = Person(family, "Fay", age=40, retirement_age=70, spending=Spending(model, 0))
        b = Person(family, "Gil", age=40, retirement_age=70, spending=Spending(model, 0))
        a.get_married(b)
        bank = BankAccount(a, "Bank", balance=100000, interest_rate=0)
        b.debt = 10000

        model.step()

        self.assertEqual(bank.balance, 90000)  # withdrawn once, not twice
        self.assertEqual(a.debt, 0)
        self.assertEqual(b.debt, 0)


class TestMixedFilingUnits(unittest.TestCase):
    """Bug 6: a family with mixed filing statuses is taxed per filing unit (not zero / not double)."""

    def test_single_and_married_units_taxed_correctly(self):
        model = LifeModel(start_year=2020, end_year=2021)
        family = Family(model)
        a = Person(family, "Single A", age=40, retirement_age=70, spending=Spending(model, 0))
        b = Person(family, "Spouse B", age=40, retirement_age=70, spending=Spending(model, 0))
        c = Person(family, "Spouse C", age=40, retirement_age=70, spending=Spending(model, 0))
        b.get_married(c)
        for p in (a, b, c):
            BankAccount(p, "Bank", balance=500000, interest_rate=0)
        Job(a, "Co", "Dev", Salary(model=model, base=60000))
        Job(b, "Co", "Dev", Salary(model=model, base=70000))
        Job(c, "Co", "Dev", Salary(model=model, base=80000))

        # Two tax units: {A} single, {B, C} married-filing-jointly.
        units = TaxUnit.build_units(family)
        self.assertEqual(len(units), 2)

        model.step()

        tax_a = get_income_taxes_due(60000, federal_standard_deduction[FilingStatus.SINGLE], FilingStatus.SINGLE).total
        tax_bc = get_income_taxes_due(
            150000,
            federal_standard_deduction[FilingStatus.MARRIED_FILING_JOINTLY],
            FilingStatus.MARRIED_FILING_JOINTLY,
        ).total

        total_taxes = sum(p.stat_taxes_paid for p in (a, b, c))
        self.assertGreater(total_taxes, 0)
        self.assertAlmostEqual(total_taxes, tax_a + tax_bc, places=2)


class TestGetMarriedMergesFamilies(unittest.TestCase):
    """Bug 6: marrying two people in different families merges them into one."""

    def test_marriage_merges_separate_families(self):
        model = LifeModel(start_year=2020, end_year=2021)
        fam_a = Family(model)
        fam_b = Family(model)
        a = Person(fam_a, "Hal", age=40, retirement_age=70, spending=Spending(model, 0))
        b = Person(fam_b, "Ivy", age=40, retirement_age=70, spending=Spending(model, 0))

        a.get_married(b)

        self.assertIs(b.family, fam_a)
        self.assertIn(b, fam_a.members)
        self.assertEqual(fam_b.members, [])
        self.assertEqual(len(TaxUnit.build_units(fam_a)), 1)


class TestMoneyConservation(unittest.TestCase):
    """Acceptance: cash conservation for a married couple with a mortgage, year by year."""

    def test_bank_conservation_year_by_year(self):
        model = LifeModel(start_year=2020, end_year=2025)
        family = Family(model)
        a = Person(family, "Jo", age=40, retirement_age=70, spending=Spending(model, base=20000))
        b = Person(family, "Kai", age=40, retirement_age=70, spending=Spending(model, base=0))
        a.get_married(b)
        bank = BankAccount(a, "Bank", balance=1_000_000, interest_rate=0)
        _make_home(a, appreciation=5.0)
        Job(a, "Co", "Dev", Salary(model=model, base=120000))

        for _ in model.get_year_range():
            bank_before = bank.balance
            model.step()
            # Pull the year's flows from the collected frame (row for the year just simulated).
            row = model.datacollector.get_model_vars_dataframe().iloc[-1]
            delta_bank = bank.balance - bank_before
            expected = row["Income"] - row["Spending"] - row["Housing"] - row["Taxes"]
            self.assertAlmostEqual(delta_bank, expected, delta=1.0)


class TestConstructionOrderIndependence(unittest.TestCase):
    """Acceptance: shuffling construction order yields identical DataCollector frames."""

    @staticmethod
    def _build_and_run(bank_first: bool):
        model = LifeModel(start_year=2020, end_year=2025, seed=42)
        family = Family(model)
        person = Person(family, "Lee", age=40, retirement_age=70, spending=Spending(model, base=15000))
        if bank_first:
            BankAccount(person, "Bank", balance=200000, interest_rate=0)
            Job(person, "Co", "Dev", Salary(model=model, base=90000))
        else:
            Job(person, "Co", "Dev", Salary(model=model, base=90000))
            BankAccount(person, "Bank", balance=200000, interest_rate=0)
        model.run()
        return model.datacollector.get_model_vars_dataframe()

    def test_frames_identical_regardless_of_order(self):
        df1 = self._build_and_run(bank_first=True)
        df2 = self._build_and_run(bank_first=False)
        self.assertTrue(df1.equals(df2))


if __name__ == "__main__":
    unittest.main()
