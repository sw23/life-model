# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from ..model import LifeModel
from ..people.person import Person, Spending
from ..people.family import Family
from ..account.bank import BankAccount
from ..charity.donation import Donation, DonationType


class TestDonation(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures"""
        self.model = LifeModel(start_year=2025, end_year=2030)
        self.family = Family(self.model)
        self.spending = Spending(self.model, base=50000)
        self.person = Person(self.family, "Test Person", 30, 65, self.spending)
        # Increased balance to support multiple years of spending and donations
        self.bank_account = BankAccount(self.person, "Test Bank", balance=500000)

    def test_donation_creation(self):
        """Test basic donation creation"""
        donation = Donation(
            self.person,
            charity_name="Red Cross",
            annual_amount=5000,
            donation_type=DonationType.CASH
        )

        self.assertEqual(donation.charity_name, "Red Cross")
        self.assertEqual(donation.annual_amount, 5000)
        self.assertEqual(donation.donation_type, DonationType.CASH)
        self.assertTrue(donation.tax_deductible)
        self.assertEqual(donation.frequency_years, 1)

    def test_donation_registration(self):
        """Test that donations are registered with the person"""
        donation = Donation(self.person, "Charity A", 1000)

        self.assertIn(donation, self.person.donations)
        self.assertEqual(len(self.person.donations), 1)

    def test_annual_donation_payment(self):
        """Test that donations are paid annually from bank account"""
        initial_balance = self.bank_account.balance
        donation = Donation(self.person, "Annual Charity", 5000)

        # Run one step
        self.model.step()

        # Check that donation was made
        self.assertEqual(donation.stat_charitable_donations, 5000)
        self.assertEqual(donation.stat_total_donated, 5000)
        # Bank balance should reflect donation + spending
        expected_balance = initial_balance - 5000 - self.spending.base
        self.assertEqual(self.bank_account.balance, expected_balance)

    def test_multi_year_frequency(self):
        """Test donations with multi-year frequency"""
        donation = Donation(
            self.person,
            "Every 2 Years",
            annual_amount=10000,
            frequency_years=2,
            start_year=2025
        )

        # Year 1 (2025) - should donate
        self.model.step()
        self.assertEqual(donation.stat_total_donated, 10000)

        # Year 2 (2026) - should NOT donate
        self.model.step()
        self.assertEqual(donation.stat_total_donated, 10000)

        # Year 3 (2027) - should donate again
        self.model.step()
        self.assertEqual(donation.stat_total_donated, 20000)

    def test_donation_with_insufficient_funds(self):
        """Test donation when insufficient funds in bank account

        Donations happen in post_step (after bills/spending), so if there aren't
        enough funds after essential expenses, the donation won't be made.
        """
        # Set balance less than spending amount - spending will consume all funds
        self.bank_account.balance = 3000
        donation = Donation(self.person, "Big Charity", 5000)

        self.model.step()

        # Spending ($50,000) happens first in step(), consuming the $3000
        # No funds left for donation in post_step
        self.assertEqual(donation.stat_charitable_donations, 0)
        self.assertEqual(self.bank_account.balance, 0)
        # Person goes into debt for remaining spending ($50k - $3k = $47k debt)
        self.assertGreater(self.person.debt, 0)
        self.assertEqual(self.person.debt, 47000)

    def test_donation_with_sufficient_funds_after_expenses(self):
        """Test donation succeeds when funds remain after bills/spending"""
        # Balance covers spending ($50k) + donation ($5k)
        self.bank_account.balance = 60000
        donation = Donation(self.person, "After Bills Charity", 5000)

        self.model.step()

        # Spending happens first, then donation from remaining funds
        self.assertEqual(donation.stat_charitable_donations, 5000)
        expected_balance = 60000 - 50000 - 5000  # balance - spending - donation
        self.assertEqual(self.bank_account.balance, expected_balance)

    def test_donation_start_and_end_years(self):
        """Test donations respect start and end years"""
        donation = Donation(
            self.person,
            "Limited Charity",
            annual_amount=3000,
            start_year=2027,
            end_year=2028
        )

        # 2025 - before start, no donation
        self.model.step()
        self.assertEqual(donation.stat_total_donated, 0)

        # 2026 - before start, no donation
        self.model.step()
        self.assertEqual(donation.stat_total_donated, 0)

        # 2027 - within range, donate
        self.model.step()
        self.assertEqual(donation.stat_total_donated, 3000)

        # 2028 - within range, donate
        self.model.step()
        self.assertEqual(donation.stat_total_donated, 6000)

        # 2029 - after end, no donation
        self.model.step()
        self.assertEqual(donation.stat_total_donated, 6000)

    def test_tax_deduction_amount(self):
        """Test tax deduction calculation"""
        donation = Donation(self.person, "Tax Deductible", 8000, tax_deductible=True)

        # Before donation
        self.assertEqual(donation.get_tax_deduction_amount(), 0)

        # After donation
        self.model.step()
        self.assertEqual(donation.get_tax_deduction_amount(), 8000)

    def test_non_tax_deductible_donation(self):
        """Test non-tax-deductible donations"""
        donation = Donation(
            self.person,
            "Non-Deductible",
            5000,
            tax_deductible=False
        )

        self.model.step()

        # Donation should be made
        self.assertEqual(donation.stat_charitable_donations, 5000)

        # But no tax deduction
        self.assertEqual(donation.get_tax_deduction_amount(), 0)

    def test_multiple_donations_to_different_charities(self):
        """Test multiple donations to different charities"""
        donation1 = Donation(self.person, "Charity A", 3000)
        donation2 = Donation(self.person, "Charity B", 2000)
        donation3 = Donation(self.person, "Charity C", 1000)

        initial_balance = self.bank_account.balance
        self.model.step()

        # All donations should be made
        self.assertEqual(donation1.stat_charitable_donations, 3000)
        self.assertEqual(donation2.stat_charitable_donations, 2000)
        self.assertEqual(donation3.stat_charitable_donations, 1000)

        # Total deduction
        total_deduction = sum(d.get_tax_deduction_amount() for d in self.person.donations)
        self.assertEqual(total_deduction, 6000)

        # Bank balance should reflect donations + spending
        expected_balance = initial_balance - 6000 - self.spending.base
        self.assertEqual(self.bank_account.balance, expected_balance)

    def test_donation_stats_reset_each_year(self):
        """Test that annual donation stats reset each year"""
        donation = Donation(self.person, "Annual Reset", 4000)

        # Year 1
        self.model.step()
        self.assertEqual(donation.stat_charitable_donations, 4000)

        # Year 2 - stat should be recalculated
        self.model.step()
        self.assertEqual(donation.stat_charitable_donations, 4000)

        # Total should accumulate
        self.assertEqual(donation.stat_total_donated, 8000)

    def test_person_charitable_deductions_property(self):
        """Test person's charitable_deductions property"""
        Donation(self.person, "Charity 1", 3000)
        Donation(self.person, "Charity 2", 2000)

        # Before donations
        self.assertEqual(self.person.charitable_deductions, 0)

        # After donations
        self.model.step()
        self.assertEqual(self.person.charitable_deductions, 5000)

    def test_different_donation_types(self):
        """Test different types of donations"""
        cash_donation = Donation(self.person, "Cash Charity", 1000, DonationType.CASH)
        stock_donation = Donation(self.person, "Stock Charity", 2000, DonationType.STOCK)
        property_donation = Donation(self.person, "Property Charity", 3000, DonationType.PROPERTY)

        self.assertEqual(cash_donation.donation_type, DonationType.CASH)
        self.assertEqual(stock_donation.donation_type, DonationType.STOCK)
        self.assertEqual(property_donation.donation_type, DonationType.PROPERTY)


if __name__ == '__main__':
    unittest.main()
