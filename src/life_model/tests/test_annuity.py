# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest

from ..account.bank import BankAccount
from ..insurance.annuity import Annuity, AnnuityPayoutType, AnnuityType
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending


class TestAnnuity(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures"""
        self.model = LifeModel(start_year=2023, end_year=2030)
        self.family = Family(self.model)
        self.john = Person(
            family=self.family, name="John", age=45, retirement_age=65, spending=Spending(self.model, base=50000)
        )
        # Set up bank accounts
        BankAccount(owner=self.john, company="Bank", balance=100000)

    def test_fixed_deferred_annuity_creation(self):
        """Test creating a fixed deferred annuity"""
        annuity = Annuity(
            person=self.john,
            annuity_type=AnnuityType.FIXED,
            initial_balance=50000,
            interest_rate=4.0,
            payout_start_age=65,
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
            person=self.john, annuity_type=AnnuityType.DEFERRED, initial_balance=100000, interest_rate=5.0
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
            payout_start_age=45,  # Same as current age
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
            person=self.john, annuity_type=AnnuityType.IMMEDIATE, initial_balance=100000, interest_rate=4.0
        )

        self.assertFalse(annuity.is_annuitized)

        annuity.pre_step()

        self.assertTrue(annuity.is_annuitized)
        self.assertIsNotNone(annuity.monthly_payout)


class TestAnnuityReserveAndTaxation(unittest.TestCase):
    """Annuitization reserve conversion, auto-annuitization, and payout taxation."""

    def setUp(self):
        self.model = LifeModel(start_year=2023, end_year=2040)
        self.family = Family(self.model)
        self.john = Person(
            family=self.family, name="John", age=65, retirement_age=65, spending=Spending(self.model, base=50000)
        )
        BankAccount(owner=self.john, company="Bank", balance=100000)

    def test_fixed_annuity_auto_annuitizes_at_payout_age(self):
        """A FIXED annuity must auto-annuitize once payout age is reached."""
        annuity = Annuity(
            person=self.john,
            annuity_type=AnnuityType.FIXED,
            initial_balance=50000,
            interest_rate=4.0,
            payout_start_age=65,
        )
        self.assertFalse(annuity.is_annuitized)
        annuity.pre_step()
        self.assertTrue(annuity.is_annuitized)

    def test_fixed_annuity_does_not_annuitize_before_payout_age(self):
        """A FIXED annuity must not annuitize before payout age."""
        young = Person(
            family=self.family, name="Kid", age=40, retirement_age=65, spending=Spending(self.model, base=1000)
        )
        BankAccount(owner=young, company="Bank", balance=1000)
        annuity = Annuity(
            person=young,
            annuity_type=AnnuityType.FIXED,
            initial_balance=50000,
            interest_rate=4.0,
            payout_start_age=65,
        )
        annuity.pre_step()
        self.assertFalse(annuity.is_annuitized)

    def test_surrender_after_annuitize_returns_zero(self):
        """Once annuitized, surrender() must not recover the balance (no double payment)."""
        annuity = Annuity(
            person=self.john,
            annuity_type=AnnuityType.IMMEDIATE,
            initial_balance=100000,
            interest_rate=4.0,
        )
        annuity.pre_step()
        self.assertTrue(annuity.is_annuitized)
        bank_before = self.john.bank_account_balance
        self.assertEqual(annuity.surrender(), 0.0)
        # No cash created by surrendering an annuitized contract.
        self.assertEqual(self.john.bank_account_balance, bank_before)

    def test_annuitized_reserve_drains_and_balance_is_zero(self):
        """Annuitizing converts the balance to a reserve that drains as payouts are made."""
        annuity = Annuity(
            person=self.john,
            annuity_type=AnnuityType.IMMEDIATE,
            initial_balance=100000,
            interest_rate=3.0,
            payout_type=AnnuityPayoutType.LIFE_ONLY,
        )
        annuity.pre_step()
        # After annuitization the withdrawable balance is gone; value sits in the reserve.
        self.assertEqual(annuity.balance, 0.0)
        self.assertGreater(annuity.annuitized_reserve, 0.0)
        reserve_after_first = annuity.annuitized_reserve
        # Run several more years of payouts; reserve must strictly decrease over time.
        for _ in range(5):
            annuity.step()
            annuity.pre_step()
        self.assertLess(annuity.annuitized_reserve, reserve_after_first)

    def test_period_certain_factor_exceeds_life_only(self):
        """A life-with-period-certain annuity is worth more than life-only (factor monotonicity)."""
        from ..insurance.annuity import calculate_annuity_factor

        life_only = calculate_annuity_factor(65, 3.0, AnnuityPayoutType.LIFE_ONLY)
        period_certain = calculate_annuity_factor(
            65, 3.0, AnnuityPayoutType.LIFE_WITH_PERIOD_CERTAIN, period_certain_years=20
        )
        self.assertGreater(period_certain, life_only)

    def test_annuity_payout_is_taxed_via_exclusion_ratio(self):
        """Payouts route the gains portion to the income ledger."""
        annuity = Annuity(
            person=self.john,
            annuity_type=AnnuityType.IMMEDIATE,
            initial_balance=100000,
            interest_rate=3.0,
        )
        annuity.pre_step()  # annuitizes and pays out the first year
        total_payout = annuity.stat_payouts_received
        self.assertGreater(total_payout, 0)
        taxable = self.john.taxable_income
        # Exclusion ratio: only the gains portion is taxable, so 0 < taxable < total payout.
        self.assertGreater(taxable, 0)
        self.assertLess(taxable, total_payout)

    def test_annuity_interest_rate_from_config(self):
        """Annuity default interest rate is config-driven (scenario override)."""
        from pathlib import Path

        from ..config.financial_config import FinancialConfig

        cfg = FinancialConfig(config_file=str(Path(__file__).parent / "fixtures" / "test_config.yaml"))
        cfg.apply_scenario("custom", {"insurance": {"annuity": {"default_interest_rate": 9.5}}})
        model = LifeModel(start_year=2023, end_year=2030, config=cfg)
        family = Family(model)
        person = Person(family=family, name="P", age=50, retirement_age=65, spending=Spending(model, base=1000))
        BankAccount(owner=person, company="Bank", balance=1000)
        annuity = Annuity(person=person, annuity_type=AnnuityType.DEFERRED, initial_balance=1000)
        self.assertEqual(annuity.interest_rate, 9.5)


if __name__ == "__main__":
    unittest.main()
