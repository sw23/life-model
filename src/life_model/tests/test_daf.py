# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from ..model import LifeModel
from ..people.person import Person, Spending
from ..people.family import Family
from ..account.bank import BankAccount
from ..charity.daf import DonorAdvisedFund


class TestDAF(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures"""
        self.model = LifeModel(start_year=2025, end_year=2030)
        self.family = Family(self.model)
        self.spending = Spending(self.model, base=50000)
        self.person = Person(self.family, "Test Person", 30, 65, self.spending)
        self.bank_account = BankAccount(self.person, "Test Bank", balance=100000)

    def test_daf_creation(self):
        """Test basic DAF creation"""
        daf = DonorAdvisedFund(
            self.person,
            fund_name="Family Foundation",
            balance=50000,
            growth_rate=7.0,
            management_fee=0.6,
            distribution_rate=5.0
        )

        self.assertEqual(daf.fund_name, "Family Foundation")
        self.assertEqual(daf.balance, 50000)
        self.assertEqual(daf.growth_rate, 7.0)
        self.assertEqual(daf.management_fee, 0.6)
        self.assertEqual(daf.distribution_rate, 5.0)

    def test_daf_registration(self):
        """Test that DAFs are registered with the person"""
        daf = DonorAdvisedFund(self.person, "Test DAF", balance=10000)

        self.assertIn(daf, self.person.donor_advised_funds)
        self.assertEqual(len(self.person.donor_advised_funds), 1)

    def test_daf_contribution_from_bank(self):
        """Test contributing to DAF from bank account"""
        daf = DonorAdvisedFund(self.person, "Test DAF", balance=0)
        initial_bank_balance = self.bank_account.balance

        amount_contributed = daf.contribute(10000)

        self.assertEqual(amount_contributed, 10000)
        self.assertEqual(daf.balance, 10000)
        self.assertEqual(self.bank_account.balance, initial_bank_balance - 10000)
        self.assertEqual(daf.stat_total_contributions, 10000)

    def test_daf_contribution_insufficient_funds(self):
        """Test DAF contribution with insufficient bank funds"""
        daf = DonorAdvisedFund(self.person, "Test DAF", balance=0)
        self.bank_account.balance = 5000

        amount_contributed = daf.contribute(10000)

        # Should only contribute what's available
        self.assertEqual(amount_contributed, 5000)
        self.assertEqual(daf.balance, 5000)
        self.assertEqual(self.bank_account.balance, 0)

    def test_daf_growth(self):
        """Test DAF investment growth"""
        daf = DonorAdvisedFund(self.person, "Growth DAF", balance=100000, growth_rate=7.0)

        # Step should apply growth
        self.model.step()

        # Order of operations in step():
        # 1. Growth applied: 100,000 * 0.07 = 7,000 -> balance = 107,000
        # 2. Fee applied: 107,000 * 0.006 = 642 -> balance = 106,358
        # 3. Distribution: 106,358 * 0.05 = 5,317.90 -> balance = 101,040.10
        # Note: Order matters because each operation compounds
        expected_balance = 100000 * 1.07  # Growth
        expected_balance = expected_balance * (1 - 0.006)  # Fee
        expected_balance = expected_balance * (1 - 0.05)  # Distribution
        self.assertAlmostEqual(daf.balance, expected_balance, places=2)

    def test_daf_management_fee(self):
        """Test DAF management fee application"""
        daf = DonorAdvisedFund(
            self.person,
            "Fee DAF",
            balance=100000,
            management_fee=0.6,
            distribution_rate=0  # No distributions to isolate fee
        )

        initial_balance = daf.balance
        self.model.step()

        # Order of operations:
        # 1. Growth applied: 100,000 * 0.07 = 7,000 -> balance = 107,000
        # 2. Fee applied: 107,000 * 0.006 = 642 -> balance = 106,358
        expected_fee = (initial_balance * 1.07) * 0.006
        self.assertAlmostEqual(daf.stat_management_fees_paid, expected_fee, places=2)

        # Balance should reflect growth minus fee (no distribution)
        expected_balance = (initial_balance * 1.07) - expected_fee
        self.assertAlmostEqual(daf.balance, expected_balance, places=2)

    def test_daf_automatic_distribution(self):
        """Test automatic distribution to charity"""
        daf = DonorAdvisedFund(
            self.person,
            "Charity DAF",
            balance=100000,
            distribution_rate=5.0,
            growth_rate=0,  # No growth to isolate distribution
            management_fee=0  # No fees to isolate distribution
        )

        self.model.step()

        # Should distribute 5% to charity
        expected_distribution = 5000
        self.assertAlmostEqual(daf.stat_charitable_donations, expected_distribution, places=2)
        self.assertAlmostEqual(daf.stat_total_donated, expected_distribution, places=2)

        # Balance should decrease by distribution amount
        self.assertAlmostEqual(daf.balance, 95000, places=2)

    def test_daf_manual_distribution(self):
        """Test manual distribution to charity"""
        daf = DonorAdvisedFund(
            self.person,
            "Manual DAF",
            balance=50000,
            distribution_rate=0  # No automatic distribution
        )

        amount_distributed = daf.distribute_to_charity(10000)

        self.assertEqual(amount_distributed, 10000)
        self.assertEqual(daf.balance, 40000)
        self.assertEqual(daf.stat_total_donated, 10000)

    def test_daf_distribution_exceeds_balance(self):
        """Test distribution when amount exceeds balance"""
        daf = DonorAdvisedFund(self.person, "Small DAF", balance=5000)

        amount_distributed = daf.distribute_to_charity(10000)

        # Should only distribute available balance
        self.assertEqual(amount_distributed, 5000)
        self.assertEqual(daf.balance, 0)

    def test_daf_tax_deduction_on_contribution(self):
        """Test that tax deduction happens on contribution, not distribution"""
        daf = DonorAdvisedFund(self.person, "Tax DAF", balance=0)

        # Contribute during the model step (contributions happen at any point before step completes)
        # Track contributions by making them and immediately checking
        daf.contribute(10000)

        # The contribution is immediately tracked
        self.assertEqual(daf.stat_contributions_this_year, 10000)
        self.assertEqual(daf.balance, 10000)

        # After model step, stat is reset but total is accumulated
        self.model.step()

        # The reset happens in pre_step, so current year contribution is 0
        # (unless we contribute again during this step)
        self.assertEqual(daf.stat_contributions_this_year, 0)

        # But total contributions are tracked
        self.assertEqual(daf.stat_total_contributions, 10000)

    def test_daf_no_deduction_on_distribution(self):
        """Test that distributions don't create additional deductions"""
        daf = DonorAdvisedFund(self.person, "Dist DAF", balance=100000, distribution_rate=5.0)

        # Run a step - will distribute but no new contribution
        self.model.step()

        # Distribution should happen
        self.assertGreater(daf.stat_charitable_donations, 0)

        # But no contribution deduction this year
        self.assertEqual(daf.stat_contributions_this_year, 0)

    def test_daf_multi_year_tracking(self):
        """Test DAF tracking over multiple years"""
        daf = DonorAdvisedFund(
            self.person,
            "Multi-Year DAF",
            balance=100000,
            growth_rate=7.0,
            management_fee=0.6,
            distribution_rate=5.0
        )

        # Year 1
        self.model.step()
        year1_balance = daf.balance
        year1_donated = daf.stat_total_donated

        # Year 2
        self.model.step()
        year2_balance = daf.balance
        year2_donated = daf.stat_total_donated

        # Balance should change each year
        self.assertNotEqual(year1_balance, year2_balance)

        # Total donated should accumulate
        self.assertGreater(year2_donated, year1_donated)

    def test_daf_stats_reset_each_year(self):
        """Test that annual stats reset properly"""
        daf = DonorAdvisedFund(self.person, "Reset DAF", balance=50000, distribution_rate=5.0)

        # Contribute in setup
        daf.contribute(10000)

        # Year 1 - step will reset and process
        self.model.step()
        year1_contribution_stat = daf.stat_contributions_this_year
        year1_donation_stat = daf.stat_charitable_donations

        # Contributions should be reset (no new contributions in step)
        self.assertEqual(year1_contribution_stat, 0)

        # Donations should be from distribution
        self.assertGreater(year1_donation_stat, 0)

        # Year 2
        self.model.step()
        year2_donation_stat = daf.stat_charitable_donations

        # Annual donation stat should be recalculated
        self.assertGreater(year2_donation_stat, 0)

    def test_multiple_dafs(self):
        """Test person with multiple DAFs"""
        daf1 = DonorAdvisedFund(self.person, "DAF 1", balance=50000)
        daf2 = DonorAdvisedFund(self.person, "DAF 2", balance=30000)

        self.assertEqual(len(self.person.donor_advised_funds), 2)

        # Contribute to both
        daf1.contribute(5000)
        daf2.contribute(3000)

        # Total charitable deduction should include both contributions
        total_deduction = sum(d.stat_contributions_this_year for d in self.person.donor_advised_funds)
        self.assertEqual(total_deduction, 8000)

    def test_daf_with_zero_distribution_rate(self):
        """Test DAF that doesn't auto-distribute"""
        daf = DonorAdvisedFund(
            self.person,
            "No Auto Dist",
            balance=100000,
            distribution_rate=0,
            growth_rate=7.0
        )

        self.model.step()

        # Should have no distributions
        self.assertEqual(daf.stat_charitable_donations, 0)

        # But should still grow
        self.assertGreater(daf.balance, 100000)

    def test_person_charitable_deductions_with_daf(self):
        """Test person's charitable deductions include DAF contributions"""
        daf = DonorAdvisedFund(self.person, "Deduction DAF", balance=0)

        # Make a contribution
        daf.contribute(15000)

        # Should be included in charitable deductions
        self.assertGreaterEqual(self.person.charitable_deductions, 15000)


if __name__ == '__main__':
    unittest.main()
