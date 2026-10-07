# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""A finished LifeModel must be garbage-collectable.

mesa 3.3 keys its agent id counters by model in a class-level dict, which kept every model ever
built (and all of its agents) alive. Batch callers build thousands of models per process, so the
leak grew without bound — it exhausted memory during SLM dataset generation.
"""

import gc
import unittest
import weakref

from life_model.account.bank import BankAccount
from life_model.model import LifeModel
from life_model.people.family import Family
from life_model.people.person import Person, Spending
from life_model.work.job import Job, Salary


def _run_model() -> weakref.ref:
    model = LifeModel(start_year=2025, end_year=2027, seed=1)
    person = Person(
        family=Family(model),
        name="Ephemeral",
        age=40,
        retirement_age=65,
        spending=Spending(model=model, base=30000, yearly_increase=2),
    )
    BankAccount(owner=person, company="Bank", type="Checking", balance=20000, interest_rate=0.5)
    Job(
        owner=person,
        company="Company",
        role="Employee",
        salary=Salary(model=model, base=80000, yearly_increase=3, yearly_bonus=1),
    )
    model.run()
    return weakref.ref(model)


class TestModelLifetime(unittest.TestCase):
    def test_model_is_freed_after_use(self):
        ref = _run_model()
        gc.collect()
        self.assertIsNone(ref(), "a finished LifeModel is still reachable")

    def test_agent_ids_still_count_per_model(self):
        first, second = LifeModel(seed=1), LifeModel(seed=1)
        self.assertEqual(Family(first).unique_id, Family(second).unique_id)
