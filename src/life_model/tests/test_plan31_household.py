# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Plan 31 on whole simulations: the settlement path posts the year-end adjustments once, the waterfall
pays the new taxes, the invariant checker stays clean, and the inputs behind each item (QCDs, stock gifts,
IRA phase-outs, self-employment, options) move the money the forms say.

Dollar assertions read published years (2024-2026) of the packaged ``tax_years`` table (history: each
value verified against its source; they do not drift when a year is added).
"""

import unittest

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount
from ..account.roth_IRA import RothIRA
from ..account.traditional_IRA import TraditionalIRA
from ..charity.donation import Donation, DonationType
from ..debt.student_loan import StudentLoan, StudentLoanType
from ..dependents.child import Child
from ..insurance.general_insurance import Insurance, InsuranceType
from ..invariants import check_model
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..tax.deductions import deductible_insurance_premiums
from ..tax.federal import FilingStatus
from ..tax.income import IncomeType
from ..work.job import Job, Salary
from ..work.payroll import PayrollDeductions
from ..work.stock import StockOption, StockPlan


def _model(start=2024, end=None, **kwargs):
    return LifeModel(start_year=start, end_year=end or start, **kwargs)


def _person(model, name="Alex", age=40, family=None, bank=1_000_000, spending=0):
    person = Person(family or Family(model), name, age=age, retirement_age=67, spending=Spending(model, spending))
    if bank is not None:
        BankAccount(person, "Bank", balance=bank, interest_rate=0)
    return person


def _job(person, salary, **kwargs):
    return Job(person, "Example Analytics", "Analyst", Salary(person.model, base=salary), **kwargs)


class TestQualifiedCharitableDistribution(unittest.TestCase):
    def test_qcd_counts_toward_the_rmd_and_is_not_income(self):
        model = _model(2024, checks="strict")
        lee = _person(model, "Lee", 75)
        ira = TraditionalIRA(lee, balance=500000, growth_rate=0)
        Donation(lee, "Food Bank", annual_amount=10000, donation_type=DonationType.QCD)
        model.step_year()
        rmd = 500000 / 24.6
        self.assertAlmostEqual(ira.balance, 500000 - rmd, places=2)  # the QCD is part of the RMD
        r = model.tax_returns[2024]
        self.assertAlmostEqual(r.ira_distributions_gross, rmd, places=2)
        self.assertAlmostEqual(r.ira_distributions_taxable, rmd - 10000, places=2)
        self.assertEqual(r.itemized_components["charity"], 0)  # not deductible
        self.assertEqual(check_model(model), [])

    def test_before_70_and_a_half_it_is_a_cash_gift(self):
        model = _model(2024)
        pat = _person(model, "Pat", 65)
        _job(pat, 50000)
        TraditionalIRA(pat, balance=100000, growth_rate=0)
        donation = Donation(pat, "Food Bank", annual_amount=1000, donation_type=DonationType.QCD)
        model.step_year()
        self.assertEqual(donation.cash_given_this_year, 1000)
        self.assertEqual(model.tax_returns[2024].itemized_components["charity"], 1000)


class TestAppreciatedStockGift(unittest.TestCase):
    def test_shares_leave_without_a_gain_and_deduct_at_fmv_up_to_30_percent(self):
        model = _model(2024, checks="strict")
        pat = _person(model, "Pat")
        _job(pat, 100000)
        brokerage = BrokerageAccount(pat, "Example Brokerage", balance=0, growth_rate=0, dividend_yield=0)
        brokerage.deposit_with_basis(50000, 10000, acquired_year=2015)
        Donation(pat, "Food Bank", annual_amount=40000, donation_type=DonationType.STOCK)
        model.step_year()
        r = model.tax_returns[2024]
        self.assertAlmostEqual(brokerage.balance, 10000)
        self.assertEqual(r.long_term_gains_realized, 0)
        # 30% of AGI 100,000 = 30,000 deducted; 10,000 carries over in the property bucket.
        self.assertAlmostEqual(r.itemized_components["charity_noncash"], 30000)
        self.assertEqual(pat.charitable_property_carryforwards, [(2024, 10000)])
        self.assertEqual(check_model(model), [])


class TestIRAPhaseouts(unittest.TestCase):
    def test_covered_worker_deduction_phases_out_and_becomes_basis(self):
        # 2024 single active participant, MAGI 82,000: (87,000 - 82,000) / 10,000 x 7,000 = 3,500 deductible.
        from ..account.job401k import Job401kAccount

        model = _model(2024)
        alex = _person(model)
        job = _job(alex, 82000)
        Job401kAccount(job, pretax_contrib_percent=0)  # eligible to defer: an active participant
        ira = TraditionalIRA(alex, balance=0, growth_rate=0)
        ira.contribute(7000)
        model.step_year()
        r = model.tax_returns[2024]
        self.assertAlmostEqual(r.adjustments["ira_deduction"], 3500)
        self.assertAlmostEqual(ira.nondeductible_basis, 3500)

    def test_not_covered_keeps_the_full_deduction(self):
        model = _model(2024)
        alex = _person(model)
        _job(alex, 200000)
        ira = TraditionalIRA(alex, balance=0, growth_rate=0)
        ira.contribute(7000)
        model.step_year()
        self.assertAlmostEqual(model.tax_returns[2024].adjustments["ira_deduction"], 7000)

    def test_roth_excess_over_the_magi_limit_is_returned(self):
        # 2024 single, MAGI 153,500: (161,000 - 153,500) / 15,000 x 7,000 = 3,500 allowed; 3,500 returned.
        model = _model(2024, checks="strict")
        alex = _person(model, bank=10000)
        _job(alex, 153500)
        roth = RothIRA(alex, balance=0, growth_rate=0)
        roth.contribute(7000)
        model.step_year()
        self.assertAlmostEqual(roth.balance, 3500)
        self.assertEqual(check_model(model), [])


class TestStudentLoanPerReturn(unittest.TestCase):
    def test_joint_return_deducts_at_most_2500(self):
        model = _model(2024)
        family = Family(model)
        a, b = _person(model, "Pat", family=family), _person(model, "Lee", family=family)
        a.get_married(b)
        for person in (a, b):
            _job(person, 40000)
            StudentLoan(
                person,
                loan_type=StudentLoanType.FEDERAL_UNSUBSIDIZED,
                original_amount=50000,
                rate_pct=8.0,
                term_years=10,
                school_name="State University",
            )
        model.step_year()
        r = model.tax_returns[2024]
        self.assertEqual(r.filing_status, FilingStatus.MARRIED_FILING_JOINTLY.name)
        self.assertAlmostEqual(r.adjustments["student_loan_interest"], 2500)  # §221(b)(1): per return


class TestLongTermCarePremiums(unittest.TestCase):
    def test_premiums_count_up_to_the_age_limit(self):
        model = _model(2024)
        pat = _person(model, "Pat", 72)
        Insurance(pat, InsuranceType.LONG_TERM_CARE, "Example Mutual", premium_annual=8000, coverage_amount=100000)
        model.step_year()
        # Over 70: $5,880 (Rev. Proc. 2023-34 §3.28); no income, so no 7.5% floor.
        self.assertAlmostEqual(model.tax_returns[2024].itemized_components["medical"], 5880)
        self.assertEqual(deductible_insurance_premiums(pat), 0)  # a new year: nothing paid yet


class TestChildTaxCreditAge(unittest.TestCase):
    def test_a_17_year_old_gets_the_credit_for_other_dependents(self):
        model = _model(2026)
        parent = _person(model)
        _job(parent, 80000)
        Child(parent, "Junior", birth_year=2009)  # 17 at the end of 2026
        model.step_year()
        r = model.tax_returns[2026]
        self.assertEqual(r.credits_nonrefundable["child_tax_credit"], 500)  # ODC, not the $2,200 CTC


class TestSelfEmployment(unittest.TestCase):
    def test_self_employed_year_is_settled_and_conserves_money(self):
        model = _model(2024, 2026, checks="strict")
        casey = _person(model, "Casey", 45, bank=50000, spending=60000)
        sep = TraditionalIRA(casey, balance=0, growth_rate=0)
        Job(
            casey,
            "Example Consulting LLC",
            "Owner",
            Salary(model, base=150000),
            kind="self_employed",
            sep_account=sep,
            plan_contribution_percent=25,
        )
        model.run()
        r = model.tax_returns[2024]
        self.assertAlmostEqual(r.self_employment_tax, 21194.33, delta=0.01)
        # 138,525 x 15.3% = 21,194.325; half 10,597.1625; SEP 20% x (150,000 - 10,597.1625).
        self.assertAlmostEqual(r.adjustments["se_tax_deduction"], 10597.1625, places=4)
        self.assertAlmostEqual(r.adjustments["self_employed_plan"], (150000 - 10597.1625) * 0.2, places=4)
        self.assertAlmostEqual(r.qbi_deduction, 0.2 * (r.agi - 14600), places=3)
        self.assertEqual(r.social_security_tax, 0)  # no W-2 FICA
        self.assertEqual(check_model(model), [])

    def test_se_tax_shares_the_wage_base_with_w2_wages(self):
        model = _model(2025)
        sam = _person(model, "Sam")
        _job(sam, 150000)
        Job(sam, "Example Consulting LLC", "Owner", Salary(model, base=100000), kind="self_employed")
        model.step_year()
        line = model.tax_returns[2025].fica[0]
        self.assertAlmostEqual(line.self_employment_tax, 26100 * 0.124 + 92350 * 0.029, places=2)

    def test_w2_only_options_rejected(self):
        model = _model(2024)
        sam = _person(model, "Sam")
        with self.assertRaises(ValueError):
            Job(sam, "Co", "Analyst", Salary(model, base=1), expenses_annual=10)
        with self.assertRaises(ValueError):
            Job(sam, "Co", "Owner", Salary(model, base=1), kind="self_employed", payroll=PayrollDeductions(1000))


class TestDependentCareFSA(unittest.TestCase):
    def test_fsa_lowers_wages_and_fica_and_reports_box_10(self):
        model = _model(2024)
        family = Family(model)
        john, jane = _person(model, "John", family=family), _person(model, "Jane", family=family)
        john.get_married(jane)
        _job(john, 70000, payroll=PayrollDeductions(dependent_care_fsa_annual=5000))
        _job(jane, 45000)
        Child(john, "Junior", birth_year=2020)
        Child(john, "Kit", birth_year=2022)
        model.step_year()
        r = model.tax_returns[2024]
        self.assertAlmostEqual(r.wages, 110000)
        self.assertAlmostEqual(r.fica[0].wages, 65000)
        self.assertAlmostEqual(r.credits_nonrefundable["dependent_care_credit"], 200)


class TestIncentiveStockOptions(unittest.TestCase):
    def test_amt_in_the_exercise_year_and_the_credit_after(self):
        model = _model(2024, 2025, checks="strict")
        morgan = _person(model, "Morgan", bank=400000, spending=60000)
        BrokerageAccount(morgan, "Example Brokerage", balance=10000, growth_rate=0, dividend_yield=0)
        job = _job(morgan, 200000)
        StockPlan(job, growth_rate=0, options=[StockOption("iso", 2024, exercise_cost=50000, value=450000)])
        model.run()
        first, second = model.tax_returns[2024], model.tax_returns[2025]
        self.assertGreater(first.amt, 100000)
        self.assertAlmostEqual(first.amt_credit_generated, first.amt)
        self.assertEqual(first.wages, 200000)  # the held ISO's spread is not wages
        self.assertGreater(second.credits_nonrefundable["minimum_tax_credit"], 0)
        self.assertEqual(second.amt, 0)
        self.assertEqual(check_model(model), [])

    def test_nso_spread_is_wages(self):
        model = _model(2024)
        sam = _person(model, "Sam")
        BrokerageAccount(sam, "Example Brokerage", balance=0, growth_rate=0)
        job = _job(sam, 100000)
        StockPlan(job, growth_rate=0, options=[StockOption("nso", 2024, exercise_cost=10000, value=30000)])
        model.step_year()
        r = model.tax_returns[2024]
        self.assertAlmostEqual(r.wages, 120000)
        self.assertEqual(r.amt, 0)


class TestKiddieTax(unittest.TestCase):
    def test_form_8814_inclusion_and_tax(self):
        model = _model(2024)
        parent = _person(model)
        _job(parent, 150000)
        Child(parent, "Kit", birth_year=2012, interest_annual=2000, dividends_annual=3000)
        model.step_year()
        r = model.tax_returns[2024]
        self.assertEqual(r.kiddie_tax, 130)
        self.assertAlmostEqual(r.other_income_by_source["form_8814"], 960)
        self.assertAlmostEqual(r.qualified_dividends, 1440)

    def test_a_child_over_the_election_limit_files_their_own_return(self):
        model = _model(2024)
        parent = _person(model)
        _job(parent, 150000)
        Child(parent, "Kit", birth_year=2012, interest_annual=13000)
        model.step_year()
        self.assertEqual(model.tax_returns[2024].kiddie_tax, 0)


class TestProjection(unittest.TestCase):
    def test_parameters_after_the_table_are_indexed_by_their_statutes(self):
        from ..config.financial_config import default_financial_config

        config = default_financial_config()
        params = config.tax_year(2030, inflation_factor=1.10)
        self.assertEqual(params.eitc.earned_income_amount[1], round(13020 * 1.1 / 10) * 10)
        self.assertEqual(params.qcd_limit, 122000)  # 111,000 x 1.1 = 122,100 rounded down to $1,000
        self.assertEqual(params.ira_phaseouts.roth_single.end - params.ira_phaseouts.roth_single.start, 15000)
        self.assertEqual(params.amt.phaseout_rate, 50)
        self.assertEqual(params.dependent_care.max_rate, 50)  # statutory, not indexed


class TestIncomeTypeIsOrdinary(unittest.TestCase):
    def test_self_employment_income_is_ordinary_not_fica(self):
        from ..tax.income import IncomeLedger

        ledger = IncomeLedger()
        ledger.add(IncomeType.SELF_EMPLOYMENT, 1000)
        self.assertEqual(ledger.ordinary_taxable, 1000)
        self.assertEqual(ledger.fica_wages, 0)
        self.assertEqual(ledger.self_employment_income, 1000)


if __name__ == "__main__":
    unittest.main()


class TestSpecFields(unittest.TestCase):
    """The Plan 31 spec fields build into the core objects and extract back."""

    def _built(self, **person):
        from ..spec import build_household
        from .spec_helpers import minimal, spec_of

        return build_household(spec_of(minimal(**person)), check=True)

    def test_self_employment_with_sep(self):
        from ..spec import spec_from_model

        built = self._built(
            jobs=[],
            accounts=[{"kind": "bank", "balance": 20000}, {"kind": "traditional_ira", "id": "sep", "balance": 0}],
            self_employment={
                "business": "Example Consulting LLC",
                "gross_receipts_annual": 120000,
                "expenses_annual": 20000,
                "sep_ira_contrib_pct": 20,
                "sep_account": "sep",
            },
        )
        job = built.people["alex"].jobs[0]
        self.assertEqual((job.kind, job.net_profit(), job.plan_contribution_percent), ("self_employed", 100000, 20))
        self.assertIs(job.sep_account, built.items["sep"])
        extracted = spec_from_model(built.model).people[0].self_employment
        self.assertEqual((extracted.gross_receipts_annual, extracted.expenses_annual), (120000, 20000))

    def test_self_employment_needs_profit_or_receipts(self):
        from pydantic import ValidationError

        from .spec_helpers import minimal, spec_of

        with self.assertRaises(ValidationError):
            spec_of(minimal(self_employment={"business": "Example Consulting LLC"}))

    def test_payroll_options_children_and_qcd(self):
        from ..spec import spec_from_model

        built = self._built(
            jobs=[
                {
                    "id": "job",
                    "company": "Co",
                    "salary_annual": 80000,
                    "payroll": {"dependent_care_fsa_annual": 5000},
                    "stock_plan": {
                        "growth_pct": 0,
                        "options": [{"kind": "iso", "exercise_year": 2027, "exercise_cost": 1000, "value": 5000}],
                    },
                }
            ],
            children=[{"name": "Kit", "birth_year": 2020, "care_expenses_annual": 3000, "interest_annual": 100}],
            giving=[{"kind": "donation", "charity": "Food Bank", "amount_annual": 100, "donation_type": "qcd"}],
        )
        person = built.people["alex"]
        job = person.jobs[0]
        self.assertEqual(job.payroll.dependent_care_fsa_annual, 5000)
        self.assertEqual(job.stock_plan.options[0].kind, "iso")
        self.assertEqual((person.children[0].care_expenses_annual, person.children[0].interest_annual), (3000, 100))
        self.assertEqual(person.donations[0].donation_type, DonationType.QCD)
        spec = spec_from_model(built.model)
        self.assertEqual(spec.people[0].jobs[0].payroll.dependent_care_fsa_annual, 5000)
        self.assertEqual(spec.people[0].jobs[0].stock_plan.options[0].exercise_cost, 1000)

    def test_other_payroll_items_are_supported_since_plan_27(self):
        from ..spec.validate import validate_spec
        from .spec_helpers import minimal, spec_of

        spec = spec_of(minimal(jobs=[{"company": "Co", "salary_annual": 1, "payroll": {"fsa_annual": 500}}]))
        self.assertNotIn("not_yet_supported", [f.code for f in validate_spec(spec)])


class TestValidatorWarnings(unittest.TestCase):
    def test_fsa_without_a_young_child_and_a_child_over_the_8814_limit(self):
        from ..spec.validate import validate_spec
        from .spec_helpers import minimal, spec_of

        spec = spec_of(
            minimal(
                jobs=[{"company": "Co", "salary_annual": 80000, "payroll": {"dependent_care_fsa_annual": 5000}}],
                children=[{"name": "Kit", "birth_year": 2010, "interest_annual": 20000}],
            )
        )
        codes = [f.code for f in validate_spec(spec)]
        self.assertIn("fsa_without_care", codes)
        self.assertIn("child_files_own_return", codes)


class TestSolo401k(unittest.TestCase):
    def test_deferral_and_profit_sharing_within_the_limits(self):
        from ..account.job401k import Job401kAccount
        from ..insurance.social_security import SocialSecurity

        model = _model(2024, checks="strict")
        casey = _person(model, "Casey", 45, bank=50000, spending=40000)
        job = Job(
            casey,
            "Example Consulting LLC",
            "Owner",
            Salary(model, base=200000),
            kind="self_employed",
            plan_contribution_percent=25,
        )
        account = Job401kAccount(job, pretax_contrib_percent=20, average_growth=0)
        SocialSecurity(casey, claim_age=67, earnings_history=[])
        model.step_year()
        # Net earnings 184,700; SE tax = 12.4% x 168,600 + 2.9% x 184,700 = 26,262.70; half 13,131.35.
        # Compensation 186,868.65: deferral 20% capped at 402(g) $23,000; employer 20% = 37,373.73;
        # together 60,373.73 under 415(c) $69,000.
        compensation = 200000 - 13131.35
        self.assertAlmostEqual(account.pretax_balance, 23000 + compensation * 0.2, places=2)
        r = model.tax_returns[2024]
        self.assertAlmostEqual(r.adjustments["self_employed_plan"], 23000 + compensation * 0.2, places=2)
        # Social Security credit: net earnings, capped at the wage base.
        self.assertEqual(casey.social_security.income_history[-1].amount, 168600)
        self.assertEqual(check_model(model), [])


class TestMonthlyTiming(unittest.TestCase):
    """Plan 31 on the monthly engine (Plan 32): profit and the FSA per month, the SEP in December."""

    def test_profit_monthly_and_sep_with_the_december_payment(self):
        model = _model(2024)
        casey = _person(model, "Casey", 45, bank=50000)
        sep = TraditionalIRA(casey, balance=0, growth_rate=0)
        Job(
            casey,
            "Example Consulting LLC",
            "Owner",
            Salary(model, base=120000),
            kind="self_employed",
            sep_account=sep,
            plan_contribution_percent=25,
        )
        for _ in range(11):
            model.step()
        self.assertAlmostEqual(casey.income.self_employment_income, 110000)
        self.assertEqual(sep.balance, 0)
        model.step()  # December: the last payment and the year's SEP contribution, then settlement
        self.assertGreater(sep.balance, 0)
        self.assertAlmostEqual(model.tax_returns[2024].business_income, 120000)

    def test_fsa_comes_out_of_each_paycheck(self):
        model = _model(2024)
        john = _person(model, "John")
        _job(john, 60000, payroll=PayrollDeductions(dependent_care_fsa_annual=1200))
        model.step()
        self.assertAlmostEqual(john.income.dependent_care_benefits, 100)
        self.assertAlmostEqual(john.fica_wages, 4900)


class TestTaxYearAges(unittest.TestCase):
    def test_section_63f_uses_the_age_at_the_end_of_the_year(self):
        # Born October 1961: 64 in January 2026, 65 by December 31 -> the $2,050 additional amount.
        model = LifeModel(start_year=2026, end_year=2026)
        pat = Person(Family(model), "Pat", None, 67, Spending(model, 0), birth="1961-10")
        BankAccount(pat, "Bank", balance=100000, interest_rate=0)
        _job(pat, 50000)
        model.step_year()
        self.assertEqual(model.tax_returns[2026].additional_standard_deduction, 2050)
