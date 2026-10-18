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
from ..config.financial_config import FinancialConfig
from ..housing.apartment import Apartment
from ..housing.home import Home, HomeExpenses, Mortgage
from ..lifeevents import LifeEvent, LifeEventRecord, LifeEvents
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..tax.federal import FilingStatus
from ..work.job import Job, Salary

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    """Fresh FinancialConfig loaded from the frozen test fixture."""
    return FinancialConfig(config_file=TEST_CONFIG)


def _model(start_year=2026, end_year=2030) -> LifeModel:
    return LifeModel(start_year=start_year, end_year=end_year, config=_fixture_config())


def _worker(model, family=None, *, name="A", age=40, salary=100000, spending=50000, bank=100000):
    family = family or Family(model)
    person = Person(family, name, age=age, retirement_age=65, spending=Spending(model, base=spending))
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
        model.step()
        model.step()
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
        model.step()  # 2026
        late = _worker(model, name="Late", age=30)  # built between steps: 30 during 2027
        model.add_agent_stat("Age", "age")
        model.step()  # 2027
        self.assertEqual(late.age, 30)
        model.step()  # 2028
        self.assertEqual(late.age, 31)


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
        LifeEvents(model, [LifeEvent(2026, "late", person.spending.add_expense, 5000, stage="post_step")])
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
        model.step()
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


if __name__ == "__main__":
    unittest.main()
