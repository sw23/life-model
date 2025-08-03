# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from unittest.mock import Mock
from ..account.brokerage import BrokerageAccount
from ..people.person import Person


class TestBrokerage(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create a mock person with required attributes
        self.mock_person = Mock(spec=Person)
        self.mock_person.model = Mock()

        # Create a brokerage account for testing
        self.brokerage = BrokerageAccount(
            person=self.mock_person,
            company="Test Brokerage",
            balance=10000.0,
            growth_rate=7.0
        )

    def test_init_default_values(self):
        """Test BrokerageAccount initialization with default values."""
        brokerage = BrokerageAccount(self.mock_person, "Default Brokerage")

        self.assertEqual(brokerage.person, self.mock_person)
        self.assertEqual(brokerage.company, "Default Brokerage")
        self.assertEqual(brokerage.balance, 0)
        self.assertEqual(brokerage.growth_rate, 7.0)
        self.assertEqual(brokerage.investments, [])

    def test_init_custom_values(self):
        """Test BrokerageAccount initialization with custom values."""
        self.assertEqual(self.brokerage.person, self.mock_person)
        self.assertEqual(self.brokerage.company, "Test Brokerage")
        self.assertEqual(self.brokerage.balance, 10000.0)
        self.assertEqual(self.brokerage.growth_rate, 7.0)
        self.assertEqual(self.brokerage.investments, [])

    def test_calculate_growth(self):
        """Test growth calculation."""
        expected_growth = 10000.0 * (7.0 / 100)
        self.assertEqual(self.brokerage.calculate_growth(), expected_growth)

        # Test with zero balance
        zero_balance_brokerage = BrokerageAccount(self.mock_person, "Zero", 0, 5.0)
        self.assertEqual(zero_balance_brokerage.calculate_growth(), 0)

        # Test with zero growth rate
        zero_growth_brokerage = BrokerageAccount(self.mock_person, "Zero Growth", 1000, 0)
        self.assertEqual(zero_growth_brokerage.calculate_growth(), 0)

    def test_get_balance(self):
        """Test balance retrieval."""
        self.assertEqual(self.brokerage.get_balance(), 10000.0)

        # Change balance and test again
        self.brokerage.balance = 15000.0
        self.assertEqual(self.brokerage.get_balance(), 15000.0)

    def test_deposit_valid_amount(self):
        """Test depositing valid amounts."""
        initial_balance = self.brokerage.balance

        # Test positive deposit
        result = self.brokerage.deposit(5000.0)
        self.assertTrue(result)
        self.assertEqual(self.brokerage.balance, initial_balance + 5000.0)

        # Test zero deposit
        initial_balance = self.brokerage.balance
        result = self.brokerage.deposit(0)
        self.assertTrue(result)
        self.assertEqual(self.brokerage.balance, initial_balance)

    def test_deposit_negative_amount(self):
        """Test depositing negative amounts should raise ValueError."""
        initial_balance = self.brokerage.balance

        # Negative deposits should raise ValueError
        with self.assertRaises(ValueError):
            self.brokerage.deposit(-1000.0)

        # Balance should remain unchanged
        self.assertEqual(self.brokerage.balance, initial_balance)

    def test_withdraw_valid_amount(self):
        """Test withdrawing valid amounts within balance."""
        initial_balance = self.brokerage.balance

        # Test partial withdrawal
        withdrawal_amount = self.brokerage.withdraw(3000.0)
        self.assertEqual(withdrawal_amount, 3000.0)
        self.assertEqual(self.brokerage.balance, initial_balance - 3000.0)

        # Test zero withdrawal
        initial_balance = self.brokerage.balance
        withdrawal_amount = self.brokerage.withdraw(0)
        self.assertEqual(withdrawal_amount, 0)
        self.assertEqual(self.brokerage.balance, initial_balance)

    def test_withdraw_exceeds_balance(self):
        """Test withdrawing more than available balance."""
        initial_balance = self.brokerage.balance

        # Try to withdraw more than available
        withdrawal_amount = self.brokerage.withdraw(15000.0)
        self.assertEqual(withdrawal_amount, initial_balance)  # Should only withdraw available amount
        self.assertEqual(self.brokerage.balance, 0)  # Balance should be zero

    def test_withdraw_exact_balance(self):
        """Test withdrawing exact balance amount."""
        initial_balance = self.brokerage.balance

        withdrawal_amount = self.brokerage.withdraw(initial_balance)
        self.assertEqual(withdrawal_amount, initial_balance)
        self.assertEqual(self.brokerage.balance, 0)

    def test_withdraw_negative_amount(self):
        """Test withdrawing negative amounts."""
        initial_balance = self.brokerage.balance

        # Negative withdrawal should return 0 and not change balance
        withdrawal_amount = self.brokerage.withdraw(-1000.0)
        self.assertEqual(withdrawal_amount, 0)
        self.assertEqual(self.brokerage.balance, initial_balance)

    def test_multiple_transactions(self):
        """Test multiple deposits and withdrawals."""
        initial_balance = 5000.0
        brokerage = BrokerageAccount(self.mock_person, "Multi Test", initial_balance, 5.0)

        # Sequence of transactions
        brokerage.deposit(2000.0)  # 7000
        self.assertEqual(brokerage.balance, 7000.0)

        withdrawn = brokerage.withdraw(1500.0)  # 5500
        self.assertEqual(withdrawn, 1500.0)
        self.assertEqual(brokerage.balance, 5500.0)

        brokerage.deposit(3000.0)  # 8500
        self.assertEqual(brokerage.balance, 8500.0)

    def test_repr_html(self):
        """Test HTML representation."""
        html = self.brokerage._repr_html_()

        self.assertIn("Test Brokerage", html)
        self.assertIn("$10,000.00", html)
        self.assertIn("7.0%", html)
        self.assertIn("<ul>", html)
        self.assertIn("</ul>", html)

    def test_repr_html_formatting(self):
        """Test HTML representation with different values and special characters."""
        # Test with HTML special characters that should be escaped
        brokerage = BrokerageAccount(
            self.mock_person,
            'Test & Co <script>alert("XSS")</script>',
            1234567.89,
            12.5
        )
        html = brokerage._repr_html_()

        # Check that dangerous characters are escaped
        self.assertIn("Test &amp; Co", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&quot;XSS&quot;", html)
        self.assertNotIn("<script>", html)  # Should not contain unescaped script tags
        self.assertNotIn("</script>", html)  # Should not contain unescaped closing script tags

        # Check formatting
        self.assertIn("$1,234,567.89", html)  # Should be formatted with commas
        self.assertIn("12.5%", html)

    def test_html_escaping_comprehensive(self):
        """Test comprehensive HTML escaping for various problematic characters."""
        test_cases = [
            ('Ampersand & Co', 'Ampersand &amp; Co'),
            ('<script>Company</script>', '&lt;script&gt;Company&lt;/script&gt;'),
            ('Quote"Company', 'Quote&quot;Company'),
            ("Apostrophe's Company", "Apostrophe&#x27;s Company"),
            ('Multi & <test> "quoted"', 'Multi &amp; &lt;test&gt; &quot;quoted&quot;'),
        ]

        for input_name, expected_escaped in test_cases:
            with self.subTest(input_name=input_name):
                brokerage = BrokerageAccount(self.mock_person, input_name, 1000, 5.0)
                html_output = brokerage._repr_html_()
                self.assertIn(expected_escaped, html_output)
                # Ensure original dangerous characters are not present
                self.assertNotIn('<script>', html_output)
                self.assertNotIn('</script>', html_output)

    def test_inheritance_from_investment(self):
        """Test that BrokerageAccount properly inherits from Investment."""
        # Test that it has inherited attributes
        self.assertTrue(hasattr(self.brokerage, 'stat_growth_history'))
        self.assertTrue(hasattr(self.brokerage, 'stat_balance_history'))

        # Test that it has inherited methods
        self.assertTrue(hasattr(self.brokerage, 'apply_growth'))
        self.assertTrue(hasattr(self.brokerage, 'step'))

    def test_apply_growth_integration(self):
        """Test integration with inherited apply_growth method."""
        initial_balance = self.brokerage.balance
        expected_growth = self.brokerage.calculate_growth()

        # Apply growth using inherited method
        actual_growth = self.brokerage.apply_growth()

        self.assertEqual(actual_growth, expected_growth)
        self.assertEqual(self.brokerage.balance, initial_balance + expected_growth)
        self.assertEqual(len(self.brokerage.stat_growth_history), 1)
        self.assertEqual(self.brokerage.stat_growth_history[0], expected_growth)

    def test_step_integration(self):
        """Test integration with inherited step method."""
        initial_balance = self.brokerage.balance

        # Call step method
        self.brokerage.step()

        # Should have applied growth and recorded balance
        self.assertGreater(self.brokerage.balance, initial_balance)
        self.assertEqual(len(self.brokerage.stat_balance_history), 1)
        self.assertEqual(len(self.brokerage.stat_growth_history), 1)


if __name__ == '__main__':
    unittest.main()
