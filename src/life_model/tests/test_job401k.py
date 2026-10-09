# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..account.job401k import Job401kAccount
from ..config.financial_config import FinancialConfig
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

    def test_deposit_validation_is_uniform(self):
        """Same rule as every account: zero is a successful no-op, negative raises (Plan 06 item 14)."""
        account = self._account()
        self.assertTrue(account.deposit(0))
        self.assertEqual(account.balance, 0)
        with self.assertRaises(ValueError):
            account.deposit(-100)

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

    def test_growth_applied_in_step_with_annual_compounding(self):
        """Growth runs in step (after this year's contributions) at an APY, like every Investment."""
        account = self._account(pretax_balance=10000, roth_balance=10000, average_growth=10)
        account.pre_step()  # RMD only; the owner is far below RMD age.
        self.assertEqual(account.pretax_balance, 10000)
        account.step()
        self.assertAlmostEqual(account.pretax_balance, 11000, places=6)
        self.assertAlmostEqual(account.roth_balance, 11000, places=6)

    def test_balance_assignment_raises(self):
        """The derived balance must never silently discard a write (Plan 06 item 8)."""
        account = self._account(pretax_balance=100)
        with self.assertRaises(AttributeError):
            account.balance = 5


class TestJob401kLimits(unittest.TestCase):
    @staticmethod
    def _fixture_config() -> FinancialConfig:
        return FinancialConfig(config_file=str(Path(__file__).parent / "fixtures" / "test_config.yaml"))

    def test_two_jobs_share_one_402g_limit(self):
        """Plan 06 item 7: two jobs can't each defer the full elective limit."""
        model = LifeModel(end_year=2020, start_year=2020, config=self._fixture_config())
        person = Person(Family(model), "P", 40, 65, Spending(model, base=0))
        BankAccount(person, "Bank", balance=0)
        job1 = Job(person, "Co1", "Dev", Salary(model, base=100000))
        Job401kAccount(job1, pretax_contrib_percent=15, average_growth=0)
        job2 = Job(person, "Co2", "Dev", Salary(model, base=100000))
        Job401kAccount(job2, pretax_contrib_percent=15, average_growth=0)

        model.step()

        # Fixture 402(g) base is $20k: job 1 defers $15k, job 2 only the remaining $5k.
        self.assertAlmostEqual(job1.retirement_account.pretax_balance, 15000, places=2)
        self.assertAlmostEqual(job2.retirement_account.pretax_balance, 5000, places=2)

    def test_employer_match_capped_by_415c(self):
        model = LifeModel(end_year=2020, start_year=2020, config=self._fixture_config())
        person = Person(Family(model), "P", 40, 65, Spending(model, base=0))
        BankAccount(person, "Bank", balance=0)
        job = Job(person, "Co", "Dev", Salary(model, base=100000))
        # Elective 20% of $100k = $20k (the fixture 402(g) base). A 300% match would be $60k, but
        # the fixture 415(c) annual-additions limit of $60k caps the match at $60k - $20k.
        Job401kAccount(job, pretax_contrib_percent=20, company_match_percent=300, average_growth=0)

        model.step()

        self.assertAlmostEqual(job.stat_retirement_contrib, 20000, places=2)
        self.assertAlmostEqual(job.stat_retirement_match, 40000, places=2)

    def test_required_minimum_distribution_in_pre_step(self):
        model = LifeModel(end_year=2020, start_year=2020)
        person = Person(Family(model), "P", 75, 60, Spending(model, base=0))
        job = Job(person, "Co", "Retiree", Salary(model, base=0))
        k401 = Job401kAccount(job, pretax_balance=100000, average_growth=0)
        k401.pre_step()
        self.assertGreater(k401.stat_required_min_distrib, 0)
        self.assertAlmostEqual(person.income.ordinary_taxable, k401.stat_required_min_distrib)
        self.assertEqual(person.income.fica_wages, 0)


if __name__ == "__main__":
    unittest.main()
