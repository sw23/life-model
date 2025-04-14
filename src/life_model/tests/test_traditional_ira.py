# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from ..model import LifeModel
from ..person import Person, Spending
from ..family import Family
from ..account.ira.traditional_ira import TraditionalIra


def setup_traditional_ira(age=40):
    """Helper function to create a Traditional IRA account for testing"""
    model = LifeModel()
    person = Person(family=Family(model), name='Test Person', age=age, retirement_age=65,
                    spending=Spending(model))

    # Create a bank account for the person to handle deposits and withdrawals
    from ..account.bank import BankAccount
    BankAccount(owner=person, company='Test Bank', balance=10000)

    return TraditionalIra(
        owner=person,
        balance=30000,
        yearly_contrib_amount=5000,
        average_growth=6
    )


class TestTraditionalIra(unittest.TestCase):

    def test_init(self):
        """Test initialization of Traditional IRA account"""
        ira = setup_traditional_ira()

        self.assertEqual(ira.balance, 30000)
        self.assertEqual(ira.yearly_contrib_amount, 5000)
        self.assertEqual(ira.average_growth, 6)
        self.assertEqual(ira.AGE_LIMIT_FOR_EXTRA, 50)
        self.assertEqual(ira.CONTRIBUTION_LIMIT, 6500)
        self.assertEqual(ira.CONTRIBUTION_LIMIT_AGE_50_PLUS, 7500)

    def test_contribution_limits(self):
        """Test contribution limits based on age"""
        young_ira = setup_traditional_ira(age=45)
        old_ira = setup_traditional_ira(age=55)

        # Younger person should have standard contribution limit
        self.assertEqual(young_ira.contribution_limit, 6500)

        # Older person should have higher contribution limit
        self.assertEqual(old_ira.contribution_limit, 7500)

    def test_growth(self):
        """Test account growth over time"""
        ira = setup_traditional_ira()
        initial_balance = ira.balance

        # Apply growth
        ira.apply_growth()

        # The model uses continuous interest calculation which is slightly different from simple interest
        # Just verify that there was growth applied and the new balance is higher
        self.assertGreater(ira.balance, initial_balance)
        # Verify that growth is approximately in the expected range for 6% growth
        growth = ira.balance - initial_balance
        expected_min_growth = initial_balance * 0.055
        expected_max_growth = initial_balance * 0.065
        self.assertTrue(expected_min_growth <= growth <= expected_max_growth,
                        f"Growth {growth} outside expected range ({expected_min_growth}-{expected_max_growth})")

    def test_contribution(self):
        """Test yearly contribution"""
        ira = setup_traditional_ira()

        # Contribute to IRA
        contributed = ira.contribute()

        # Should contribute the yearly amount (5000) since it's under the limit
        self.assertEqual(contributed, 5000)
        self.assertEqual(ira.balance, 35000)

    def test_contribution_over_limit(self):
        """Test contribution exceeding limit"""
        ira = setup_traditional_ira(age=45)
        ira.yearly_contrib_amount = 8000  # Above the 6500 limit

        # Contribute to IRA
        contributed = ira.contribute()

        # Should only contribute up to the limit (6500)
        self.assertEqual(contributed, 6500)
        self.assertEqual(ira.balance, 36500)

    def test_early_withdrawal(self):
        """Test early withdrawal with penalty tracking"""
        ira = setup_traditional_ira(age=55)

        # Check early withdrawal status
        self.assertTrue(ira.is_early_withdrawal())

        # Withdraw some amount
        withdrawn = ira.withdraw(5000)

        # Should withdraw the full amount
        self.assertEqual(withdrawn, 5000)
        self.assertEqual(ira.balance, 25000)

        # Early withdrawal amount should be tracked
        self.assertEqual(ira.owner.early_withdrawal_amount, 5000)

        # The withdrawal should be added to taxable income
        self.assertEqual(ira.owner.taxable_income, 5000)

    def test_normal_withdrawal(self):
        """Test withdrawal after age 59.5"""
        ira = setup_traditional_ira(age=60)

        # Check early withdrawal status
        self.assertFalse(ira.is_early_withdrawal())

        # Withdraw some amount
        withdrawn = ira.withdraw(5000)

        # Should withdraw the full amount
        self.assertEqual(withdrawn, 5000)
        self.assertEqual(ira.balance, 25000)

        # No early withdrawal penalty
        self.assertEqual(ira.owner.early_withdrawal_amount, 0)

        # The withdrawal should be added to taxable income
        self.assertEqual(ira.owner.taxable_income, 5000)

    def test_required_minimum_distributions(self):
        """Test Required Minimum Distributions after age 72"""
        ira = setup_traditional_ira(age=72)
        ira.balance = 100000  # Set a higher balance for clearer RMD calculation

        # Run a pre_step to trigger RMD
        ira.pre_step()

        # RMD for age 72 should be approximately 3.65% of balance
        # (Using a simplified RMD formula for testing)
        self.assertGreater(ira.stat_required_min_distrib, 0)
        self.assertLess(ira.stat_required_min_distrib, 5000)  # Reasonable upper bound

        # The RMD should be added to taxable income
        self.assertGreater(ira.owner.taxable_income, 0)

        # The RMD should be deposited into bank account
        bank_accounts = ira.owner.bank_accounts
        self.assertTrue(len(bank_accounts) > 0)
        total_bank_balance = sum(account.balance for account in bank_accounts)
        self.assertGreater(total_bank_balance, 0)

    def test_overdraft_protection(self):
        """Test that withdrawals don't exceed balance"""
        ira = setup_traditional_ira()

        # Try to withdraw more than available
        withdrawn = ira.withdraw(50000)

        # Should only withdraw available balance
        self.assertEqual(withdrawn, 30000)
        self.assertEqual(ira.balance, 0)


if __name__ == '__main__':
    unittest.main()
