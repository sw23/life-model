# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from unittest.mock import Mock
from ..debt.student_loan import StudentLoan, StudentLoanType
from ..people.person import Person


class TestStudentLoan(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create a mock person with required attributes
        self.mock_person = Mock(spec=Person)
        self.mock_person.model = Mock()

        # Create a student loan for testing
        self.student_loan = StudentLoan(
            person=self.mock_person,
            loan_type=StudentLoanType.FEDERAL_SUBSIDIZED,
            loan_amount=25000.0,
            yearly_interest_rate=4.5,
            length_years=10,
            school_name="State University"
        )

    def test_init_default_values(self):
        """Test StudentLoan initialization with default values."""
        loan = StudentLoan(
            self.mock_person,
            StudentLoanType.PRIVATE,
            15000.0,
            6.0,
            8,
            "Private College"
        )

        self.assertEqual(loan.person, self.mock_person)
        self.assertEqual(loan.loan_type, StudentLoanType.PRIVATE)
        self.assertEqual(loan.loan_amount, 15000.0)
        self.assertEqual(loan.yearly_interest_rate, 6.0)
        self.assertEqual(loan.length_years, 8)
        self.assertEqual(loan.school_name, "Private College")
        self.assertEqual(loan.principal, 15000.0)  # Should default to loan_amount
        self.assertIsNotNone(loan.monthly_payment)  # Should be calculated

    def test_init_custom_values(self):
        """Test StudentLoan initialization with custom values."""
        custom_principal = 20000.0
        custom_payment = 300.0

        loan = StudentLoan(
            self.mock_person,
            StudentLoanType.FEDERAL_UNSUBSIDIZED,
            25000.0,
            5.0,
            12,
            "Custom University",
            principal=custom_principal,
            monthly_payment=custom_payment
        )

        self.assertEqual(loan.principal, custom_principal)
        self.assertEqual(loan.monthly_payment, custom_payment)

    def test_student_loan_type_enum(self):
        """Test StudentLoanType enum values."""
        self.assertEqual(StudentLoanType.FEDERAL_SUBSIDIZED.value, "Federal Subsidized")
        self.assertEqual(StudentLoanType.FEDERAL_UNSUBSIDIZED.value, "Federal Unsubsidized")
        self.assertEqual(StudentLoanType.PRIVATE.value, "Private")
        self.assertEqual(StudentLoanType.PLUS.value, "PLUS")

    def test_get_monthly_payment(self):
        """Test monthly payment calculation."""
        # Test with known values
        loan_amount = 20000.0
        years = 10
        rate = 5.0

        loan = StudentLoan(
            self.mock_person,
            StudentLoanType.FEDERAL_SUBSIDIZED,
            loan_amount,
            rate,
            years,
            "Test University"
        )

        # Calculate expected payment manually using loan formula
        monthly_rate = rate / (100 * 12)  # 0.004167
        num_payments = years * 12  # 120
        factor = (1 + monthly_rate) ** num_payments
        expected_payment = loan_amount * monthly_rate * factor / (factor - 1)

        self.assertAlmostEqual(loan.get_monthly_payment(), expected_payment, places=2)
        # Should also match the monthly_payment attribute
        self.assertAlmostEqual(loan.monthly_payment, expected_payment, places=2)

    def test_get_monthly_payment_zero_interest(self):
        """Test monthly payment calculation with zero interest rate."""
        loan = StudentLoan(
            self.mock_person,
            StudentLoanType.FEDERAL_SUBSIDIZED,
            24000.0,
            0.0,
            10,
            "Zero Interest School"
        )

        # With 0% interest, payment should be loan_amount / num_payments
        expected_payment = 24000.0 / (10 * 12)  # 200.0
        self.assertEqual(loan.get_monthly_payment(), expected_payment)

    def test_make_payment_normal(self):
        """Test making a normal monthly payment."""
        initial_principal = self.student_loan.principal
        monthly_payment = self.student_loan.monthly_payment

        # Calculate expected values
        monthly_interest = (self.student_loan.yearly_interest_rate / 100) * initial_principal / 12
        expected_principal_payment = monthly_payment - monthly_interest

        total_paid = self.student_loan.make_payment(monthly_payment)

        self.assertAlmostEqual(total_paid, monthly_payment, places=2)
        self.assertAlmostEqual(
            self.student_loan.principal,
            initial_principal - expected_principal_payment,
            places=2
        )

        # Check statistics tracking
        self.assertEqual(len(self.student_loan.stat_principal_payment_history), 1)
        self.assertEqual(len(self.student_loan.stat_interest_payment_history), 1)

    def test_make_payment_with_extra_principal(self):
        """Test making a payment with extra principal."""
        initial_principal = self.student_loan.principal
        monthly_payment = self.student_loan.monthly_payment
        extra_principal = 100.0

        monthly_interest = (self.student_loan.yearly_interest_rate / 100) * initial_principal / 12
        expected_principal_payment = monthly_payment - monthly_interest + extra_principal
        expected_total_payment = monthly_payment + extra_principal

        total_paid = self.student_loan.make_payment(monthly_payment, extra_principal)

        self.assertAlmostEqual(total_paid, expected_total_payment, places=2)
        self.assertAlmostEqual(
            self.student_loan.principal,
            initial_principal - expected_principal_payment,
            places=2
        )

    def test_make_payment_exceeds_balance(self):
        """Test making a payment that exceeds the remaining balance."""
        # Set a low principal balance
        self.student_loan.principal = 50.0

        # Try to make a large payment
        large_payment = 1000.0

        total_paid = self.student_loan.make_payment(large_payment)

        # Should only pay what's needed to pay off the loan
        self.assertEqual(self.student_loan.principal, 0.0)
        self.assertLessEqual(total_paid, large_payment)

    def test_make_payment_zero_amount(self):
        """Test making a zero payment."""
        initial_principal = self.student_loan.principal

        total_paid = self.student_loan.make_payment(0.0)

        # With zero payment, no money should be paid
        self.assertEqual(total_paid, 0.0)

        # Principal should grow by the unpaid interest (negative amortization)
        monthly_interest = (self.student_loan.yearly_interest_rate / 100) * initial_principal / 12
        expected_new_principal = initial_principal + monthly_interest
        self.assertAlmostEqual(self.student_loan.principal, expected_new_principal, places=2)

    def test_make_payment_negative_amount(self):
        """Test making a negative payment should raise ValueError."""
        with self.assertRaises(ValueError) as context:
            self.student_loan.make_payment(-100.0)

        self.assertIn("cannot be negative", str(context.exception).lower())

    def test_make_payment_negative_extra_principal(self):
        """Test negative extra principal should raise ValueError."""
        with self.assertRaises(ValueError) as context:
            self.student_loan.make_payment(200.0, -50.0)

        self.assertIn("cannot be negative", str(context.exception).lower())

    def test_get_interest_amount(self):
        """Test annual interest amount calculation."""
        expected_annual_interest = self.student_loan.principal * (self.student_loan.yearly_interest_rate / 100)
        actual_annual_interest = self.student_loan.get_interest_amount()

        self.assertEqual(actual_annual_interest, expected_annual_interest)

    def test_repr_html(self):
        """Test HTML representation."""
        html = self.student_loan._repr_html_()

        self.assertIn("Federal Subsidized", html)
        self.assertIn("State University", html)
        self.assertIn("$25,000.00", html)  # Loan amount
        self.assertIn("4.5%", html)        # Interest rate
        self.assertIn("<ul>", html)
        self.assertIn("</ul>", html)

    def test_repr_html_escaping(self):
        """Test HTML representation with special characters."""
        loan = StudentLoan(
            self.mock_person,
            StudentLoanType.PRIVATE,
            10000.0,
            5.0,
            10,
            'Evil University & Co <script>alert("XSS")</script>'
        )
        html = loan._repr_html_()

        # Check that dangerous characters are escaped
        self.assertIn("Evil University &amp; Co", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&quot;XSS&quot;", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("</script>", html)

    def test_statistics_initialization(self):
        """Test that statistics tracking lists are properly initialized."""
        self.assertEqual(self.student_loan.stat_principal_payment_history, [])
        self.assertEqual(self.student_loan.stat_interest_payment_history, [])
        self.assertEqual(self.student_loan.stat_balance_history, [])

    def test_inheritance_from_loan(self):
        """Test that StudentLoan properly inherits from Loan base class."""
        # Test that it has inherited attributes
        self.assertTrue(hasattr(self.student_loan, 'stat_principal_payment_history'))
        self.assertTrue(hasattr(self.student_loan, 'stat_interest_payment_history'))
        self.assertTrue(hasattr(self.student_loan, 'stat_balance_history'))

        # Test that it has inherited methods
        self.assertTrue(hasattr(self.student_loan, 'get_interest_amount'))
        self.assertTrue(hasattr(self.student_loan, 'step'))
        self.assertTrue(hasattr(self.student_loan, 'calculate_monthly_payment'))

    def test_multiple_payments(self):
        """Test making multiple payments over time."""
        initial_principal = self.student_loan.principal
        monthly_payment = self.student_loan.monthly_payment

        # Make 12 payments
        for _ in range(12):
            self.student_loan.make_payment(monthly_payment)

        # Principal should have decreased
        self.assertLess(self.student_loan.principal, initial_principal)

        # Should have 12 payment records
        self.assertEqual(len(self.student_loan.stat_principal_payment_history), 12)
        self.assertEqual(len(self.student_loan.stat_interest_payment_history), 12)

    def test_edge_case_high_interest_rate(self):
        """Test with extremely high interest rate."""
        high_rate_loan = StudentLoan(
            self.mock_person,
            StudentLoanType.PRIVATE,
            10000.0,
            25.0,  # 25% APR
            5,
            "Expensive School"
        )

        monthly_interest = (25.0 / 100) * 10000.0 / 12
        self.assertGreater(monthly_interest, 0)
        self.assertGreater(high_rate_loan.monthly_payment, monthly_interest)

    def test_edge_case_short_term_loan(self):
        """Test with very short loan term."""
        short_loan = StudentLoan(
            self.mock_person,
            StudentLoanType.FEDERAL_SUBSIDIZED,
            5000.0,
            3.0,
            1,  # 1 year
            "Quick Degree"
        )

        # Payment should be higher for shorter term
        self.assertGreater(short_loan.monthly_payment, self.student_loan.monthly_payment)

    def test_loan_types_with_different_scenarios(self):
        """Test different loan types with realistic scenarios."""
        # Federal Subsidized (typically lower rates, same amount for fair comparison)
        fed_sub = StudentLoan(
            self.mock_person,
            StudentLoanType.FEDERAL_SUBSIDIZED,
            15000.0,  # Same amount for comparison
            3.73,     # 2023-2024 rate
            10,
            "Public University"
        )

        # Federal Unsubsidized (slightly higher rates, same amount)
        fed_unsub = StudentLoan(
            self.mock_person,
            StudentLoanType.FEDERAL_UNSUBSIDIZED,
            15000.0,  # Same amount for comparison
            5.28,     # 2023-2024 rate
            10,
            "Public University"
        )

        # Private loan (typically highest rates, same amount)
        private = StudentLoan(
            self.mock_person,
            StudentLoanType.PRIVATE,
            15000.0,  # Same amount for comparison
            8.5,      # Higher private rate
            10,
            "Private University"
        )

        # Verify payment amounts make sense relative to rates
        # With same loan amounts and terms, higher rates should mean higher payments
        self.assertLess(fed_sub.monthly_payment, fed_unsub.monthly_payment)
        self.assertLess(fed_unsub.monthly_payment, private.monthly_payment)

        # Test that all loan types are properly created
        self.assertEqual(fed_sub.loan_type, StudentLoanType.FEDERAL_SUBSIDIZED)
        self.assertEqual(fed_unsub.loan_type, StudentLoanType.FEDERAL_UNSUBSIDIZED)
        self.assertEqual(private.loan_type, StudentLoanType.PRIVATE)


if __name__ == '__main__':
    unittest.main()
