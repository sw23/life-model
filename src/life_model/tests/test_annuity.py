# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..account.bank import BankAccount
from ..insurance.annuity import Annuity, AnnuityType, AnnuityPayoutType


class TestAnnuity(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures"""
        self.model = LifeModel(start_year=2023, end_year=2030)
        self.family = Family(self.model)
        self.john = Person(
            family=self.family,
            name='John',
            age=45,
            retirement_age=65,
            spending=Spending(self.model, base=50000)
        )
        # Set up bank accounts
        BankAccount(owner=self.john, company='Bank', balance=100000)

    def test_fixed_deferred_annuity_creation(self):
        """Test creating a fixed deferred annuity"""
        annuity = Annuity(
            person=self.john,
            annuity_type=AnnuityType.FIXED,
            initial_balance=50000,
            interest_rate=4.0,
            payout_start_age=65
        )

        self.assertEqual(annuity.person, self.john)
        self.assertEqual(annuity.annuity_type, AnnuityType.FIXED)
        self.assertEqual(annuity.balance, 50000)
        self.assertEqual(annuity.interest_rate, 4.0)
        self.assertEqual(annuity.payout_start_age, 65)
        self.assertTrue(annuity.is_active)
        self.assertFalse(annuity.is_annuitized)
        self.assertEqual(annuity.payout_type, AnnuityPayoutType.LIFE_ONLY)

    def test_annuity_interest_growth(self):
        """Test interest growth on annuity balance"""
        annuity = Annuity(
            person=self.john,
            annuity_type=AnnuityType.DEFERRED,
            initial_balance=100000,
            interest_rate=5.0
        )

        initial_balance = annuity.balance
        annuity.step()

        # Should have grown by 5%
        expected_balance = initial_balance * 1.05
        self.assertAlmostEqual(annuity.balance, expected_balance, places=2)
        self.assertGreater(annuity.stat_interest_earned, 0)

    def test_annuity_annuitization(self):
        """Test converting annuity to income payments"""
        annuity = Annuity(
            person=self.john,
            annuity_type=AnnuityType.DEFERRED,
            initial_balance=200000,
            interest_rate=4.0,
            payout_start_age=45  # Same as current age
        )

        result = annuity.annuitize()

        self.assertTrue(result)
        self.assertTrue(annuity.is_annuitized)
        self.assertIsNotNone(annuity.monthly_payout)
        self.assertGreater(annuity.monthly_payout or 0, 0)
        self.assertEqual(annuity.annuitization_year, self.model.year)

    def test_immediate_annuity_auto_annuitization(self):
        """Test that immediate annuities auto-annuitize in pre_step"""
        annuity = Annuity(
            person=self.john,
            annuity_type=AnnuityType.IMMEDIATE,
            initial_balance=100000,
            interest_rate=4.0
        )

        self.assertFalse(annuity.is_annuitized)

        annuity.pre_step()

        self.assertTrue(annuity.is_annuitized)
        self.assertIsNotNone(annuity.monthly_payout)


if __name__ == '__main__':
    unittest.main()
