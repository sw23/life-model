# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest

from ..account.bank import BankAccount
from ..account.pension import Pension
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..tax.income import IncomeType


class TestPension(unittest.TestCase):
    def _person(self, age, retirement_age, start_year=2020, end_year=2020):
        model = LifeModel(start_year=start_year, end_year=end_year)
        return Person(
            family=Family(model), name="Pat", age=age, retirement_age=retirement_age, spending=Spending(model, 0)
        )

    def test_no_benefit_before_retirement(self):
        person = self._person(age=50, retirement_age=65)
        pension = Pension(person, "MegaCorp", vesting_years=5, benefit_amount=24000)
        self.assertFalse(pension.is_eligible())
        self.assertEqual(pension.get_annual_benefit(), 0.0)

    def test_benefit_paid_once_retired(self):
        person = self._person(age=66, retirement_age=65)
        pension = Pension(person, "MegaCorp", vesting_years=5, benefit_amount=24000)
        self.assertTrue(pension.is_eligible())
        self.assertEqual(pension.get_annual_benefit(), 24000)

    def test_explicit_start_age_overrides_retirement(self):
        person = self._person(age=62, retirement_age=60)
        pension = Pension(person, "MegaCorp", vesting_years=5, benefit_amount=24000, start_age=65)
        # Retired but not yet at the pension's start age.
        self.assertTrue(person.is_retired)
        self.assertFalse(pension.is_eligible())
        person.age = 65
        self.assertTrue(pension.is_eligible())

    def test_pension_registered_on_owner(self):
        person = self._person(age=66, retirement_age=65)
        pension = Pension(person, "MegaCorp", vesting_years=5, benefit_amount=24000)
        self.assertIn(pension, person.pensions)

    def test_benefit_lands_in_cash_and_ordinary_income_not_fica(self):
        model = LifeModel(start_year=2020, end_year=2020)
        person = Person(
            family=Family(model), name="Pat", age=66, retirement_age=65, spending=Spending(model, 0)
        )
        BankAccount(person, "Bank", balance=0, interest_rate=0)
        pension = Pension(person, "MegaCorp", vesting_years=5, benefit_amount=30000)

        # Isolate the deposit (before the year's tax settlement runs in the step stage).
        pension.pre_step()

        # The full benefit is deposited as cash.
        self.assertEqual(person.bank_account_balance, 30000)
        # It is ordinary taxable income but NOT FICA wages.
        entries = [e for e in person.income.entries if e.income_type == IncomeType.PENSION]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].amount, 30000)
        self.assertEqual(entries[0].fica_wages, 0.0)
        # Pension fills only the ordinary column of the ledger, never FICA wages.
        self.assertEqual(person.income.ordinary_taxable, 30000)
        self.assertEqual(person.income.fica_wages, 0.0)

    def test_pension_income_stat_recorded(self):
        model = LifeModel(start_year=2020, end_year=2020)
        person = Person(
            family=Family(model), name="Pat", age=66, retirement_age=65, spending=Spending(model, 0)
        )
        BankAccount(person, "Bank", balance=0, interest_rate=0)
        Pension(person, "MegaCorp", vesting_years=5, benefit_amount=30000)
        model.step()
        df = model.datacollector.get_model_vars_dataframe()
        self.assertEqual(dict(zip(df["Year"], df["Pension Income"]))[2020], 30000)

    def test_cola_compounds(self):
        model = LifeModel(start_year=2020, end_year=2022)
        person = Person(
            family=Family(model), name="Pat", age=66, retirement_age=65, spending=Spending(model, 0)
        )
        BankAccount(person, "Bank", balance=0, interest_rate=0)
        Pension(person, "MegaCorp", vesting_years=5, benefit_amount=10000, cola_percent=2.0)
        model.run()
        df = model.datacollector.get_model_vars_dataframe()
        pension_by_year = dict(zip(df["Year"], df["Pension Income"]))
        # Year 1 level, then +2% compounding each subsequent year.
        self.assertAlmostEqual(pension_by_year[2020], 10000, places=2)
        self.assertAlmostEqual(pension_by_year[2021], 10200, places=2)
        self.assertAlmostEqual(pension_by_year[2022], 10404, places=2)

    def test_no_cola_before_eligibility(self):
        # A pension not yet in pay does not accrue COLA.
        model = LifeModel(start_year=2020, end_year=2021)
        person = Person(
            family=Family(model), name="Pat", age=63, retirement_age=65, spending=Spending(model, 0)
        )
        BankAccount(person, "Bank", balance=0, interest_rate=0)
        pension = Pension(person, "MegaCorp", vesting_years=5, benefit_amount=10000, cola_percent=2.0)
        model.run()  # ages 64, 65 -> becomes eligible in the final year only
        # Benefit was level while not in pay; COLA only compounds once benefits have started.
        self.assertAlmostEqual(pension.benefit_amount, 10200, places=2)


if __name__ == "__main__":
    unittest.main()
