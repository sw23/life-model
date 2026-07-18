# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the LifeModel ``collect_data`` opt-out flag.

The flag must produce zero behavior change to the simulation itself: with the same seed and
household, a model built with ``collect_data=False`` steps to exactly the same balances as one
built with the default ``collect_data=True`` — only the DataCollector frames disappear.
"""

import unittest

from life_model.account.bank import BankAccount
from life_model.account.job401k import Job401kAccount
from life_model.model import LifeModel, ModelSetupException
from life_model.people.family import Family
from life_model.people.person import Person, Spending
from life_model.work.job import Job, Salary


def _build_household(model: LifeModel) -> Person:
    """A small but representative household: job, bank account, and 401k."""
    family = Family(model)
    person = Person(
        family=family,
        name="Collector",
        age=40,
        retirement_age=65,
        spending=Spending(model=model, base=30000, yearly_increase=2),
    )
    BankAccount(owner=person, company="Bank", type="Checking", balance=20000, interest_rate=0.5)
    job = Job(
        owner=person,
        company="Company",
        role="Employee",
        salary=Salary(model=model, base=80000, yearly_increase=3, yearly_bonus=1),
    )
    Job401kAccount(job=job, pretax_balance=50000, pretax_contrib_percent=5, average_growth=6)
    return person


class TestCollectDataFlag(unittest.TestCase):
    def test_default_is_collecting(self):
        model = LifeModel(start_year=2025, end_year=2027, seed=1)
        self.assertIsNotNone(model.datacollector)

    def test_collect_data_false_produces_no_frames(self):
        model = LifeModel(start_year=2025, end_year=2027, seed=1, collect_data=False)
        _build_household(model)
        model.run()
        self.assertIsNone(model.datacollector)

    def test_collect_data_false_does_not_change_simulation(self):
        # Golden-frame guard: identical seeds and households must land on identical balances
        # whether or not frames are collected.
        results = {}
        for collect in (True, False):
            model = LifeModel(start_year=2025, end_year=2035, seed=42, collect_data=collect)
            person = _build_household(model)
            model.run()
            results[collect] = (
                person.bank_account_balance,
                sum(acct.balance for acct in person.all_retirement_accounts),
                person.debt,
            )
        self.assertEqual(results[True], results[False])

    def test_collect_data_true_frames_match_simulated_years(self):
        model = LifeModel(start_year=2025, end_year=2027, seed=1)
        _build_household(model)
        model.run()
        df = model.datacollector.get_model_vars_dataframe()
        self.assertEqual(list(df["Year"]), [2025, 2026, 2027])

    def test_reporting_helpers_raise_clearly_without_collection(self):
        model = LifeModel(start_year=2025, end_year=2026, seed=1, collect_data=False)
        _build_household(model)
        model.run()
        with self.assertRaises(ModelSetupException):
            model.get_yearly_stat_df()
        with self.assertRaises(ModelSetupException):
            model.add_agent_stat("Title", "stat_title")

    def test_collect_data_is_keyword_only(self):
        with self.assertRaises(TypeError):
            LifeModel(2026, 2025, 1, None, None, False)  # collect_data passed positionally


if __name__ == "__main__":
    unittest.main()
