# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Plan 26: engine timing, events and settlement correctness.

Each test class reproduces one defect from the plan's problem statement (the probe scripts that
found them) and pins the corrected behaviour. Dollar assertions load the frozen fixture config.
"""

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..config.financial_config import FinancialConfig
from ..lifeevents import LifeEvent, LifeEvents
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
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


if __name__ == "__main__":
    unittest.main()
