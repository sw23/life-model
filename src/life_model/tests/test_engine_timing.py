# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Plan 26: engine timing, events and settlement correctness.

Each test class reproduces one defect from the plan's problem statement (the probe scripts that
found them) and pins the corrected behaviour. Dollar assertions load the frozen fixture config.
"""

import unittest
import warnings
from pathlib import Path

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount, TaxLot
from ..account.job401k import Job401kAccount
from ..account.pension import Pension
from ..account.roth_IRA import RothIRA
from ..config.financial_config import FinancialConfig
from ..dependents.child import Child
from ..healthcare.medical_costs import MedicalCosts
from ..housing.apartment import Apartment
from ..housing.home import Home, HomeExpenses, Mortgage
from ..insurance.annuity import Annuity, AnnuityType
from ..insurance.life_insurance import LifeInsurance, LifeInsuranceType, PremiumIncreaseType
from ..insurance.social_security import SocialSecurity, taxable_social_security
from ..lifeevents import LifeEvent, LifeEventRecord, LifeEvents
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..people.tax_unit import DEFAULT_WITHDRAWAL_ORDER, TaxUnit
from ..people.types import MortalityMode
from ..tax.federal import FilingStatus
from ..tax.income import IncomeLedger, IncomeType
from ..tax.state import state_income_tax_for_unit
from ..work.job import Job, Salary
from ..work.stock import StockPlan, VestingSchedule
from .helpers import run_months

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    """Fresh FinancialConfig loaded from the frozen test fixture."""
    return FinancialConfig(config_file=TEST_CONFIG)


def _model(start_year=2026, end_year=2030) -> LifeModel:
    return LifeModel(start_year=start_year, end_year=end_year, config=_fixture_config())


def _worker(model, family=None, *, name="A", age=40, salary=100000, spending=50000, bank=100000, retirement_age=65):
    family = family or Family(model)
    person = Person(family, name, age=age, retirement_age=retirement_age, spending=Spending(model, base=spending))
    BankAccount(person, "Bank", balance=bank, interest_rate=0)
    if salary:
        Job(person, "Co", "Eng", Salary(model, base=salary))
    return person


def _agent_column(model, agent, column):
    frame = model.datacollector.get_agent_vars_dataframe().xs(agent.unique_id, level="AgentID")
    return frame[column].tolist()


class TestAgeSemantics(unittest.TestCase):
    """Item 1 / D1: the constructor age is the age during the first simulated year."""

    def test_collected_age_starts_at_constructor_age(self):
        model = _model()
        person = _worker(model)
        model.add_agent_stat("Age", "age")
        model.run()
        self.assertEqual(_agent_column(model, person, "Age"), [40, 41, 42, 43, 44])

    def test_get_year_at_age_is_start_year_plus_offset(self):
        model = _model()
        person = _worker(model)
        self.assertEqual(person.get_year_at_age(42), 2028)
        self.assertEqual(person.get_year_at_age(40), 2026)
        model.step_year()
        model.step_year()
        # Stable as the simulation advances (no drift once ages start incrementing).
        self.assertEqual(person.get_year_at_age(42), 2028)

    def test_age_in_inverts_get_year_at_age(self):
        model = _model()
        person = _worker(model)
        self.assertEqual(person.age_in(2026), 40)
        self.assertEqual(person.age_in(2030), 44)
        model.run()
        self.assertEqual(person.age_in(2026), 40)
        self.assertEqual(person.age_in(person.get_year_at_age(65)), 65)

    def test_event_dated_by_age_fires_at_that_age(self):
        model = _model()
        person = _worker(model)
        fired = []
        LifeEvents(model, [LifeEvent(person.get_year_at_age(42), "age 42", lambda: fired.append(person.age))])
        model.run()
        self.assertEqual(fired, [42])

    def test_person_created_mid_run_keeps_constructor_age_that_year(self):
        model = _model()
        _worker(model)
        model.step_year()  # 2026
        late = _worker(model, name="Late", age=30)  # built between steps: 30 during 2027
        model.add_agent_stat("Age", "age")
        model.step_year()  # 2027
        self.assertEqual(late.age_in(2027), 30)
        model.step_year()  # 2028
        self.assertEqual(late.age_in(2028), 31)
        # Between steps the model is at the next month to simulate, and ``age`` is the age then.
        self.assertEqual((model.year, late.age), (2029, 32))


def _frame(model):
    return model.datacollector.get_model_vars_dataframe().set_index("Year")


def _buy_home(person, price=300000, down=60000):
    """Life-event callable: buy a home now (down payment + closing costs leave the household)."""
    model = person.model
    mortgage = Mortgage(loan_amount=price - down, start_date=model.year, length_years=30, yearly_interest_rate=6.0)
    expenses = HomeExpenses(
        model=model,
        property_tax_percent=1.0,
        home_insurance_percent=0.0,
        maintenance_amount=2000,
        maintenance_increase=10.0,
        improvement_amount=0,
        improvement_increase=0.0,
        hoa_amount=0,
        hoa_increase=0.0,
    )
    return Home(
        person=person,
        name="New House",
        purchase_price=price,
        value_yearly_increase=5.0,
        down_payment=down,
        mortgage=mortgage,
        expenses=expenses,
        purchase=True,
    )


class TestEventsStage(unittest.TestCase):
    """Item 2 / D2: events fire after income arrives and before the year is settled."""

    def test_stage_order(self):
        self.assertEqual(LifeModel.STAGES, ("pre_step", "events", "step", "post_step"))

    def test_one_time_expense_from_event_is_paid_this_year(self):
        model = _model(end_year=2028)
        person = _worker(model)
        LifeEvents(model, [LifeEvent(2027, "car", person.spending.add_expense, 30000)])
        model.run()
        df = _frame(model)
        self.assertEqual(df.loc[2026, "Spending"], 50000)
        self.assertEqual(df.loc[2027, "Spending"], 80000)
        self.assertEqual(df.loc[2028, "Spending"], 50000)
        # The bank paid it in 2027: that year saves $30k less than the year before.
        saved_2026 = df.loc[2026, "Bank Balance"] - 100000
        saved_2027 = df.loc[2027, "Bank Balance"] - df.loc[2026, "Bank Balance"]
        self.assertAlmostEqual(saved_2026 - saved_2027, 30000 + (df.loc[2027, "Taxes"] - df.loc[2026, "Taxes"]), 2)

    def test_home_bought_mid_year_has_its_gains_taxed_and_pays_first_year_costs(self):
        model = _model(end_year=2028)
        person = _worker(model, bank=0, salary=0, spending=0)
        brokerage = BrokerageAccount(person, "Broker", balance=200000, growth_rate=0, dividend_yield=0)
        brokerage.lots = [TaxLot(value=200000, cost_basis=100000, acquired_year=2020)]
        homes = []
        LifeEvents(model, [LifeEvent(2027, "buy", lambda: homes.append(_buy_home(person)))])
        model.run()
        df = _frame(model)
        home = homes[0]
        closing = 300000 * model.config.housing.closing_cost_percent / 100
        # The purchase sold brokerage (half of each dollar is gain) and the gain was taxed in 2027.
        self.assertGreater(df.loc[2027, "Capital Gains"], (60000 + closing) / 2 - 1)
        self.assertGreater(df.loc[2027, "Taxes"], 0)
        self.assertEqual(df.loc[2026, "Taxes"], 0)
        # First-year housing costs were paid in the purchase year (12 mortgage payments + expenses).
        expected_housing_2027 = 12 * home.mortgage.monthly_payment + 2000 + 300000 * 0.01
        self.assertAlmostEqual(df.loc[2027, "Housing"], expected_housing_2027, delta=1.0)
        # The purchase year was a full year of use, so the escalators run at its end like any other
        # year's (2027 and 2028 increases).
        self.assertAlmostEqual(home.expenses.maintenance_amount, 2420, places=6)
        self.assertAlmostEqual(home.home_value, 330750, places=6)

    def test_salary_change_applies_same_year(self):
        model = _model(end_year=2028)
        person = _worker(model, salary=0)
        salary = Salary(model, base=100000)
        job = Job(person, "Co", "Eng", salary)
        LifeEvents(model, [LifeEvent(2027, "raise", setattr, salary, "base", 150000)])
        model.run()
        df = _frame(model)
        self.assertEqual(df.loc[2026, "Income"], 100000)
        self.assertEqual(df.loc[2027, "Income"], 150000)
        self.assertEqual(job.stat_gross_income, 150000)

    def test_job_started_by_event_pays_that_year(self):
        model = _model(end_year=2028)
        person = _worker(model, salary=0)
        jobs = []

        def start_job():
            jobs.append(Job(person, "NewCo", "Eng", Salary(model, base=80000, yearly_increase=10)))

        LifeEvents(model, [LifeEvent(2027, "new job", start_job)])
        model.run()
        df = _frame(model)
        self.assertEqual(df.loc[2026, "Income"], 0)
        self.assertEqual(df.loc[2027, "Income"], 80000)  # booked by the step-stage payroll true-up
        self.assertAlmostEqual(df.loc[2028, "Income"], 88000, places=6)  # first raise after a year

    def test_marriage_event_files_jointly_that_year(self):
        model = _model(end_year=2027)
        family = Family(model)
        a = _worker(model, family, name="A")
        b = _worker(model, family, name="B", salary=0)
        LifeEvents(model, [LifeEvent(2027, "wedding", a.get_married, b)])
        model.run()
        self.assertEqual(a.filing_status, FilingStatus.MARRIED_FILING_JOINTLY)
        df = _frame(model)
        # Same income both years; filing jointly in 2027 lowers the tax.
        self.assertLess(df.loc[2027, "Taxes"], df.loc[2026, "Taxes"])

    def test_events_are_logged(self):
        model = _model(end_year=2027)
        person = _worker(model)
        LifeEvents(model, [LifeEvent(2027, "car", person.spending.add_expense, 1000)])
        model.run()
        records = [e for e in model.event_log.list if isinstance(e, LifeEventRecord)]
        self.assertEqual(len(records), 1)
        self.assertEqual((records[0].year, records[0].name, records[0].stage), (2027, "car", "events"))

    def test_pre_step_event_applies_before_income(self):
        model = _model(end_year=2027)
        person = _worker(model, salary=0)
        salary = Salary(model, base=100000)
        Job(person, "Co", "Eng", salary)
        seen = []
        LifeEvents(model, [LifeEvent(2027, "peek", lambda: seen.append(person.income.fica_wages), stage="pre_step")])
        model.run()
        self.assertEqual(seen, [0.0])  # wages had not arrived yet

    def test_post_step_event_takes_effect_next_year(self):
        model = _model(end_year=2028)
        person = _worker(model)
        # December's post_step: after the year's last bills are paid (Plan 32: events fire in a month).
        LifeEvents(model, [LifeEvent(2026, "late", person.spending.add_expense, 5000, stage="post_step", month=12)])
        model.run()
        df = _frame(model)
        self.assertEqual(df.loc[2026, "Spending"], 50000)
        self.assertEqual(df.loc[2027, "Spending"], 55000)

    def test_unknown_stage_rejected(self):
        with self.assertRaises(ValueError):
            LifeEvent(2026, "x", print, stage="step")


class TestCreatedYear(unittest.TestCase):
    """D2: agents record when (and in which stage) they were built.

    An agent built by a life event is consumed in its creation year (events run before settlement,
    and Job.step books a new job's payroll), so its year-end escalator runs that year like any
    other agent's: a mid-year lease's rent rises at the end of its first year, as a setup lease's does.
    """

    def test_setup_agents_escalate_in_the_first_year(self):
        model = _model(end_year=2027)
        person = _worker(model, salary=0)
        salary = Salary(model, base=100000, yearly_increase=10)
        Job(person, "Co", "Eng", salary)
        rent = Apartment(person, "Flat", monthly_rent=1000, yearly_increase=10)
        self.assertEqual((salary.created_year, salary.created_in_stage), (2026, None))
        model.step_year()
        self.assertAlmostEqual(salary.base, 110000, places=6)
        self.assertAlmostEqual(rent.monthly_rent, 1100, places=6)

    def test_mid_year_agents_are_used_and_escalated_in_their_creation_year(self):
        model = _model(end_year=2028)
        person = _worker(model)
        built = {}

        def sign_lease():
            built["rent"] = Apartment(person, "Flat", monthly_rent=1000, yearly_increase=10)
            built["spending"] = Spending(model, base=1000, yearly_increase=10)

        LifeEvents(model, [LifeEvent(2027, "lease", sign_lease)])
        model.run()
        rent = built["rent"]
        self.assertEqual((rent.created_year, rent.created_in_stage), (2027, "events"))
        self.assertTrue(rent.created_in_stage is not None and not rent.created_during_this_year)  # now 2029
        df = _frame(model)
        self.assertEqual(df.loc[2027, "Housing"], 12000)  # the signed rent, paid for 2027
        self.assertAlmostEqual(df.loc[2028, "Housing"], 13200, places=6)
        self.assertAlmostEqual(rent.monthly_rent, 1210, places=6)
        self.assertAlmostEqual(built["spending"].base, 1210, places=6)


class TestPastEvents(unittest.TestCase):
    """Item 3 / D3: events dated before the start year raise, or apply at construction."""

    def test_past_event_raises(self):
        model = _model()
        person = _worker(model)
        with self.assertRaises(ValueError):
            LifeEvents(model, [LifeEvent(2024, "car", person.spending.add_expense, 30000)])

    def test_allow_past_applies_immediately(self):
        model = _model(end_year=2026)
        family = Family(model)
        a = _worker(model, family, name="A")
        b = _worker(model, family, name="B", salary=0)
        LifeEvents(model, [LifeEvent(2024, "wedding", a.get_married, b)], allow_past=True)
        self.assertIs(a.spouse, b)  # applied at construction, before the first year
        model.run()
        self.assertEqual(a.filing_status, FilingStatus.MARRIED_FILING_JOINTLY)
        records = [e for e in model.event_log.list if isinstance(e, LifeEventRecord)]
        self.assertEqual([r.stage for r in records], ["construction"])

    def test_event_after_end_year_warns(self):
        model = _model(end_year=2027)
        person = _worker(model)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            LifeEvents(model, [LifeEvent(2040, "late", person.spending.add_expense, 1)])
        self.assertTrue(any("after the simulation's end year" in str(w.message) for w in caught))


def _probe4_household(*, spouse_first=False, years=3):
    """The review's probe 4: a married homeowner couple with a 401k and a taxable brokerage account,
    whose combined bank comfortably covers every year's bills."""
    model = LifeModel(start_year=2026, end_year=2026 + years - 1, config=_fixture_config())
    family = Family(model)

    def build_a():
        a = Person(family, "A", age=40, retirement_age=65, spending=Spending(model, base=60000))
        BankAccount(a, "Bank", balance=30000, interest_rate=0)
        BrokerageAccount(a, "Fid", balance=300000, growth_rate=6, dividend_yield=0)
        job = Job(a, "Co", "Eng", Salary(model, base=180000, yearly_bonus=10))
        Job401kAccount(job=job, pretax_balance=200000, pretax_contrib_percent=10, average_growth=6)
        return a

    def build_b():
        b = Person(family, "B", age=38, retirement_age=65, spending=Spending(model, base=20000))
        BankAccount(b, "Bank", balance=20000, interest_rate=0)
        Job(b, "Co2", "Mgr", Salary(model, base=120000))
        return b

    if spouse_first:
        b = build_b()
        a = build_a()
    else:
        a = build_a()
        b = build_b()
    a.get_married(b)
    mortgage = Mortgage(loan_amount=480000, start_date=2024, length_years=30, yearly_interest_rate=6.5)
    expenses = HomeExpenses(
        model=model,
        property_tax_percent=1.2,
        home_insurance_percent=0.5,
        maintenance_amount=3000,
        maintenance_increase=2,
        improvement_amount=0,
        improvement_increase=0,
        hoa_amount=0,
        hoa_increase=0,
    )
    Home(a, "Home", 600000, 3.0, 120000, mortgage, expenses)
    return model


class TestHouseholdWaterfall(unittest.TestCase):
    """Item 4 / D4: a married unit pays from all members' banks before selling anyone's brokerage."""

    def test_married_couple_sells_no_brokerage_while_combined_bank_covers_bills(self):
        model = _probe4_household()
        model.run()
        df = _frame(model)
        self.assertTrue((df["Capital Gains"] == 0).all())
        self.assertTrue((df["Brokerage Balance"].diff().dropna() > 0).all())  # only growth, no sales
        self.assertTrue((df["Bank Balance"] > 0).all())

    def test_result_independent_of_spouse_construction_order(self):
        first = _probe4_household(spouse_first=False, years=5)
        second = _probe4_household(spouse_first=True, years=5)
        first.run()
        second.run()
        a = first.datacollector.get_model_vars_dataframe()
        b = second.datacollector.get_model_vars_dataframe()
        for column in a.columns:
            for x, y in zip(a[column], b[column]):
                self.assertAlmostEqual(float(x), float(y), delta=1e-6, msg=column)

    def test_withdrawal_order_validation(self):
        model = _model()
        with self.assertRaises(ValueError):
            Family(model, withdrawal_order=("brokerage", "bank", "roth_basis", "pretax", "roth_earnings"))
        with self.assertRaises(ValueError):
            Family(model, withdrawal_order=("bank", "brokerage", "pretax"))
        self.assertEqual(Family(model).withdrawal_order, DEFAULT_WITHDRAWAL_ORDER)

    def test_unit_pay_bills_uses_both_banks_before_brokerage(self):
        model = _model()
        family = Family(model)
        a = _worker(model, family, name="A", salary=0, bank=1000)
        b = _worker(model, family, name="B", salary=0, bank=5000)
        a.get_married(b)
        brokerage = BrokerageAccount(a, "Fid", balance=10000, growth_rate=0, dividend_yield=0)
        unit = TaxUnit.for_member(a)
        self.assertEqual(len(unit.members), 2)
        self.assertEqual(unit.pay_bills(4000), 0)
        self.assertEqual(a.bank_account_balance + b.bank_account_balance, 2000)
        self.assertEqual(brokerage.balance, 10000)


class TestRothBasisBeforePretax(unittest.TestCase):
    """Item 10 / D4: under 59.5, penalty-free Roth basis is spent before a penalized pre-tax draw."""

    def _saver(self, withdrawal_order=None):
        model = _model(end_year=2026)
        family = Family(model, withdrawal_order=withdrawal_order)
        person = _worker(model, family, age=45, salary=0, spending=30000, bank=0)
        job = Job(person, "Old", "Eng", Salary(model, base=0))
        account = Job401kAccount(job=job, pretax_balance=200000, average_growth=0)
        roth = RothIRA(person, balance=50000, growth_rate=0)
        return model, person, account, roth

    def test_roth_basis_pays_before_the_401k(self):
        model, person, account, roth = self._saver()
        model.run()
        self.assertAlmostEqual(roth.balance, 20000, places=2)
        self.assertEqual(account.pretax_balance, 200000)
        self.assertEqual(person.stat_taxes_paid, 0)  # no 10% penalty, no ordinary income
        self.assertEqual(person.debt, 0)

    def test_pretax_first_order_keeps_old_behaviour_reachable(self):
        order = ("bank", "brokerage", "pretax", "roth_basis", "roth_earnings")
        model, person, account, roth = self._saver(withdrawal_order=order)
        model.run()
        self.assertEqual(roth.balance, 50000)
        self.assertLess(account.pretax_balance, 200000 - 30000)  # grossed up for tax + penalty
        self.assertGreater(person.stat_taxes_paid, 0)


class TestMidYearPurchaseUsesHouseholdWaterfall(unittest.TestCase):
    """Item 11 / D4: a purchase the bank and brokerage can't cover draws the 401k, not a credit card."""

    def test_home_purchase_draws_the_401k_instead_of_creating_debt(self):
        model = _model(end_year=2026)
        person = _worker(model, age=62, salary=0, spending=0, bank=10000)
        job = Job(person, "Old", "Eng", Salary(model, base=0))
        account = Job401kAccount(job=job, pretax_balance=500000, average_growth=0)
        home = _buy_home(person)  # at setup: purchase=True pays down + closing now
        closing = 300000 * model.config.housing.closing_cost_percent / 100
        self.assertEqual(person.debt, 0)
        self.assertAlmostEqual(account.pretax_balance, 500000 - (60000 + closing - 10000), places=2)
        model.run()
        # The distribution was taxed with the year's return and the year's bills were paid.
        self.assertGreater(person.stat_taxes_paid, 0)
        self.assertEqual(person.debt, 0)
        self.assertGreater(home.home_value, 0)


class TestBankInterestIsIncome(unittest.TestCase):
    """Item 5 / D5: bank interest is ordinary (NIIT) income on the owner's ledger."""

    def _taxes(self, rate):
        model = _model(end_year=2027)
        person = _worker(model, spending=10000, bank=0)
        BankAccount(person, "Savings", balance=1_000_000, interest_rate=rate)
        model.run()
        return _frame(model)["Taxes"].tolist()

    def test_interest_raises_taxes(self):
        taxed, untaxed = self._taxes(5), self._taxes(0)
        for with_interest, without in zip(taxed, untaxed):
            # ~$51k of interest on top of $100k of wages: at least the 22% bracket's worth.
            self.assertGreater(with_interest - without, 0.22 * 50000)

    def test_interest_is_posted_to_the_ledger_as_interest(self):
        model = _model()
        person = _worker(model, salary=0, bank=0)
        account = BankAccount(person, "Savings", balance=10000, interest_rate=5, compounding="annual")
        run_months(model, account.step)  # a year of monthly interest (Plan 32)
        totals = person.income.totals_by_type()
        self.assertAlmostEqual(totals[IncomeType.INTEREST], 500, places=6)
        self.assertAlmostEqual(person.income.net_investment_income, 500, places=6)
        self.assertAlmostEqual(account.balance, 10500, places=6)

    def test_compounding_convention(self):
        model = _model()
        person = _worker(model, salary=0, bank=0)
        annual = BankAccount(person, "A", balance=1000, interest_rate=5, compounding="annual")
        monthly = BankAccount(person, "M", balance=1000, interest_rate=5, compounding="monthly")
        default = BankAccount(person, "D", balance=1000, interest_rate=5)
        for account in (annual, monthly, default):
            run_months(model, account.step)  # a year of monthly interest (Plan 32)
        self.assertAlmostEqual(annual.balance, 1050, places=6)
        # interest_rate is an APR compounded monthly: APY = (1 + 0.05/12)^12 - 1 = 5.116%.
        self.assertAlmostEqual(monthly.balance, 1000 * (1 + 0.05 / 12) ** 12, places=6)
        self.assertEqual(default.balance, monthly.balance)  # config default: monthly
        with self.assertRaises(ValueError):
            BankAccount(person, "X", compounding="daily")

    def test_interest_accrues_before_settlement_and_is_reported_at_year_end(self):
        model = _model(end_year=2026)
        person = _worker(model, salary=0, spending=10000, bank=0)
        account = BankAccount(person, "Savings", balance=100000, interest_rate=5, compounding="annual")
        model.run()
        taxes = person.stat_taxes_paid
        self.assertAlmostEqual(account.balance, 100000 + 5000 - 10000 - taxes, places=2)
        self.assertAlmostEqual(account.stat_useable_balance, account.balance, places=6)


class TestTaxExemptInterestTypes(unittest.TestCase):
    """D5: interest types for Plan 27's fixed income: municipal (federally exempt) and Treasury
    (state-exempt)."""

    def test_municipal_interest_is_outside_ordinary_income_and_niit(self):
        ledger = IncomeLedger()
        ledger.add(IncomeType.TAX_EXEMPT_INTEREST, 1000)
        ledger.add(IncomeType.INTEREST, 200)
        self.assertEqual(ledger.ordinary_taxable, 200)
        self.assertEqual(ledger.net_investment_income, 200)
        self.assertEqual(ledger.tax_exempt_interest, 1000)

    def test_treasury_interest_is_federally_taxable_and_state_exempt(self):
        ledger = IncomeLedger()
        ledger.add(IncomeType.TREASURY_INTEREST, 1000)
        self.assertEqual(ledger.ordinary_taxable, 1000)
        self.assertEqual(ledger.net_investment_income, 1000)

        # Structural check (with == without), so the live config's real CA pack is fine here.
        config = FinancialConfig()
        wages_only = IncomeLedger()
        wages_only.add_wages(100000, 100000)
        with_treasury = IncomeLedger()
        with_treasury.add_wages(100000, 100000)
        with_treasury.add(IncomeType.TREASURY_INTEREST, 50000)
        for state, legacy_base in (("CA", None), (None, 100000)):
            base = wages_only.totals_by_type(), with_treasury.totals_by_type()
            plain = state_income_tax_for_unit(base[0], FilingStatus.SINGLE, state, legacy_base or 0, config)
            treasury = state_income_tax_for_unit(
                base[1], FilingStatus.SINGLE, state, (legacy_base or 0) + 50000, config
            )
            self.assertGreater(plain, 0)
            self.assertAlmostEqual(plain, treasury, places=6, msg=state)


def _retiree(model, family=None, *, name="R", age=70, bank=0, spending=0, retirement_age=65):
    """A retiree already collecting Social Security (40 years of $60k earnings, claimed at 67)."""
    person = _worker(
        model, family, name=name, age=age, salary=0, spending=spending, bank=bank, retirement_age=retirement_age
    )
    history = [(year, 60000) for year in range(1980, 2020)]
    SocialSecurity(person=person, withdrawal_start_age=67, income_history=history)
    return person


class TestSocialSecurityTaxedAtSettlement(unittest.TestCase):
    """Item 6 / D6: the taxable share of benefits comes from the unit's final ledger.

    Benefits need the live config's wage-index and COLA history (the fixture is trimmed); every
    assertion is relative to ``taxable_social_security`` under the same config, not a dollar pin.
    """

    def test_joint_return_pools_the_spouses_income(self):
        model = LifeModel(start_year=2026, end_year=2026)
        family = Family(model)
        retiree = _retiree(model, family)
        spouse = _worker(model, family, name="S", age=60, salary=60000, spending=0)
        retiree.get_married(spouse)
        model.run()
        benefit = retiree.stat_ss_income
        self.assertGreater(benefit, 20000)
        expected = taxable_social_security(benefit, 60000, FilingStatus.MARRIED_FILING_JOINTLY, model.config)
        self.assertGreater(expected, 0)
        # AGI = the spouse's wages + the taxable benefits (the retiree alone would owe none).
        self.assertAlmostEqual(retiree.agi_history[2026], 60000 + expected, places=2)

    def test_solver_draw_raises_the_taxable_share(self):
        model = LifeModel(start_year=2026, end_year=2026)
        retiree = _retiree(model, spending=60000)
        job = Job(retiree, "Old", "Eng", Salary(model, base=0))
        account = Job401kAccount(job=job, pretax_balance=1_000_000, average_growth=0)
        model.run()
        rmd = account.stat_required_min_distrib
        draw = 1_000_000 - account.pretax_balance - rmd
        benefit = retiree.stat_ss_income
        taxable = retiree.agi_history[2026] - draw - rmd
        self.assertGreater(draw, 0)
        expected = taxable_social_security(benefit, draw + rmd, FilingStatus.SINGLE, model.config)
        self.assertGreater(expected, 0)
        self.assertAlmostEqual(taxable, expected, places=2)
        self.assertEqual(retiree.debt, 0)  # the draw was sized for the tax on the SS it made taxable

    def test_rsu_vest_counts_toward_provisional_income(self):
        model = LifeModel(start_year=2026, end_year=2027)
        retiree = _retiree(model, age=68, retirement_age=80)  # still on payroll (RSUs only)
        job = Job(retiree, "Co", "Advisor", Salary(model, base=0))
        StockPlan(job, signon_value=80000, schedule=VestingSchedule([1.0]), growth_rate=0)
        model.run()
        benefit = retiree.stat_ss_income
        expected = taxable_social_security(benefit, 80000, FilingStatus.SINGLE, model.config)
        self.assertAlmostEqual(retiree.agi_history[2027], 80000 + expected, places=2)


class TestMatchTiers(unittest.TestCase):
    """Item 7 / D7: the employer match as plan documents state it, the deprecated alias, 415(c)."""

    def _match(self, *, deferral=6, salary=100000, bonus=0, model=None, **account_kwargs):
        model = model or _model(end_year=2026)
        person = _worker(model, salary=0, bank=0, spending=0)
        job = Job(person, "Co", "Eng", Salary(model, base=salary, yearly_bonus=bonus))
        Job401kAccount(job=job, pretax_contrib_percent=deferral, average_growth=0, **account_kwargs)
        model.run()
        return job.stat_retirement_match

    def test_single_tier(self):
        self.assertAlmostEqual(self._match(match_tiers=[(50, 6)]), 3000, places=6)

    def test_safe_harbor_tiers(self):
        tiers = [(100, 3), (50, 2)]
        self.assertAlmostEqual(self._match(match_tiers=tiers), 4000, places=6)  # 3% + 1% of pay
        self.assertAlmostEqual(self._match(deferral=4, match_tiers=tiers), 3500, places=6)
        self.assertAlmostEqual(self._match(deferral=2, match_tiers=tiers), 2000, places=6)

    def test_match_on_bonus(self):
        tiers = [(100, 6)]
        self.assertAlmostEqual(self._match(bonus=10, match_tiers=tiers), 6000, places=6)
        self.assertAlmostEqual(self._match(bonus=10, match_tiers=tiers, match_on_bonus=True), 6600, places=6)

    def test_deprecated_percent_warns_and_keeps_the_legacy_formula(self):
        with self.assertWarns(DeprecationWarning) as caught:
            match = self._match(company_match_percent=6)
        self.assertAlmostEqual(match, 360, places=6)  # 6% of the $6,000 deferral
        self.assertIn("match_tiers=[(100, 6)]", str(caught.warning))

    def test_tiers_and_deprecated_percent_are_exclusive(self):
        with self.assertRaises(ValueError):
            self._match(company_match_percent=6, match_tiers=[(100, 6)])

    def test_415c_limit_is_year_indexed(self):
        # A huge match is capped at that year's annual-additions limit minus the deferral.
        model = LifeModel(start_year=2023, end_year=2023)
        self.assertEqual(model.year_config.get_job_401k_annual_additions_limit(), 66000)
        match = self._match(model=model, salary=1_000_000, deferral=1, match_tiers=[(1000, 10)])
        self.assertAlmostEqual(match, 66000 - 10000, places=6)

    def test_unvested_match_forfeited_on_leaving_early(self):
        model = _model(end_year=2028)
        person = _worker(model, salary=0, bank=0, spending=0)
        job = Job(person, "Co", "Eng", Salary(model, base=100000))
        account = Job401kAccount(
            job=job, pretax_contrib_percent=6, average_growth=0, match_tiers=[(100, 6)], match_vesting_years=3
        )
        # Quits after December 2027's paycheck (Plan 32: an event in a year fires in its month).
        LifeEvents(model, [LifeEvent(2027, "quit", job.retire, month=12)])
        model.run()
        # Two years of deferrals stay; two years of unvested match are forfeited.
        self.assertAlmostEqual(account.pretax_balance, 2 * 6000, places=6)

    def test_match_vests_after_the_service_requirement(self):
        model = _model(end_year=2028)
        person = _worker(model, salary=0, bank=0, spending=0)
        job = Job(person, "Co", "Eng", Salary(model, base=100000))
        account = Job401kAccount(
            job=job, pretax_contrib_percent=6, average_growth=0, match_tiers=[(100, 6)], match_vesting_years=3
        )
        model.run()  # 2026-2028: three years of service
        self.assertEqual(account.unvested_match, 0)
        job.retire()
        self.assertAlmostEqual(account.pretax_balance, 3 * 12000, places=6)


class TestLevelTermPremiums(unittest.TestCase):
    """Item 8 / D8: term premiums are level unless age banding is asked for."""

    def _premiums(self, **kwargs):
        model = _model(end_year=2030)
        person = _worker(model)
        LifeInsurance(person, LifeInsuranceType.TERM, 500000, 50, term_years=20, **kwargs)
        model.run()
        return _frame(model)["Life Ins Premiums"].tolist()

    def test_default_is_level(self):
        self.assertEqual(self._premiums(), [600.0] * 5)
        self.assertEqual(self._premiums(premium_increase_rate=0), [600.0] * 5)
        self.assertEqual(self._premiums(premium_increase_rate=PremiumIncreaseType.LEVEL), [600.0] * 5)

    def test_age_banded_is_explicit(self):
        premiums = self._premiums(premium_increase_rate=PremiumIncreaseType.AGE_BANDED)
        self.assertEqual(premiums[0], 600.0)
        self.assertGreater(premiums[1], premiums[0])
        self.assertIs(PremiumIncreaseType.AGE_BASED, PremiumIncreaseType.AGE_BANDED)  # deprecated alias

    def test_whole_life_default_is_level(self):
        model = _model(end_year=2028)
        person = _worker(model)
        policy = LifeInsurance(person, LifeInsuranceType.WHOLE, 250000, 100)
        model.run()
        self.assertEqual(policy.monthly_premium, 100)


class TestAnnuityDefaults(unittest.TestCase):
    """Item 9 / D9: FIXED/VARIABLE annuities stay in accumulation unless a payout age is given."""

    def test_fixed_annuity_accumulates(self):
        model = _model(end_year=2028)
        person = _worker(model)
        annuity = Annuity(person, AnnuityType.FIXED, initial_balance=100000, interest_rate=4)
        model.run()
        self.assertFalse(annuity.is_annuitized)
        self.assertIsNone(annuity.payout_start_age)
        self.assertAlmostEqual(annuity.balance, 100000 * 1.04**3, places=6)

    def test_accumulation_contract_can_still_be_annuitized_on_election(self):
        model = _model(end_year=2026)
        person = _worker(model, age=66)
        annuity = Annuity(person, AnnuityType.FIXED, initial_balance=100000, interest_rate=4)
        self.assertTrue(annuity.annuitize())
        self.assertEqual(annuity.payout_start_age, 66)

    def test_immediate_and_deferred_keep_their_payout_ages(self):
        model = _model(end_year=2026)
        person = _worker(model, age=50)
        immediate = Annuity(person, AnnuityType.IMMEDIATE, initial_balance=100000)
        deferred = Annuity(person, AnnuityType.DEFERRED, initial_balance=100000)
        self.assertEqual(immediate.payout_start_age, 50)
        self.assertEqual(deferred.payout_start_age, model.config.insurance.annuity.default_payout_start_age)
        model.run()
        self.assertTrue(immediate.is_annuitized)
        self.assertFalse(deferred.is_annuitized)

    def test_variable_tracks_equity_unless_a_rate_is_given(self):
        config = _fixture_config()
        config.model.economy.equity_return = 9.0
        model = LifeModel(start_year=2026, end_year=2026, config=config)
        person = _worker(model)
        market = Annuity(person, AnnuityType.VARIABLE, initial_balance=100000)
        stated = Annuity(person, AnnuityType.VARIABLE, initial_balance=100000, interest_rate=3)
        model.run()
        self.assertAlmostEqual(market.balance, 109000, places=6)
        self.assertAlmostEqual(stated.balance, 103000, places=6)


class TestPensionServiceAccrues(unittest.TestCase):
    """Item 13 / task 10: pension service grows while the participant works for the sponsor."""

    def test_unvested_participant_vests_by_working(self):
        model = _model(end_year=2030)
        person = _worker(model, age=60, salary=0, retirement_age=63)
        Job(person, "MegaCorp", "Eng", Salary(model, base=80000))
        pension = Pension(person, "MegaCorp", vesting_years=5, benefit_amount=20000, years_of_service=2)
        model.run()
        # Paid 2026-2029 (retires during 2029, the year they are 63): 2 + 4 = 6 years. Vested (5)
        # at the start of 2029, so the benefit starts that year; nothing was paid before.
        self.assertEqual(pension.years_of_service, 6)
        self.assertTrue(pension.is_vested)
        df = _frame(model)
        self.assertEqual(df.loc[2028, "Pension Income"], 0)
        self.assertEqual(df.loc[2029, "Pension Income"], 20000)

    def test_formula_benefit_grows_with_service_and_final_salary(self):
        model = _model(end_year=2027)
        person = _worker(model, age=50, salary=0)
        Job(person, "MegaCorp", "Eng", Salary(model, base=100000, yearly_increase=10))
        pension = Pension(
            person, "MegaCorp", vesting_years=5, years_of_service=10, benefit_multiplier=1.5, final_salary=90000
        )
        model.run()
        # 12 years of service at the 2027 salary of $110,000.
        self.assertAlmostEqual(pension.benefit_amount, 12 * 0.015 * 110000, places=6)

    def test_no_service_without_the_sponsor(self):
        model = _model(end_year=2027)
        person = _worker(model, age=50)  # works at "Co", not the sponsor
        pension = Pension(person, "MegaCorp", vesting_years=5, benefit_amount=20000, years_of_service=1)
        model.run()
        self.assertEqual(pension.years_of_service, 1)


class TestSmallFixes(unittest.TestCase):
    """Item 13 / task 10: one-time expenses in combined spending; unpaid end-of-life costs; one tax path."""

    def test_combined_spending_includes_one_time_expenses(self):
        model = _model()
        family = Family(model)
        a = _worker(model, family, name="A", spending=10000)
        _worker(model, family, name="B", spending=5000)
        a.spending.add_expense(2500)
        self.assertEqual(family.combined_spending, 17500)

    def test_end_of_life_costs_the_bank_cannot_cover_are_paid_by_the_estate(self):
        model = _model(end_year=2026)
        family = Family(model)
        parent = Person(
            family,
            "Parent",
            age=80,
            retirement_age=65,
            spending=Spending(model, base=0),
            mortality_mode=MortalityMode.FIXED_AGE,
            death_age=80,
        )
        BankAccount(parent, "Bank", balance=1000, interest_rate=0)
        BrokerageAccount(parent, "Broker", balance=200000, growth_rate=0, dividend_yield=0)
        MedicalCosts(parent)
        child = _worker(model, family, name="Child", age=51, salary=0, spending=0, bank=0)
        model.run()
        healthcare = model.config.healthcare
        self.assertGreater(child.stat_money_spent, 0)  # the unpaid remainder was billed to the heir
        self.assertEqual(child.debt, 0)
        cost = child.stat_money_spent + 1000
        self.assertGreater(cost, healthcare.funeral_cost)
        events = " | ".join(e.message for e in model.event_log.list)
        self.assertIn("end-of-life costs from the estate", events)

    def test_person_taxes_are_the_one_person_unit_taxes(self):
        model = _model(end_year=2026)
        person = _worker(model, salary=0, bank=0)
        Child(person, "Kid", birth_year=2020)
        person.income.add_wages(60000, 60000)
        self.assertEqual(person.get_income_taxes_due().total, TaxUnit([person]).get_income_taxes_due().total)
        self.assertGreater(TaxUnit([person]).get_income_taxes_due().credits, 0)  # the CTC is included


if __name__ == "__main__":
    unittest.main()
