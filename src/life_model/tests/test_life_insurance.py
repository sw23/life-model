# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..account.bank import BankAccount
from ..insurance.life_insurance import LifeInsurance, LifeInsuranceType, PremiumIncreaseType


class TestLifeInsurance(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures"""
        self.model = LifeModel(start_year=2023, end_year=2030)
        self.family = Family(self.model)
        self.john = Person(
            family=self.family,
            name='John',
            age=35,
            retirement_age=65,
            spending=Spending(self.model, base=50000)
        )
        self.jane = Person(
            family=self.family,
            name='Jane',
            age=33,
            retirement_age=65,
            spending=Spending(self.model, base=45000)
        )
        # Set up bank accounts
        BankAccount(owner=self.john, company='Bank', balance=10000)
        BankAccount(owner=self.jane, company='Bank', balance=15000)

    def test_term_life_policy_creation(self):
        """Test creating a term life insurance policy"""
        policy = LifeInsurance(
            person=self.john,
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=50,
            term_years=20
        )

        self.assertEqual(policy.person, self.john)
        self.assertEqual(policy.policy_type, LifeInsuranceType.TERM)
        self.assertEqual(policy.death_benefit, 500000)
        self.assertEqual(policy.monthly_premium, 50)
        self.assertEqual(policy.yearly_premium, 600)
        self.assertEqual(policy.term_years, 20)
        self.assertTrue(policy.is_active)
        self.assertFalse(policy.is_lapsed)
        self.assertEqual(policy.cash_value, 0)

    def test_whole_life_policy_creation(self):
        """Test creating a whole life insurance policy"""
        policy = LifeInsurance(
            person=self.jane,
            policy_type=LifeInsuranceType.WHOLE,
            death_benefit=300000,
            monthly_premium=200,
            cash_value_growth_rate=3.0
        )

        self.assertEqual(policy.policy_type, LifeInsuranceType.WHOLE)
        self.assertEqual(policy.cash_value_growth_rate, 3.0)
        self.assertIsNone(policy.term_years)
        self.assertFalse(policy.is_term_expired)

    def test_premium_payment_success(self):
        """Test successful premium payment"""
        policy = LifeInsurance(
            person=self.john,
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=50
        )

        initial_balance = self.john.bank_account_balance
        result = policy.make_premium_payment()

        self.assertTrue(result)
        self.assertEqual(policy.total_premiums_paid, 600)
        self.assertEqual(policy.consecutive_missed_payments, 0)
        self.assertEqual(self.john.bank_account_balance, initial_balance - 600)

    def test_premium_payment_insufficient_funds(self):
        """Test premium payment with insufficient funds"""
        # Create policy with high premium
        policy = LifeInsurance(
            person=self.john,
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=1000  # $12000/year - more than bank balance
        )

        result = policy.make_premium_payment()

        self.assertFalse(result)
        self.assertEqual(policy.consecutive_missed_payments, 1)
        self.assertEqual(self.john.bank_account_balance, 0)  # All money used for partial payment

    def test_policy_lapse_after_missed_payments(self):
        """Test policy lapse after consecutive missed payments"""
        policy = LifeInsurance(
            person=self.john,
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=2000,  # Too expensive
            max_missed_payments=2
        )

        # Miss first payment
        policy.make_premium_payment()
        self.assertFalse(policy.is_lapsed)
        self.assertEqual(policy.consecutive_missed_payments, 1)

        # Miss second payment - should lapse
        policy.make_premium_payment()
        self.assertTrue(policy.is_lapsed)
        self.assertFalse(policy.is_active)

    def test_whole_life_cash_value_growth(self):
        """Test cash value growth for whole life policies"""
        policy = LifeInsurance(
            person=self.jane,
            policy_type=LifeInsuranceType.WHOLE,
            death_benefit=300000,
            monthly_premium=200,
            cash_value_growth_rate=5.0
        )

        # Make a payment to build initial cash value
        policy.make_premium_payment()
        initial_cash_value = policy.cash_value
        self.assertGreater(initial_cash_value, 0)

        # Simulate cash value growth
        policy.step()
        self.assertGreater(policy.cash_value, initial_cash_value)

    def test_whole_life_loan_functionality(self):
        """Test taking and repaying loans against whole life policies"""
        policy = LifeInsurance(
            person=self.jane,
            policy_type=LifeInsuranceType.WHOLE,
            death_benefit=300000,
            monthly_premium=100,
            cash_value_growth_rate=3.0
        )

        # Build up cash value
        policy.cash_value = 10000
        initial_balance = self.jane.bank_account_balance

        # Take a loan
        loan_amount = policy.take_loan(5000)
        self.assertEqual(loan_amount, 4500)  # 90% of cash value available for loan
        self.assertEqual(policy.outstanding_loan_balance, 4500)
        self.assertEqual(self.jane.bank_account_balance, initial_balance + 4500)

        # Repay part of the loan
        repayment = policy.repay_loan(2000)
        self.assertEqual(repayment, 2000)
        self.assertEqual(policy.outstanding_loan_balance, 2500)

    def test_term_life_loan_not_allowed(self):
        """Test that term life policies don't allow loans"""
        policy = LifeInsurance(
            person=self.john,
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=50
        )

        loan_amount = policy.take_loan(5000)
        self.assertEqual(loan_amount, 0)
        self.assertEqual(policy.outstanding_loan_balance, 0)

    def test_term_policy_expiration(self):
        """Test term policy expiration"""
        policy = LifeInsurance(
            person=self.john,
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=50,
            term_years=5
        )

        # Fast-forward to policy expiration
        for _ in range(5):
            self.model.step()

        self.assertTrue(policy.is_term_expired)
        policy.step()
        self.assertFalse(policy.is_active)

    def test_premium_increase(self):
        """Test premium increases over time"""
        policy = LifeInsurance(
            person=self.john,
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=50,
            premium_increase_rate=5.0  # 5% annual increase
        )

        initial_premium = policy.monthly_premium
        policy.step()
        self.assertGreater(policy.monthly_premium, initial_premium)
        expected_premium = initial_premium * 1.05
        self.assertAlmostEqual(policy.monthly_premium, expected_premium, places=2)

    def test_death_benefit_calculation(self):
        """Test death benefit calculation with loans"""
        policy = LifeInsurance(
            person=self.jane,
            policy_type=LifeInsuranceType.WHOLE,
            death_benefit=300000,
            monthly_premium=100
        )

        # No loans - full death benefit
        self.assertEqual(policy.net_death_benefit, 300000)

        # With outstanding loan
        policy.outstanding_loan_balance = 50000
        self.assertEqual(policy.net_death_benefit, 250000)

        # Loan exceeds death benefit
        policy.outstanding_loan_balance = 350000
        self.assertEqual(policy.net_death_benefit, 0)

    def test_whole_life_premium_payment_with_cash_value(self):
        """Test using cash value to pay premiums for whole life policies"""
        policy = LifeInsurance(
            person=self.jane,
            policy_type=LifeInsuranceType.WHOLE,
            death_benefit=300000,
            monthly_premium=500  # High premium
        )

        # Build up cash value but drain bank account
        policy.cash_value = 5000
        self.jane.deduct_from_bank_accounts(self.jane.bank_account_balance)

        # Should be able to pay using cash value
        result = policy.make_premium_payment()
        self.assertTrue(result)
        self.assertLess(policy.cash_value, 5000)  # Cash value used for payment

    def test_loan_interest_accumulation(self):
        """Test loan interest accumulation"""
        policy = LifeInsurance(
            person=self.jane,
            policy_type=LifeInsuranceType.WHOLE,
            death_benefit=300000,
            monthly_premium=100,
            loan_interest_rate=6.0
        )

        # Take a loan
        policy.cash_value = 10000
        policy.take_loan(5000)
        initial_loan_balance = policy.outstanding_loan_balance

        # Step to accumulate interest
        policy.step()
        expected_balance = initial_loan_balance * 1.06
        self.assertAlmostEqual(policy.outstanding_loan_balance, expected_balance, places=2)

    def test_policy_statistics_tracking(self):
        """Test that policy statistics are properly tracked"""
        policy = LifeInsurance(
            person=self.john,
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=50
        )

        # Make a payment
        policy.make_premium_payment()

        # Check stats
        self.assertEqual(policy.stat_premium_payments, 600)
        self.assertEqual(policy.stat_policy_active, 1)
        self.assertEqual(policy.stat_cash_value, 0)  # Term life has no cash value

        # For whole life
        whole_policy = LifeInsurance(
            person=self.jane,
            policy_type=LifeInsuranceType.WHOLE,
            death_benefit=300000,
            monthly_premium=100
        )

        whole_policy.make_premium_payment()
        whole_policy.step()

        self.assertGreater(whole_policy.stat_cash_value, 0)

    def test_repr_html(self):
        """Test HTML representation"""
        policy = LifeInsurance(
            person=self.john,
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=50,
            term_years=20
        )

        html = policy._repr_html_()
        self.assertIn('Term', html)
        self.assertIn('$500,000', html)
        self.assertIn('$50.00', html)
        self.assertIn('20 years', html)
        self.assertIn('Active', html)

    def test_age_based_premium_increases(self):
        """Test realistic age-based premium increases for term life"""
        policy = LifeInsurance(
            person=self.john,  # age 35
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=50,
            term_years=30
        )

        initial_premium = policy.monthly_premium

        # Age the person and test premium increases
        self.john.age = 45
        new_premium = policy.calculate_age_based_premium_increase()
        self.assertGreater(new_premium, initial_premium)

        # Test at older age - should be much higher
        self.john.age = 65
        older_premium = policy.calculate_age_based_premium_increase()
        self.assertGreater(older_premium, new_premium)

        # Verify the multiplier effect
        self.assertGreater(older_premium / initial_premium, 5)  # Should be at least 5x more expensive

    def test_policy_drop_with_surrender_value(self):
        """Test voluntarily dropping a whole life policy with cash surrender"""
        policy = LifeInsurance(
            person=self.jane,
            policy_type=LifeInsuranceType.WHOLE,
            death_benefit=300000,
            monthly_premium=200
        )

        # Make payments to build cash value
        policy.make_premium_payment()
        policy.step()
        initial_cash_value = policy.cash_value

        # Age the policy to get better surrender value
        policy.policy_start_year = self.model.year - 5  # 5 years old

        initial_bank_balance = self.jane.bank_accounts[0].balance

        # Drop the policy
        policy.drop_policy()

        # Policy should be inactive
        self.assertFalse(policy.is_active)

        # Person should receive surrender value (80% of available cash value for mature policy)
        expected_surrender = initial_cash_value * 0.8
        final_bank_balance = self.jane.bank_accounts[0].balance
        self.assertAlmostEqual(final_bank_balance - initial_bank_balance, expected_surrender, places=2)

    def test_policy_drop_term_life(self):
        """Test dropping a term life policy (no surrender value)"""
        policy = LifeInsurance(
            person=self.john,
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=75
        )

        initial_bank_balance = self.john.bank_accounts[0].balance

        # Drop the policy
        policy.drop_policy()

        # Policy should be inactive
        self.assertFalse(policy.is_active)

        # No surrender value for term life
        final_bank_balance = self.john.bank_accounts[0].balance
        self.assertEqual(final_bank_balance, initial_bank_balance)

    def test_configurable_age_multipliers(self):
        """Test that age multipliers can be customized via constructor"""
        # Create custom age multipliers for a more aggressive pricing structure
        custom_multipliers = {
            20: 1.0, 30: 2.0, 40: 4.0, 50: 8.0, 60: 16.0, 70: 32.0
        }

        policy = LifeInsurance(
            person=self.john,  # age 35
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=50,
            term_years=30,
            premium_increase_rate=custom_multipliers  # Pass dict as premium_increase_rate
        )

        # Test that the custom multipliers are used
        self.assertEqual(policy.age_multipliers, custom_multipliers)

        # Test premium calculation with custom multipliers
        self.john.age = 40
        new_premium = policy.calculate_age_based_premium_increase()
        expected_premium = 50 * 4.0  # base premium * multiplier for age 40
        self.assertEqual(new_premium, expected_premium)

        # Test interpolation between custom age brackets
        self.john.age = 35  # Between 30 (2.0x) and 40 (4.0x)
        interpolated_premium = policy.calculate_age_based_premium_increase()
        # Should be 50% between 2.0 and 4.0, so 3.0x
        expected_interpolated = 50 * 3.0
        self.assertEqual(interpolated_premium, expected_interpolated)

    def test_default_age_multipliers(self):
        """Test that default age multipliers are used when none provided"""
        policy = LifeInsurance(
            person=self.john,
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=50,
            term_years=30
        )

        # Should have default age multipliers
        expected_defaults = {
            20: 1.0, 25: 1.1, 30: 1.3, 35: 1.6, 40: 2.1,
            45: 2.8, 50: 3.8, 55: 5.2, 60: 7.1, 65: 10.0,
            70: 15.0, 75: 23.0, 80: 35.0, 85: 55.0
        }
        self.assertEqual(policy.age_multipliers, expected_defaults)

    def test_update_term_life_premiums_method(self):
        """Test the update_term_life_premiums method"""
        policy = LifeInsurance(
            person=self.john,  # age 35
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=50,
            term_years=30
        )

        initial_premium = policy.monthly_premium

        # Age the person significantly
        self.john.age = 55

        # Update premiums
        policy.update_term_life_premiums()

        # Premium should have increased significantly
        self.assertGreater(policy.monthly_premium, initial_premium)
        self.assertGreater(policy.monthly_premium / initial_premium, 3)  # At least 3x increase

    def test_premium_increase_rate_types(self):
        """Test that premium_increase_rate accepts both float and dict"""
        # Test with float (yearly percentage increase)
        yearly_policy = LifeInsurance(
            person=self.john,
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=50,
            premium_increase_rate=5.0  # 5% yearly increase
        )

        self.assertEqual(yearly_policy.premium_increase_type, PremiumIncreaseType.YEARLY)
        self.assertEqual(yearly_policy.yearly_increase_rate, 5.0)
        self.assertEqual(yearly_policy.age_multipliers, {})

        # Test with dict (age-based multipliers)
        age_multipliers = {30: 1.0, 40: 2.0, 50: 4.0}
        age_policy = LifeInsurance(
            person=self.john,
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=50,
            premium_increase_rate=age_multipliers
        )

        self.assertEqual(age_policy.premium_increase_type, PremiumIncreaseType.AGE_BASED)
        self.assertEqual(age_policy.yearly_increase_rate, 0.0)
        self.assertEqual(age_policy.age_multipliers, age_multipliers)

        # Test with None (default age-based)
        default_policy = LifeInsurance(
            person=self.john,
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=50,
            premium_increase_rate=None
        )

        self.assertEqual(default_policy.premium_increase_type, PremiumIncreaseType.AGE_BASED)
        self.assertEqual(default_policy.yearly_increase_rate, 0.0)
        self.assertGreater(len(default_policy.age_multipliers), 0)  # Should have default multipliers


if __name__ == '__main__':
    unittest.main()
