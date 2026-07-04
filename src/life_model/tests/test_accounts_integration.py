# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Integration tests for Plan 06 — account subsystem unification.

Exercises several account types together through the real simulation pipeline: registry surfacing,
the tax-efficient liquidation order, and annual contribution-limit resets.
"""

import unittest

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount
from ..account.hsa import HealthSavingsAccount, HSAType
from ..account.job401k import Job401kAccount
from ..account.roth_IRA import RothIRA
from ..account.traditional_IRA import TraditionalIRA
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..work.job import Job, Salary


class TestAccountSurfacing(unittest.TestCase):
    def test_all_account_types_are_registry_backed(self):
        model = LifeModel(1)
        person = Person(Family(model), "P", 40, 65, Spending(model))
        job = Job(person, "Co", "Dev", Salary(model, base=0))
        k401 = Job401kAccount(job, pretax_balance=1000)
        hsa = HealthSavingsAccount(person, HSAType.INDIVIDUAL, employer_contribution=0)
        roth = RothIRA(person)
        trad = TraditionalIRA(person)
        brokerage = BrokerageAccount(person, "B", balance=1000)

        tax_advantaged = person.all_tax_advantaged_accounts
        for account in (hsa, roth, trad):
            self.assertIn(account, tax_advantaged)
        self.assertIn(k401, person.all_retirement_accounts)
        self.assertIn(brokerage, person.brokerage_accounts)


class TestLiquidationOrder(unittest.TestCase):
    def test_brokerage_drained_before_pretax_401k(self):
        """D3: cash is raised from taxable brokerage before pre-tax 401k."""
        model = LifeModel(end_year=2020, start_year=2020)
        person = Person(Family(model), "Retiree", 65, 60, Spending(model, base=5000))
        BankAccount(person, "Bank", balance=0)
        BrokerageAccount(person, "B", balance=10000, growth_rate=0)  # basis == balance, no gain
        job = Job(person, "Co", "Retiree", Salary(model, base=0))
        Job401kAccount(job, pretax_balance=100000, average_growth=0)

        model.step()

        # The $5k of spending came from the brokerage (no embedded gain -> no tax), leaving the
        # 401k untouched.
        self.assertAlmostEqual(person.brokerage_accounts[0].balance, 5000, delta=1.0)
        self.assertEqual(job.retirement_account.pretax_balance, 100000)
        self.assertEqual(person.debt, 0)


class TestAnnualContributionReset(unittest.TestCase):
    def test_401k_deferrals_reset_each_year(self):
        """Item 3/7: 402(g) room resets annually rather than being a lifetime cap."""
        model = LifeModel(end_year=2022, start_year=2020)
        person = Person(Family(model), "P", 40, 65, Spending(model, base=0))
        BankAccount(person, "Bank", balance=0)
        job = Job(person, "Co", "Dev", Salary(model, base=100000))
        Job401kAccount(job, pretax_contrib_percent=10, average_growth=0)

        model.run()  # 3 years

        # 10% of $100k deferred each year for 3 years, no growth.
        self.assertAlmostEqual(job.retirement_account.pretax_balance, 30000, delta=1.0)

    def test_hsa_contribution_resets_across_years(self):
        model = LifeModel(1)
        person = Person(Family(model), "P", 40, 65, Spending(model))
        hsa = HealthSavingsAccount(person, HSAType.INDIVIDUAL, employer_contribution=0)
        for _ in range(3):
            hsa.contribute(1000)
            self.assertEqual(hsa.contributions_ytd, 1000)
            hsa.post_step()
            self.assertEqual(hsa.contributions_ytd, 0)


if __name__ == "__main__":
    unittest.main()
