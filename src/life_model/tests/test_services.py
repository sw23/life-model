# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from ..account.bank import BankAccount
from ..account.job401k import Job401kAccount
from ..config.financial_config import FinancialConfig
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..services.payment_service import PaymentService
from ..services.tax_calculation_service import TaxCalculationService
from ..tax.federal import FilingStatus
from ..work.job import Job, Salary

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    """Fresh FinancialConfig loaded from the frozen test fixture."""
    return FinancialConfig(config_file=TEST_CONFIG)


class TestTaxCalculationService(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(1, config=_fixture_config())
        self.family = Family(self.model, "Test Family")
        self.spending = Spending(self.model, base=50000)
        self.person = Person(self.family, "John", 30, 67, self.spending)
        self.person.filing_status = FilingStatus.SINGLE

        # Add a bank account
        self.bank = BankAccount(self.person, "Test Bank", balance=10000)

        # Add a job with 401k
        self.salary = Salary(self.model, base=100000)
        self.job = Job(self.person, "Test Corp", "Engineer", self.salary)
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

    def test_calculate_taxes_on_401k_withdrawal_unmocked_against_fixture(self):
        """Real tax path against the frozen fixture: no other income, $30k pre-tax withdrawal.

        Federal: ($30,000 - $10,000 standard deduction) x 10% = $2,000 (no FICA on distributions),
        plus the 10% early-withdrawal additional tax because the owner is 30: $3,000.
        State: the DEFAULT pack's flat 5% applies to the federal-style AGI base, i.e. after the
        federal deduction: $20,000 x 5% = $1,000.
        Exactly $6,000: no max-marginal-rate buffer (Plan 05 item 9).
        """
        self.assertEqual(self.person.taxable_income, 0)
        result = self.tax_service.calculate_taxes_on_401k_withdrawal(30000)
        self.assertAlmostEqual(result, 6000.0, places=2)

    def test_sizing_is_the_exact_fixed_point(self):
        """$30k of expenses, $10k in the bank, owner aged 30, fixture rates.

        taxes(G) = 10% x (G - 10k) federal + 10% x G penalty + 5% x (G - 10k) state = 0.25 G - 1,500,
        so G = 30,000 + 0.25 G - 1,500 - 10,000  ->  G = 24,666.67 (no over-withdrawal).
        """
        gross = self.tax_service.size_401k_withdrawal(30000)
        self.assertAlmostEqual(gross, 74000 / 3, places=2)
        self.assertEqual(self.job401k.pretax_balance, 50000)  # sizing moves no money

    def test_calculate_taxes_on_401k_withdrawal_zero_amount(self):
        """Test tax calculation with zero withdrawal amount"""
        result = self.tax_service.calculate_taxes_on_401k_withdrawal(0)
        self.assertEqual(result, 0.0)

    def test_total_401k_withdrawal_not_needed_when_bank_covers_expenses(self):
        """When the bank balance covers expenses, no 401k withdrawal is made."""
        total_withdrawal, _ = self.tax_service.calculate_total_401k_withdrawal(5000)
        self.assertEqual(total_withdrawal, 0.0)
        self.assertEqual(self.job401k.pretax_balance, 50000)

    def test_total_401k_withdrawal_covers_expenses_plus_taxes(self):
        """A shortfall drives a pre-tax withdrawal sized to cover expenses and the tax on it."""
        total_withdrawal, final_taxes = self.tax_service.calculate_total_401k_withdrawal(30000)
        # Bank held $10k, so at least the $20k shortfall (plus tax) is withdrawn from pre-tax.
        self.assertGreaterEqual(total_withdrawal, 20000)
        self.assertLess(self.job401k.pretax_balance, 50000)
        self.assertGreaterEqual(final_taxes.total, 0.0)


class TestPaymentService(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(2, config=_fixture_config())
        self.family = Family(self.model, "Test Family")
        self.spending = Spending(self.model, base=50000)
        self.person = Person(self.family, "Jane", 35, 67, self.spending)

        # Add a bank account
        self.bank = BankAccount(self.person, "Test Bank", balance=5000)

        # Add a job with 401k
        self.salary = Salary(self.model, base=100000)
        self.job = Job(self.person, "Test Corp", "Engineer", self.salary)
        self.job401k = Job401kAccount(self.job, pretax_balance=30000, roth_balance=15000)
        self.job.retirement_account = self.job401k

        self.payment_service = PaymentService(self.person)

    def test_pay_from_brokerage_conserves_money(self):
        """Regression: brokerage proceeds used to land in the bank AND count as paid (free money)."""
        from ..account.brokerage import BrokerageAccount

        self.bank.balance = 0
        self.job401k.roth_balance = 0
        brokerage = BrokerageAccount(self.person, "Broker", balance=10000, growth_rate=0)

        unpaid = self.payment_service.pay_bills_with_prioritization(4000)

        self.assertEqual(unpaid, 0)
        self.assertEqual(brokerage.balance, 6000)
        self.assertEqual(self.bank.balance, 0)

    def test_roth_ira_drawn_after_roth_401k(self):
        from ..account.roth_IRA import RothIRA

        self.bank.balance = 0
        self.job401k.roth_balance = 1000
        roth_ira = RothIRA(self.person, balance=5000, growth_rate=0)

        unpaid = self.payment_service.pay_bills_with_prioritization(3000)

        self.assertEqual(unpaid, 0)
        self.assertEqual(self.job401k.roth_balance, 0)
        self.assertEqual(roth_ira.balance, 3000)

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
        """Payments follow bank -> brokerage -> Roth 401k -> Roth IRA, each on the remainder."""
        manager = Mock()
        with (
            patch.object(self.person, "deduct_from_bank_accounts", return_value=2000) as mock_bank,
            patch.object(self.person, "withdraw_from_brokerage_accounts", return_value=0) as mock_brokerage,
            patch.object(self.person, "deduct_from_roth_401ks", return_value=0) as mock_roth,
            patch.object(self.person, "deduct_from_roth_iras", return_value=0) as mock_roth_ira,
        ):
            manager.attach_mock(mock_bank, "bank")
            manager.attach_mock(mock_brokerage, "brokerage")
            manager.attach_mock(mock_roth, "roth_401k")
            manager.attach_mock(mock_roth_ira, "roth_ira")

            self.payment_service.pay_bills_with_prioritization(8000)

        # Bank first; the brokerage step sells into the bank and pays the remainder from it; the
        # Roth 401k gets what is still unpaid; the Roth IRA is not needed once nothing remains.
        self.assertEqual(
            manager.mock_calls,
            [call.bank(8000), call.brokerage(2000), call.bank(2000), call.roth_401k(2000)],
        )


class TestServiceIntegration(unittest.TestCase):
    """Test integration between services and Person class"""

    def setUp(self):
        self.model = LifeModel(3)
        self.family = Family(self.model, "Test Family")
        self.spending = Spending(self.model, base=40000)
        self.person = Person(self.family, "Integration Test", 40, 67, self.spending)

        # Add accounts
        self.bank = BankAccount(self.person, "Test Bank", balance=15000)

        self.salary = Salary(self.model, base=80000)
        self.job = Job(self.person, "Test Corp", "Manager", self.salary)
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


if __name__ == "__main__":
    unittest.main()
