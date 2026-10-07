# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Integration tests for Plan 06 — account subsystem unification.

Exercises several account types together through the real simulation pipeline: registry surfacing,
the withdrawal order, annual contribution-limit resets, and the tax treatment of contributions,
pre-tax draws, and early-withdrawal penalties at year-end settlement.
"""

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount
from ..account.hsa import HealthSavingsAccount, HSAType
from ..account.job401k import Job401kAccount
from ..account.roth_IRA import RothIRA
from ..account.traditional_IRA import TraditionalIRA
from ..config.financial_config import FinancialConfig
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..work.job import Job, Salary

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    """Fresh FinancialConfig loaded from the frozen test fixture."""
    return FinancialConfig(config_file=TEST_CONFIG)


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
        job = Job(person, "Co", "Dev", Salary(model, base=100000, yearly_increase=0))
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


class TestPretaxDrawsAtSettlement(unittest.TestCase):
    def _retiree(self, age, ira_balance):
        model = LifeModel(end_year=2020, start_year=2020, config=_fixture_config())
        person = Person(Family(model), "R", age, 40, Spending(model, base=30000, yearly_increase=0))
        BankAccount(person, "Bank", balance=0, interest_rate=0)
        ira = TraditionalIRA(person, balance=ira_balance, growth_rate=0)
        return model, person, ira

    def test_ira_only_retiree_draws_the_ira_instead_of_running_up_debt(self):
        model, person, ira = self._retiree(age=65, ira_balance=200000)
        model.step()
        self.assertEqual(person.debt, 0)
        self.assertLess(ira.balance, 200000)
        # Fixture: draw D with tax 10% x (D - $10k) federal + 5% x (D - $10k) state = $30k bills.
        # 0.85 D + 1,500 = 30,000  ->  D = 33,529.41. The bank ends empty.
        self.assertAlmostEqual(200000 - ira.balance, 33529.41, places=1)
        self.assertAlmostEqual(person.bank_account_balance, 0, places=1)

    def test_early_draw_is_sized_for_and_charged_the_penalty(self):
        model, person, ira = self._retiree(age=45, ira_balance=200000)
        model.step()
        self.assertEqual(person.debt, 0)
        # As above plus the 10% additional tax on the whole draw: 0.75 D + 1,500 = 30,000.
        self.assertAlmostEqual(200000 - ira.balance, 38000.0, places=1)
        self.assertAlmostEqual(person.bank_account_balance, 0, places=1)
        df = model.datacollector.get_model_vars_dataframe()
        # Federal = 10% x $28k income tax + $3.8k penalty.
        self.assertAlmostEqual(df["Federal Taxes"].iloc[-1], 2800 + 3800, places=1)


class TestTraditionalVersusRoth(unittest.TestCase):
    def _taxes_after_contributing(self, account_cls):
        model = LifeModel(end_year=2020, start_year=2020, config=_fixture_config())
        person = Person(Family(model), "W", 40, 65, Spending(model, base=0))
        BankAccount(person, "Bank", balance=10000, interest_rate=0)
        Job(person, "Co", "Dev", Salary(model, base=60000, yearly_increase=0))
        account_cls(person, growth_rate=0).contribute(6000)
        model.step()
        return model.datacollector.get_model_vars_dataframe()["Federal Taxes"].iloc[-1]

    def test_traditional_contribution_lowers_federal_tax_and_roth_does_not(self):
        traditional = self._taxes_after_contributing(TraditionalIRA)
        roth = self._taxes_after_contributing(RothIRA)
        # Fixture brackets: 10% to $40k, 25% above. Taxable income $50k (Roth) vs $44k (Traditional):
        # the $6k deduction comes off the 25% bracket.
        self.assertAlmostEqual(roth - traditional, 6000 * 0.25, places=1)


if __name__ == "__main__":
    unittest.main()


class TestHsaFundsSettlement(unittest.TestCase):
    """HSAs are a settlement source: tax-free for medical costs, else taxable as a last resort."""

    def _person(self, age, hsa_balance, spending=0):
        model = LifeModel(end_year=2026, start_year=2026, config=_fixture_config())
        person = Person(Family(model), "P", age, 40, Spending(model, base=spending, yearly_increase=0))
        BankAccount(person, "Bank", balance=0, interest_rate=0)
        hsa = HealthSavingsAccount(
            person, HSAType.INDIVIDUAL, balance=hsa_balance, growth_rate=0, employer_contribution=0
        )
        return model, person, hsa

    def test_medical_costs_reimbursed_tax_free_when_cash_is_short(self):
        model, person, hsa = self._person(age=50, hsa_balance=50000)
        person.spending.add_expense(8000)

        class _Medical:  # stand-in for a healthcare agent's stamped cost
            stat_medical_costs = 8000

        person.model.registries.medical_costs.register(person, _Medical())
        model.step()
        self.assertAlmostEqual(hsa.balance, 42000, places=2)
        self.assertEqual(person.stat_taxes_paid, 0)  # qualified distribution: no tax, no penalty
        self.assertEqual(person.debt, 0)

    def test_non_medical_draw_is_last_resort_and_penalized_before_65(self):
        model, person, hsa = self._person(age=50, hsa_balance=100000, spending=30000)
        model.step()
        self.assertEqual(person.debt, 0)
        # Fixture: D with 10% x (D - 10k) federal + 20% x D penalty + 5% x (D - 10k) state = 30k:
        # 0.65 D + 1,500 = 30,000 -> D = 43,846.15.
        self.assertAlmostEqual(100000 - hsa.balance, 28500 / 0.65, places=1)
