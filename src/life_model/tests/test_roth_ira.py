# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest

from ..account.roth_IRA import RothIRA
from ..account.traditional_IRA import TraditionalIRA
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending


class TestRothIRA(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(start_year=2020, end_year=2020)
        self.person = Person(
            family=Family(self.model), name="Sam", age=40, retirement_age=65, spending=Spending(self.model, 0)
        )

    def _ira(self, **kwargs):
        kwargs.setdefault("growth_rate", 5.0)
        return RothIRA(self.person, **kwargs)

    def test_contribute_up_to_limit(self):
        ira = self._ira(contribution_limit=6000)
        self.assertEqual(ira.contribute(4000), 4000)
        self.assertEqual(ira.balance, 4000)

    def test_contribute_clamped_at_limit(self):
        ira = self._ira(contribution_limit=6000)
        ira.contribute(5000)
        self.assertEqual(ira.contribute(5000), 1000)
        self.assertEqual(ira.balance, 6000)

    def test_deposit_is_a_plain_credit(self):
        """deposit() credits without using contribution room (rollovers); validation is uniform."""
        ira = self._ira(contribution_limit=6000)
        self.assertTrue(ira.deposit(1000))
        self.assertEqual(ira.balance, 1000)
        self.assertEqual(ira.remaining_contribution_room(), 6000)
        self.assertTrue(ira.deposit(0))
        with self.assertRaises(ValueError):
            ira.deposit(-100)

    def test_withdraw_capped_at_balance(self):
        ira = self._ira(contribution_limit=6000, balance=3000)
        self.assertEqual(ira.withdraw(5000), 3000)
        self.assertEqual(ira.balance, 0)
        self.assertEqual(ira.withdraw(100), 0)

    def test_deposit_withdraw_round_trip(self):
        ira = self._ira(contribution_limit=6000)
        ira.deposit(2000)
        self.assertEqual(ira.withdraw(2000), 2000)
        self.assertEqual(ira.balance, 0)

    def test_growth_positive_on_positive_balance(self):
        ira = self._ira(contribution_limit=6000, balance=1000)
        growth = ira.calculate_growth()
        self.assertAlmostEqual(growth, 50.0, places=6)

    def test_reset_annual_contributions(self):
        ira = self._ira(contribution_limit=6000)
        ira.contribute(6000)
        ira.reset_annual_contributions()
        self.assertEqual(ira.contributions_ytd, 0)
        self.assertEqual(ira.contribute(1000), 1000)


def _plan06_person(age: int = 40, year: int = 2020) -> Person:
    model = LifeModel(end_year=year, start_year=year)
    return Person(Family(model), "P", age, 65, Spending(model))


class TestRothIRATaxSemantics(unittest.TestCase):
    def test_contribution_basis_withdrawn_tax_free(self):
        person = _plan06_person(age=40)
        roth = RothIRA(person, balance=1000, growth_rate=0)
        self.assertEqual(roth.withdraw(500), 500)
        self.assertEqual(person.income.ordinary_taxable, 0)
        self.assertEqual(person.income.penalties, 0)

    def test_non_qualified_earnings_taxed_and_penalized(self):
        person = _plan06_person(age=40)
        roth = RothIRA(person, balance=1000, growth_rate=10)
        roth.apply_growth()  # balance 1100, basis 1000, earnings 100
        roth.withdraw(1000)  # basis first: tax-free
        self.assertEqual(person.income.ordinary_taxable, 0)
        roth.withdraw(100)  # all earnings: taxed + 10% penalty
        self.assertAlmostEqual(person.income.ordinary_taxable, 100)
        self.assertAlmostEqual(person.income.penalties, 10)

    def test_qualified_earnings_tax_free_at_retirement_age(self):
        person = _plan06_person(age=66)
        roth = RothIRA(person, balance=1000, growth_rate=10)
        roth.apply_growth()
        roth.withdraw(1100)
        self.assertEqual(person.income.ordinary_taxable, 0)
        self.assertEqual(person.income.penalties, 0)

    def test_tax_free_withdrawable_is_basis_before_59_and_a_half(self):
        roth = RothIRA(_plan06_person(age=40), balance=1000, growth_rate=10)
        roth.apply_growth()
        self.assertAlmostEqual(roth.tax_free_withdrawable(), 1000)
        old_roth = RothIRA(_plan06_person(age=66), balance=1000, growth_rate=10)
        old_roth.apply_growth()
        self.assertAlmostEqual(old_roth.tax_free_withdrawable(), 1100)

    def test_ira_limit_shared_with_traditional(self):
        person = _plan06_person()
        roth = RothIRA(person, growth_rate=0)
        trad = TraditionalIRA(person, growth_rate=0)
        limit = roth.annual_contribution_limit()
        self.assertEqual(roth.contribute(limit), limit)
        self.assertEqual(trad.remaining_contribution_room(), 0)
        self.assertEqual(trad.contribute(1000), 0)


if __name__ == "__main__":
    unittest.main()
