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


class TestAnnuityPerModelConfig(unittest.TestCase):
    """Annuity pricing reads the owning model's config, not a process-global one."""

    @staticmethod
    def _short_horizon_config():
        from ..config.financial_config import FinancialConfig

        cfg = FinancialConfig()
        cfg.apply_scenario("short_horizon", {"insurance": {"annuity": {"max_projection_age": 75}}})
        return cfg

    def test_life_expectancy_honors_explicit_config(self):
        from ..insurance.annuity import calculate_life_expectancy

        short = calculate_life_expectancy(65, config=self._short_horizon_config())
        default = calculate_life_expectancy(65)
        self.assertLessEqual(short, 10.0)  # capped by the 75-year horizon
        self.assertGreater(default, short)

    def _monthly_payout(self, config=None):
        model = LifeModel(start_year=2023, end_year=2030, config=config)
        person = Person(family=Family(model), name="P", age=65, retirement_age=65, spending=Spending(model, base=1000))
        BankAccount(owner=person, company="Bank", balance=1000)
        annuity = Annuity(
            person=person,
            annuity_type=AnnuityType.FIXED,
            initial_balance=100000,
            interest_rate=3.0,
            payout_start_age=65,
        )
        self.assertTrue(annuity.annuitize())
        return annuity.monthly_payout

    def test_models_with_different_annuity_config_price_differently(self):
        """A shorter actuarial horizon in one model means fewer expected payments, so a larger payout.

        The custom model is built first so any leak into shared state would also corrupt the default.
        """
        short_payout = self._monthly_payout(self._short_horizon_config())
        default_payout = self._monthly_payout()
        self.assertGreater(short_payout, default_payout)


if __name__ == "__main__":
    unittest.main()


class TestAnnuityDistributionTaxes(unittest.TestCase):
    """Pre-annuitization distributions: gains first (IRC §72(e)), 10% before 59.5 (§72(q))."""

    def _owner(self, age):
        model = LifeModel(start_year=2026, end_year=2026)
        person = Person(Family(model), "O", age=age, retirement_age=65, spending=Spending(model, 0))
        BankAccount(person, "Bank", balance=0, interest_rate=0)
        annuity = Annuity(
            person, AnnuityType.DEFERRED, initial_balance=50000, interest_rate=0, surrender_charge_years=0
        )
        annuity.balance = 60000  # $10k of gain over the $50k basis
        return person, annuity

    def test_withdrawal_is_gain_first_and_penalized_before_59_and_a_half(self):
        person, annuity = self._owner(age=50)
        self.assertEqual(annuity.withdraw(15000), 15000)
        self.assertAlmostEqual(person.income.ordinary_taxable, 10000)  # all of the gain
        self.assertAlmostEqual(person.income.penalties, 1000)
        self.assertAlmostEqual(annuity.basis, 45000)  # the other $5k returned basis
        self.assertAlmostEqual(person.bank_account_balance, 15000)

    def test_surrender_taxes_the_gain_without_penalty_after_59_and_a_half(self):
        person, annuity = self._owner(age=66)
        self.assertEqual(annuity.surrender(), 60000)
        self.assertAlmostEqual(person.income.ordinary_taxable, 10000)
        self.assertEqual(person.income.penalties, 0)


class TestJointAndSurvivor(unittest.TestCase):
    def _couple(self, *, husband_death_age=None, wife_death_age=None, start_year=2026, end_year=2027):
        from ..people.types import MortalityMode

        model = LifeModel(start_year=start_year, end_year=end_year)
        family = Family(model)

        def make(name, age, death_age):
            kwargs = {}
            if death_age is not None:
                kwargs = {"mortality_mode": MortalityMode.FIXED_AGE, "death_age": death_age}
            person = Person(family, name, age=age, retirement_age=60, spending=Spending(model, 0), **kwargs)
            BankAccount(person, "Bank", balance=0, interest_rate=0)
            return person

        husband = make("H", 70, husband_death_age)
        wife = make("W", 68, wife_death_age)
        husband.get_married(wife)
        return model, husband, wife

    def test_survivor_benefit_raises_the_price_of_each_payment(self):
        from ..insurance.annuity import calculate_annuity_factor

        life = calculate_annuity_factor(70, 3.0, AnnuityPayoutType.LIFE_ONLY)
        half = calculate_annuity_factor(
            70, 3.0, AnnuityPayoutType.JOINT_AND_SURVIVOR, joint_age=68, survivor_percent=50
        )
        full = calculate_annuity_factor(
            70, 3.0, AnnuityPayoutType.JOINT_AND_SURVIVOR, joint_age=68, survivor_percent=100
        )
        none = calculate_annuity_factor(70, 3.0, AnnuityPayoutType.JOINT_AND_SURVIVOR, joint_age=68, survivor_percent=0)
        self.assertLess(life, half)
        self.assertLess(half, full)
        self.assertAlmostEqual(none, life, delta=life * 0.01)  # 0% survivor ~ single life

    def test_annuitizing_without_a_joint_life_is_rejected(self):
        model = LifeModel(start_year=2026, end_year=2026)
        single = Person(Family(model), "S", age=70, retirement_age=60, spending=Spending(model, 0))
        annuity = Annuity(
            single, AnnuityType.IMMEDIATE, initial_balance=100000, payout_type=AnnuityPayoutType.JOINT_AND_SURVIVOR
        )
        with self.assertRaises(ValueError):
            annuity.annuitize()

    def test_survivor_receives_the_survivor_share_then_payments_stop(self):
        # Husband 70 dies at 72 (2027); wife 68 dies at 72 (2030).
        model, husband, wife = self._couple(husband_death_age=72, wife_death_age=72, end_year=2032)
        annuity = Annuity(
            husband,
            AnnuityType.IMMEDIATE,
            initial_balance=200000,
            interest_rate=3.0,
            payout_type=AnnuityPayoutType.JOINT_AND_SURVIVOR,
            survivor_percent=50,
        )
        model.step()  # 2026: annuitized, full payments
        full_monthly = annuity.monthly_payout
        self.assertAlmostEqual(annuity.stat_payouts_received, 12 * full_monthly, places=6)
        model.step()  # 2027: husband reaches 72 and dies
        self.assertTrue(husband.is_deceased)
        self.assertIs(annuity.person, wife)
        self.assertTrue(annuity.survivor_phase)
        before = annuity.stat_payouts_received
        model.step()  # 2028: the survivor share
        self.assertAlmostEqual(annuity.stat_payouts_received - before, 12 * full_monthly * 0.5, places=6)
        while not wife.is_deceased:
            model.step()
        self.assertFalse(annuity.is_active)


class TestAnnuityDeathTerms(unittest.TestCase):
    def _owner_with_heir(self, death_age, end_year=2045):
        from ..people.types import MortalityMode

        model = LifeModel(start_year=2026, end_year=end_year)
        family = Family(model)
        # Aged so the owner lives through the first simulated year and dies in the second.
        owner = Person(
            family,
            "O",
            age=death_age - 2,
            retirement_age=60,
            spending=Spending(model, 0),
            mortality_mode=MortalityMode.FIXED_AGE,
            death_age=death_age,
        )
        heir = Person(family, "H", age=40, retirement_age=70, spending=Spending(model, 0))
        owner.estate_beneficiary = heir
        for person in (owner, heir):
            BankAccount(person, "Bank", balance=0, interest_rate=0)
        return model, owner, heir

    def test_period_certain_pays_the_heir_only_until_the_guarantee_ends(self):
        model, owner, heir = self._owner_with_heir(death_age=71)
        annuity = Annuity(
            owner,
            AnnuityType.IMMEDIATE,
            initial_balance=500000,
            interest_rate=3.0,
            payout_type=AnnuityPayoutType.LIFE_WITH_PERIOD_CERTAIN,
            period_certain_years=5,
        )
        while annuity.is_active and model.year <= model.end_year:
            model.step()
        self.assertTrue(owner.is_deceased)
        self.assertIs(annuity.person, heir)
        self.assertEqual(annuity.remaining_period_certain_payments, 0)
        # Exactly the 60 guaranteed payments, even though reserve was left over.
        self.assertAlmostEqual(annuity.stat_payouts_received, 60 * annuity.monthly_payout, places=4)
        self.assertGreater(annuity.annuitized_reserve, 0)

    def test_accumulation_phase_value_paid_to_heir_with_gain_taxed(self):
        model, owner, heir = self._owner_with_heir(death_age=61, end_year=2027)
        annuity = Annuity(owner, AnnuityType.DEFERRED, initial_balance=80000, interest_rate=5.0, payout_start_age=70)
        model.step()  # 2026: grows 5%
        value = annuity.balance
        model.step()  # 2027: owner reaches 61 and dies
        self.assertTrue(owner.is_deceased)
        self.assertFalse(annuity.is_active)
        self.assertEqual(annuity.balance, 0.0)
        # The heir received the full contract value (taxes on the gain settled from it).
        self.assertGreater(heir.bank_account_balance, 0)
        self.assertLessEqual(heir.bank_account_balance, value)


class TestAnnuityReserveConservation(unittest.TestCase):
    def test_payouts_plus_reserve_equal_premium_plus_interest(self):
        model = LifeModel(start_year=2026, end_year=2045)
        person = Person(Family(model), "R", age=65, retirement_age=60, spending=Spending(model, 0))
        BankAccount(person, "Bank", balance=0, interest_rate=0)
        annuity = Annuity(
            person,
            AnnuityType.IMMEDIATE,
            initial_balance=250000,
            interest_rate=4.0,
            payout_type=AnnuityPayoutType.LIFE_ONLY,
        )
        model.run()
        self.assertAlmostEqual(
            annuity.stat_payouts_received + annuity.annuitized_reserve,
            250000 + annuity.stat_interest_earned,
            places=4,
        )
        self.assertGreater(annuity.stat_payouts_received, 0)


class TestTermLifeMultipliersFromConfig(unittest.TestCase):
    def test_age_multipliers_come_from_config(self):
        from ..config.financial_config import FinancialConfig
        from ..insurance.life_insurance import LifeInsurance, LifeInsuranceType

        config = FinancialConfig()
        config.apply_scenario("flat", {"insurance": {"life": {"term_age_multipliers": {20: 1.0, 90: 1.0}}}})
        model = LifeModel(start_year=2026, end_year=2026, config=config)
        person = Person(Family(model), "P", age=60, retirement_age=65, spending=Spending(model, 0))
        policy = LifeInsurance(person, LifeInsuranceType.TERM, 500000, 50.0, 20)
        # Scenario dicts deep-merge, so the age-90 point is added to the configured curve.
        self.assertEqual(policy.age_multipliers, dict(config.insurance.life.term_age_multipliers))
        self.assertEqual(policy.age_multipliers[90], 1.0)
