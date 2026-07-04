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
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..work.job import Job, Salary


def _person(age: int = 40) -> Person:
    model = LifeModel(1)
    return Person(Family(model), "P", age, 65, Spending(model))


class TestInvestmentGrowthParity(unittest.TestCase):
    """Acceptance: every Investment subclass grows identically for the same APY (item 13)."""

    def test_all_investments_grow_identically(self):
        person = _person()
        rate = 10.0
        brokerage = BrokerageAccount(person, "B", balance=1000, growth_rate=rate)
        roth = RothIRA(person, balance=1000, growth_rate=rate)
        trad = TraditionalIRA(person, balance=1000, growth_rate=rate)
        hsa = HealthSavingsAccount(person, HSAType.INDIVIDUAL, balance=1000, growth_rate=rate, employer_contribution=0)
        job = Job(person, "Co", "Dev", Salary(person.model, base=0))
        k401 = Job401kAccount(job, pretax_balance=1000, average_growth=rate)

        for account in (brokerage, roth, trad, hsa):
            account.apply_growth()
        k401.apply_growth()

        for account in (brokerage, roth, trad, hsa, k401):
            self.assertAlmostEqual(account.balance, 1100.0, places=6)


class TestBalanceSetter(unittest.TestCase):
    """Acceptance: account.balance = x either works or raises — never silently discarded (item 8)."""

    def test_stored_balance_is_settable(self):
        person = _person()
        brokerage = BrokerageAccount(person, "B", balance=1000)
        brokerage.balance = 2500
        self.assertEqual(brokerage.balance, 2500)

    def test_derived_401k_balance_raises_on_assignment(self):
        person = _person()
        job = Job(person, "Co", "Dev", Salary(person.model, base=0))
        k401 = Job401kAccount(job, pretax_balance=1000, roth_balance=500)
        self.assertEqual(k401.balance, 1500)
        with self.assertRaises(AttributeError):
            k401.balance = 9999
        self.assertEqual(k401.balance, 1500)


if __name__ == "__main__":
    unittest.main()
