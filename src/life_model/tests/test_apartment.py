# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the Apartment housing option (rent paid through tax-unit settlement)."""

import unittest

from ..account.bank import BankAccount
from ..housing.apartment import Apartment
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending


class TestApartment(unittest.TestCase):
    def test_yearly_rent_is_twelve_months(self):
        model = LifeModel(start_year=2020, end_year=2020)
        family = Family(model)
        person = Person(family, "Renter", age=30, retirement_age=70, spending=Spending(model, 0))
        apartment = Apartment(person=person, name="Downtown", monthly_rent=1500, yearly_increase=0.0)
        self.assertEqual(apartment.yearly_rent, 18000)

    def test_rent_is_paid_from_bank_each_year(self):
        model = LifeModel(start_year=2020, end_year=2020)
        family = Family(model)
        person = Person(family, "Renter", age=30, retirement_age=70, spending=Spending(model, 0))
        bank = BankAccount(person, "Bank", balance=100000, interest_rate=0)
        Apartment(person=person, name="Downtown", monthly_rent=1500, yearly_increase=0.0)
        model.run()
        self.assertEqual(bank.balance, 100000 - 18000)

    def test_rent_escalates_after_the_year(self):
        model = LifeModel(start_year=2020, end_year=2021)
        family = Family(model)
        person = Person(family, "Renter", age=30, retirement_age=70, spending=Spending(model, 0))
        BankAccount(person, "Bank", balance=1000000, interest_rate=0)
        apartment = Apartment(person=person, name="Downtown", monthly_rent=1000, yearly_increase=10.0)
        model.run()
        # Rent escalates 10% per year after each year's rent is paid.
        self.assertAlmostEqual(apartment.monthly_rent, 1000 * 1.10 * 1.10, places=2)


if __name__ == "__main__":
    unittest.main()
