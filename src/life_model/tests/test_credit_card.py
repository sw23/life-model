# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from unittest.mock import Mock
from ..debt.credit_card import CreditCard, CreditCardType
from ..people.person import Person


class TestCreditCard(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create a mock person with required attributes
        self.mock_person = Mock(spec=Person)
        self.mock_person.model = Mock()

        # Create a credit card for testing
        self.credit_card = CreditCard(
            person=self.mock_person,
            card_name="Chase Sapphire",
            credit_limit=10000.0,
            current_balance=2000.0,
            yearly_interest_rate=18.0,
            minimum_payment_percent=2.0
        )

    def test_init_default_values(self):
        """Test CreditCard initialization with default values."""
        card = CreditCard(
            self.mock_person,
            "Basic Card",
            5000.0
        )

        self.assertEqual(card.person, self.mock_person)
        self.assertEqual(card.card_name, "Basic Card")
        self.assertEqual(card.credit_limit, 5000.0)
        self.assertEqual(card.principal, 0.0)  # Should default to 0
        self.assertEqual(card.yearly_interest_rate, 18.0)  # Default
        self.assertEqual(card.minimum_payment_percent, 2.0)  # Default

    def test_init_custom_values(self):
        """Test CreditCard initialization with custom values."""
        self.assertEqual(self.credit_card.card_name, "Chase Sapphire")
        self.assertEqual(self.credit_card.credit_limit, 10000.0)
        self.assertEqual(self.credit_card.principal, 2000.0)
        self.assertEqual(self.credit_card.yearly_interest_rate, 18.0)
        self.assertEqual(self.credit_card.minimum_payment_percent, 2.0)

    def test_get_available_credit(self):
        """Test available credit calculation."""
        expected_available = 10000.0 - 2000.0  # 8000.0
        self.assertEqual(self.credit_card.get_available_credit(), expected_available)

        # Test with zero balance
        zero_balance_card = CreditCard(self.mock_person, "Zero Card", 5000.0, 0.0)
        self.assertEqual(zero_balance_card.get_available_credit(), 5000.0)

        # Test with max balance
        max_balance_card = CreditCard(self.mock_person, "Max Card", 3000.0, 3000.0)
        self.assertEqual(max_balance_card.get_available_credit(), 0.0)

    def test_get_available_credit_over_limit(self):
        """Test available credit when balance exceeds limit."""
        over_limit_card = CreditCard(self.mock_person, "Over Limit", 1000.0, 1200.0)
        # Should return 0, not negative
        self.assertEqual(over_limit_card.get_available_credit(), 0.0)

    def test_charge_successful(self):
        """Test successful charge within credit limit."""
        initial_balance = self.credit_card.principal
        charge_amount = 500.0

        result = self.credit_card.charge(charge_amount)

        self.assertTrue(result)
        self.assertEqual(self.credit_card.principal, initial_balance + charge_amount)

    def test_charge_at_limit(self):
        """Test charging exactly to the credit limit."""
        available_credit = self.credit_card.get_available_credit()

        result = self.credit_card.charge(available_credit)

        self.assertTrue(result)
        self.assertEqual(self.credit_card.principal, self.credit_card.credit_limit)
        self.assertEqual(self.credit_card.get_available_credit(), 0.0)

    def test_charge_exceeds_limit(self):
        """Test charging more than available credit."""
        initial_balance = self.credit_card.principal
        available_credit = self.credit_card.get_available_credit()
        excessive_charge = available_credit + 100.0

        result = self.credit_card.charge(excessive_charge)

        self.assertFalse(result)
        self.assertEqual(self.credit_card.principal, initial_balance)  # Balance unchanged

    def test_charge_zero_amount(self):
        """Test charging zero amount."""
        initial_balance = self.credit_card.principal

        result = self.credit_card.charge(0.0)

        self.assertTrue(result)  # Should succeed
        self.assertEqual(self.credit_card.principal, initial_balance)  # Balance unchanged

    def test_charge_negative_amount(self):
        """Test charging negative amount should raise ValueError."""
        initial_balance = self.credit_card.principal

        with self.assertRaises(ValueError) as context:
            self.credit_card.charge(-100.0)

        self.assertIn("Cannot charge negative amounts", str(context.exception))
        # Balance should remain unchanged
        self.assertEqual(self.credit_card.principal, initial_balance)

    def test_get_minimum_payment(self):
        """Test minimum payment calculation."""
        # 2% of 2000 = 40, but minimum is $25
        expected_minimum = 2000.0 * 0.02  # 40.0
        self.assertEqual(self.credit_card.get_minimum_payment(), expected_minimum)

        # Test with low balance where minimum $25 applies
        low_balance_card = CreditCard(self.mock_person, "Low Balance", 1000.0, 100.0, 18.0, 2.0)
        self.assertEqual(low_balance_card.get_minimum_payment(), 25.0)  # 2% of 100 = 2, but min is 25

    def test_get_minimum_payment_zero_balance(self):
        """Test minimum payment with zero balance."""
        zero_balance_card = CreditCard(self.mock_person, "Zero", 1000.0, 0.0)
        self.assertEqual(zero_balance_card.get_minimum_payment(), 0.0)  # No payment required when balance is zero

    def test_make_payment_normal(self):
        """Test making a normal payment."""
        initial_balance = self.credit_card.principal
        payment_amount = 300.0

        # Calculate expected values
        monthly_interest = (self.credit_card.yearly_interest_rate / 100) * initial_balance / 12
        expected_principal_payment = payment_amount - monthly_interest

        total_paid = self.credit_card.make_payment(payment_amount)

        self.assertAlmostEqual(total_paid, payment_amount, places=2)
        self.assertAlmostEqual(
            self.credit_card.principal,
            initial_balance - expected_principal_payment,
            places=2
        )

    def test_make_payment_with_extra_principal(self):
        """Test making a payment with extra principal."""
        initial_balance = self.credit_card.principal
        payment_amount = 200.0
        extra_principal = 100.0

        monthly_interest = (self.credit_card.yearly_interest_rate / 100) * initial_balance / 12
        expected_principal_payment = payment_amount - monthly_interest + extra_principal
        expected_total_payment = payment_amount + extra_principal

        total_paid = self.credit_card.make_payment(payment_amount, extra_principal)

        self.assertAlmostEqual(total_paid, expected_total_payment, places=2)
        self.assertAlmostEqual(
            self.credit_card.principal,
            initial_balance - expected_principal_payment,
            places=2
        )

    def test_make_payment_pays_off_card(self):
        """Test making a payment that pays off the entire balance."""
        # Calculate payment needed to pay off completely
        monthly_interest = (self.credit_card.yearly_interest_rate / 100) * self.credit_card.principal / 12
        payoff_amount = self.credit_card.principal + monthly_interest

        total_paid = self.credit_card.make_payment(payoff_amount)

        self.assertAlmostEqual(self.credit_card.principal, 0.0, places=2)
        self.assertAlmostEqual(total_paid, payoff_amount, places=2)

    def test_make_payment_exceeds_balance(self):
        """Test making a payment larger than the balance."""
        initial_balance = self.credit_card.principal
        large_payment = initial_balance + 1000.0

        total_paid = self.credit_card.make_payment(large_payment)

        # Should pay off completely but not more
        self.assertAlmostEqual(self.credit_card.principal, 0.0, places=2)
        self.assertLessEqual(total_paid, large_payment)

    def test_make_payment_zero_amount(self):
        """Test making a zero payment."""
        initial_balance = self.credit_card.principal

        total_paid = self.credit_card.make_payment(0.0)

        # With zero payment, no payment should be processed
        self.assertEqual(total_paid, 0.0)
        # Balance should remain unchanged
        self.assertEqual(self.credit_card.principal, initial_balance)

    def test_get_interest_amount(self):
        """Test annual interest calculation."""
        expected_annual_interest = self.credit_card.principal * (self.credit_card.yearly_interest_rate / 100)
        actual_annual_interest = self.credit_card.get_interest_amount()

        self.assertEqual(actual_annual_interest, expected_annual_interest)

    def test_multiple_charges_and_payments(self):
        """Test multiple charges and payments over time."""
        initial_balance = self.credit_card.principal

        # Make some charges
        self.credit_card.charge(100.0)
        self.credit_card.charge(200.0)
        expected_balance = initial_balance + 300.0
        self.assertEqual(self.credit_card.principal, expected_balance)

        # Make a payment
        payment = 150.0
        monthly_interest = (self.credit_card.yearly_interest_rate / 100) * expected_balance / 12
        expected_principal_payment = payment - monthly_interest

        self.credit_card.make_payment(payment)
        self.assertAlmostEqual(
            self.credit_card.principal,
            expected_balance - expected_principal_payment,
            places=2
        )

    def test_repr_html(self):
        """Test HTML representation."""
        html = self.credit_card._repr_html_()

        self.assertIn("Chase Sapphire", html)
        self.assertIn("$10,000.00", html)  # Credit limit
        self.assertIn("$2,000.00", html)   # Current balance
        self.assertIn("$8,000.00", html)   # Available credit
        self.assertIn("18.0%", html)       # Interest rate
        self.assertIn("<ul>", html)
        self.assertIn("</ul>", html)

    def test_repr_html_escaping(self):
        """Test HTML representation with special characters."""
        card = CreditCard(
            self.mock_person,
            'Evil Bank & Co <script>alert("XSS")</script>',
            5000.0,
            1000.0
        )
        html = card._repr_html_()

        # Check that dangerous characters are escaped
        self.assertIn("Evil Bank &amp; Co", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&quot;XSS&quot;", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("</script>", html)

    def test_statistics_initialization(self):
        """Test that statistics tracking lists are properly initialized."""
        self.assertEqual(self.credit_card.stat_principal_payment_history, [])
        self.assertEqual(self.credit_card.stat_interest_payment_history, [])
        self.assertEqual(self.credit_card.stat_balance_history, [])

    def test_inheritance_from_loan(self):
        """Test that CreditCard properly inherits from Loan base class."""
        # Test that it has inherited attributes
        self.assertTrue(hasattr(self.credit_card, 'stat_principal_payment_history'))
        self.assertTrue(hasattr(self.credit_card, 'stat_interest_payment_history'))
        self.assertTrue(hasattr(self.credit_card, 'stat_balance_history'))

        # Test that it has inherited methods
        self.assertTrue(hasattr(self.credit_card, 'get_interest_amount'))
        self.assertTrue(hasattr(self.credit_card, 'step'))

    def test_credit_card_type_enum(self):
        """Test CreditCardType enum values."""
        self.assertEqual(CreditCardType.VISA.value, "Visa")
        self.assertEqual(CreditCardType.MASTERCARD.value, "MasterCard")
        self.assertEqual(CreditCardType.AMERICAN_EXPRESS.value, "American Express")
        self.assertEqual(CreditCardType.DISCOVER.value, "Discover")
        self.assertEqual(CreditCardType.STORE_CARD.value, "Store Card")

    def test_edge_case_high_interest_rate(self):
        """Test with extremely high interest rate."""
        high_rate_card = CreditCard(self.mock_person, "Loan Shark", 1000.0, 500.0, 35.0)

        monthly_interest = (35.0 / 100) * 500.0 / 12
        self.assertGreater(monthly_interest, 0)

        # Minimum payment might not even cover interest
        min_payment = high_rate_card.get_minimum_payment()
        self.assertGreater(min_payment, 0)

    def test_edge_case_zero_interest(self):
        """Test with zero interest rate."""
        zero_rate_card = CreditCard(self.mock_person, "Promo Card", 1000.0, 500.0, 0.0)

        payment = 100.0
        initial_balance = zero_rate_card.principal

        total_paid = zero_rate_card.make_payment(payment)

        # With 0% interest, entire payment should go to principal
        self.assertEqual(total_paid, payment)
        self.assertEqual(zero_rate_card.principal, initial_balance - payment)


if __name__ == '__main__':
    unittest.main()
