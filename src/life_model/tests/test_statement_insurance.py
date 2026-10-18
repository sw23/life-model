# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Plan 27 PR D: insurance, Social Security and spending entered from statements.

Life insurance, annuities and pensions already in force (D1), health cost sharing and disability income
(D9), Social Security's spousal benefit, full retirement age by birth year, PIA override and earnings
test (D10), spending categories, schedules, recurring expenses and per-child costs (D6). Dollar
assertions use the frozen fixture config; Social Security amounts are checked against SSA's published
rules (the spousal reduction table on ssa.gov/oact/quickcalc/earlyretire.html, the 2026 exempt amounts on
ssa.gov/oact/cola/rtea.html).
"""

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..account.pension import Pension
from ..account.traditional_IRA import TraditionalIRA
from ..config.financial_config import FinancialConfig
from ..dependents.child import Child
from ..healthcare.medical_costs import MedicalCosts
from ..insurance.annuity import Annuity, AnnuityType
from ..insurance.general_insurance import Insurance, InsuranceType
from ..insurance.life_insurance import LifeInsurance, LifeInsuranceType
from ..insurance.social_security import (
    SocialSecurity,
    earnings_test_exempt_amounts,
    full_retirement_age,
    spousal_reduction_factor,
)
from ..ledger import account_label, household_balance_sheet
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, RecurringExpense, Spending, SpendingLine
from ..tax.income import IncomeType
from ..work.job import Job, Salary

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _model(start="2026-01", end_year=2030, checks="off", config=None):
    return LifeModel(
        start=start, end_year=end_year, config=config or FinancialConfig(config_file=TEST_CONFIG), checks=checks
    )


def _person(model, *, birth="1966-01", bank=200000.0, spending=None, family=None, name="P", retirement_age=70):
    spending = spending if spending is not None else Spending(model, 0)
    person = Person(family or Family(model), name, None, retirement_age, spending, birth=birth)
    BankAccount(person, company="Bank", balance=bank, interest_pct=0)
    return person


class TestExistingLifePolicy(unittest.TestCase):
    """Acceptance (Plan 27 PR D): an existing whole-life policy with $20k cash value and a $5k loan."""

    def test_cash_value_and_loan_on_the_balance_sheet(self):
        model = _model(checks="strict")
        person = _person(model)
        policy = LifeInsurance(
            person,
            LifeInsuranceType.WHOLE,
            death_benefit=250000,
            premium_monthly=200,
            cash_value_growth_pct=4.0,
            loan_interest_pct=6.0,
            issue_year=2012,
            cash_value=20000,
            loan_balance=5000,
            premiums_paid=30000,
        )
        self.assertEqual(policy.policy_years_active, 14)
        self.assertEqual(household_balance_sheet(model).lines[account_label(policy)], 15000)
        self.assertEqual(policy.net_death_benefit, 245000)
        # The loan cap is a share of the cash value net of the loan.
        self.assertAlmostEqual(policy.available_cash_value, 15000, places=6)
        model.step_year()
        # Year 1: 60% of the $2,400 premium (a later policy year) plus 4% growth; the loan accrues 6%.
        self.assertAlmostEqual(policy.cash_value, (20000 + 2400 * 0.6) * 1.04, places=6)
        self.assertAlmostEqual(policy.outstanding_loan_balance, 5300, places=6)
        model.run()

    def test_existing_policy_mid_run_posts_its_opening_value(self):
        model = _model(checks="strict")
        person = _person(model)
        model.step()
        model.current_stage = "events"
        LifeInsurance(person, LifeInsuranceType.WHOLE, 100000, 100, cash_value=8000, loan_balance=1000)
        model.current_stage = None
        model.run()

    def test_term_policy_cannot_have_cash_value(self):
        model = _model()
        with self.assertRaises(ValueError):
            LifeInsurance(_person(model), LifeInsuranceType.TERM, 100000, 30, term_years=20, cash_value=10)

    def test_term_policy_expires_from_its_issue_year(self):
        model = _model(end_year=2028)
        policy = LifeInsurance(_person(model), LifeInsuranceType.TERM, 500000, 40, term_years=20, issue_year=2007)
        model.step_year()  # 2026: year 19
        self.assertTrue(policy.is_active)
        model.step_year()  # 2027: year 20, the term ends at the year end
        self.assertFalse(policy.is_active)


class TestExistingAnnuity(unittest.TestCase):
    def test_spia_in_payout_pays_for_life_without_a_reserve(self):
        model = _model(end_year=2040, checks="strict")
        person = _person(model, birth="1956-01")
        annuity = Annuity(
            person,
            annuity_type=AnnuityType.IMMEDIATE,
            payout_monthly=1500,
            basis=180000,
            purchase_year=2021,
            in_payout=True,
        )
        model.step_year()
        self.assertAlmostEqual(annuity.stat_payouts_received, 18000, places=6)
        taxable = 18000 * (1 - annuity.exclusion_ratio)
        self.assertAlmostEqual(annuity.stat_taxable_payouts, taxable, places=6)
        self.assertGreater(annuity.exclusion_ratio, 0)
        model.run()  # well past any reserve a made-up balance would have had
        self.assertTrue(annuity.is_active)

    def test_qualified_contract_is_fully_taxable(self):
        model = _model(end_year=2027)
        person = _person(model, birth="1955-01")
        annuity = Annuity(
            person, annuity_type=AnnuityType.IMMEDIATE, payout_monthly=1000, qualified=True, in_payout=True
        )
        for _ in range(11):  # (the income ledger is cleared at the year end)
            model.step()
        self.assertAlmostEqual(annuity.stat_taxable_payouts, 11000, places=6)
        pension_income = sum(e.amount for e in person.income.entries if e.income_type == IncomeType.PENSION)
        self.assertAlmostEqual(pension_income, 11000, places=6)

    def test_purchase_year_runs_the_surrender_clock(self):
        model = _model()
        annuity = Annuity(
            _person(model),
            annuity_type=AnnuityType.FIXED,
            balance=100000,
            surrender_charge_years=7,
            basis=80000,
            purchase_year=2020,
        )
        self.assertEqual(annuity.years_since_purchase, 6)
        self.assertTrue(annuity.is_in_surrender_period)
        self.assertEqual(annuity.basis, 80000)

    def test_cola_rider(self):
        model = _model(end_year=2027)
        annuity = Annuity(
            _person(model, birth="1955-01"),
            annuity_type=AnnuityType.IMMEDIATE,
            payout_monthly=1000,
            in_payout=True,
            cola_pct=2,
        )
        model.step_year()
        self.assertAlmostEqual(annuity.monthly_payout, 1020, places=6)


class TestPensionFromStatement(unittest.TestCase):
    def test_final_average_from_salary_history(self):
        model = _model()
        person = _person(model)
        history = {2019: 80000, 2020: 90000, 2021: 100000, 2022: 95000, 2023: 110000, 2024: 120000, 2025: 115000}
        pension = Pension(
            person,
            company="Co",
            vesting_years=5,
            years_of_service=20,
            benefit_multiplier_pct=1.5,
            salary_history=history,
            final_average_years=3,
        )
        # Highest three consecutive years: 2023-2025 (115,000 average).
        self.assertAlmostEqual(pension.final_salary, 115000, places=6)
        self.assertAlmostEqual(pension.benefit_amount, 20 * 0.015 * 115000, places=6)

    def test_early_retirement_reduction(self):
        model = _model(end_year=2027)
        person = _person(model, birth="1966-01")
        pension = Pension(
            person,
            company="Co",
            vesting_years=5,
            benefit_annual=24000,
            start_age=60,
            normal_retirement_age=65,
            early_reduction_pct_per_year=6,
        )
        model.step_year()
        # Starts at 60, five years early: 30% less.
        self.assertAlmostEqual(pension.stat_pension_income, 24000 * 0.7, places=6)

    def test_survivor_election_reduces_the_benefit(self):
        model = _model(end_year=2027)
        family = Family(model)
        retiree = _person(model, birth="1961-01", family=family)
        spouse = _person(model, birth="1963-01", family=family, name="S")
        retiree.get_married(spouse)
        fixed = Pension(
            retiree,
            company="Co",
            vesting_years=5,
            benefit_annual=30000,
            start_age=65,
            survivor_pct=50,
            survivor_reduction=10,
        )
        model.step_year()
        self.assertAlmostEqual(fixed.stat_pension_income, 27000, places=6)

    def test_actuarial_survivor_factor_is_below_one(self):
        model = _model()
        family = Family(model)
        retiree = _person(model, birth="1961-01", family=family)
        spouse = _person(model, birth="1963-01", family=family, name="S")
        retiree.get_married(spouse)
        pension = Pension(
            retiree,
            company="Co",
            vesting_years=5,
            benefit_annual=30000,
            survivor_pct=100,
            survivor_reduction="actuarial",
        )
        self.assertLess(pension.survivor_factor(), 1.0)
        self.assertGreater(pension.survivor_factor(), 0.7)

    def test_employee_basis_recovered_by_the_simplified_method(self):
        model = _model(end_year=2027)
        person = _person(model, birth="1961-01")
        pension = Pension(
            person, company="Co", vesting_years=5, benefit_annual=24000, start_age=65, employee_basis=26000
        )
        for _ in range(11):  # (the income ledger is cleared at the year end)
            model.step()
        # Age 65 at the start: 260 payments (Pub. 575 Table 1), $100 a month tax-free.
        self.assertAlmostEqual(pension.monthly_exclusion, 100, places=6)
        taxable = sum(e.amount for e in person.income.entries if e.income_type == IncomeType.PENSION)
        self.assertAlmostEqual(taxable, 11 * (2000 - 100), places=6)

    def test_lump_sum_rolls_into_an_ira(self):
        model = _model(end_year=2027, checks="strict")
        person = _person(model, birth="1961-01")
        ira = TraditionalIRA(person, balance=0)
        pension = Pension(
            person,
            company="Co",
            vesting_years=5,
            benefit_annual=24000,
            start_age=65,
            lump_sum=True,
            lump_sum_amount=300000,
            rollover_account=ira,
        )
        model.step_year()
        self.assertTrue(pension.paid_out)
        self.assertGreater(ira.balance, 300000)  # rolled in January, then grew
        taxable = sum(e.amount for e in person.income.entries if e.income_type == IncomeType.PENSION)
        self.assertEqual(taxable, 0)
        model.run()


class TestHealthAndDisability(unittest.TestCase):
    def test_health_policy_caps_medical_costs(self):
        model = _model(end_year=2026)
        person = _person(model, birth="1966-01")
        costs = MedicalCosts(person, annual_cost=24000)
        Insurance(
            person, InsuranceType.HEALTH, "Plan", 6000, 1e7, deductible=2000, oop_max_annual=5000, coinsurance_pct=20
        )
        model.step_year()
        # $24,000 of covered costs: $2,000 deductible + 20% of the rest would be $6,400; the cap is $5,000.
        self.assertAlmostEqual(costs.stat_medical_costs, 5000, places=6)
        self.assertAlmostEqual(costs.gross_costs_ytd, 24000, places=6)

    def test_health_policy_below_the_cap(self):
        model = _model(end_year=2026)
        person = _person(model, birth="1966-01")
        costs = MedicalCosts(person, annual_cost=6000)
        Insurance(
            person, InsuranceType.HEALTH, "Plan", 6000, 1e7, deductible=1000, oop_max_annual=8000, coinsurance_pct=20
        )
        model.step_year()
        self.assertAlmostEqual(costs.stat_medical_costs, 1000 + 0.2 * 5000, places=6)

    def test_disability_benefit_replaces_pay(self):
        model = _model(end_year=2027, checks="strict")
        person = _person(model, birth="1981-01")
        Job(person, company="Co", role="Eng", salary=Salary(model, base_annual=120000))
        policy = Insurance(
            person,
            InsuranceType.DISABILITY,
            "Ins",
            1500,
            0,
            benefit_pct=60,
            benefit_max_monthly=5000,
            elimination_months=3,
            benefits_taxable=True,
        )
        model.step()  # January's pay
        policy.start_disability_claim()
        for job in person.jobs:
            job.retire()
        model.step_year()
        # Filed in February (after January's step): 60% of $10,000 a month capped at $5,000, from May
        # (three months' elimination): 8 payments.
        self.assertAlmostEqual(policy.stat_disability_benefits, 40000, places=6)
        model.run()


class TestSocialSecurityStatement(unittest.TestCase):
    def test_full_retirement_age_by_birth_year(self):
        self.assertEqual(full_retirement_age(1954), 66)
        self.assertAlmostEqual(full_retirement_age(1957), 66.5)
        self.assertAlmostEqual(full_retirement_age(1959), 66 + 10 / 12)
        self.assertEqual(full_retirement_age(1960), 67)

    def test_spousal_reduction_table(self):
        # SSA: a $500 spousal benefit at 62 is $350 (36 months) for FRA 66 and $325 (60 months) for FRA 67.
        self.assertAlmostEqual(500 * spousal_reduction_factor(48), 350, places=6)
        self.assertAlmostEqual(500 * spousal_reduction_factor(60), 325, places=6)
        self.assertAlmostEqual(500 * spousal_reduction_factor(56), 333.33, places=2)

    def test_spousal_benefit_beats_the_low_earners_own(self):
        """Acceptance (Plan 27 PR D)."""
        model = _model(start="2027-01", end_year=2028)
        family = Family(model)
        high = _person(model, birth="1960-01", family=family, name="High")
        low = _person(model, birth="1960-01", family=family, name="Low")
        high.get_married(low)
        SocialSecurity(high, 67, pia_override_monthly=3000)
        low_ss = SocialSecurity(low, 67, pia_override_monthly=600, spousal_benefit=True)
        model.step()
        own = low_ss.get_pia()
        self.assertAlmostEqual(own, 600, places=2)
        # Both at FRA (67 in January 2027): 600 + (50% x 3,000 - 600) = 1,500.
        self.assertAlmostEqual(low_ss.monthly_benefit(), 1500, places=2)
        self.assertGreater(low_ss.monthly_benefit(), own)

    def test_early_spousal_benefit_is_reduced(self):
        model = _model(start="2027-01", end_year=2028)
        family = Family(model)
        high = _person(model, birth="1960-01", family=family, name="High")
        low = _person(model, birth="1965-01", family=family, name="Low")
        high.get_married(low)
        SocialSecurity(high, 67, pia_override_monthly=3000)
        low_ss = SocialSecurity(low, 62, pia_override_monthly=600, spousal_benefit=True)
        model.step()
        # 62 in January 2027, FRA 67: own 600 x 70%, spousal excess 900 x 65% (60 months early).
        self.assertAlmostEqual(low_ss.monthly_benefit(), 420 + 585, places=2)

    def test_pia_override_after_62_gets_only_colas(self):
        model = _model(end_year=2027)
        person = _person(model, birth="1960-01")
        ss = SocialSecurity(person, 67, pia_override_monthly=2000)
        self.assertEqual(ss.primary_insurance_amount(2026), 2000)
        model.step_year()
        # 2027 adds the COLA for 2026: the realized inflation of the fixed economy (3%), to the dime.
        self.assertAlmostEqual(ss.primary_insurance_amount(2027), 2060.0, places=6)

    def test_fra_from_birth_year_changes_the_delayed_credit(self):
        model = _model()
        person = _person(model, birth="1957-01")
        configured = SocialSecurity(person, 67, pia_override_monthly=2000)
        self.assertAlmostEqual(configured.get_pia(), 2000, places=2)
        by_birth = SocialSecurity(
            _person(model, birth="1957-01", name="Q"), 67, pia_override_monthly=2000, fra_from_birth_year=True
        )
        # FRA 66 and 6 months: six months of 8%/yr delayed credits (4%).
        self.assertAlmostEqual(by_birth.get_pia(), 2080, places=2)

    def test_earnings_test_withholds_and_recomputes_at_fra(self):
        # The live config: the fixture's wage index lacks the 1992 base the 2027 exempt amount projects from.
        model = _model(end_year=2031, config=FinancialConfig())
        person = _person(model, birth="1964-01", retirement_age=63)
        Job(person, company="Co", role="Eng", salary=Salary(model, base_annual=44480))
        ss = SocialSecurity(person, 62, pia_override_monthly=2000, earnings_test=True)
        model.step_year()
        # 2026 lower exempt amount $24,480: $20,000 over, $10,000 withheld from 2027's checks.
        self.assertAlmostEqual(ss.withholding_due, 10000, places=6)
        model.step_year()
        self.assertEqual(ss.withholding_due, 0)
        # Whole checks (70% of the PIA, with the COLA) withheld before FRA, the last one partly.
        months = int(10000 // ss._pia_by_year[2027])
        self.assertEqual(ss.months_withheld, months)
        while model.year < 2031:
            model.step_year()
        model.step()  # January 2031: FRA (67); the reduction is recomputed without the withheld months
        factor = 1 - (36 * 5 / 9 + (60 - months - 36) * 5 / 12) / 100
        self.assertAlmostEqual(ss.get_pia(), round(ss.primary_insurance_amount() * factor, 2), places=2)

    def test_exempt_amounts_follow_the_wage_index_past_the_table(self):
        config = FinancialConfig()
        self.assertEqual(earnings_test_exempt_amounts(2026, config), (24480, 65160))
        lower, higher = earnings_test_exempt_amounts(2027, config)
        self.assertGreaterEqual(higher, 65160)
        self.assertGreaterEqual(lower, 24480)
        self.assertEqual(lower % 120, 0)


class TestSpendingModel(unittest.TestCase):
    def test_age_schedule_100_80_70(self):
        """Acceptance (Plan 27 PR D): 100/80/70% of the entered spending by age band."""
        model = _model(start="2026-01", end_year=2047)
        spending = Spending(model, 60000, 0, schedule=[(65, 100), (75, 80), (85, 87.5)])
        _person(model, birth="1961-01", spending=spending, bank=5e6)
        totals = {}
        for year in range(2026, 2048):
            model.step_year()
            totals[year] = model.datacollector.get_model_vars_dataframe().iloc[-1]["Spending"]
        self.assertAlmostEqual(totals[2026], 60000, places=4)  # 65: the step at 65 keeps 100%
        self.assertAlmostEqual(totals[2035], 60000, places=4)  # 74
        self.assertAlmostEqual(totals[2036], 48000, places=4)  # 75: 80%
        self.assertAlmostEqual(totals[2045], 48000, places=4)  # 84
        self.assertAlmostEqual(totals[2046], 42000, places=4)  # 85: 70% of the entered amount

    def test_categories_with_years_and_monthly_amounts(self):
        model = _model(end_year=2029)
        spending = Spending(
            model,
            12000,
            0,
            categories={
                "groceries": SpendingLine(800, period="monthly", growth_pct=0),
                "travel": SpendingLine(6000, growth_pct=0, start_year=2027, end_year=2028, essential=False),
            },
        )
        _person(model, spending=spending, bank=1e6)
        frame = model.run().model_frame.set_index("Year")
        self.assertAlmostEqual(frame.loc[2026, "Spending"], 12000 + 9600, places=6)
        self.assertAlmostEqual(frame.loc[2027, "Spending"], 12000 + 9600 + 6000, places=6)
        self.assertAlmostEqual(frame.loc[2029, "Spending"], 12000 + 9600, places=6)

    def test_essential_and_discretionary_totals(self):
        model = _model(end_year=2027)
        spending = Spending(
            model,
            0,
            0,
            categories={
                "groceries": SpendingLine(800, period="monthly", growth_pct=0),
                "travel": SpendingLine(6000, growth_pct=0, essential=False),
            },
        )
        _person(model, spending=spending, bank=1e6)
        for _ in range(11):
            model.step()
        self.assertAlmostEqual(spending.essential_spending_this_year(), 8800, places=6)
        self.assertAlmostEqual(spending.discretionary_spending_this_year(), 5500, places=6)

    def test_recurring_expense_added_later(self):
        model = _model(end_year=2030)
        spending = Spending(model, 0, 0)
        _person(model, spending=spending, bank=1e6)
        spending.add_line("tuition", RecurringExpense(24000, 2027, 2028))
        frame = model.run().model_frame.set_index("Year")
        self.assertEqual(frame.loc[2026, "Spending"], 0)
        self.assertAlmostEqual(frame.loc[2027, "Spending"], 24000, places=6)
        self.assertEqual(frame.loc[2029, "Spending"], 0)

    def test_per_child_cost_override(self):
        model = _model(end_year=2026)
        person = _person(model, bank=1e6)
        child = Child(person, "Kid", 2020, cost_annual=15000, college_cost_annual=40000)
        self.assertEqual(child.nominal_cost_for_age(5), 15000)
        self.assertEqual(child.nominal_cost_for_age(19), 40000)
        model.step_year()
        self.assertAlmostEqual(child.stat_dependent_costs, 15000, places=6)


if __name__ == "__main__":
    unittest.main()
