# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from ..model import LifeModel
from ..person import Person, Spending
from ..family import Family
from ..job import Job, Salary
from ..account.job401k import Job401kAccount


def setup_job401k():
    """Helper function to create a 401k account for testing"""
    model = LifeModel()
    person = Person(family=Family(model), name='Test Person', age=40, retirement_age=65,
                    spending=Spending(model))
    job = Job(owner=person, company='Test Company', role='Test Role',
              salary=Salary(model=model, base=100000))

    # Create a bank account for the person to handle deposits
    from ..account.bank import BankAccount
    BankAccount(owner=person, company='Test Bank', balance=0)

    return Job401kAccount(
        job=job,
        pretax_balance=50000,
        pretax_contrib_percent=10,
        roth_balance=25000,
        roth_contrib_percent=5,
        average_growth=5,
        company_match_percent=50
    )


class TestJob401k(unittest.TestCase):

    def test_init(self):
        """Test initialization of 401k account"""
        account = setup_job401k()

        self.assertEqual(account.pretax_balance, 50000)
        self.assertEqual(account.roth_balance, 25000)
        self.assertEqual(account.balance, 75000)
        self.assertEqual(account.pretax_contrib_percent, 10)
        self.assertEqual(account.roth_contrib_percent, 5)
        self.assertEqual(account.average_growth, 5)
        self.assertEqual(account.company_match_percent, 50)

    def test_contributions(self):
        """Test contribution calculations"""
        account = setup_job401k()

        # Test pretax contribution calculation
        pretax_contrib = account.pretax_contrib(100000)
        self.assertEqual(pretax_contrib, 10000)

        # Test Roth contribution calculation
        roth_contrib = account.roth_contrib(100000)
        self.assertEqual(roth_contrib, 5000)

        # Test company match calculation
        company_match = account.company_match(15000)
        self.assertEqual(company_match, 7500)

    def test_growth(self):
        """Test account growth over time"""
        account = setup_job401k()
        initial_balance = account.balance

        # Run a pre_step to apply growth
        account.pre_step()

        # The model uses continuous interest calculation which is slightly different from simple interest
        # Just verify that there was growth applied and the new balance is higher
        self.assertGreater(account.balance, initial_balance)
        # Verify that growth is approximately in the 4-6% range
        growth = account.balance - initial_balance
        expected_min_growth = initial_balance * 0.04
        expected_max_growth = initial_balance * 0.06
        self.assertTrue(expected_min_growth <= growth <= expected_max_growth,
                        f"Growth {growth} outside expected range ({expected_min_growth}-{expected_max_growth})")

    def test_early_withdrawal_pretax(self):
        """Test early withdrawal from pretax balance with penalties"""
        account = setup_job401k()

        # Set owner age to ensure it's an early withdrawal
        account.owner.age = 55

        # Withdraw 10000 early from pretax
        withdrawn = account.deduct_pretax(10000)

        self.assertEqual(withdrawn, 10000)
        self.assertEqual(account.pretax_balance, 40000)
        self.assertEqual(account.stat_early_withdrawal_penalty, 1000)  # 10% of 10000

    def test_early_withdrawal_roth(self):
        """Test early withdrawal from Roth balance with penalties"""
        account = setup_job401k()

        # Set owner age to ensure it's an early withdrawal
        account.owner.age = 55

        # Withdraw 5000 early from Roth
        withdrawn = account.deduct_roth(5000)

        self.assertEqual(withdrawn, 5000)
        self.assertEqual(account.roth_balance, 20000)
        self.assertEqual(account.stat_early_withdrawal_penalty, 500)  # 10% of 5000

    def test_normal_withdrawal(self):
        """Test normal withdrawal after retirement age"""
        account = setup_job401k()

        # Set owner age to be past retirement age
        account.owner.age = 60

        # Withdraw 5000 from each account type
        pretax_withdrawn = account.deduct_pretax(5000)
        roth_withdrawn = account.deduct_roth(5000)

        self.assertEqual(pretax_withdrawn, 5000)
        self.assertEqual(roth_withdrawn, 5000)
        self.assertEqual(account.pretax_balance, 45000)
        self.assertEqual(account.roth_balance, 20000)
        self.assertEqual(account.stat_early_withdrawal_penalty, 0)  # No penalty

    def test_combined_withdraw_method(self):
        """Test the combined withdraw method with both Roth-first and pretax-first strategies"""
        account = setup_job401k()
        account.owner.age = 65  # No early withdrawal penalty

        # Test Roth-first strategy (default)
        withdrawn = account.withdraw(30000, from_roth_first=True)

        self.assertEqual(withdrawn, 30000)
        self.assertEqual(account.roth_balance, 0)  # Full Roth balance (25000) used
        self.assertEqual(account.pretax_balance, 45000)  # 50000 - 5000

        # Reset for next test
        account = setup_job401k()
        account.owner.age = 65

        # Test pretax-first strategy
        withdrawn = account.withdraw(30000, from_roth_first=False)

        self.assertEqual(withdrawn, 30000)
        self.assertEqual(account.pretax_balance, 20000)  # 50000 - 30000
        self.assertEqual(account.roth_balance, 25000)  # Unchanged

    def test_withdrawal_limits(self):
        """Test withdrawals that exceed account balances"""
        account = setup_job401k()

        # Try to withdraw more than the combined balance
        withdrawn = account.withdraw(100000)

        self.assertEqual(withdrawn, 75000)  # Should only withdraw available balance
        self.assertEqual(account.pretax_balance, 0)
        self.assertEqual(account.roth_balance, 0)


if __name__ == '__main__':
    unittest.main()
