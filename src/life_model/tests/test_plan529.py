# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from unittest.mock import Mock
from ..dependents.plan529 import Plan529
from ..dependents.child import Child
from ..people.person import Person
from ..model import LifeModel


class TestPlan529(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create a real LifeModel instance for proper mesa.Agent compatibility
        self.model = LifeModel(start_year=2025, end_year=2050)

        # Create a mock person with required attributes
        self.mock_person = Mock(spec=Person)
        self.mock_person.model = self.model
        self.mock_person.unique_id = 1

        # Create a mock child
        self.mock_child = Mock(spec=Child)
        self.mock_child.name = "Test Child"
        self.mock_child.birth_year = 2020
        self.mock_child.model = self.model

        # Create a 529 plan for testing
        self.plan = Plan529(
            owner=self.mock_person,
            beneficiary=self.mock_child,
            balance=10000.0,
            state='NY',
            growth_rate=7.0
        )

    def test_init_default_values(self):
        """Test Plan529 initialization with default values."""
        plan = Plan529(self.mock_person)

        self.assertEqual(plan.person, self.mock_person)
        self.assertIsNone(plan.beneficiary)
        self.assertEqual(plan.balance, 0)
        self.assertEqual(plan.state, 'NY')
        self.assertEqual(plan.growth_rate, 7.0)
        self.assertEqual(plan.total_contributions, 0)
        self.assertEqual(plan.total_earnings, 0)

    def test_init_custom_values(self):
        """Test Plan529 initialization with custom values."""
        self.assertEqual(self.plan.person, self.mock_person)
        self.assertEqual(self.plan.beneficiary, self.mock_child)
        self.assertEqual(self.plan.balance, 10000.0)
        self.assertEqual(self.plan.state, 'NY')
        self.assertEqual(self.plan.growth_rate, 7.0)
        self.assertEqual(self.plan.total_contributions, 10000.0)
        self.assertEqual(self.plan.total_earnings, 0)

    def test_contribute_within_limits(self):
        """Test making contributions within annual and lifetime limits."""
        initial_balance = self.plan.balance
        contribution = self.plan.contribute(5000.0)

        self.assertEqual(contribution, 5000.0)
        self.assertEqual(self.plan.balance, initial_balance + 5000.0)
        self.assertEqual(self.plan.contributions_this_year, 5000.0)
        self.assertEqual(self.plan.total_contributions, 15000.0)

    def test_contribute_exceeds_annual_limit(self):
        """Test contribution limited by annual limit."""
        plan = Plan529(self.mock_person, annual_contribution_limit=10000.0)

        # First contribution uses up most of annual limit
        plan.contribute(9000.0)

        # Second contribution should be limited
        contribution = plan.contribute(5000.0)
        self.assertEqual(contribution, 1000.0)  # Only 1000 left in annual limit
        self.assertEqual(plan.contributions_this_year, 10000.0)

    def test_contribute_exceeds_lifetime_limit(self):
        """Test contribution limited by lifetime limit."""
        plan = Plan529(
            self.mock_person,
            balance=490000.0,
            lifetime_contribution_limit=500000.0
        )

        # Try to contribute more than remaining lifetime limit
        contribution = plan.contribute(20000.0)
        self.assertEqual(contribution, 10000.0)  # Only 10000 left in lifetime limit
        self.assertEqual(plan.total_contributions, 500000.0)

    def test_contribute_zero_and_negative(self):
        """Test contributing zero or negative amounts."""
        initial_balance = self.plan.balance

        # Zero contribution
        contribution = self.plan.contribute(0)
        self.assertEqual(contribution, 0)
        self.assertEqual(self.plan.balance, initial_balance)

        # Negative contribution
        contribution = self.plan.contribute(-1000.0)
        self.assertEqual(contribution, 0)
        self.assertEqual(self.plan.balance, initial_balance)

    def test_withdraw_qualified(self):
        """Test qualified withdrawal for education expenses."""
        initial_balance = self.plan.balance

        withdrawn = self.plan.withdraw_qualified(3000.0)
        self.assertEqual(withdrawn, 3000.0)
        self.assertEqual(self.plan.balance, initial_balance - 3000.0)
        self.assertEqual(self.plan.qualified_withdrawals, 3000.0)
        self.assertEqual(self.plan.total_withdrawals, 3000.0)

    def test_withdraw_qualified_exceeds_balance(self):
        """Test qualified withdrawal exceeding balance."""
        initial_balance = self.plan.balance

        withdrawn = self.plan.withdraw_qualified(20000.0)
        self.assertEqual(withdrawn, initial_balance)
        self.assertEqual(self.plan.balance, 0)

    def test_withdraw_non_qualified(self):
        """Test non-qualified withdrawal with penalty."""
        # Set up a plan with known earnings
        self.plan.total_earnings = 2000.0
        initial_balance = self.plan.balance

        withdrawn, penalty = self.plan.withdraw_non_qualified(3000.0)

        self.assertEqual(withdrawn, 3000.0)
        self.assertEqual(self.plan.balance, initial_balance - 3000.0)
        self.assertEqual(self.plan.non_qualified_withdrawals, 3000.0)

        # Calculate expected penalty (10% of earnings portion)
        earnings_ratio = 2000.0 / initial_balance
        earnings_withdrawn = 3000.0 * earnings_ratio
        expected_penalty = earnings_withdrawn * 0.10
        self.assertAlmostEqual(penalty, expected_penalty, places=2)

    def test_withdraw_non_qualified_exceeds_balance(self):
        """Test non-qualified withdrawal exceeding balance."""
        initial_balance = self.plan.balance

        withdrawn, penalty = self.plan.withdraw_non_qualified(20000.0)
        self.assertEqual(withdrawn, initial_balance)
        self.assertEqual(self.plan.balance, 0)

    def test_get_balance(self):
        """Test balance retrieval."""
        self.assertEqual(self.plan.get_balance(), 10000.0)

        self.plan.balance = 15000.0
        self.assertEqual(self.plan.get_balance(), 15000.0)

    def test_deposit(self):
        """Test deposit via contribute method."""
        initial_balance = self.plan.balance

        result = self.plan.deposit(5000.0)
        self.assertTrue(result)
        self.assertEqual(self.plan.balance, initial_balance + 5000.0)

        # Test deposit of zero
        result = self.plan.deposit(0)
        self.assertFalse(result)

    def test_withdraw(self):
        """Test withdraw defaults to qualified withdrawal."""
        initial_balance = self.plan.balance

        withdrawn = self.plan.withdraw(3000.0)
        self.assertEqual(withdrawn, 3000.0)
        self.assertEqual(self.plan.balance, initial_balance - 3000.0)
        self.assertEqual(self.plan.qualified_withdrawals, 3000.0)

    def test_calculate_growth(self):
        """Test growth calculation."""
        # Expected growth: 10000 * (1 + 0.07)^1 - 10000 = 700
        expected_growth = 10000.0 * (1.07) - 10000.0
        calculated_growth = self.plan.calculate_growth()
        self.assertAlmostEqual(calculated_growth, expected_growth, places=2)

    def test_reset_annual_contributions(self):
        """Test resetting annual contribution tracking."""
        self.plan.contribute(5000.0)
        self.assertEqual(self.plan.contributions_this_year, 5000.0)

        self.plan.reset_annual_contributions()
        self.assertEqual(self.plan.contributions_this_year, 0)

    def test_change_beneficiary(self):
        """Test changing plan beneficiary."""
        new_child = Mock(spec=Child)
        new_child.name = "New Child"
        new_child.birth_year = 2022

        self.plan.change_beneficiary(new_child)
        self.assertEqual(self.plan.beneficiary, new_child)

        # Test changing to None
        self.plan.change_beneficiary(None)
        self.assertIsNone(self.plan.beneficiary)

    def test_repr_html(self):
        """Test HTML representation."""
        html = self.plan._repr_html_()

        self.assertIn("Test Child", html)
        self.assertIn("$10,000.00", html)
        self.assertIn("NY", html)
        self.assertIn("7.0%", html)
        self.assertIn("<ul>", html)
        self.assertIn("</ul>", html)

    def test_repr_html_no_beneficiary(self):
        """Test HTML representation without beneficiary."""
        plan = Plan529(self.mock_person, balance=5000.0)
        html = plan._repr_html_()

        self.assertIn("No beneficiary", html)
        self.assertIn("$5,000.00", html)

    def test_repr_html_escaping(self):
        """Test HTML escaping in representation."""
        mock_child_malicious = Mock(spec=Child)
        mock_child_malicious.name = '<script>alert("XSS")</script>'

        plan = Plan529(
            self.mock_person,
            beneficiary=mock_child_malicious,
            state='<test>',
            balance=1000.0
        )
        html = plan._repr_html_()

        # Check that dangerous characters are escaped
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;test&gt;", html)

    def test_pre_step(self):
        """Test pre-step phase applies growth."""
        initial_balance = self.plan.balance
        initial_earnings = self.plan.total_earnings

        self.plan.pre_step()

        # Balance should increase by growth
        # Note: calculate_growth uses current balance which changed, so recalculate
        # expected_growth = initial_balance * (1.07) - initial_balance

        self.assertGreater(self.plan.balance, initial_balance)
        self.assertGreater(self.plan.total_earnings, initial_earnings)
        self.assertEqual(len(self.plan.stat_growth_history), 1)

    def test_step(self):
        """Test step phase tracks statistics."""
        self.plan.contributions_this_year = 5000.0
        self.plan.qualified_withdrawals = 2000.0

        self.plan.step()

        self.assertEqual(self.plan.stat_529_balance, self.plan.balance)
        self.assertEqual(len(self.plan.stat_contributions_history), 1)
        self.assertEqual(self.plan.stat_contributions_history[0], 5000.0)
        self.assertEqual(len(self.plan.stat_balance_history), 1)

    def test_post_step(self):
        """Test post-step phase resets annual tracking."""
        self.plan.contributions_this_year = 5000.0
        self.plan.qualified_withdrawals = 2000.0
        self.plan.non_qualified_withdrawals = 500.0

        self.plan.post_step()

        self.assertEqual(self.plan.contributions_this_year, 0)
        self.assertEqual(self.plan.qualified_withdrawals, 0)
        self.assertEqual(self.plan.non_qualified_withdrawals, 0)

    def test_full_year_cycle(self):
        """Test a complete year cycle with contributions, growth, and withdrawals."""
        plan = Plan529(
            self.mock_person,
            beneficiary=self.mock_child,
            balance=0,
            growth_rate=7.0
        )

        # Year start: Make contributions
        plan.contribute(10000.0)
        self.assertEqual(plan.balance, 10000.0)
        self.assertEqual(plan.total_contributions, 10000.0)

        # Pre-step: Apply growth
        plan.pre_step()
        self.assertAlmostEqual(plan.balance, 10700.0, places=0)
        self.assertAlmostEqual(plan.total_earnings, 700.0, places=0)

        # Make a qualified withdrawal
        plan.withdraw_qualified(2000.0)
        self.assertAlmostEqual(plan.balance, 8700.0, places=0)

        # Step: Track stats
        plan.step()
        self.assertEqual(len(plan.stat_balance_history), 1)

        # Post-step: Reset annual tracking
        plan.post_step()
        self.assertEqual(plan.contributions_this_year, 0)

    def test_multiple_beneficiaries_scenario(self):
        """Test scenario with multiple children and 529 plans."""
        child1 = Mock(spec=Child)
        child1.name = "Child 1"
        child2 = Mock(spec=Child)
        child2.name = "Child 2"

        plan1 = Plan529(self.mock_person, beneficiary=child1, balance=20000.0)
        plan2 = Plan529(self.mock_person, beneficiary=child2, balance=15000.0)

        # Each plan should track independently
        plan1.contribute(5000.0)
        plan2.contribute(3000.0)

        self.assertEqual(plan1.balance, 25000.0)
        self.assertEqual(plan2.balance, 18000.0)

    def test_inheritance_from_investment(self):
        """Test that Plan529 properly inherits from Investment."""
        # Test that it has inherited attributes
        self.assertTrue(hasattr(self.plan, 'stat_growth_history'))
        self.assertTrue(hasattr(self.plan, 'stat_balance_history'))

        # Test that it has inherited methods
        self.assertTrue(hasattr(self.plan, 'apply_growth'))
        self.assertTrue(hasattr(self.plan, 'calculate_growth'))

    def test_registry_registration(self):
        """Test that plan registers with model registry."""
        # Verify the plan is in the registry
        registered_plans = self.model.registries.plan_529s.get_items(self.mock_person)
        self.assertIn(self.plan, registered_plans)


if __name__ == '__main__':
    unittest.main()
