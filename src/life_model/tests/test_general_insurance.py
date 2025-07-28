# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..account.bank import BankAccount
from ..insurance.general_insurance import Insurance, InsuranceType, ClaimStatus


class TestGeneralInsurance(unittest.TestCase):

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
        # Set up bank account
        BankAccount(owner=self.john, company='Bank', balance=50000)

    def test_auto_insurance_creation(self):
        """Test creating auto insurance policy"""
        insurance = Insurance(
            person=self.john,
            insurance_type=InsuranceType.AUTO,
            company='State Farm',
            annual_premium=1200,
            coverage_amount=300000,
            deductible=500
        )

        self.assertEqual(insurance.person, self.john)
        self.assertEqual(insurance.insurance_type, InsuranceType.AUTO)
        self.assertEqual(insurance.company, 'State Farm')
        self.assertEqual(insurance.annual_premium, 1200)
        self.assertEqual(insurance.coverage_amount, 300000)
        self.assertEqual(insurance.deductible, 500)
        self.assertTrue(insurance.is_active)
        self.assertTrue(insurance.is_coverage_active)

    def test_home_insurance_creation(self):
        """Test creating home insurance policy"""
        insurance = Insurance(
            person=self.john,
            insurance_type=InsuranceType.HOME,
            company='Allstate',
            annual_premium=2000,
            coverage_amount=500000,
            deductible=1000,
            premium_increase_rate=4.0
        )

        self.assertEqual(insurance.insurance_type, InsuranceType.HOME)
        self.assertEqual(insurance.premium_increase_rate, 4.0)
        self.assertEqual(insurance.base_annual_premium, 2000)

    def test_premium_payment_success(self):
        """Test successful premium payment"""
        insurance = Insurance(
            person=self.john,
            insurance_type=InsuranceType.AUTO,
            company='GEICO',
            annual_premium=1500,
            coverage_amount=250000,
            deductible=250
        )

        initial_balance = self.john.bank_account_balance
        result = insurance.pay_premium()

        self.assertTrue(result)
        self.assertEqual(insurance.stat_premiums_paid, 1500)
        self.assertEqual(self.john.bank_account_balance, initial_balance - 1500)
        self.assertTrue(insurance.is_active)

    def test_premium_payment_insufficient_funds(self):
        """Test premium payment with insufficient funds"""
        insurance = Insurance(
            person=self.john,
            insurance_type=InsuranceType.AUTO,
            company='Progressive',
            annual_premium=60000,  # More than available balance
            coverage_amount=250000,
            deductible=500
        )

        result = insurance.pay_premium()

        self.assertFalse(result)
        self.assertFalse(insurance.is_active)  # Policy should lapse
        self.assertEqual(self.john.bank_account_balance, 0)  # All money used

    def test_file_claim_success(self):
        """Test filing a successful insurance claim"""
        insurance = Insurance(
            person=self.john,
            insurance_type=InsuranceType.AUTO,
            company='State Farm',
            annual_premium=1200,
            coverage_amount=100000,
            deductible=1000
        )

        initial_balance = self.john.bank_account_balance
        claim = insurance.file_claim(15000, "Car accident repair")

        self.assertIsNotNone(claim)
        assert claim is not None  # Help type checker
        self.assertEqual(claim.amount, 15000)
        self.assertEqual(claim.description, "Car accident repair")
        self.assertEqual(claim.status, ClaimStatus.APPROVED)
        self.assertEqual(claim.payout_amount, 14000)  # 15000 - 1000 deductible
        self.assertEqual(insurance.stat_claims_filed, 1)
        self.assertEqual(insurance.stat_claims_paid_out, 14000)

        # Check that payout was added to bank account and deductible was deducted
        expected_balance = initial_balance + 14000 - 1000
        self.assertEqual(self.john.bank_account_balance, expected_balance)

    def test_file_claim_exceeds_coverage(self):
        """Test filing claim that exceeds coverage limit"""
        insurance = Insurance(
            person=self.john,
            insurance_type=InsuranceType.AUTO,
            company='GEICO',
            annual_premium=1000,
            coverage_amount=50000,
            deductible=500
        )

        claim = insurance.file_claim(75000, "Major accident")

        self.assertIsNotNone(claim)
        assert claim is not None  # Help type checker
        self.assertEqual(claim.status, ClaimStatus.DENIED)
        self.assertEqual(claim.payout_amount, 0)
        self.assertEqual(insurance.stat_claims_paid_out, 0)

    def test_file_claim_below_deductible(self):
        """Test filing claim below deductible amount"""
        insurance = Insurance(
            person=self.john,
            insurance_type=InsuranceType.AUTO,
            company='Progressive',
            annual_premium=1200,
            coverage_amount=100000,
            deductible=2000
        )

        claim = insurance.file_claim(1500, "Minor damage")

        self.assertIsNotNone(claim)
        assert claim is not None  # Help type checker
        self.assertEqual(claim.status, ClaimStatus.DENIED)
        self.assertEqual(claim.payout_amount, 0)

    def test_max_claims_per_year(self):
        """Test maximum claims per year limit"""
        insurance = Insurance(
            person=self.john,
            insurance_type=InsuranceType.AUTO,
            company='State Farm',
            annual_premium=1200,
            coverage_amount=100000,
            deductible=500,
            max_claims_per_year=2
        )

        # File first claim
        claim1 = insurance.file_claim(5000, "First accident")
        self.assertIsNotNone(claim1)
        self.assertEqual(insurance.claims_this_year, 1)

        # File second claim
        claim2 = insurance.file_claim(3000, "Second accident")
        self.assertIsNotNone(claim2)
        self.assertEqual(insurance.claims_this_year, 2)

        # Try to file third claim - should be rejected
        claim3 = insurance.file_claim(2000, "Third accident")
        self.assertIsNone(claim3)
        self.assertEqual(insurance.claims_this_year, 2)

    def test_coverage_age_limits(self):
        """Test insurance coverage with age limits"""
        insurance = Insurance(
            person=self.john,
            insurance_type=InsuranceType.DISABILITY,
            company='MetLife',
            annual_premium=1800,
            coverage_amount=75000,
            deductible=0,
            coverage_start_age=25,
            coverage_end_age=65
        )

        # Current age (35) is within coverage range
        self.assertTrue(insurance.is_coverage_active)

        # Simulate aging beyond coverage end age
        self.john.age = 70
        self.assertFalse(insurance.is_coverage_active)

        # Test before coverage start age
        self.john.age = 20
        self.assertFalse(insurance.is_coverage_active)

    def test_update_coverage(self):
        """Test updating coverage amount and deductible"""
        insurance = Insurance(
            person=self.john,
            insurance_type=InsuranceType.HOME,
            company='Allstate',
            annual_premium=2000,
            coverage_amount=400000,
            deductible=1000
        )

        original_premium = insurance.annual_premium
        insurance.update_coverage(600000, 1500)

        self.assertEqual(insurance.coverage_amount, 600000)
        self.assertEqual(insurance.deductible, 1500)
        # Premium should increase proportionally
        expected_premium = original_premium * (600000 / 400000)
        self.assertAlmostEqual(insurance.annual_premium, expected_premium, places=2)

    def test_cancel_policy(self):
        """Test cancelling insurance policy"""
        insurance = Insurance(
            person=self.john,
            insurance_type=InsuranceType.AUTO,
            company='GEICO',
            annual_premium=1200,
            coverage_amount=250000,
            deductible=500
        )

        self.assertTrue(insurance.is_active)
        insurance.cancel_policy()
        self.assertFalse(insurance.is_active)

    def test_claim_history(self):
        """Test claim history tracking"""
        insurance = Insurance(
            person=self.john,
            insurance_type=InsuranceType.HOME,
            company='State Farm',
            annual_premium=2000,
            coverage_amount=500000,
            deductible=2000
        )

        # File multiple claims
        insurance.file_claim(10000, "Storm damage")
        insurance.file_claim(5000, "Theft")

        # Test getting all claims
        all_claims = insurance.get_claim_history()
        self.assertEqual(len(all_claims), 2)

        # Test getting claims for specific year
        current_year_claims = insurance.get_claim_history(self.model.year)
        self.assertEqual(len(current_year_claims), 2)

        # Test total claims amount
        total_amount = insurance.get_total_claims_amount()
        self.assertEqual(total_amount, 15000)

        # Test total payouts
        total_payouts = insurance.get_total_payouts()
        self.assertEqual(total_payouts, 11000)  # 8000 + 3000 (after deductibles)

    def test_premium_increase_over_time(self):
        """Test premium increases over time"""
        insurance = Insurance(
            person=self.john,
            insurance_type=InsuranceType.AUTO,
            company='Progressive',
            annual_premium=1000,
            coverage_amount=200000,
            deductible=500,
            premium_increase_rate=5.0
        )

        original_premium = insurance.annual_premium

        # Simulate one year passing - premium increase only applies after first year
        insurance.policy_start_year = self.model.year - 1  # Make it appear the policy is one year old
        insurance.step()

        # Premium should increase by 5%
        expected_premium = original_premium * 1.05
        self.assertAlmostEqual(insurance.annual_premium, expected_premium, places=2)

    def test_pre_step_premium_payment(self):
        """Test that premiums are paid in pre_step"""
        insurance = Insurance(
            person=self.john,
            insurance_type=InsuranceType.AUTO,
            company='State Farm',
            annual_premium=1200,
            coverage_amount=250000,
            deductible=500
        )

        initial_balance = self.john.bank_account_balance
        insurance.pre_step()

        # Premium should have been paid
        self.assertEqual(self.john.bank_account_balance, initial_balance - 1200)
        self.assertEqual(insurance.stat_premiums_paid, 1200)

    def test_health_insurance(self):
        """Test health insurance specific features"""
        insurance = Insurance(
            person=self.john,
            insurance_type=InsuranceType.HEALTH,
            company='Blue Cross',
            annual_premium=6000,
            coverage_amount=1000000,
            deductible=3000
        )

        self.assertEqual(insurance.insurance_type, InsuranceType.HEALTH)

        # Test medical claim
        claim = insurance.file_claim(15000, "Surgery")
        self.assertIsNotNone(claim)
        assert claim is not None  # Help type checker
        self.assertEqual(claim.payout_amount, 12000)  # 15000 - 3000 deductible

    def test_umbrella_insurance(self):
        """Test umbrella insurance"""
        insurance = Insurance(
            person=self.john,
            insurance_type=InsuranceType.UMBRELLA,
            company='State Farm',
            annual_premium=300,
            coverage_amount=2000000,
            deductible=0
        )

        self.assertEqual(insurance.insurance_type, InsuranceType.UMBRELLA)
        self.assertEqual(insurance.coverage_amount, 2000000)
        self.assertEqual(insurance.deductible, 0)

    def test_repr_html(self):
        """Test HTML representation"""
        insurance = Insurance(
            person=self.john,
            insurance_type=InsuranceType.AUTO,
            company='GEICO',
            annual_premium=1200,
            coverage_amount=300000,
            deductible=500
        )

        # File a claim to test claims display
        insurance.file_claim(5000, "Accident")

        html = insurance._repr_html_()

        self.assertIn('Auto', html)
        self.assertIn('GEICO', html)
        self.assertIn('1,200', html)
        self.assertIn('300,000', html)
        self.assertIn('500', html)
        self.assertIn('Active', html)
        self.assertIn('Claims Filed: 1', html)


if __name__ == '__main__':
    unittest.main()
