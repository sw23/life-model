# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..account.job401k import Job401kAccount
from ..config.financial_config import FinancialConfig
from ..limits import job_401k_contrib_limit
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..work.job import Job, Salary

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    """Fresh FinancialConfig loaded from the frozen test fixture."""
    return FinancialConfig(config_file=TEST_CONFIG)


class TestJobContributionRouting(unittest.TestCase):
    def _person(self, age=40, config=None):
        model = LifeModel(start_year=2020, end_year=2020, config=config or _fixture_config())
        person = Person(family=Family(model), name="Sam", age=age, retirement_age=70, spending=Spending(model, 0))
        BankAccount(person, "Bank", balance=0, interest_rate=0)
        return person

    def test_pretax_deferral_reduces_ordinary_income_but_not_fica(self):
        person = self._person()
        job = Job(person, "Co", "Dev", Salary(model=person.model, base=100000))
        Job401kAccount(job=job, pretax_contrib_percent=10, average_growth=0)
        job.pre_step()
        # Take-home = gross - 401k contribution.
        self.assertEqual(person.bank_account_balance, 90000)
        # Ordinary income reduced by the pre-tax deferral; FICA base is the full gross.
        self.assertEqual(person.taxable_income, 90000)
        self.assertEqual(person.fica_wages, 100000)

    def test_roth_contribution_stays_taxable_income(self):
        person = self._person()
        job = Job(person, "Co", "Dev", Salary(model=person.model, base=100000))
        account = Job401kAccount(job=job, roth_contrib_percent=10, average_growth=0)
        job.pre_step()
        self.assertEqual(person.bank_account_balance, 90000)
        # Roth deferrals are after-tax: ordinary income is not reduced.
        self.assertEqual(person.taxable_income, 100000)
        self.assertEqual(account.roth_balance, 10000)

    def test_company_match_added_to_pretax_balance_only(self):
        person = self._person()
        job = Job(person, "Co", "Dev", Salary(model=person.model, base=100000))
        account = Job401kAccount(job=job, pretax_contrib_percent=10, company_match_percent=50, average_growth=0)
        job.pre_step()
        # $10k pre-tax contribution + 50% match = $15k in the pre-tax balance.
        self.assertEqual(account.pretax_balance, 15000)
        self.assertEqual(job.stat_retirement_match, 5000)
        # The match is employer money and does not touch the worker's take-home or income.
        self.assertEqual(person.bank_account_balance, 90000)

    def test_contribution_capped_at_annual_limit(self):
        person = self._person()
        job = Job(person, "Co", "Dev", Salary(model=person.model, base=1_000_000))
        account = Job401kAccount(job=job, pretax_contrib_percent=50, average_growth=0)
        job.pre_step()
        # A 50% deferral on a $1M salary is far above any annual 401k limit, so it is capped.
        limit = job_401k_contrib_limit(person.age)
        self.assertEqual(account.pretax_balance, limit)
        self.assertEqual(job.stat_retirement_contrib, limit)
        self.assertLess(account.pretax_balance, 500000)

    def test_bonus_included_in_gross_income(self):
        person = self._person()
        job = Job(person, "Co", "Dev", Salary(model=person.model, base=100000, yearly_bonus=10))
        job.pre_step()
        # Gross = base + 10% bonus = $110k, all deposited (no 401k).
        self.assertEqual(job.stat_gross_income, 110000)
        self.assertEqual(person.bank_account_balance, 110000)

    def test_retired_job_produces_no_income(self):
        person = self._person()
        job = Job(person, "Co", "Dev", Salary(model=person.model, base=100000))
        job.retired = True
        job.pre_step()
        self.assertEqual(job.stat_gross_income, 0)
        self.assertEqual(person.bank_account_balance, 0)
        self.assertEqual(person.taxable_income, 0)


class TestSalary(unittest.TestCase):
    def test_bonus_is_percentage_of_base(self):
        model = LifeModel(start_year=2020, end_year=2020)
        salary = Salary(model=model, base=100000, yearly_bonus=5)
        self.assertEqual(salary.bonus, 5000)

    def test_escalator_grows_base_in_post_step(self):
        model = LifeModel(start_year=2020, end_year=2020)
        salary = Salary(model=model, base=100000, yearly_increase=10)
        salary.post_step()
        self.assertAlmostEqual(salary.base, 110000, places=6)


class TestRetire(unittest.TestCase):
    def test_retire_marks_job_retired(self):
        model = LifeModel(start_year=2020, end_year=2020)
        person = Person(family=Family(model), name="Sam", age=40, retirement_age=70, spending=Spending(model, 0))
        job = Job(person, "Co", "Dev", Salary(model=model, base=100000))
        self.assertFalse(job.retired)
        job.retire()
        self.assertTrue(job.retired)


if __name__ == "__main__":
    unittest.main()
