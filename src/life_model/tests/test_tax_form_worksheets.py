# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Plan 31's tax functions against the forms' worked numbers.

Dollar assertions read published years (2024-2026) of the packaged ``tax_years`` table: those values
are history (each verified against its Rev. Proc. / IRS notice), so they do not drift when a later year
is added. Expected values are worked by hand in each test's comment.
"""

import unittest

from ..config.financial_config import default_financial_config
from ..tax.amt import AMTInputs, alternative_minimum_tax, minimum_tax_credit_allowed, minimum_tax_credit_generated
from ..tax.credits import (
    ReturnFacts,
    Student,
    child_tax_credit_parts,
    dependent_care_credit,
    dependent_care_rate,
    earned_income_credit,
    education_credits,
    eic_table_amount,
    excluded_dependent_care_benefits,
    savers_credit,
    savers_credit_rate,
)
from ..tax.federal import FilingStatus
from ..tax.qbi import qbi_deduction
from ..tax.self_employment import self_employed_plan_contribution, self_employment_tax

S, J, H, M = (
    FilingStatus.SINGLE,
    FilingStatus.MARRIED_FILING_JOINTLY,
    FilingStatus.HEAD_OF_HOUSEHOLD,
    FilingStatus.MARRIED_FILING_SEPARATELY,
)


def year(y: int):
    config = default_financial_config()
    return config.year_view(config.tax_year(y))


class TestEarnedIncomeCredit(unittest.TestCase):
    def setUp(self):
        self.p24 = year(2024).tax.federal.eitc

    def test_rows_of_the_published_2024_table(self):
        """Rows of the 2024 EIC Table (Form 1040 instructions), single and joint columns."""
        self.assertEqual([eic_table_amount(1, n, False, self.p24) for n in range(4)], [2, 9, 10, 11])
        self.assertEqual(eic_table_amount(12320, 0, False, self.p24), 479)  # 12,300-12,350
        self.assertEqual(eic_table_amount(12360, 1, False, self.p24), 4213)  # band holding the $12,390 kink
        self.assertEqual(eic_table_amount(17260, 0, True, self.p24), 630)  # joint, band starting at the threshold

    def test_phaseout_uses_the_smaller_of_earned_income_and_agi(self):
        # Two children, earned $28,000: 6,960 - 21.06% x (28,025 - 22,720) = 5,842.77 -> 5,843. With $2,000 of
        # interest AGI is $30,000: 6,960 - 21.06% x (30,025 - 22,720) = 5,421.57 -> 5,422 (the smaller).
        self.assertEqual(earned_income_credit(28000, 28000, 2, S, self.p24), 5843)
        self.assertEqual(earned_income_credit(28000, 30000, 2, S, self.p24, investment_income=2000), 5422)

    def test_disqualifications(self):
        self.assertEqual(earned_income_credit(15000, 15000, 1, M, self.p24), 0)  # separate return
        self.assertEqual(earned_income_credit(15000, 15000, 1, S, self.p24, investment_income=11601), 0)
        # No qualifying child: a filer must be 25-64.
        self.assertEqual(earned_income_credit(9000, 9000, 0, S, self.p24, ages=[24]), 0)
        self.assertGreater(earned_income_credit(9000, 9000, 0, S, self.p24, ages=[30]), 0)


class TestChildTaxCredit(unittest.TestCase):
    def test_schedule_8812_part_ii_a(self):
        # 2024, two children, tax 613 (nonrefundable), earned income $28,000: line 16a = 4,000 - 613 = 3,387,
        # 16b = 3,400, line 20 = 15% x 25,500 = 3,825 -> refundable 3,387.
        cfg = year(2024)
        self.assertEqual(child_tax_credit_parts(2, 28000, 613, H, cfg, earned_income=28000), (613, 3387))
        # Earned income $10,000: line 20 = 15% x 7,500 = 1,125 limits the refundable part.
        self.assertEqual(child_tax_credit_parts(2, 10000, 0, H, cfg, earned_income=10000), (0, 1125))

    def test_three_children_part_ii_b(self):
        # Three children, no tax, earned $12,000 (line 20 = 1,425), payroll taxes 918 + EIC 0: 25 = 918 < 1,425.
        cfg = year(2024)
        self.assertEqual(child_tax_credit_parts(3, 12000, 0, S, cfg, earned_income=12000, payroll_taxes=918), (0, 1425))
        # Payroll taxes of 2,000 with an EIC of 100: line 25 = 1,900 beats line 20.
        parts = child_tax_credit_parts(3, 12000, 0, S, cfg, earned_income=12000, payroll_taxes=2000, eitc=100)
        self.assertEqual(parts, (0, 1900))

    def test_credit_for_other_dependents(self):
        # One CTC child and one 17-year-old: 2,200 + 500 = 2,700 (2026), all nonrefundable with enough tax.
        cfg = year(2026)
        self.assertEqual(
            child_tax_credit_parts(1, 90000, 5000, S, cfg, other_dependents=1, earned_income=90000), (2700, 0)
        )
        # Only other dependents: nothing refundable.
        self.assertEqual(
            child_tax_credit_parts(0, 90000, 100, S, cfg, other_dependents=1, earned_income=90000), (100, 0)
        )


class TestDependentCare(unittest.TestCase):
    def test_rate_tables(self):
        p24, p26 = year(2024).tax.federal.dependent_care, year(2026).tax.federal.dependent_care
        self.assertEqual(dependent_care_rate(15000, False, p24), 35)
        self.assertEqual(dependent_care_rate(15001, False, p24), 34)  # "or fraction thereof"
        self.assertEqual(dependent_care_rate(43001, False, p24), 20)
        # 2026 (OBBBA §70405): 50% down to 35% by $45,000; joint from $150,000 one point per $4,000.
        self.assertEqual(dependent_care_rate(15000, True, p26), 50)
        self.assertEqual(dependent_care_rate(110000, True, p26), 35)
        self.assertEqual(dependent_care_rate(160000, True, p26), 32)  # 35 - ceil(10,000 / 4,000)
        self.assertEqual(dependent_care_rate(160000, False, p26), 20)  # single: floors at 20

    def test_fsa_exclusion_reduces_the_limit(self):
        cfg = year(2024)
        params = cfg.tax.federal.dependent_care
        excluded = excluded_dependent_care_benefits(5000, 24000, [65000, 45000], J, params)
        self.assertEqual(excluded, 5000)
        facts = ReturnFacts(
            2024,
            J,
            110000,
            10000,
            earned_income=[65000, 45000],
            care_persons=2,
            care_expenses=24000,
            excluded_care_benefits=excluded,
        )
        self.assertEqual(dependent_care_credit(facts, cfg).nonrefundable, 200)  # (6,000 - 5,000) x 20%
        # The lower earner's earned income caps the expenses.
        facts.earned_income = [65000, 600]
        facts.excluded_care_benefits = 0.0
        self.assertEqual(dependent_care_credit(facts, cfg).nonrefundable, 120)


class TestEducationAndSavers(unittest.TestCase):
    def test_aotc_phaseout_and_llc_after_four_years(self):
        cfg = year(2025)
        facts = ReturnFacts(2025, J, 170000, 20000, students=[Student(10000)])
        line = education_credits(facts, cfg)
        # 2,500 x (180,000 - 170,000) / 20,000 = 1,250; 40% refundable.
        self.assertAlmostEqual(line.refundable, 500)
        self.assertAlmostEqual(line.nonrefundable, 750)
        facts = ReturnFacts(2025, S, 50000, 20000, students=[Student(10000, aotc_years_claimed=4)])
        self.assertEqual(education_credits(facts, cfg).nonrefundable, 2000)  # LLC: 20% x 10,000

    def test_savers_credit_tiers_and_sunset(self):
        cfg = year(2024)
        params = cfg.tax.federal.savers_credit
        self.assertEqual(savers_credit_rate(46000, J, params), 50)
        self.assertEqual(savers_credit_rate(46001, J, params), 20)
        self.assertEqual(savers_credit_rate(37500, H, params), 20)
        self.assertEqual(savers_credit_rate(38251, S, params), 0)
        facts = ReturnFacts(2024, S, 24000, 1000, ages=[30], savers_contributions=[5000])
        self.assertEqual(savers_credit(facts, cfg).nonrefundable, 400)  # 20% x 2,000
        facts.ages = [17]
        self.assertEqual(savers_credit(facts, cfg).total, 0)
        # SECURE 2.0 §103: replaced by the Saver's Match from 2027.
        late = ReturnFacts(2027, S, 24000, 1000, ages=[30], savers_contributions=[5000])
        self.assertEqual(savers_credit(late, year(2027)).total, 0)


class TestAMT(unittest.TestCase):
    def test_iso_exercise_2024_and_2026(self):
        # Single, $200,000 wages, a $400,000 ISO spread held. 2024: AMTI 185,400 + 14,600 + 400,000 = 600,000
        # (under the $609,350 phase-out) - 85,700 = 514,300 -> 28% x 514,300 - 4,652 = 139,352.
        cfg = year(2024)
        inputs = AMTInputs(taxable_income=185400, deduction_addback=14600, iso_adjustment=400000, regular_tax=37538.5)
        result = alternative_minimum_tax(inputs, S, cfg.tax.federal.amt)
        self.assertAlmostEqual(result.tentative_minimum_tax, 139352)
        self.assertAlmostEqual(result.amt, 139352 - 37538.5)
        # 2026 (OBBBA): the exemption phases out at 50% over $500,000: 90,100 - 50,000 = 40,100.
        cfg26 = year(2026)
        inputs26 = AMTInputs(taxable_income=183900, deduction_addback=16100, iso_adjustment=400000, regular_tax=36734)
        result26 = alternative_minimum_tax(inputs26, S, cfg26.tax.federal.amt)
        self.assertAlmostEqual(result26.exemption, 40100)
        self.assertAlmostEqual(result26.tentative_minimum_tax, 559900 * 0.28 - 4890)
        # Only the deferral item (the ISO) creates a credit: exclusion-only AMTI 200,000 -> no AMT.
        exclusion = alternative_minimum_tax(inputs26, S, cfg26.tax.federal.amt, include_deferral_items=False)
        self.assertEqual(minimum_tax_credit_generated(result26, exclusion, 36734), result26.amt)

    def test_part_iii_capital_gains(self):
        # 2024 single, AMTI = 300,000 of which 100,000 long-term gain; regular ordinary 185,400 - 100,000.
        cfg = year(2024)
        inputs = AMTInputs(
            taxable_income=200000,
            deduction_addback=14600,
            iso_adjustment=85400,
            preferential_income=100000,
            regular_taxable_ordinary=100000,
        )
        result = alternative_minimum_tax(inputs, S, cfg.tax.federal.amt, cfg.get_capital_gains_brackets(S))
        # Line 6 = 300,000 - 85,700 = 214,300; 17 = 114,300 x 26% = 29,718; 15% on 100,000 (the 0% band is
        # used up by the 100,000 regular ordinary income): 15,000. Line 40 = min(44,718, 26% x 214,300 = 55,718).
        self.assertAlmostEqual(result.tentative_minimum_tax, 29718 + 15000)

    def test_minimum_tax_credit_limit(self):
        self.assertEqual(minimum_tax_credit_allowed(100000, 37067, 29094), 7973)
        self.assertEqual(minimum_tax_credit_allowed(5000, 37067, 29094), 5000)
        self.assertEqual(minimum_tax_credit_allowed(5000, 20000, 29094), 0)


class TestQBI(unittest.TestCase):
    def test_below_threshold_form_8995(self):
        params = year(2024).tax.federal.qbi
        result = qbi_deduction(111522.27, 96922.27, 0, S, params)
        self.assertAlmostEqual(result.deduction, 19384.454, places=3)  # 20% x taxable income (smaller)

    def test_above_threshold_without_wages_phases_out(self):
        params = year(2024).tax.federal.qbi
        # Halfway through the $50,000 range with no W-2 wages or UBIA: 20% x 100,000 = 20,000 reduced by half.
        result = qbi_deduction(100000, 191950 + 25000, 0, S, params)
        self.assertAlmostEqual(result.deduction, 10000)
        # An SSTB counts only half its QBI, then the same reduction: 10,000 - 5,000 = 5,000.
        self.assertAlmostEqual(qbi_deduction(100000, 191950 + 25000, 0, S, params, sstb=True).deduction, 5000)
        self.assertEqual(qbi_deduction(100000, 300000, 0, S, params).deduction, 0)

    def test_2026_minimum_deduction(self):
        params = year(2026).tax.federal.qbi
        # 20% x 1,500 = 300 -> the $400 minimum for at least $1,000 of active QBI (§199A(i), OBBBA).
        self.assertEqual(qbi_deduction(1500, 50000, 0, S, params).deduction, 400)
        self.assertEqual(qbi_deduction(900, 50000, 0, S, params).deduction, 180)


class TestSelfEmploymentTax(unittest.TestCase):
    def test_pub_560_worksheet_numbers(self):
        # Pub. 560 (2025) example: $200,000 profit -> SE deduction $13,596 (net earnings 184,700; SS capped
        # at the 2025 base 176,100: 21,836.40 + Medicare 5,356.30 = 27,192.70; half 13,596.35).
        cfg = year(2025)
        se = self_employment_tax(200000, 0, cfg)
        self.assertAlmostEqual(se.net_earnings, 184700)
        self.assertAlmostEqual(se.deduction, 13596.35)
        # Pub. 560's rate table: a 10% plan rate is 0.090909 for the self-employed.
        plan = self_employed_plan_contribution(200000, se.deduction, 10, cfg)
        self.assertAlmostEqual(plan.employer, (200000 - 13596.35) * 0.090909, places=4)

    def test_wage_base_shared_with_w2_wages(self):
        # 2025: $150,000 of W-2 SS wages leaves 26,100 of the base: SS 12.4% x 26,100 = 3,236.40.
        se = self_employment_tax(100000, 150000, year(2025))
        self.assertAlmostEqual(se.social_security, 3236.40)
        self.assertAlmostEqual(se.medicare, 92350 * 0.029)
        self.assertEqual(self_employment_tax(400, 0, year(2025)).total, 0)  # net earnings under $400

    def test_plan_limits(self):
        cfg = year(2024)
        # 25% plan rate on a $600,000 profit: 20% of net earnings exceeds 415(c) $69,000.
        se = self_employment_tax(600000, 0, cfg)
        self.assertEqual(self_employed_plan_contribution(600000, se.deduction, 25, cfg).employer, 69000)
        # A solo 401(k): deferrals use the 402(g) room first, the employer part fills 415(c).
        plan = self_employed_plan_contribution(
            150000, 10597.17, 25, cfg, elective_pretax_wanted=23000, elective_room=23000
        )
        self.assertEqual(plan.elective_pretax, 23000)
        self.assertAlmostEqual(plan.employer, (150000 - 10597.17) * 0.2)
        self.assertAlmostEqual(plan.deductible, plan.employer + 23000)


if __name__ == "__main__":
    unittest.main()
