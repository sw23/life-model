# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from ..model import LifeModel
from ..person import Person, Spending
from ..family import Family
from ..account.ira.roth_ira import RothIra


def setup_roth_ira(age=40):
    """Helper function to create a Roth IRA account for testing"""
    model = LifeModel()
    person = Person(family=Family(model), name='Test Person', age=age, retirement_age=65,
                    spending=Spending(model))

    # Create a bank account for the person to handle deposits and withdrawals
    from ..account.bank import BankAccount
    BankAccount(owner=person, company='Test Bank', balance=10000)

    return RothIra(
        owner=person,
        balance=25000,
        yearly_contrib_amount=4000,
        average_growth=5.5
    )


class TestRothIra(unittest.TestCase):

    def test_init(self):
        """Test initialization of Roth IRA account"""
        ira = setup_roth_ira()

        self.assertEqual(ira.balance, 25000)
        self.assertEqual(ira.yearly_contrib_amount, 4000)
        self.assertEqual(ira.average_growth, 5.5)
        self.assertEqual(ira.total_contributions, 0)  # Should start with 0 tracked contributions

    def test_contribution_limits(self):
        """Test contribution limits based on age"""
        young_ira = setup_roth_ira(age=45)
        old_ira = setup_roth_ira(age=55)

        # Younger person should have standard contribution limit
        self.assertEqual(young_ira.contribution_limit, 6500)

        # Older person should have higher contribution limit
        self.assertEqual(old_ira.contribution_limit, 7500)

    def test_growth(self):
        """Test account growth over time"""
        ira = setup_roth_ira()
        initial_balance = ira.balance

        # Apply growth
        ira.apply_growth()

        # The model uses continuous interest calculation which is slightly different from simple interest
        # Just verify that there was growth applied and the new balance is higher
        self.assertGreater(ira.balance, initial_balance)
        # Verify that growth is approximately in the expected range for 5.5% growth
        growth = ira.balance - initial_balance
        expected_min_growth = initial_balance * 0.05
        expected_max_growth = initial_balance * 0.06
        self.assertTrue(expected_min_growth <= growth <= expected_max_growth,
                        f"Growth {growth} outside expected range ({expected_min_growth}-{expected_max_growth})")

    def test_contribution(self):
        """Test yearly contribution and tracking of contributions"""
        ira = setup_roth_ira()

        # Contribute to IRA
        contributed = ira.contribute()

        # Should contribute the yearly amount (4000) since it's under the limit
        self.assertEqual(contributed, 4000)
        self.assertEqual(ira.balance, 29000)

        # Manually update total_contributions since we're bypassing pre_step
        ira.total_contributions += contributed
        self.assertEqual(ira.total_contributions, 4000)

    def test_contribution_over_limit(self):
        """Test contribution exceeding limit"""
        ira = setup_roth_ira(age=45)
        ira.yearly_contrib_amount = 8000  # Above the 6500 limit

        # Contribute to IRA
        contributed = ira.contribute()

        # Should only contribute up to the limit (6500)
        self.assertEqual(contributed, 6500)
        self.assertEqual(ira.balance, 31500)

        # Manually update total_contributions since we're bypassing pre_step
        ira.total_contributions += contributed
        self.assertEqual(ira.total_contributions, 6500)

    def test_pre_step(self):
        """Test the pre_step function with growth and contributions"""
        ira = setup_roth_ira()
        initial_balance = ira.balance

        # Run pre_step to apply growth and contributions
        ira.pre_step()

        # Verify balance has increased by both growth and contribution
        self.assertGreater(ira.balance, initial_balance)
        # The balance should have increased by approximately 4000 (contribution) plus growth
        min_expected = initial_balance + 4000 + (initial_balance * 0.05)  # Minimum with 5% growth
        max_expected = initial_balance + 4000 + (initial_balance * 0.06)  # Maximum with 6% growth
        self.assertTrue(min_expected <= ira.balance <= max_expected,
                        f"Balance {ira.balance} outside expected range ({min_expected}-{max_expected})")

        # Verify contributions are tracked
        self.assertEqual(ira.total_contributions, 4000)
        self.assertGreater(len(ira.stat_balance_history), 0)

    def test_early_withdrawal_contributions_only(self):
        """Test early withdrawal of just contributions (no penalty)"""
        ira = setup_roth_ira(age=50)

        # Set up contributions tracking
        ira.total_contributions = 10000

        # Withdraw only contributions
        withdrawn = ira.withdraw(8000)

        # Should withdraw the full amount with no penalties
        self.assertEqual(withdrawn, 8000)
        self.assertEqual(ira.balance, 17000)
        self.assertEqual(ira.total_contributions, 2000)  # 10000 - 8000

        # No early withdrawal penalty since only contributions were withdrawn
        self.assertEqual(ira.owner.early_withdrawal_amount, 0)

    def test_early_withdrawal_with_earnings(self):
        """Test early withdrawal that includes earnings (with penalty)"""
        ira = setup_roth_ira(age=50)

        # Set up contributions tracking
        ira.total_contributions = 5000

        # Withdraw more than just contributions
        withdrawn = ira.withdraw(10000)

        # Should withdraw the full amount
        self.assertEqual(withdrawn, 10000)
        self.assertEqual(ira.balance, 15000)
        self.assertEqual(ira.total_contributions, 0)  # All contributions used

        # Early withdrawal penalty should apply to earnings portion (5000)
        self.assertEqual(ira.owner.early_withdrawal_amount, 5000)

    def test_qualified_withdrawal(self):
        """Test qualified withdrawal after age 59.5 (no penalties)"""
        ira = setup_roth_ira(age=65)

        # Set up some contributions
        ira.total_contributions = 15000

        # Withdraw more than contributions but after 59.5
        withdrawn = ira.withdraw(20000)

        # Should withdraw the full amount
        self.assertEqual(withdrawn, 20000)
        self.assertEqual(ira.balance, 5000)
        self.assertEqual(ira.total_contributions, 0)  # All contributions used

        # No early withdrawal penalty since owner is over 59.5
        self.assertEqual(ira.owner.early_withdrawal_amount, 0)

    def test_overdraft_protection(self):
        """Test that withdrawals don't exceed balance"""
        ira = setup_roth_ira()
        ira.total_contributions = 5000

        # Try to withdraw more than available
        withdrawn = ira.withdraw(30000)

        # Should only withdraw available balance
        self.assertEqual(withdrawn, 25000)
        self.assertEqual(ira.balance, 0)
        self.assertEqual(ira.total_contributions, 0)


if __name__ == '__main__':
    unittest.main()
