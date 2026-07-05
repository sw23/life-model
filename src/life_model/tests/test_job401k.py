# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest

from ..account.job401k import Job401kAccount
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..work.job import Job, Salary


class TestJob401k(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(start_year=2020, end_year=2020)
        self.person = Person(
            family=Family(self.model), name="Sam", age=40, retirement_age=65, spending=Spending(self.model, 0)
        )
        self.job = Job(owner=self.person, company="Co", role="Dev", salary=Salary(model=self.model, base=0))

    def _account(self, **kwargs):
        return Job401kAccount(job=self.job, **kwargs)

    def test_balance_is_sum_of_pretax_and_roth(self):
        account = self._account(pretax_balance=1000, roth_balance=500)
        self.assertEqual(account.balance, 1500)
        self.assertEqual(account.get_balance(), 1500)

    def test_contribution_helpers_scale_with_salary(self):
        account = self._account(pretax_contrib_percent=10, roth_contrib_percent=5, company_match_percent=50)
        self.assertEqual(account.pretax_contrib(100000), 10000)
        self.assertEqual(account.roth_contrib(100000), 5000)
        self.assertEqual(account.company_match(10000), 5000)

    def test_deposit_goes_to_pretax(self):
        account = self._account()
        self.assertTrue(account.deposit(2000))
        self.assertEqual(account.pretax_balance, 2000)
        self.assertEqual(account.roth_balance, 0)

    def test_deposit_non_positive_rejected(self):
        account = self._account()
        self.assertFalse(account.deposit(0))
        self.assertFalse(account.deposit(-100))

    def test_withdraw_drains_pretax_before_roth(self):
        account = self._account(pretax_balance=1000, roth_balance=1000)
        withdrawn = account.withdraw(1500)
        self.assertEqual(withdrawn, 1500)
        self.assertEqual(account.pretax_balance, 0)
        self.assertEqual(account.roth_balance, 500)

    def test_withdraw_capped_at_balance(self):
        account = self._account(pretax_balance=200, roth_balance=100)
        self.assertEqual(account.withdraw(10000), 300)
        self.assertEqual(account.balance, 0)

    def test_withdraw_non_positive_returns_zero(self):
        account = self._account(pretax_balance=1000)
        self.assertEqual(account.withdraw(0), 0.0)
        self.assertEqual(account.withdraw(-5), 0.0)
        self.assertEqual(account.pretax_balance, 1000)

    def test_growth_applied_in_pre_step(self):
        account = self._account(pretax_balance=10000, roth_balance=10000, average_growth=10)
        account.pre_step()
        # Continuous 10% growth on each balance.
        self.assertGreater(account.pretax_balance, 10000)
        self.assertGreater(account.roth_balance, 10000)
        self.assertAlmostEqual(account.pretax_balance, account.roth_balance, places=6)


if __name__ == "__main__":
    unittest.main()
