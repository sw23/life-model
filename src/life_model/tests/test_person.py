# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..config.financial_config import FinancialConfig
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..work.job import Job, Salary

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    """Fresh FinancialConfig loaded from the frozen test fixture."""
    return FinancialConfig(config_file=TEST_CONFIG)


class TestPerson(unittest.TestCase):
    def test_get_year_at_age(self):
        model = LifeModel(start_year=2020)
        person = Person(
            family=Family(model), name="Yami Raymundo", age=23, retirement_age=60, spending=Spending(model, 10000)
        )
        self.assertEqual(person.get_year_at_age(50), 2047)

    def test_federal_taxes_due(self):
        model = LifeModel(start_year=2020, config=_fixture_config())
        person = Person(
            family=Family(model), name="Cas Harjabertaz", age=36, retirement_age=56, spending=Spending(model, 0)
        )
        BankAccount(owner=person, company="Bank of Mojave", type="Checking")
        job = Job(owner=person, company="Fiber Fashion", role="Personal Shopper", salary=Salary(model=model, base=0))
        # Fixture: $10k standard deduction, brackets 10% to $40k then 25%.
        # DEFAULT (5%) state income tax enters the SALT itemized deduction. It only
        # changes the outcome for the top earner, whose state tax ($28,295 = 5% of the $565,900
        # post-standard AGI) exceeds the $10k standard deduction, flipping them to itemizing:
        # federal tax on ($575,900 - $28,295) = $130,901.25. Lower rows keep the standard deduction
        # (state tax < $10k) and are unchanged.
        tax_data = (
            (5900, 0),  # Below standard deduction
            (15900, 590),
            (50900, 4225),
            (95900, 15475),
            (109900, 18975),
            (120900, 21725),
            (575900, 130901.25),  # state income tax enters SALT
        )
        for salary, taxes_due in tax_data:
            job.salary.base = salary
            model.step()
            self.assertEqual(person.stat_taxes_paid_federal, taxes_due)

    # TODO - Add test for state taxes

    def test_ss_taxes_due(self):
        model = LifeModel(start_year=2020, config=_fixture_config())
        person = Person(
            family=Family(model), name="Julie Antipater", age=24, retirement_age=65, spending=Spending(model, 0)
        )
        BankAccount(owner=person, company="Acrobatable", type="Checking")
        job = Job(owner=person, company="Acrobatable", role="Software Developer", salary=Salary(model=model, base=0))
        # Fixture Social Security wage base is $110,000.
        tax_data = (
            (5900, 5900 * 0.062),
            (15900, 15900 * 0.062),
            (50900, 50900 * 0.062),
            (95900, 95900 * 0.062),
            (109900, 109900 * 0.062),
            (120900, 110000 * 0.062),  # Above the fixture max of $110,000
            (575900, 110000 * 0.062),  # Above the fixture max of $110,000
        )
        for salary, taxes_due in tax_data:
            job.salary.base = salary
            model.step()
            self.assertEqual(person.stat_taxes_paid_ss, taxes_due)

    def test_medicare_taxes_due(self):
        model = LifeModel(start_year=2020, config=_fixture_config())
        person = Person(
            family=Family(model), name="Gunnel Ingi", age=33, retirement_age=50, spending=Spending(model, 0)
        )
        BankAccount(owner=person, company="Bits and Bytes", type="Checking")
        job = Job(owner=person, company="Bits and Bytes", role="Researcher", salary=Salary(model=model, base=0))
        # Fixture medicare rate 1.45%, additional 0.9% over $200,000 (single).
        tax_data = (
            (5900, 5900 * 0.0145),
            (15900, 15900 * 0.0145),
            (50900, 50900 * 0.0145),
            (95900, 95900 * 0.0145),
            (109900, 109900 * 0.0145),
            (120900, 120900 * 0.0145),
            (575900, (575900 * 0.0145 + (575900 - 200000) * 0.009)),  # Additional tax since over $200,000
        )
        for salary, taxes_due in tax_data:
            job.salary.base = salary
            model.step()
            self.assertAlmostEqual(person.stat_taxes_paid_medicare, taxes_due, places=2)


class TestPersonWithdrawalHelpers(unittest.TestCase):
    """Person-level withdrawal helpers: money lands in the bank and taxable
    distributions create income-ledger entries settled at year end."""

    def _make_person(self):
        model = LifeModel(start_year=2025)
        person = Person(family=Family(model), name="Withdrawer", age=45, retirement_age=65, spending=Spending(model, 0))
        BankAccount(owner=person, company="Bank", type="Checking", balance=1000)
        return model, person

    def test_withdraw_from_traditional_iras_is_taxable_income(self):
        from ..account.traditional_IRA import TraditionalIRA

        model, person = self._make_person()
        TraditionalIRA(person=person, balance=50000)
        withdrawn = person.withdraw_from_traditional_iras(20000)
        self.assertEqual(withdrawn, 20000)
        self.assertEqual(person.bank_account_balance, 21000)
        self.assertEqual(person.taxable_income, 20000)
        self.assertEqual(person.traditional_iras[0].balance, 30000)

    def test_withdraw_from_roth_iras_is_tax_free(self):
        from ..account.roth_IRA import RothIRA

        model, person = self._make_person()
        RothIRA(person=person, balance=50000)
        withdrawn = person.withdraw_from_roth_iras(20000)
        self.assertEqual(withdrawn, 20000)
        self.assertEqual(person.bank_account_balance, 21000)
        self.assertEqual(person.taxable_income, 0)

    def test_withdraw_from_roth_401ks_is_tax_free(self):
        from ..account.job401k import Job401kAccount

        model, person = self._make_person()
        job = Job(owner=person, company="Co", role="Dev", salary=Salary(model=model, base=0))
        Job401kAccount(job=job, roth_balance=30000)
        withdrawn = person.withdraw_from_roth_401ks(10000)
        self.assertEqual(withdrawn, 10000)
        self.assertEqual(person.bank_account_balance, 11000)
        self.assertEqual(person.taxable_income, 0)

    def test_withdraw_from_hsas_and_brokerage_are_untaxed_transfers(self):
        from ..account.brokerage import BrokerageAccount
        from ..account.hsa import HealthSavingsAccount, HSAType

        model, person = self._make_person()
        HealthSavingsAccount(person=person, hsa_type=HSAType.INDIVIDUAL, balance=5000)
        BrokerageAccount(person=person, company="Broker", balance=8000)
        self.assertEqual(person.withdraw_from_hsas(2000), 2000)
        self.assertEqual(person.withdraw_from_brokerage_accounts(3000), 3000)
        self.assertEqual(person.bank_account_balance, 6000)
        self.assertEqual(person.taxable_income, 0)

    def test_withdrawals_are_capped_at_available_balance(self):
        from ..account.traditional_IRA import TraditionalIRA

        model, person = self._make_person()
        TraditionalIRA(person=person, balance=1500)
        withdrawn = person.withdraw_from_traditional_iras(10000)
        self.assertEqual(withdrawn, 1500)
        self.assertEqual(person.taxable_income, 1500)

    def test_traditional_ira_withdrawal_is_taxed_at_settlement(self):
        # The ledger entry must actually increase the taxes settled by the tax unit in step().
        from ..account.traditional_IRA import TraditionalIRA

        results = {}
        for withdraw in (False, True):
            model = LifeModel(start_year=2025, config=_fixture_config())
            person = Person(
                family=Family(model), name="Settler", age=45, retirement_age=65, spending=Spending(model, 0)
            )
            BankAccount(owner=person, company="Bank", type="Checking", balance=100000)
            ira = TraditionalIRA(person=person, balance=100000, growth_rate=0)
            if withdraw:
                person.withdraw_from_traditional_iras(50000)
            else:
                # Move the same cash without a ledger entry so both runs have identical balances.
                person.receive_cash(ira.withdraw(50000))
            model.step()
            results[withdraw] = person.stat_taxes_paid
        self.assertGreater(results[True], results[False])
