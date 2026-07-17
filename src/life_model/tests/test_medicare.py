# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for AGI history recording and the Medicare/IRMAA agent."""

import unittest

from ..account.bank import BankAccount
from ..healthcare import Medicare
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..tax.income import IncomeType


def _flat_model(start_year=2026, end_year=2040):
    """A model with zero CPI and zero medical inflation premium so factors are exactly 1.0."""
    from ..config.financial_config import FinancialConfig

    cfg = FinancialConfig()
    cfg.apply_scenario("flat", {"economy": {"inflation": 0.0}, "healthcare": {"medical_inflation_premium": 0.0}})
    return LifeModel(start_year=start_year, end_year=end_year, config=cfg)


def _make_person(model, age, balance=5_000_000):
    family = Family(model)
    person = Person(family=family, name="P", age=age, retirement_age=90, spending=Spending(model, base=0))
    BankAccount(owner=person, company="Bank", balance=balance)
    return person


class TestAGIHistory(unittest.TestCase):
    def test_settle_year_records_agi(self):
        """TaxUnit.settle_year records the unit's AGI (income - deductions, floored at 0)."""
        model = LifeModel(start_year=2026, end_year=2027)
        person = _make_person(model, age=40)
        person.income.add(IncomeType.ORDINARY, 100000)
        model.step()
        deductions = person.federal_deductions
        self.assertIn(2026, person.agi_history)
        self.assertAlmostEqual(person.agi_history[2026], 100000 - deductions, places=2)

    def test_agi_floored_at_zero(self):
        """AGI never goes negative when deductions exceed income."""
        model = LifeModel(start_year=2026, end_year=2027)
        person = _make_person(model, age=40)
        model.step()
        self.assertEqual(person.agi_history[2026], 0.0)

    def test_married_couple_both_record_unit_agi(self):
        """Both spouses record the joint return's AGI (not a split)."""
        model = LifeModel(start_year=2026, end_year=2027)
        family = Family(model)
        a = Person(family=family, name="A", age=40, retirement_age=90, spending=Spending(model, base=0))
        b = Person(family=family, name="B", age=40, retirement_age=90, spending=Spending(model, base=0))
        BankAccount(owner=a, company="Bank", balance=1_000_000)
        a.get_married(b)
        a.income.add(IncomeType.ORDINARY, 150000)
        b.income.add(IncomeType.ORDINARY, 50000)
        model.step()
        self.assertEqual(a.agi_history[2026], b.agi_history[2026])
        self.assertGreater(a.agi_history[2026], 0)


class TestMedicare(unittest.TestCase):
    def test_not_eligible_before_65_no_charge(self):
        """No premiums are charged before the eligibility age."""
        model = _flat_model()
        person = _make_person(model, age=50)
        medicare = Medicare(person)
        model.step()
        self.assertEqual(medicare.stat_medical_costs, 0.0)
        self.assertEqual(person.stat_money_spent, 0.0)

    def test_below_threshold_pays_base_premium(self):
        """MAGI below the first IRMAA threshold pays base Part B + Part D only."""
        model = _flat_model()
        person = _make_person(model, age=70)
        person.agi_history[model.year - 2] = 50000
        medicare = Medicare(person)
        cfg = model.config.healthcare.medicare
        expected = (cfg.irmaa_tiers[0].part_b_monthly + cfg.part_d_base_monthly_premium) * 12
        self.assertAlmostEqual(medicare.annual_premium(), expected, places=6)

    def test_one_tier_over_pays_base_plus_surcharge(self):
        """MAGI one dollar over the first threshold pays the tier-1 premium + Part D surcharge."""
        model = _flat_model()
        person = _make_person(model, age=70)
        cfg = model.config.healthcare.medicare
        person.agi_history[model.year - 2] = cfg.irmaa_tiers[1].magi_min_single + 1
        medicare = Medicare(person)
        tier1 = cfg.irmaa_tiers[1]
        expected = (tier1.part_b_monthly + cfg.part_d_base_monthly_premium + tier1.part_d_monthly_surcharge) * 12
        self.assertAlmostEqual(medicare.annual_premium(), expected, places=6)

    def test_exactly_at_threshold_stays_in_lower_tier(self):
        """IRMAA applies only when MAGI exceeds the threshold (a cliff, not >=)."""
        model = _flat_model()
        person = _make_person(model, age=70)
        cfg = model.config.healthcare.medicare
        person.agi_history[model.year - 2] = cfg.irmaa_tiers[1].magi_min_single
        medicare = Medicare(person)
        expected = (cfg.irmaa_tiers[0].part_b_monthly + cfg.part_d_base_monthly_premium) * 12
        self.assertAlmostEqual(medicare.annual_premium(), expected, places=6)

    def test_mfj_uses_married_thresholds(self):
        """A married person is assessed against the MFJ threshold column."""
        model = _flat_model()
        family = Family(model)
        a = Person(family=family, name="A", age=70, retirement_age=65, spending=Spending(model, base=0))
        b = Person(family=family, name="B", age=70, retirement_age=65, spending=Spending(model, base=0))
        BankAccount(owner=a, company="Bank", balance=1_000_000)
        a.get_married(b)
        cfg = model.config.healthcare.medicare
        # A MAGI over the single threshold but under the MFJ threshold stays at the base premium.
        magi = cfg.irmaa_tiers[1].magi_min_single + 1000
        self.assertLess(magi, cfg.irmaa_tiers[1].magi_min_married_filing_jointly)
        a.agi_history[model.year - 2] = magi
        medicare = Medicare(a)
        expected = (cfg.irmaa_tiers[0].part_b_monthly + cfg.part_d_base_monthly_premium) * 12
        self.assertAlmostEqual(medicare.annual_premium(), expected, places=6)

    def test_lookback_uses_year_minus_two(self):
        """Raising year-N AGI above a tier boundary raises premiums in year N+2 exactly."""
        model = _flat_model(start_year=2026, end_year=2032)
        person = _make_person(model, age=66)
        medicare = Medicare(person)
        cfg = model.config.healthcare.medicare
        base_annual = (cfg.irmaa_tiers[0].part_b_monthly + cfg.part_d_base_monthly_premium) * 12
        tier1 = cfg.irmaa_tiers[1]
        tier1_annual = (tier1.part_b_monthly + cfg.part_d_base_monthly_premium + tier1.part_d_monthly_surcharge) * 12

        premiums_by_year = {}
        # One-time income spike in 2028 pushes that year's AGI into (only) the first IRMAA tier.
        for _ in model.get_year_range():
            if model.year == 2028:
                person.income.add(IncomeType.ORDINARY, 130000)
            model.step()
            premiums_by_year[model.year - 1] = medicare.stat_medical_costs

        self.assertGreater(person.agi_history[2028], tier1.magi_min_single)
        self.assertLess(person.agi_history[2028], cfg.irmaa_tiers[2].magi_min_single)
        # 2029 (lookback to 2027, AGI 0) still pays base; 2030 (lookback to 2028) pays tier 1;
        # 2031 (lookback to 2029, AGI 0) drops back to base.
        self.assertAlmostEqual(premiums_by_year[2029], base_annual, places=6)
        self.assertAlmostEqual(premiums_by_year[2030], tier1_annual, places=6)
        self.assertAlmostEqual(premiums_by_year[2031], base_annual, places=6)

    def test_lookback_falls_back_to_earliest_available(self):
        """With no year-2 record, the earliest recorded AGI is used; with none at all, 0."""
        model = _flat_model()
        person = _make_person(model, age=70)
        medicare = Medicare(person)
        self.assertEqual(medicare.lookback_magi(), 0.0)
        person.agi_history[model.year - 1] = 250000  # only last year recorded
        self.assertEqual(medicare.lookback_magi(), 250000)

    def test_premium_flows_through_settlement(self):
        """The premium lands in stat_money_spent via the bill path."""
        model = _flat_model()
        person = _make_person(model, age=70)
        Medicare(person)
        model.step()
        cfg = model.config.healthcare.medicare
        expected = (cfg.irmaa_tiers[0].part_b_monthly + cfg.part_d_base_monthly_premium) * 12
        self.assertAlmostEqual(person.stat_money_spent, expected, places=2)


class TestWidowIRMAACliff(unittest.TestCase):
    """Pins the (intentional) widow IRMAA cliff documented in medicare.py.

    A recent widow(er) files SINGLE while the two-year lookback still holds joint-era AGI, so
    identical income history is measured against the roughly half-sized single thresholds and
    premiums jump. Real-world SSA life-changing-event reassessment is not modeled.
    """

    def test_widow_pays_more_on_identical_joint_era_agi(self):
        from ..tax.federal import FilingStatus

        model = _flat_model()
        cfg = model.config.healthcare.medicare
        # Joint-era AGI: below the MFJ tier-1 threshold, but inside the SINGLE tier-1 band
        # (above the single tier-1 threshold, below the single tier-2 threshold).
        joint_agi = (cfg.irmaa_tiers[1].magi_min_single + cfg.irmaa_tiers[2].magi_min_single) / 2
        self.assertLess(joint_agi, cfg.irmaa_tiers[1].magi_min_married_filing_jointly)

        person = _make_person(model, age=70)
        person.agi_history[model.year - 2] = joint_agi
        medicare = Medicare(person)

        # While married (MFJ thresholds): base premium.
        person.filing_status = FilingStatus.MARRIED_FILING_JOINTLY
        base = (cfg.irmaa_tiers[0].part_b_monthly + cfg.part_d_base_monthly_premium) * 12
        self.assertAlmostEqual(medicare.annual_premium(), base, places=6)

        # Newly widowed (SINGLE thresholds, same lookback AGI): tier-1 surcharge applies.
        person.filing_status = FilingStatus.SINGLE
        tier1 = cfg.irmaa_tiers[1]
        surcharged = (tier1.part_b_monthly + cfg.part_d_base_monthly_premium + tier1.part_d_monthly_surcharge) * 12
        self.assertAlmostEqual(medicare.annual_premium(), surcharged, places=6)
        self.assertGreater(surcharged, base)


if __name__ == "__main__":
    unittest.main()
