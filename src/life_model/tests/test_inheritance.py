# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..account.bank import BankAccount
from ..account.job401k import Job401kAccount
from ..account.hsa import HealthSavingsAccount, HSAType
from ..account.brokerage import BrokerageAccount
from ..account.traditional_IRA import TraditionalIRA
from ..account.roth_IRA import RothIRA
from ..account.pension import Pension
from ..work.job import Job, Salary
from ..base_classes import FinancialAccount, Investment, RetirementAccount, Benefit


class TestInheritanceHierarchy(unittest.TestCase):
    """Test the standardized inheritance hierarchy"""

    def setUp(self):
        self.model = LifeModel()
        self.family = Family(self.model)
        self.spending = Spending(model=self.model, base=12000, yearly_increase=2.0)
        self.person = Person(
            family=self.family,
            name="Test Person",
            age=30,
            retirement_age=65,
            spending=self.spending
        )

    def test_bank_account_inheritance(self):
        """Test that BankAccount properly inherits from FinancialAccount"""
        bank = BankAccount(
            owner=self.person,
            company="Test Bank",
            type="Checking",
            balance=1000,
            interest_rate=0.1
        )

        # Test inheritance
        self.assertIsInstance(bank, FinancialAccount)

        # Test abstract method implementations
        self.assertEqual(bank.get_balance(), 1000)
        self.assertTrue(bank.deposit(500))
        self.assertEqual(bank.get_balance(), 1500)
        self.assertEqual(bank.withdraw(200), 200)
        self.assertEqual(bank.get_balance(), 1300)

    def test_job401k_inheritance(self):
        """Test that Job401kAccount properly inherits from RetirementAccount"""
        salary = Salary(model=self.model, base=100000, yearly_increase=3.0)
        job = Job(owner=self.person, company="Tech Corp", role="Engineer", salary=salary)

        account = Job401kAccount(
            job=job,
            pretax_balance=10000,
            roth_balance=5000,
            average_growth=7.0
        )

        # Test inheritance
        self.assertIsInstance(account, RetirementAccount)
        self.assertIsInstance(account, FinancialAccount)

        # Test abstract method implementations
        self.assertEqual(account.get_balance(), 15000)
        self.assertTrue(account.deposit(1000))
        self.assertEqual(account.get_balance(), 16000)
        withdrawn = account.withdraw(2000)
        self.assertEqual(withdrawn, 2000)
        self.assertEqual(account.get_balance(), 14000)

    def test_hsa_inheritance(self):
        """Test that HSA properly inherits from FinancialAccount"""
        hsa = HealthSavingsAccount(
            person=self.person,
            hsa_type=HSAType.INDIVIDUAL,
            balance=3000
        )

        # Test inheritance
        self.assertIsInstance(hsa, FinancialAccount)

        # Test abstract method implementations
        self.assertEqual(hsa.get_balance(), 3000)
        self.assertTrue(hsa.deposit(500))
        self.assertEqual(hsa.get_balance(), 3500)

    def test_investment_accounts_inheritance(self):
        """Test that investment accounts properly inherit from Investment"""
        brokerage = BrokerageAccount(
            person=self.person,
            company="Vanguard",
            balance=50000,
            growth_rate=7.0
        )

        traditional_ira = TraditionalIRA(
            person=self.person,
            balance=25000,
            growth_rate=6.5
        )

        roth_ira = RothIRA(
            person=self.person,
            balance=15000,
            growth_rate=6.5
        )

        # Test inheritance
        self.assertIsInstance(brokerage, Investment)
        self.assertIsInstance(brokerage, FinancialAccount)

        self.assertIsInstance(traditional_ira, Investment)
        self.assertIsInstance(traditional_ira, FinancialAccount)

        self.assertIsInstance(roth_ira, Investment)
        self.assertIsInstance(roth_ira, FinancialAccount)

        # Test that they all have growth functionality
        self.assertTrue(hasattr(brokerage, 'calculate_growth'))
        self.assertTrue(hasattr(traditional_ira, 'calculate_growth'))
        self.assertTrue(hasattr(roth_ira, 'calculate_growth'))

    def test_pension_inheritance(self):
        """Test that Pension properly inherits from Benefit"""
        pension = Pension(
            person=self.person,
            company="Big Corp",
            vesting_years=5,
            benefit_amount=24000
        )

        # Test inheritance
        self.assertIsInstance(pension, Benefit)

        # Test abstract method implementations
        self.assertEqual(pension.get_annual_benefit(), 0)  # Not retired yet
        self.assertFalse(pension.is_eligible())

    def test_abstract_methods_enforced(self):
        """Test that abstract methods are properly enforced"""
        # This test ensures that all required abstract methods are implemented
        # by creating instances and calling their methods

        bank = BankAccount(owner=self.person, company="Bank", balance=1000)
        self.assertTrue(callable(bank.get_balance))
        self.assertTrue(callable(bank.deposit))
        self.assertTrue(callable(bank.withdraw))

        # Test that the methods actually work
        initial_balance = bank.get_balance()
        bank.deposit(100)
        self.assertEqual(bank.get_balance(), initial_balance + 100)

        withdrawn = bank.withdraw(50)
        self.assertEqual(withdrawn, 50)
        self.assertEqual(bank.get_balance(), initial_balance + 50)

    def test_polymorphic_behavior(self):
        """Test that objects can be treated polymorphically through base classes"""
        # Create different types of financial accounts
        bank = BankAccount(owner=self.person, company="Bank", balance=1000)
        hsa = HealthSavingsAccount(person=self.person, hsa_type=HSAType.INDIVIDUAL, balance=2000)
        brokerage = BrokerageAccount(person=self.person, company="Broker", balance=5000)

        # Treat them all as FinancialAccount
        accounts = [bank, hsa, brokerage]

        total_balance = 0
        for account in accounts:
            self.assertIsInstance(account, FinancialAccount)
            total_balance += account.get_balance()

        self.assertEqual(total_balance, 8000)

        # Test depositing to all accounts polymorphically
        for account in accounts:
            account.deposit(100)

        new_total = sum(account.get_balance() for account in accounts)
        self.assertEqual(new_total, 8300)


if __name__ == '__main__':
    unittest.main()
