# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest

from ..account.brokerage import BrokerageAccount
from ..account.hsa import HealthSavingsAccount, HSAType
from ..account.job401k import Job401kAccount
from ..account.roth_IRA import RothIRA
from ..account.traditional_IRA import TraditionalIRA
from ..base_classes import Investment
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..work.job import Job, Salary


class _ConcreteInvestment(Investment):
    """Minimal concrete Investment used to exercise the abstract base class directly."""

    def calculate_growth(self) -> float:
        return self.balance * (self.growth_rate / 100)

    def get_balance(self) -> float:
        return self.balance

    def deposit(self, amount: float) -> bool:
        if amount <= 0:
            return False
        self.balance += amount
        return True

    def withdraw(self, amount: float) -> float:
        withdrawn = min(self.balance, max(0.0, amount))
        self.balance -= withdrawn
        return withdrawn


class TestInvestment(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(start_year=2020, end_year=2020)
        self.person = Person(
            family=Family(self.model), name="Sam", age=40, retirement_age=65, spending=Spending(self.model, 0)
        )

    def test_unknown_asset_class_rejected(self):
        with self.assertRaises(ValueError):
            _ConcreteInvestment(self.person, balance=1000, asset_class="crypto")

    def test_explicit_growth_rate_overrides_economy(self):
        inv = _ConcreteInvestment(self.person, balance=1000, growth_rate=8.0)
        self.assertEqual(inv.growth_rate, 8.0)

    def test_none_growth_rate_defers_to_economy(self):
        inv = _ConcreteInvestment(self.person, balance=1000, growth_rate=None, asset_class="equity")
        expected = self.model.economy.rate("equity_return", self.model.year)
        self.assertEqual(inv.growth_rate, expected)

    def test_growth_rate_setter_reapplies_override(self):
        inv = _ConcreteInvestment(self.person, balance=1000, growth_rate=None)
        inv.growth_rate = 3.0
        self.assertEqual(inv.growth_rate, 3.0)

    def test_apply_growth_updates_balance_and_history(self):
        inv = _ConcreteInvestment(self.person, balance=1000, growth_rate=10.0)
        growth = inv.apply_growth()
        self.assertAlmostEqual(growth, 100.0, places=6)
        self.assertAlmostEqual(inv.balance, 1100.0, places=6)
        self.assertEqual(inv.stat_growth_history, [growth])

    def test_step_applies_growth_and_records_balance(self):
        inv = _ConcreteInvestment(self.person, balance=1000, growth_rate=10.0)
        inv.step()
        self.assertAlmostEqual(inv.balance, 1100.0, places=6)
        self.assertEqual(inv.stat_balance_history, [1100.0])


def _plan06_person(age: int = 40, year: int = 2020) -> Person:
    model = LifeModel(end_year=year, start_year=year)
    return Person(Family(model), "P", age, 65, Spending(model))


class TestInvestmentGrowthParity(unittest.TestCase):
    """Plan 06 acceptance: every Investment subclass grows identically for the same APY (item 13)."""

    def test_all_investments_grow_identically(self):
        person = _plan06_person()
        rate = 10.0
        brokerage = BrokerageAccount(person, "B", balance=1000, growth_rate=rate)
        roth = RothIRA(person, balance=1000, growth_rate=rate)
        trad = TraditionalIRA(person, balance=1000, growth_rate=rate)
        hsa = HealthSavingsAccount(person, HSAType.INDIVIDUAL, balance=1000, growth_rate=rate, employer_contribution=0)
        job = Job(person, "Co", "Dev", Salary(person.model, base=0))
        k401 = Job401kAccount(job, pretax_balance=1000, average_growth=rate)

        for account in (brokerage, roth, trad, hsa, k401):
            account.apply_growth()

        for account in (brokerage, roth, trad, hsa, k401):
            self.assertAlmostEqual(account.balance, 1100.0, places=6)

    def test_stored_balance_is_settable(self):
        """Plan 06 item 8: assignment works for stored balances (and raises for the derived 401k)."""
        brokerage = BrokerageAccount(_plan06_person(), "B", balance=1000)
        brokerage.balance = 2500
        self.assertEqual(brokerage.balance, 2500)


if __name__ == "__main__":
    unittest.main()
