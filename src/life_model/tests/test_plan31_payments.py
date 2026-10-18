# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Plan 31 tasks 6-7: withholding, estimated payments and the April settlement (D3), the ACA premium tax
credit, residency timelines and part-year state returns (D4), qualifying surviving spouses and dependents
(D5), and the contribution plans' tax hold-back.

Dollar assertions read published years (2024-2026) of the packaged tables (each verified against its source:
IRS Pub. 15-T, Form 2210 and 8962 instructions, state revenue departments).
"""

import datetime
import unittest

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount
from ..config.financial_config import default_financial_config
from ..config.models import UnknownStateError
from ..dependents.child import Child
from ..dependents.dependent import Dependent
from ..insurance.general_insurance import Insurance, InsuranceType
from ..invariants import check_model
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..people.tax_unit import TaxUnit
from ..policies import ContributionPlan
from ..tax.federal import FilingStatus
from ..tax.payments import (
    W4,
    EstimatedPayments,
    FlatWithholding,
    derived_withholding_table,
    federal_withholding,
    supplemental_withholding,
    underpayment_penalty,
    withholding_table,
)
from ..tax.ptc import MarketplaceCoverage, applicable_figure, premium_tax_credit
from ..work.job import Job, Salary
from ..work.payroll import PayrollDeductions


def _view(year):
    config = default_financial_config()
    return config.year_view(config.tax_year(year))


def _person(model, name="Alex", age=40, family=None, bank=50_000, spending=0, **kwargs):
    person = Person(
        family or Family(model), name, age=age, retirement_age=67, spending=Spending(model, spending), **kwargs
    )
    if bank is not None:
        BankAccount(person, company="Bank", balance=bank, interest_pct=0)
    return person


def _job(person, salary, company="Example Analytics", withholding="w4_default", bonus_pct=0, **kwargs):
    return Job(
        person,
        company=company,
        role="Analyst",
        salary=Salary(person.model, base_annual=salary, bonus_pct=bonus_pct),
        payroll=PayrollDeductions(withholding=withholding),
        **kwargs,
    )


def _tax_entries(model):
    frame = model.ledger.to_frame()
    return frame[frame.kind.isin(["tax", "penalty"])]


# --------------------------------------------------------------------------------------------------
# Pub. 15-T
# --------------------------------------------------------------------------------------------------


class TestPercentageMethod(unittest.TestCase):
    def test_pub_15t_worked_example(self):
        # 2025, single, standard schedule, $8,000 a month: (96,000 - 8,600 = 87,400) on the row over 54,875:
        # 5,578.50 + 22% x 32,525 = 12,734.00 a year, 1,061.17 a month (Worksheet 1A).
        monthly = federal_withholding(8000, W4(), "single", _view(2025))
        self.assertAlmostEqual(monthly, (5578.50 + 0.22 * (87400 - 54875)) / 12, places=6)
        self.assertAlmostEqual(monthly, 1061.17, places=2)

    def test_w4_entries(self):
        view = _view(2025)
        base = federal_withholding(8000, W4(), "single", view)
        # Step 3: $2,000 of credits is $166.67 less a month; Step 4(c) adds the extra.
        self.assertAlmostEqual(federal_withholding(8000, W4(dependents_annual=2000), "single", view), base - 2000 / 12)
        self.assertAlmostEqual(federal_withholding(8000, W4(extra_monthly=50), "single", view), base + 50)
        # Step 2 checkbox: no Step 1g amount, the halved schedule (2025 single checkbox: over 59,175 -> 8,825.50 at 24%).
        expected = (8825.50 + 0.24 * (96000 - 59175)) / 12
        self.assertAlmostEqual(federal_withholding(8000, W4(multiple_jobs=True), "single", view), expected, places=6)
        self.assertEqual(federal_withholding(8000, FlatWithholding(pct=10), "single", view), 800)
        self.assertEqual(federal_withholding(8000, FlatWithholding(amount_monthly=900), "single", view), 900)

    def test_derived_tables_reproduce_the_published_ones(self):
        """Projected years derive the tables from brackets and the standard deduction; the rule reproduces every
        published 2024 and 2026 row (the checkbox schedules' thresholds are printed rounded to the dollar). The 2025
        tables were published before OBBBA raised the 2025 standard deduction ($15,000 to $15,750), so they derive
        from the old amounts: the engine withholds by the published tables, as employers did."""
        for year in (2024, 2026):
            view = _view(year)
            for status in ("single", "married_filing_jointly", "head_of_household"):
                for checkbox in (False, True):
                    with self.subTest(year=year, status=status, checkbox=checkbox):
                        published = withholding_table(view, status, checkbox=checkbox)
                        derived = derived_withholding_table(view, status, checkbox=checkbox)
                        for row, other in zip(published, derived, strict=True):
                            for a, b in zip(row, other, strict=True):
                                self.assertLessEqual(abs(a - b), 1.0)

    def test_supplemental_rates(self):
        view = _view(2025)
        self.assertAlmostEqual(supplemental_withholding(10000, 0, view), 2200)
        # $50,000 crossing $1,000,000 of the year's supplemental wages: 22% below, 37% above.
        self.assertAlmostEqual(supplemental_withholding(50000, 980000, view), 20000 * 0.22 + 30000 * 0.37)


# --------------------------------------------------------------------------------------------------
# Withholding and the April settlement
# --------------------------------------------------------------------------------------------------


class TestWithholdingAndAprilSettlement(unittest.TestCase):
    def test_default_is_the_december_lump(self):
        model = LifeModel(start_year=2025, end_year=2025, checks="strict")
        person = _person(model, state="TX")
        _job(person, 96000, withholding=None)
        model.run()
        taxes = _tax_entries(model)
        self.assertEqual(set(taxes.month), {12})
        self.assertFalse(model.tax_returns[2025].settled_in_april)
        self.assertEqual(person.taxes_owed, 0)

    def test_withholding_splits_the_year_across_paychecks_and_april(self):
        model = LifeModel(start_year=2025, end_year=2026, checks="strict")
        person = _person(model, state="TX")
        _job(person, 96000, bonus_pct=10)
        model.run()
        r = model.tax_returns[2025]
        self.assertTrue(r.settled_in_april)
        taxes = _tax_entries(model)
        year = taxes[taxes.year == 2025]
        federal = year[year.sink == "IRS: federal income tax"]
        # Twelve paychecks withhold; December's settlement accrues the remainder to the April balance.
        self.assertEqual(
            sorted(federal[federal.from_account.str.startswith("BankAccount")].month.unique()), list(range(1, 13))
        )
        # $8,000 a month regular wages; the March bonus ($9,600) at the 22% supplemental rate.
        regular = (5578.50 + 0.22 * (96000 - 8600 - 54875)) / 12
        self.assertAlmostEqual(r.federal_income_tax_withheld, 12 * regular + 0.22 * 9600, places=2)
        # The ledger's year of tax outflows is the return's liability, whatever was paid when.
        self.assertAlmostEqual(year.amount.sum(), r.total_tax, places=2)
        # The balance due (or refund) on the 2025 return is settled in April 2026, from the bank to the payable.
        balance = r.amount_owed - r.overpayment
        april = taxes[(taxes.year == 2026) & (taxes.month == 4) & taxes.cause.str.contains("2025", na=False)]
        self.assertAlmostEqual(april.amount.sum(), abs(balance), places=2)
        self.assertAlmostEqual(person.taxes_owed, model.tax_returns[2026].amount_owed, places=2)
        self.assertEqual(check_model(model), [])

    def test_two_employers_over_withhold_social_security(self):
        model = LifeModel(start_year=2025, end_year=2025, checks="strict")
        person = _person(model, state="TX")
        _job(person, 120000, company="First")
        _job(person, 120000, company="Second")
        model.run()
        r = model.tax_returns[2025]
        base = 176100  # 2025 wage base
        # Each employer withholds 6.2% of its own $120,000; the return owes 6.2% of the wage base.
        self.assertAlmostEqual(r.social_security_withheld, 2 * 120000 * 0.062, places=2)
        self.assertAlmostEqual(r.social_security_tax, base * 0.062, places=2)
        self.assertAlmostEqual(r.excess_social_security_withheld, (240000 - base) * 0.062, places=2)
        # The excess is a payment on the return (Schedule 3 line 11).
        self.assertGreater(r.total_payments, r.federal_income_tax_withheld + r.excess_social_security_withheld - 0.01)

    def test_state_withholding_annualizes_the_pack(self):
        # 2025 Georgia: 5.19% of (96,000 - 12,000) = 4,359.60 a year, 363.30 a month.
        model = LifeModel(start_year=2025, end_year=2025, checks="strict")
        person = _person(model, state="GA")
        _job(person, 96000)
        model.run()
        r = model.tax_returns[2025]
        self.assertAlmostEqual(r.state_withheld, (96000 - 12000) * 0.0519, places=2)
        self.assertAlmostEqual(r.state_tax, (96000 - 12000) * 0.0519, places=2)
        self.assertAlmostEqual(r.state_balance_due, 0.0, places=2)

    def test_rsu_vest_withholds_supplemental_and_delivers_net_shares(self):
        from ..work.stock import StockPlan

        model = LifeModel(start_year=2025, end_year=2026, checks="strict")
        person = _person(model, state="TX")
        brokerage = BrokerageAccount(person, company="Broker", balance=0, growth_pct=0)
        job = _job(person, 100000)
        StockPlan(job, signon_value=40000, growth_pct=0, disposition="hold", brokerage_account=brokerage)
        model.run()
        vest = 10000.0  # 2026: a quarter of the sign-on grant vests
        payments = person.tax_payments[2026]
        self.assertGreater(payments.federal_withheld, 0)
        withheld_on_vest = vest * 0.22 + vest * 0.062 + vest * 0.0145
        self.assertAlmostEqual(brokerage.balance, vest - withheld_on_vest, places=2)
        self.assertEqual(check_model(model), [])


# --------------------------------------------------------------------------------------------------
# Estimated payments and Form 2210
# --------------------------------------------------------------------------------------------------


class TestEstimatedPayments(unittest.TestCase):
    def test_penalty_regular_method(self):
        """No payments against a $10,000 required annual payment (2025: 7% all year, 365-day year): each $2,500
        installment accrues from its due date to April 15, 2026 (the worksheet's four rate periods; April 1-15, 2026
        stays in rate period 4)."""
        days = [
            (datetime.date(2026, 4, 15) - datetime.date(2025, 4, 15)).days,
            (datetime.date(2026, 4, 15) - datetime.date(2025, 6, 15)).days,
            (datetime.date(2026, 4, 15) - datetime.date(2025, 9, 15)).days,
            (datetime.date(2026, 4, 15) - datetime.date(2026, 1, 15)).days,
        ]
        expected = sum(2500 * 0.07 * d / 365 for d in days)
        form = underpayment_penalty(
            2025, 10000, 0.0, [], prior_year_tax=12000, prior_year_agi=90000, separate=False, config=_view(2025)
        )
        self.assertEqual(form.required_annual_payment, 9000)  # 90% of this year's (less than last year's 12,000)
        expected = sum(2250 * 0.07 * d / 365 for d in days)
        self.assertAlmostEqual(form.penalty, round(expected, 2), places=2)

    def test_safe_harbor_and_thresholds(self):
        view = _view(2025)
        # Withholding covers last year's tax: no penalty.
        form = underpayment_penalty(
            2025, 20000, 15000, [], prior_year_tax=15000, prior_year_agi=100000, separate=False, config=view
        )
        self.assertEqual(form.penalty, 0.0)
        # Over $150,000 of prior-year AGI: 110% of last year's tax.
        form = underpayment_penalty(
            2025, 20000, 15000, [], prior_year_tax=15000, prior_year_agi=200000, separate=False, config=view
        )
        self.assertEqual(form.required_annual_payment, 16500)
        self.assertGreater(form.penalty, 0)
        # Under $1,000 after withholding, or no tax last year: none.
        self.assertEqual(
            underpayment_penalty(
                2025, 20000, 19500, [], prior_year_tax=1, prior_year_agi=0, separate=False, config=view
            ).penalty,
            0,
        )
        self.assertEqual(
            underpayment_penalty(
                2025, 20000, 0, [], prior_year_tax=0, prior_year_agi=0, separate=False, config=view
            ).penalty,
            0,
        )
        # Timely equal installments of the required payment: none.
        paid = [(i, 4500) for i in range(4)]
        self.assertEqual(
            underpayment_penalty(
                2025, 20000, 0, paid, prior_year_tax=18000, prior_year_agi=0, separate=False, config=view
            ).penalty,
            0,
        )

    def test_quarterly_payments_post_on_the_due_months(self):
        model = LifeModel(start_year=2025, end_year=2026, checks="strict")
        person = _person(model, state="TX", estimated_payments=EstimatedPayments(quarterly=3000, prior_year_tax=10000))
        _job(person, 100000, withholding=None)
        model.run()
        taxes = _tax_entries(model)
        est = taxes[taxes.cause.str.contains("2025 Q", na=False)]
        self.assertEqual(sorted(zip(est.year, est.month, strict=True)), [(2025, 4), (2025, 6), (2025, 9), (2026, 1)])
        r = model.tax_returns[2025]
        self.assertEqual(r.estimated_tax_payments, 12000)
        self.assertTrue(r.settled_in_april)
        self.assertEqual(check_model(model), [])

    def test_safe_harbor_policy_pays_last_years_tax(self):
        model = LifeModel(start_year=2025, end_year=2026, checks="strict")
        person = _person(
            model,
            state="TX",
            estimated_payments=EstimatedPayments(policy="safe_harbor", prior_year_tax=8000, prior_year_agi=90000),
        )
        _job(person, 100000, withholding=None)
        model.run()
        r = model.tax_returns[2025]
        self.assertAlmostEqual(r.estimated_tax_payments, 8000, places=2)
        self.assertEqual(r.estimated_tax_penalty, 0.0)
        self.assertEqual(check_model(model), [])


# --------------------------------------------------------------------------------------------------
# Contribution plans never sell back a contribution to pay the year's tax
# --------------------------------------------------------------------------------------------------


class TestContributionHoldBack(unittest.TestCase):
    def _run(self, withholding=None):
        model = LifeModel(start_year=2026, end_year=2026, checks="strict")
        person = _person(model, "Saver", bank=1000, spending=30000, state="TX")
        brokerage = BrokerageAccount(person, company="Broker", balance=0, growth_pct=0)
        _job(person, 150000, withholding=withholding)
        person.add_contribution_plan(ContributionPlan(brokerage, amount_annual=120000))
        model.run()
        return model, person, brokerage

    def test_no_december_sell_back(self):
        """Before Plan 31 this household contributed $1,000 of its $1,000-ish monthly surplus January-November and
        then sold $25,209 of the brokerage in December to pay the year's taxes (fourth-wave 1cd3555). The plan now
        holds back the month's share of the year's unpaid tax: nothing is sold."""
        model, person, brokerage = self._run()
        events = model.event_log.to_frame()
        self.assertFalse((events.kind == "forced_sale").any())
        self.assertEqual(person.debt, 0)
        self.assertGreater(brokerage.balance, 80000)
        self.assertEqual(check_model(model), [])

    def test_with_withholding_the_plan_keeps_only_the_unpaid_balance(self):
        model, person, _brokerage = self._run("w4_default")
        events = model.event_log.to_frame()
        self.assertFalse((events.kind == "forced_sale").any())
        # The year's balance due waits in the bank for April (a liability on the balance sheet until then).
        self.assertGreaterEqual(person.spendable_bank_balance, person.taxes_owed - 0.01)


# --------------------------------------------------------------------------------------------------
# Premium tax credit
# --------------------------------------------------------------------------------------------------


class TestPremiumTaxCredit(unittest.TestCase):
    def test_applicable_figure(self):
        params = _view(2025).tax.federal.premium_tax_credit
        # 26 CFR 1.36B-3(g): linear in the band, to 0.01% (the 2025 Table 2: 303% -> 0.0608).
        self.assertEqual(applicable_figure(303, params), 0.0608)
        self.assertEqual(applicable_figure(150, params), 0.0)
        self.assertEqual(applicable_figure(401, params), 0.085)
        params = _view(2026).tax.federal.premium_tax_credit
        self.assertEqual(applicable_figure(120, params), 0.021)

    def test_form_8962_annual_and_cliff(self):
        params = _view(2025).tax.federal.premium_tax_credit
        months = [(1500.0, 1400.0, 0.0)] * 12
        # Two people, $60,000: 2024 guideline 15,060 + 5,380 = 20,440 -> 293% -> 4 + 2 x 43/50 = 5.72%.
        out = premium_tax_credit(60000, 2, months, FilingStatus.MARRIED_FILING_JOINTLY, params)
        self.assertEqual(out["fpl_percent"], 293)
        self.assertEqual(out["applicable_figure"], 0.0572)
        self.assertEqual(out["contribution"], round(60000 * 0.0572))
        self.assertEqual(out["allowed"], 12 * 1400 - round(60000 * 0.0572))
        # 2026: above 400% of the poverty line (2025 guideline, 2 people: 21,150 x 4) no credit, and advance
        # payments are repaid in full (no limit from 2026).
        params = _view(2026).tax.federal.premium_tax_credit
        out = premium_tax_credit(90000, 2, [(1500.0, 1400.0, 500.0)] * 12, FilingStatus.MARRIED_FILING_JOINTLY, params)
        self.assertEqual(out["fpl_percent"], 401)
        self.assertEqual((out["allowed"], out["repayment"]), (0.0, 6000.0))

    def test_repayment_limit_2025(self):
        params = _view(2025).tax.federal.premium_tax_credit
        # Single at 250% of the line (2024 guideline 15,060 -> $37,650): excess advance repaid up to $975.
        out = premium_tax_credit(37650, 1, [(500.0, 400.0, 400.0)] * 12, FilingStatus.SINGLE, params)
        self.assertEqual(out["fpl_percent"], 250)
        self.assertEqual(out["repayment"], min(975.0, out["advance"] - out["allowed"]))

    def test_marketplace_policy_on_a_return(self):
        model = LifeModel(start_year=2025, end_year=2025, checks="strict")
        family = Family(model)
        a = _person(model, "Ann", age=60, family=family, state="TX", bank=200000)
        b = _person(model, "Ben", age=59, family=family, state="TX", bank=None)
        a.get_married(b)
        _job(b, 50000, withholding=None)
        Insurance(
            a,
            InsuranceType.HEALTH,
            "Marketplace",
            premium_annual=18000,
            coverage_amount=1e6,
            marketplace=MarketplaceCoverage(slcsp_monthly=1400),
        )
        model.run()
        r = model.tax_returns[2025]
        self.assertGreater(r.premium_tax_credit_allowed, 0)
        self.assertEqual(r.credits_refundable["premium_tax_credit"], r.premium_tax_credit_allowed)
        self.assertEqual(check_model(model), [])


# --------------------------------------------------------------------------------------------------
# Residency (D4)
# --------------------------------------------------------------------------------------------------


class TestResidency(unittest.TestCase):
    def test_unknown_state_is_refused_and_packed_states_are_accepted(self):
        model = LifeModel(start_year=2026)
        with self.assertRaises(UnknownStateError):
            Person(Family(model), "Zed", age=40, retirement_age=65, spending=Spending(model, 0), state="ZZ")
        for state in ("GA", "NC", "OH", "MI", "NJ", "VA", "AZ", "TN", "IN", "MO", "MD", "DEFAULT"):
            Person(Family(model), "Ok", age=40, retirement_age=65, spending=Spending(model, 0), state=state)
        with self.assertRaises(UnknownStateError):
            Person(
                Family(model),
                "Mover",
                age=40,
                retirement_age=65,
                spending=Spending(model, 0),
                state="CA",
                residency=[("2026-07", "ZZ")],
            )

    def test_timeline(self):
        model = LifeModel(start_year=2026)
        p = Person(
            Family(model),
            "Mover",
            age=40,
            retirement_age=65,
            spending=Spending(model, 0),
            state="CA",
            residency=[("2026-07", "TX")],
        )
        self.assertEqual(p.state_at(2026, 6), "CA")
        self.assertEqual(p.state_at(2026, 7), "TX")
        self.assertEqual(p.states_in_year(2026), ["CA", "TX"])
        self.assertEqual(p.state, "CA")

    def test_part_year_allocates_wages_by_month(self):
        model = LifeModel(start_year=2025, end_year=2025, checks="strict")
        person = _person(model, state="CA", residency=[("2025-07", "TX")])
        _job(person, 120000, withholding=None)
        model.run()
        r = model.tax_returns[2025]
        detail = r.state_return
        self.assertEqual(detail.method, "part_year")
        ca, tx = detail.parts
        self.assertEqual((ca.state, tx.state), ("CA", "TX"))
        self.assertAlmostEqual(ca.income, 60000, places=2)
        # The ratio method: CA tax on the whole year's income as a resident, times CA's half.
        model2 = LifeModel(start_year=2025, end_year=2025)
        full = _person(model2, state="CA")
        _job(full, 120000, withholding=None)
        model2.run()
        self.assertAlmostEqual(ca.tax, model2.tax_returns[2025].state_tax / 2, places=2)
        self.assertEqual(tx.tax, 0)
        self.assertEqual(r.state, "TX")


# --------------------------------------------------------------------------------------------------
# Filing status (D5)
# --------------------------------------------------------------------------------------------------


class TestQualifyingSurvivingSpouseAndDependents(unittest.TestCase):
    def test_qss_for_two_years_then_head_of_household(self):
        model = LifeModel(start_year=2025, end_year=2027)
        person = _person(model, "Wren", state="TX", widowed_year=2024)
        Child(person, "Kit", 2015)
        _job(person, 80000, withholding=None)
        model.run()
        self.assertEqual(model.tax_returns[2025].filing_status, "QUALIFYING_SURVIVING_SPOUSE")
        self.assertEqual(model.tax_returns[2026].filing_status, "QUALIFYING_SURVIVING_SPOUSE")
        self.assertEqual(model.tax_returns[2027].filing_status, "HEAD_OF_HOUSEHOLD")
        # The joint standard deduction (2025: $31,500).
        self.assertEqual(model.tax_returns[2025].standard_deduction, 31500)

    def test_widow_without_a_child_files_single(self):
        model = LifeModel(start_year=2025, end_year=2025)
        person = _person(model, "Wren", state="TX", widowed_year=2024)
        _job(person, 80000, withholding=None)
        model.run()
        self.assertEqual(model.tax_returns[2025].filing_status, "SINGLE")

    def test_dependent_parent_gives_head_of_household_and_the_odc(self):
        model = LifeModel(start_year=2025, end_year=2025)
        person = _person(model, "Sam", state="TX")
        Dependent(person, "Pat", relationship="parent", gross_income_annual=3000, support_annual=12000)
        _job(person, 80000, withholding=None)
        model.run()
        r = model.tax_returns[2025]
        self.assertEqual(r.filing_status, "HEAD_OF_HOUSEHOLD")
        self.assertEqual(r.standard_deduction, 23625)
        self.assertEqual(r.credits_nonrefundable.get("child_tax_credit"), 500)

    def test_parent_over_the_income_limit_does_not_qualify(self):
        model = LifeModel(start_year=2025, end_year=2025)
        person = _person(model, "Sam", state="TX")
        Dependent(person, "Pat", relationship="parent", gross_income_annual=5200)  # not less than $5,200
        _job(person, 80000, withholding=None)
        model.run()
        self.assertEqual(model.tax_returns[2025].filing_status, "SINGLE")

    def test_other_relative_needs_to_live_with_the_person(self):
        model = LifeModel(start_year=2025, end_year=2025)
        person = _person(model, "Sam", state="TX")
        Dependent(person, "Lee", relationship="sibling", gross_income_annual=0)
        _job(person, 80000, withholding=None)
        TaxUnit.build_units(person.family)
        model.run()
        r = model.tax_returns[2025]
        self.assertEqual(r.filing_status, "SINGLE")
        self.assertEqual(r.credits_nonrefundable.get("child_tax_credit"), 500)  # still a dependent (ODC)


if __name__ == "__main__":
    unittest.main()


# --------------------------------------------------------------------------------------------------
# The spec
# --------------------------------------------------------------------------------------------------


class TestSpecFields(unittest.TestCase):
    def _spec(self):
        from .spec_helpers import minimal

        data = minimal(
            state="CA",
            residency=[["2026-07", "TX"]],
            widowed_year=2025,
            estimated_payments={"policy": "safe_harbor", "prior_year_tax": 9000, "prior_year_agi": 90000},
            dependents=[{"id": "mom", "name": "Mom", "relationship": "parent", "support_annual": 6000}],
            children=[{"name": "Kit", "birth_year": 2016}],
            insurance=[
                {
                    "kind": "health",
                    "premium_annual": 9000,
                    "coverage_amount": 1000000,
                    "marketplace": {"slcsp_monthly": 700, "advance_monthly": "estimate"},
                }
            ],
        )
        data["people"][0]["jobs"][0]["payroll"] = {"withholding": {"w4": {"extra_monthly": 25}}}
        return data

    def test_build_and_extract_round_trip(self):
        from ..spec import HouseholdSpec, build_household, dumps, spec_from_model
        from ..spec.builder import canonical

        spec = HouseholdSpec.model_validate(self._spec())
        built = build_household(spec)
        model = built.model
        person = built.people["alex"]
        self.assertEqual(person.residency, [("2026-01", "CA"), ("2026-07", "TX")])
        self.assertEqual(person.spouse_death_year, 2025)
        self.assertEqual(person.estimated_payments.policy, "safe_harbor")
        self.assertEqual(person.jobs[0].withholding, W4(extra_monthly=25))
        self.assertEqual(person.qualifying_relatives[0].relationship, "parent")
        self.assertEqual(dumps(spec_from_model(model)), dumps(canonical(spec)))
        model.checks = "strict"
        model.run()
        r = model.tax_returns[2026]
        self.assertEqual(r.filing_status, "QUALIFYING_SURVIVING_SPOUSE")
        self.assertEqual(r.state_return.method, "part_year")
        self.assertTrue(r.settled_in_april)

    def test_unknown_residency_state_is_an_error(self):
        from ..spec import validate_spec

        data = self._spec()
        data["people"][0]["residency"] = [["2026-07", "ZZ"]]
        self.assertIn("unknown_state", [f.code for f in validate_spec(data)])

    def test_validator_suggests_withholding_when_w2s_show_it(self):
        from ..spec import validate_spec
        from .spec_helpers import minimal

        data = minimal(state="TX")
        data["actuals"] = {2026: {"w2": [{"person": "alex", "employer": "Co", "boxes": {"1": 80000, "2": 9000}}]}}
        self.assertIn("withholding_suggested", [f.code for f in validate_spec(data)])
        data["people"][0]["jobs"][0]["payroll"] = {"withholding": "w4_default"}
        self.assertNotIn("withholding_suggested", [f.code for f in validate_spec(data)])
