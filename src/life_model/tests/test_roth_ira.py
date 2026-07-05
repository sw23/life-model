# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest

from ..account.roth_IRA import RothIRA
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

    def test_deposit_reports_success(self):
        ira = self._ira(contribution_limit=6000)
        self.assertTrue(ira.deposit(1000))
        self.assertFalse(ira.deposit(0))
        self.assertFalse(ira.deposit(-100))

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
        self.assertEqual(ira.contributions_this_year, 0)
        self.assertEqual(ira.contribute(1000), 1000)


if __name__ == "__main__":
    unittest.main()
