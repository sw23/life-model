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


def _person(age: int = 40) -> Person:
    model = LifeModel(1)
    return Person(Family(model), "P", age, 65, Spending(model))


class TestRothIRA(unittest.TestCase):
    def test_contribution_basis_withdrawn_tax_free(self):
        person = _person(age=40)
        roth = RothIRA(person, balance=1000, growth_rate=0)
        withdrawn = roth.withdraw(500)
        self.assertEqual(withdrawn, 500)
        self.assertEqual(person.income.ordinary_taxable, 0)
        self.assertEqual(person.income.penalties, 0)

    def test_non_qualified_earnings_taxed_and_penalized(self):
        person = _person(age=40)
        roth = RothIRA(person, balance=1000, growth_rate=10)
        roth.apply_growth()  # balance 1100, basis 1000, earnings 100
        # Drain the tax-free basis first.
        roth.withdraw(1000)
        self.assertEqual(person.income.ordinary_taxable, 0)
        # The next $100 is all earnings: taxed + 10% penalty.
        roth.withdraw(100)
        self.assertAlmostEqual(person.income.ordinary_taxable, 100)
        self.assertAlmostEqual(person.income.penalties, 10)

    def test_qualified_earnings_tax_free_at_retirement_age(self):
        person = _person(age=66)
        roth = RothIRA(person, balance=1000, growth_rate=10)
        roth.apply_growth()
        roth.withdraw(1100)  # basis + earnings, all qualified
        self.assertEqual(person.income.ordinary_taxable, 0)
        self.assertEqual(person.income.penalties, 0)

    def test_ira_limit_shared_with_traditional(self):
        person = _person()
        roth = RothIRA(person, growth_rate=0)
        trad = TraditionalIRA(person, growth_rate=0)
        limit = roth.annual_contribution_limit()
        self.assertEqual(roth.contribute(limit), limit)
        # The shared IRA limit is exhausted; the traditional IRA can accept nothing more.
        self.assertEqual(trad.remaining_contribution_room(), 0)
        self.assertEqual(trad.contribute(1000), 0)

    def test_annual_contribution_resets(self):
        person = _person()
        roth = RothIRA(person, growth_rate=0)
        roth.contribute(1000)
        self.assertEqual(roth.contributions_ytd, 1000)
        roth.post_step()
        self.assertEqual(roth.contributions_ytd, 0)


if __name__ == "__main__":
    unittest.main()
