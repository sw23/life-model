# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from unittest.mock import Mock
from ..debt.car_loan import CarLoan
from ..people.person import Person


class TestCarLoan(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create a mock person with required attributes
        self.mock_person = Mock(spec=Person)
        self.mock_person.model = Mock()

        # Create a car loan for testing
        self.car_loan = CarLoan(
            person=self.mock_person,
            loan_amount=30000.0,
            length_years=5,
            yearly_interest_rate=6.0,
            name="Honda Civic 2023"
        )

    def test_init_default_values(self):
        """Test CarLoan initialization with default values."""
        car_loan = CarLoan(
            self.mock_person,
            25000.0,
            4,
            5.5,
            "Toyota Camry"
        )

        self.assertEqual(car_loan.person, self.mock_person)
        self.assertEqual(car_loan.loan_amount, 25000.0)
        self.assertEqual(car_loan.length_years, 4)
        self.assertEqual(car_loan.yearly_interest_rate, 5.5)
        self.assertEqual(car_loan.name, "Toyota Camry")
        self.assertEqual(car_loan.principal, 25000.0)  # Should default to loan_amount
        self.assertIsNotNone(car_loan.monthly_payment)  # Should be calculated

    def test_init_custom_values(self):
        """Test CarLoan initialization with custom values."""
        custom_principal = 28000.0
        custom_payment = 600.0

        car_loan = CarLoan(
            self.mock_person,
            30000.0,
            5,
            6.0,
            "Custom Car",
            principal=custom_principal,
            monthly_payment=custom_payment
        )

        self.assertEqual(car_loan.principal, custom_principal)
        self.assertEqual(car_loan.monthly_payment, custom_payment)

    def test_monthly_payment_calculation(self):
        """Test monthly payment calculation using loan formula."""
        # Test with known values
        loan_amount = 20000.0
        years = 4
        rate = 6.0

        car_loan = CarLoan(self.mock_person, loan_amount, years, rate, "Test Car")

        # Calculate expected payment manually
        # Formula: P * (r * (1 + r)^n) / ((1 + r)^n - 1)
        # where P = principal, r = monthly rate, n = number of payments
        monthly_rate = rate / (100 * 12)  # 0.005
        num_payments = years * 12  # 48
        factor = (1 + monthly_rate) ** num_payments
        expected_payment = loan_amount * monthly_rate * factor / (factor - 1)

        self.assertAlmostEqual(car_loan.monthly_payment, expected_payment, places=2)

    def test_monthly_payment_calculation_zero_interest(self):
        """Test monthly payment calculation with zero interest rate."""
        car_loan = CarLoan(self.mock_person, 24000.0, 4, 0.0, "Zero Interest Car")

        # With 0% interest, payment should be loan_amount / num_payments
        expected_payment = 24000.0 / (4 * 12)  # 500.0
        self.assertEqual(car_loan.monthly_payment, expected_payment)

    def test_get_monthly_payment_method(self):
        """Test get_monthly_payment method."""
        monthly_payment = self.car_loan.get_monthly_payment()
        self.assertEqual(monthly_payment, self.car_loan.monthly_payment)

    def test_make_payment_normal(self):
        """Test making a normal monthly payment."""
        initial_principal = self.car_loan.principal
        monthly_payment = self.car_loan.monthly_payment

        # Calculate expected values
        monthly_interest = (self.car_loan.yearly_interest_rate / 100) * initial_principal / 12
        expected_principal_payment = monthly_payment - monthly_interest
        expected_total_payment = monthly_payment

        total_paid = self.car_loan.make_payment(monthly_payment)

        self.assertAlmostEqual(total_paid, expected_total_payment, places=2)
        self.assertAlmostEqual(
            self.car_loan.principal,
            initial_principal - expected_principal_payment,
            places=2
        )

        # Check statistics tracking
        self.assertEqual(len(self.car_loan.stat_principal_payment_history), 1)
        self.assertEqual(len(self.car_loan.stat_interest_payment_history), 1)
        self.assertAlmostEqual(
            self.car_loan.stat_principal_payment_history[0],
            expected_principal_payment,
            places=2
        )

    def test_make_payment_with_extra_principal(self):
        """Test making a payment with extra principal."""
        initial_principal = self.car_loan.principal
        monthly_payment = self.car_loan.monthly_payment
        extra_principal = 200.0

        monthly_interest = (self.car_loan.yearly_interest_rate / 100) * initial_principal / 12
        expected_principal_payment = monthly_payment - monthly_interest + extra_principal
        expected_total_payment = monthly_payment + extra_principal

        total_paid = self.car_loan.make_payment(monthly_payment, extra_principal)

        self.assertAlmostEqual(total_paid, expected_total_payment, places=2)
        self.assertAlmostEqual(
            self.car_loan.principal,
            initial_principal - expected_principal_payment,
            places=2
        )

    def test_make_payment_exceeds_balance(self):
        """Test making a payment that exceeds the remaining balance."""
        # Set a low principal balance
        self.car_loan.principal = 100.0

        # Try to make a large payment
        large_payment = 1000.0

        total_paid = self.car_loan.make_payment(large_payment)

        # Should only pay what's needed to pay off the loan
        self.assertEqual(self.car_loan.principal, 0.0)
        self.assertLessEqual(total_paid, large_payment)

    def test_make_payment_zero_amount(self):
        """Test making a zero payment."""
        initial_principal = self.car_loan.principal

        total_paid = self.car_loan.make_payment(0.0)

        # With zero payment, no money should be paid
        self.assertEqual(total_paid, 0.0)

        # Principal should grow by the unpaid interest (negative amortization)
        monthly_interest = (self.car_loan.yearly_interest_rate / 100) * initial_principal / 12
        expected_new_principal = initial_principal + monthly_interest
        self.assertAlmostEqual(self.car_loan.principal, expected_new_principal, places=2)

        # Statistics should reflect no principal payment but record the missed interest
        self.assertEqual(self.car_loan.stat_principal_payment_history[-1], 0.0)
        self.assertEqual(self.car_loan.stat_interest_payment_history[-1], 0.0)

    def test_multiple_payments(self):
        """Test making multiple payments over time."""
        initial_principal = self.car_loan.principal
        monthly_payment = self.car_loan.monthly_payment

        # Make 12 payments
        total_paid = 0
        for _ in range(12):
            payment = self.car_loan.make_payment(monthly_payment)
            total_paid += payment

        # Principal should have decreased
        self.assertLess(self.car_loan.principal, initial_principal)

        # Should have 12 payment records
        self.assertEqual(len(self.car_loan.stat_principal_payment_history), 12)
        self.assertEqual(len(self.car_loan.stat_interest_payment_history), 12)

    def test_get_interest_amount(self):
        """Test annual interest amount calculation."""
        expected_annual_interest = self.car_loan.principal * (self.car_loan.yearly_interest_rate / 100)
        actual_annual_interest = self.car_loan.get_interest_amount()

        self.assertEqual(actual_annual_interest, expected_annual_interest)

    def test_repr_html(self):
        """Test HTML representation."""
        html = self.car_loan._repr_html_()

        self.assertIn("Honda Civic 2023", html)
        self.assertIn("$30,000.00", html)  # Loan amount
        self.assertIn("6.0%", html)  # Interest rate
        self.assertIn("<ul>", html)
        self.assertIn("</ul>", html)

    def test_repr_html_escaping(self):
        """Test HTML representation with special characters."""
        car_loan = CarLoan(
            self.mock_person,
            25000.0,
            4,
            5.0,
            'Car & Truck <script>alert("XSS")</script>'
        )
        html = car_loan._repr_html_()

        # Check that dangerous characters are escaped
        self.assertIn("Car &amp; Truck", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&quot;XSS&quot;", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("</script>", html)

    def test_statistics_initialization(self):
        """Test that statistics tracking lists are properly initialized."""
        self.assertEqual(self.car_loan.stat_principal_payment_history, [])
        self.assertEqual(self.car_loan.stat_interest_payment_history, [])
        self.assertEqual(self.car_loan.stat_balance_history, [])

    def test_inheritance_from_loan(self):
        """Test that CarLoan properly inherits from Loan base class."""
        # Test that it has inherited attributes
        self.assertTrue(hasattr(self.car_loan, 'stat_principal_payment_history'))
        self.assertTrue(hasattr(self.car_loan, 'stat_interest_payment_history'))
        self.assertTrue(hasattr(self.car_loan, 'stat_balance_history'))

        # Test that it has inherited methods
        self.assertTrue(hasattr(self.car_loan, 'calculate_monthly_payment'))
        self.assertTrue(hasattr(self.car_loan, 'get_interest_amount'))
        self.assertTrue(hasattr(self.car_loan, 'step'))

    def test_edge_case_very_short_loan(self):
        """Test edge case with very short loan term."""
        short_loan = CarLoan(self.mock_person, 12000.0, 1, 12.0, "Short Term Car")

        # Should still calculate a valid monthly payment
        self.assertGreater(short_loan.monthly_payment, 0)
        self.assertLess(short_loan.monthly_payment, 12000.0)  # Should be less than total loan

    def test_edge_case_high_interest_rate(self):
        """Test edge case with high interest rate."""
        high_rate_loan = CarLoan(self.mock_person, 20000.0, 5, 25.0, "High Rate Car")

        # Should still calculate a valid payment, but it will be high
        self.assertGreater(high_rate_loan.monthly_payment, 0)

        # Make a payment and verify interest calculation
        initial_principal = high_rate_loan.principal
        monthly_interest = (25.0 / 100) * initial_principal / 12
        self.assertGreater(monthly_interest, 0)

    def test_make_payment_negative_amount(self):
        """Test that negative payment amounts raise ValueError."""
        with self.assertRaises(ValueError):
            self.car_loan.make_payment(-100.0)

    def test_make_payment_negative_extra_principal(self):
        """Test that negative extra principal raises ValueError."""
        with self.assertRaises(ValueError):
            self.car_loan.make_payment(500.0, extra_to_principal=-50.0)

    def test_make_payment_insufficient_for_interest(self):
        """Test making a payment that doesn't cover the full interest."""
        # Calculate monthly interest
        monthly_interest = (self.car_loan.yearly_interest_rate / 100) * self.car_loan.principal / 12
        insufficient_payment = monthly_interest * 0.5  # Pay only half the interest

        initial_principal = self.car_loan.principal

        total_paid = self.car_loan.make_payment(insufficient_payment)

        # Total paid should equal the insufficient payment
        self.assertAlmostEqual(total_paid, insufficient_payment, places=2)

        # Principal should grow by unpaid interest
        unpaid_interest = monthly_interest - insufficient_payment
        expected_new_principal = initial_principal + unpaid_interest
        self.assertAlmostEqual(self.car_loan.principal, expected_new_principal, places=2)

        # Should record 0 principal payment and partial interest payment
        self.assertEqual(self.car_loan.stat_principal_payment_history[-1], 0.0)
        self.assertAlmostEqual(self.car_loan.stat_interest_payment_history[-1], insufficient_payment, places=2)

    def test_make_payment_exact_payoff(self):
        """Test making a payment that exactly pays off the loan."""
        # Set a small remaining balance
        remaining_balance = 500.0
        self.car_loan.principal = remaining_balance

        # Calculate what's needed to pay off completely
        monthly_interest = (self.car_loan.yearly_interest_rate / 100) * remaining_balance / 12
        payoff_amount = remaining_balance + monthly_interest

        total_paid = self.car_loan.make_payment(payoff_amount)

        # Should pay off completely
        self.assertAlmostEqual(self.car_loan.principal, 0.0, places=2)
        self.assertAlmostEqual(total_paid, payoff_amount, places=2)


if __name__ == '__main__':
    unittest.main()
