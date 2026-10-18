# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Plan 27 PR B: jobs and payroll as the pay stub and offer letter show them.

Pre-tax payroll deductions (§125 premiums, health FSA, HSA through payroll, employer HSA, commuter), job
start and end, structured bonuses and raise schedules, existing RSU grants and the ESPP. Dollar assertions
read the published 2026 year of the packaged ``tax_years`` table.
"""

import unittest

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount
from ..account.hsa import HealthSavingsAccount
from ..account.job401k import Job401kAccount
from ..invariants import check_model
from ..ledger import FlowKind
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..tax.income import IncomeType
from ..work.job import Bonus, Job, Salary
from ..work.payroll import PayrollDeductions
from ..work.stock import ESPP, StockGrant, StockPlan, VestingSchedule


def _model(start=2026, end=None, **kwargs):
    kwargs.setdefault("checks", "strict")
    return LifeModel(start_year=start, end_year=end or start, **kwargs)


def _person(model, name="Alex", age=40, bank=0.0, state="TX"):
    person = Person(Family(model), name, age=age, retirement_age=67, spending=Spending(model, 0), state=state)
    BankAccount(person, company="Bank", balance=bank, interest_pct=0)
    return person


def _job(person, salary=100_000, **kwargs):
    salary_kwargs = {k: kwargs.pop(k) for k in ("bonus_pct", "bonus", "raises", "raise_pct") if k in kwargs}
    return Job(
        person,
        company="Example Analytics",
        salary=Salary(person.model, base_annual=salary, **salary_kwargs),
        **kwargs,
    )


def _year(model):
    model.step_year()
    return model.tax_returns[model.year - 1]


class TestPayrollDeductions(unittest.TestCase):
    def test_health_premium_lowers_income_tax_and_fica(self):
        """Acceptance: a $500/mo pre-tax health premium lowers both income tax and FICA by the right amounts."""
        base = _model()
        alex = _person(base)
        _job(alex)
        with_premium = _model()
        lee = _person(with_premium, "Lee")
        _job(lee, payroll=PayrollDeductions(health_premium_monthly=500))
        before, after = _year(base), _year(with_premium)
        self.assertAlmostEqual(before.wages - after.wages, 6_000, places=6)
        # FICA: 7.65% of the premium (under the wage base); income tax: the 22% bracket (2026 single,
        # taxable income $83,900 -> $77,900).
        ss_medicare = lambda r: sum(line.social_security + line.medicare for line in r.fica)
        self.assertAlmostEqual(ss_medicare(before) - ss_medicare(after), 6_000 * 0.0765, places=4)
        self.assertEqual(before.marginal_rate, 22)
        self.assertEqual(after.marginal_rate, 22)
        self.assertAlmostEqual(before.federal_tax - after.federal_tax, 6_000 * 0.22, places=4)
        # Cash: the premium leaves the paycheck; the tax saving comes back at settlement.
        saving = before.total_tax - after.total_tax
        self.assertAlmostEqual(alex.bank_account_balance - lee.bank_account_balance, 6_000 - saving, places=2)
        premiums = [e for e in with_premium.ledger if e.kind == FlowKind.PREMIUM.value]
        self.assertAlmostEqual(sum(e.amount for e in premiums), 6_000, places=6)
        self.assertEqual(check_model(with_premium), [])

    def test_fsa_commuter_and_hsa_are_excluded_from_wages_within_their_limits(self):
        model = _model()
        alex = _person(model)
        hsa = HealthSavingsAccount(alex, growth_pct=0, employer_contribution_annual=0)
        _job(
            alex,
            payroll=PayrollDeductions(
                fsa_annual=4_000,  # over the $3,400 2026 limit (Rev. Proc. 2025-32)
                commuter_monthly=400,  # over the $340 monthly limit
                hsa_employee_annual=3_000,
                hsa_employer_annual=1_000,
                dental_vision_monthly=50,
            ),
        )
        tax_return = _year(model)
        excluded = 3_400 + 340 * 12 + 3_000 + 600
        self.assertAlmostEqual(tax_return.wages, 100_000 - excluded, places=4)
        self.assertAlmostEqual(tax_return.fica[0].wages, 100_000 - excluded, places=4)
        self.assertAlmostEqual(hsa.balance, 4_000, places=4)
        # No above-the-line HSA deduction: the payroll money never was wages.
        self.assertNotIn("hsa_deduction", tax_return.adjustments)
        employer = [e for e in model.ledger if e.cause == "employer HSA contribution"]
        self.assertTrue(all(e.source == "Example Analytics" for e in employer))
        self.assertEqual(check_model(model), [])

    def test_hsa_payroll_respects_the_limit(self):
        model = _model()
        alex = _person(model)
        hsa = HealthSavingsAccount(alex, growth_pct=0, employer_contribution_annual=0)
        _job(alex, payroll=PayrollDeductions(hsa_employee_annual=4_000, hsa_employer_annual=2_000))
        _year(model)
        self.assertAlmostEqual(hsa.balance, 4_400, places=4)  # 2026 self-only limit


class TestJobStartAndEnd(unittest.TestCase):
    def test_job_ending_in_2030_pays_nothing_in_2031_and_no_match(self):
        """Acceptance: a job ending in 2030 pays nothing in 2031 and triggers no match."""
        model = _model(2029, 2031)
        alex = _person(model)
        job = _job(alex, end_year=2030)
        Job401kAccount(job, pretax_contrib_pct=6, match_tiers=[(100, 6)], growth_pct=0)
        model.run()
        by_year = {}
        for entry in model.ledger:
            if entry.kind in (FlowKind.WAGE.value, FlowKind.MATCH.value):
                by_year[(entry.year, entry.kind)] = by_year.get((entry.year, entry.kind), 0.0) + entry.amount
        self.assertAlmostEqual(by_year[(2030, "wage")], 100_000, places=4)
        self.assertAlmostEqual(by_year[(2030, "match")], 6_000, places=4)
        self.assertNotIn((2031, "wage"), by_year)
        self.assertNotIn((2031, "match"), by_year)
        self.assertTrue(job.retired)
        self.assertEqual(check_model(model), [])

    def test_job_starting_later_and_mid_year_months(self):
        model = _model(2026, 2027)
        alex = _person(model)
        job = _job(alex, salary=120_000, start_year="2026-07", end_year="2027-03")
        model.run()
        wages = {y: sum(e.amount for e in model.ledger if e.kind == "wage" and e.year == y) for y in (2026, 2027)}
        self.assertAlmostEqual(wages[2026], 60_000, places=4)
        self.assertAlmostEqual(wages[2027], 30_000, places=4)
        self.assertEqual(job.years_of_service, 2)


class TestBonusAndRaises(unittest.TestCase):
    def test_fixed_bonus_signon_and_a_raise_schedule(self):
        model = _model(2026, 2028)
        alex = _person(model)
        job = _job(
            alex,
            bonus=Bonus(target_pct=10, fixed_annual=5_000, signon=20_000),
            raises=[(2027, 5)],
            raise_pct=2,
        )
        model.run()
        bonus = {
            y: sum(e.amount for e in model.ledger if e.kind == "bonus" and e.year == y) for y in (2026, 2027, 2028)
        }
        self.assertAlmostEqual(bonus[2026], 10_000 + 5_000 + 20_000, places=4)
        self.assertAlmostEqual(bonus[2027], 10_500 + 5_000, places=4)  # base 105,000 after the 2027 raise
        self.assertAlmostEqual(bonus[2028], 10_710 + 5_000, places=4)  # then 2%
        self.assertAlmostEqual(job.salary.base, 100_000 * 1.05 * 1.02 * 1.02, places=4)

    def test_bonus_range_is_seeded(self):
        def bonus(seed):
            model = _model(seed=seed)
            alex = _person(model)
            _job(alex, bonus=Bonus(target_pct=20, range_pct=(50, 150)))
            model.step_year()
            return sum(e.amount for e in model.ledger if e.kind == "bonus")

        self.assertEqual(bonus(1), bonus(1))
        self.assertTrue(10_000 <= bonus(2) <= 30_000)


class TestEquity(unittest.TestCase):
    def test_existing_grant_vests_its_remaining_slices(self):
        model = _model(2026, 2028)
        alex = _person(model)
        job = _job(alex)
        grant = StockGrant(value_at_grant=80_000, grant_year=2024, schedule=VestingSchedule.four_year())
        plan = StockPlan(job, growth_pct=0, existing_grants=[grant])
        self.assertAlmostEqual(grant.vested_fraction, 0.25)  # the 2025 vest happened before the start
        self.assertAlmostEqual(plan.unvested_value, 60_000)
        model.run()
        vests = {y: sum(e.amount for e in model.ledger if e.kind == "vest" and e.year == y) for y in (2026, 2027, 2028)}
        self.assertEqual(vests, {2026: 20_000, 2027: 20_000, 2028: 20_000})

    def test_existing_grant_revalued_to_the_statement(self):
        model = _model()
        alex = _person(model)
        job = _job(alex)
        grant = StockGrant(
            value_at_grant=80_000, grant_year=2024, schedule=VestingSchedule.four_year(), unvested_value=90_000
        )
        plan = StockPlan(job, growth_pct=0, existing_grants=[grant])
        self.assertAlmostEqual(plan.unvested_value, 90_000)
        model.step_year()
        self.assertAlmostEqual(plan.stat_stock_vested, 30_000)

    def test_espp_discount_is_wages_without_fica(self):
        model = _model()
        alex = _person(model)
        job = _job(alex)
        StockPlan(job, growth_pct=0, espp=ESPP(contribution_pct=10))
        tax_return = _year(model)
        contributions = 10_000
        discount = contributions / 0.85 - contributions
        self.assertAlmostEqual(tax_return.wages, 100_000 + discount, places=4)
        self.assertAlmostEqual(tax_return.fica[0].wages, 100_000, places=4)
        espp = [e for e in alex.income.entries if e.source == "espp"]
        self.assertEqual(espp, [])  # the ledger was settled; the return has it
        self.assertEqual(check_model(model), [])

    def test_espp_held_shares_and_the_25k_limit(self):
        model = _model()
        alex = _person(model, bank=50_000)
        job = _job(alex, salary=400_000)
        account = BrokerageAccount(alex, growth_pct=0, dividend_yield_pct=0)
        StockPlan(job, growth_pct=0, espp=ESPP(contribution_pct=15, disposition="hold"))
        model.step_year()
        # $60,000 of contributions wanted; the stock bought is capped at $25,000 (offering-date value) a year.
        self.assertAlmostEqual(account.balance, 25_000, places=2)
        self.assertAlmostEqual(account.cost_basis, 25_000, places=2)
        with self.assertRaises(ValueError):
            ESPP(contribution_pct=10, discount_pct=20)


class TestIncomeTypes(unittest.TestCase):
    def test_payroll_items_change_no_income_type_but_wages(self):
        model = _model()
        alex = _person(model)
        _job(alex, payroll=PayrollDeductions(health_premium_monthly=100))
        model.step()
        wages = [e for e in alex.income.entries if e.income_type == IncomeType.WAGES]
        self.assertAlmostEqual(sum(e.amount for e in wages), 100_000 / 12 - 100, places=6)
        self.assertAlmostEqual(sum(e.fica_wages for e in wages), 100_000 / 12 - 100, places=6)
