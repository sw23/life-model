# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest

from ..account.pension import Pension
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending


class TestPension(unittest.TestCase):
    def _person(self, age, retirement_age):
        model = LifeModel(start_year=2020, end_year=2020)
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


if __name__ == "__main__":
    unittest.main()
