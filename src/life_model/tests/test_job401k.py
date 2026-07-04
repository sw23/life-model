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

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    return FinancialConfig(config_file=TEST_CONFIG)


class TestJob401k(unittest.TestCase):
    def test_balance_is_pretax_plus_roth(self):
        model = LifeModel(1)
        person = Person(Family(model), "P", 40, 65, Spending(model))
        job = Job(person, "Co", "Dev", Salary(model, base=0))
        k401 = Job401kAccount(job, pretax_balance=1000, roth_balance=500)
        self.assertEqual(k401.balance, 1500)
        with self.assertRaises(AttributeError):
            k401.balance = 5000

    def test_annual_compounding_growth(self):
        model = LifeModel(1)
        person = Person(Family(model), "P", 40, 65, Spending(model))
        job = Job(person, "Co", "Dev", Salary(model, base=0))
        k401 = Job401kAccount(job, pretax_balance=1000, roth_balance=1000, average_growth=10)
        k401.apply_growth()
        self.assertAlmostEqual(k401.pretax_balance, 1100, places=6)
        self.assertAlmostEqual(k401.roth_balance, 1100, places=6)

    def test_two_jobs_share_one_402g_limit(self):
        """Item 7: two jobs can't each defer the full elective limit."""
        model = LifeModel(end_year=2020, start_year=2020)
        person = Person(Family(model), "P", 40, 65, Spending(model, base=0))
        BankAccount(person, "Bank", balance=0)
        limit = person.remaining_401k_elective_room()  # live 402(g) limit for age 40
        job1 = Job(person, "Co1", "Dev", Salary(model, base=100000))
        Job401kAccount(job1, pretax_contrib_percent=20, average_growth=0)
        job2 = Job(person, "Co2", "Dev", Salary(model, base=100000))
        Job401kAccount(job2, pretax_contrib_percent=20, average_growth=0)

        model.step()

        total_deferred = job1.retirement_account.pretax_balance + job2.retirement_account.pretax_balance
        self.assertAlmostEqual(total_deferred, limit, places=2)

    def test_employer_match_capped_by_415c(self):
        model = LifeModel(end_year=2020, start_year=2020, config=_fixture_config())
        person = Person(Family(model), "P", 40, 65, Spending(model, base=0))
        BankAccount(person, "Bank", balance=0)
        job = Job(person, "Co", "Dev", Salary(model, base=100000))
        # Elective 20% of 100k = 20000 (== fixture 402(g) base). Match 300% would be 60000, but the
        # fixture 415(c) annual-additions limit is 60000, so match is capped to 60000 - 20000.
        Job401kAccount(job, pretax_contrib_percent=20, company_match_percent=300, average_growth=0)

        model.step()

        self.assertAlmostEqual(job.stat_retirement_contrib, 20000, places=2)
        self.assertAlmostEqual(job.stat_retirement_match, 40000, places=2)

    def test_required_minimum_distribution(self):
        model = LifeModel(end_year=2020, start_year=2020)
        person = Person(Family(model), "P", 75, 60, Spending(model, base=0))
        job = Job(person, "Co", "Retiree", Salary(model, base=0))
        k401 = Job401kAccount(job, pretax_balance=100000, average_growth=0)
        k401.step()
        self.assertGreater(k401.stat_required_min_distrib, 0)
        self.assertAlmostEqual(person.income.ordinary_taxable, k401.stat_required_min_distrib)
        self.assertEqual(person.income.fica_wages, 0)


if __name__ == "__main__":
    unittest.main()
