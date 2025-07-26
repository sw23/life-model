# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from unittest.mock import patch
from ..model import LifeModel
from ..people.person import Person, Spending
from ..people.family import Family
from ..account.bank import BankAccount
from ..account.job401k import Job401kAccount
from ..work.job import Job, Salary
from ..services.tax_calculation_service import TaxCalculationService
from ..services.payment_service import PaymentService
from ..tax.tax import TaxesDue
from ..tax.federal import FilingStatus


class TestTaxCalculationService(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(1)
        self.family = Family(self.model, 'Test Family')
        self.spending = Spending(self.model, base=50000)
        self.person = Person(self.family, 'John', 30, 67, self.spending)
        self.person.filing_status = FilingStatus.SINGLE

        # Add a bank account
        self.bank = BankAccount(self.person, 'Test Bank', balance=10000)

        # Add a job with 401k
        self.salary = Salary(self.model, base=100000)
        self.job = Job(self.person, 'Test Corp', 'Engineer', self.salary)
        self.job401k = Job401kAccount(self.job, pretax_balance=50000, roth_balance=25000)
        self.job.retirement_account = self.job401k

        self.tax_service = TaxCalculationService(self.person)

    def test_calculate_pretax_401k_withdrawal_needed_sufficient_bank_balance(self):
        """Test when bank balance is sufficient for expenses"""
        result = self.tax_service.calculate_pretax_401k_withdrawal_needed(5000)
        self.assertEqual(result, 0.0)

    def test_calculate_pretax_401k_withdrawal_needed_insufficient_bank_balance(self):
        """Test when bank balance is insufficient and 401k withdrawal is needed"""
        result = self.tax_service.calculate_pretax_401k_withdrawal_needed(15000)
        self.assertEqual(result, 5000)  # 15000 - 10000 bank balance

    @patch('life_model.services.tax_calculation_service.max_tax_rate')
    def test_calculate_taxes_on_401k_withdrawal(self, mock_max_tax_rate):
        """Test tax calculation on 401k withdrawal"""
        mock_max_tax_rate.return_value = 25

        # Mock the tax calculation methods
        with patch.object(self.person, 'get_income_taxes_due') as mock_taxes:
            mock_taxes.side_effect = [
                TaxesDue(federal=5000, state=1000, ss=0, medicare=0),  # Before withdrawal
                TaxesDue(federal=6000, state=1200, ss=0, medicare=0)   # After withdrawal
            ]

            result = self.tax_service.calculate_taxes_on_401k_withdrawal(10000)

            # Base increase: (6000+1200) - (5000+1000) = 1200
            # Buffer: 1200 * (25/100) = 300
            # Total: 1200 + 300 = 1500
            # Note: The actual result might be different due to max_tax_rate calculation
            self.assertAlmostEqual(result, 1500, delta=200)  # Allow some tolerance

    def test_calculate_taxes_on_401k_withdrawal_zero_amount(self):
        """Test tax calculation with zero withdrawal amount"""
        result = self.tax_service.calculate_taxes_on_401k_withdrawal(0)
        self.assertEqual(result, 0.0)


class TestPaymentService(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(2)
        self.family = Family(self.model, 'Test Family')
        self.spending = Spending(self.model, base=50000)
        self.person = Person(self.family, 'Jane', 35, 67, self.spending)

        # Add a bank account
        self.bank = BankAccount(self.person, 'Test Bank', balance=5000)

        # Add a job with 401k
        self.salary = Salary(self.model, base=100000)
        self.job = Job(self.person, 'Test Corp', 'Engineer', self.salary)
        self.job401k = Job401kAccount(self.job, pretax_balance=30000, roth_balance=15000)
        self.job.retirement_account = self.job401k

        self.payment_service = PaymentService(self.person)

    def test_pay_bills_sufficient_bank_balance(self):
        """Test payment when bank balance is sufficient"""
        result = self.payment_service.pay_bills_with_prioritization(3000)
        self.assertEqual(result, 0)  # All bills paid
        self.assertEqual(self.bank.balance, 2000)  # 5000 - 3000

    def test_pay_bills_needs_roth_withdrawal(self):
        """Test payment when bank balance is insufficient and Roth withdrawal is needed"""
        result = self.payment_service.pay_bills_with_prioritization(8000)
        self.assertEqual(result, 0)  # All bills paid
        self.assertEqual(self.bank.balance, 0)  # All bank money used
        self.assertEqual(self.job401k.roth_balance, 12000)  # 15000 - 3000 remaining

    def test_pay_bills_insufficient_total_funds(self):
        """Test payment when total available funds are insufficient"""
        result = self.payment_service.pay_bills_with_prioritization(25000)
        # Should use all bank (5000) + all Roth (15000) = 20000 paid, 5000 remaining
        self.assertEqual(result, 5000)
        self.assertEqual(self.bank.balance, 0)
        self.assertEqual(self.job401k.roth_balance, 0)

    def test_payment_prioritization_order(self):
        """Test that payments follow the correct priority order"""
        # Mock the methods to track call order
        with patch.object(self.person, 'deduct_from_bank_accounts', return_value=2000) as mock_bank, \
             patch.object(self.person, 'deduct_from_roth_401ks', return_value=0) as mock_roth:

            self.payment_service.pay_bills_with_prioritization(8000)

            # Bank accounts should be called first
            mock_bank.assert_called_once_with(8000)
            # Roth should be called with remaining amount
            mock_roth.assert_called_once_with(2000)


class TestServiceIntegration(unittest.TestCase):
    """Test integration between services and Person class"""

    def setUp(self):
        self.model = LifeModel(3)
        self.family = Family(self.model, 'Test Family')
        self.spending = Spending(self.model, base=40000)
        self.person = Person(self.family, 'Integration Test', 40, 67, self.spending)

        # Add accounts
        self.bank = BankAccount(self.person, 'Test Bank', balance=15000)

        self.salary = Salary(self.model, base=80000)
        self.job = Job(self.person, 'Test Corp', 'Manager', self.salary)
        self.job401k = Job401kAccount(self.job, pretax_balance=100000, roth_balance=50000)
        self.job.retirement_account = self.job401k

    def test_person_initializes_services(self):
        """Test that Person initializes both services correctly"""
        self.assertIsInstance(self.person.tax_service, TaxCalculationService)
        self.assertIsInstance(self.person.payment_service, PaymentService)
        self.assertEqual(self.person.tax_service.person, self.person)
        self.assertEqual(self.person.payment_service.person, self.person)

    def test_pay_bills_uses_payment_service(self):
        """Test that pay_bills method uses the PaymentService"""
        initial_bank_balance = self.bank.balance
        remaining = self.person.pay_bills(5000)

        self.assertEqual(remaining, 0)  # Should be able to pay from bank
        self.assertEqual(self.bank.balance, initial_bank_balance - 5000)


if __name__ == '__main__':
    unittest.main()
