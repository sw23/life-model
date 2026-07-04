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


def _person(age: int = 66, retirement_age: int = 65) -> Person:
    model = LifeModel(end_year=2020, start_year=2020)
    person = Person(Family(model), "P", age, retirement_age, Spending(model))
    BankAccount(person, "Bank", balance=0)
    return person


class TestPension(unittest.TestCase):
    def test_not_vested_is_ineligible(self):
        person = _person(age=66)
        pension = Pension(person, "Co", vesting_years=5, benefit_amount=24000, years_of_service=2)
        self.assertFalse(pension.is_eligible())
        self.assertEqual(pension.get_annual_benefit(), 0)

    def test_before_election_age_is_ineligible(self):
        person = _person(age=60, retirement_age=65)
        pension = Pension(person, "Co", vesting_years=5, benefit_amount=24000)
        self.assertFalse(pension.is_eligible())
        self.assertEqual(pension.get_annual_benefit(), 0)

    def test_vested_and_elected_pays_taxable_benefit(self):
        person = _person(age=66, retirement_age=65)
        pension = Pension(person, "Co", vesting_years=5, benefit_amount=24000)
        self.assertTrue(pension.is_eligible())
        pension.pre_step()
        self.assertEqual(person.bank_account_balance, 24000)
        # Pension income is ordinary income, not FICA wages.
        self.assertEqual(person.income.ordinary_taxable, 24000)
        self.assertEqual(person.income.fica_wages, 0)

    def test_accrual_formula(self):
        person = _person(age=66, retirement_age=65)
        pension = Pension(
            person,
            "Co",
            vesting_years=5,
            years_of_service=20,
            benefit_multiplier=2.0,
            final_salary=100000,
        )
        # 20 years x 2% x $100k = $40k.
        self.assertEqual(pension.get_annual_benefit(), 40000)

    def test_registered_on_person(self):
        person = _person()
        pension = Pension(person, "Co", vesting_years=5, benefit_amount=1000)
        self.assertIn(pension, person.pensions)


if __name__ == "__main__":
    unittest.main()
