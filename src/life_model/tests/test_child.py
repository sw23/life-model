# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..config.financial_config import FinancialConfig
from ..dependents.child import Child
from ..dependents.plan529 import Plan529
from ..model import LifeModel
from ..people.family import Family
from ..people.person import MortalityMode, Person, Spending

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    return FinancialConfig(config_file=TEST_CONFIG)


class TestChild(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(start_year=2020, end_year=2025)
        self.person = Person(
            family=Family(self.model), name="Parent", age=30, retirement_age=65, spending=Spending(self.model, 0)
        )

    def test_age_tracks_model_year(self):
        child = Child(self.person, "Kid", birth_year=2018)
        self.assertEqual(child.age, self.model.year - 2018)

    def test_age_advances_with_simulation(self):
        child = Child(self.person, "Kid", birth_year=2020)
        self.assertEqual(child.age, 0)
        self.model.step()
        self.assertEqual(child.age, 1)

    def test_child_born_in_future_has_negative_age(self):
        child = Child(self.person, "Unborn", birth_year=2030)
        self.assertEqual(child.age, self.model.year - 2030)


class TestChildRegistry(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(start_year=2020, end_year=2025)
        self.person = Person(
            family=Family(self.model), name="Parent", age=30, retirement_age=65, spending=Spending(self.model, 0)
        )

    def test_child_registers_on_person(self):
        child = Child(self.person, "Kid", birth_year=2018)
        self.assertIn(child, self.person.children)

    def test_add_child_helper_defaults_to_model_year(self):
        child = self.person.add_child("Kid")
        self.assertEqual(child.birth_year, self.model.year)
        self.assertIn(child, self.person.children)

    def test_registries_include_children(self):
        child = Child(self.person, "Kid", birth_year=2018)
        self.assertIn(self.model.registries.children, self.model.registries.iter_registries())
        # clear_all removes the person's children from the registry.
        self.model.registries.clear_all(self.person)
        self.assertEqual(self.person.children, [])
        self.assertNotIn(child, self.model.registries.children.get_all_items())


class TestChildGrowUp(unittest.TestCase):
    def test_grow_up_returns_person_and_unregisters_child(self):
        model = LifeModel(start_year=2020, end_year=2025)
        parent = Person(Family(model), "Parent", age=40, retirement_age=65, spending=Spending(model, 0))
        child = Child(parent, "Kid", birth_year=2002)  # age 18
        adult = child.grow_up()
        self.assertIsInstance(adult, Person)
        self.assertEqual(adult.age, 18)
        self.assertIs(adult.family, parent.family)
        self.assertNotIn(child, parent.children)


class TestChildCosts(unittest.TestCase):
    """Age-banded child costs flow through Spending.add_expense (fixture: childcare 10k,
    school 5k, college 20k; inflation 0 in the fixture economy default)."""

    def _model(self):
        # Fixed economy with zero inflation so nominal == charged cost.
        model = LifeModel(start_year=2026, end_year=2027, config=_fixture_config())
        return model

    def test_childcare_band_cost_charged_in_year_one(self):
        model = self._model()
        parent = Person(Family(model), "Parent", age=30, retirement_age=70, spending=Spending(model, base=0))
        child = Child(parent, "Kid", birth_year=2026)  # age 0 -> childcare band
        model.step()  # year 2026
        # Childcare band cost (10000) charged to the parent's spending as a one-time expense.
        self.assertEqual(child.stat_dependent_costs, 10000)
        self.assertEqual(parent.stat_money_spent, 10000)

    def test_school_band_cost(self):
        model = self._model()
        parent = Person(Family(model), "Parent", age=40, retirement_age=70, spending=Spending(model, base=0))
        child = Child(parent, "Kid", birth_year=2016)  # age 10 -> school band
        model.step()
        self.assertEqual(child.stat_dependent_costs, 5000)

    def test_adult_child_incurs_no_cost(self):
        model = self._model()
        parent = Person(Family(model), "Parent", age=50, retirement_age=70, spending=Spending(model, base=0))
        child = Child(parent, "Adult", birth_year=2000)  # age 26 -> past college band
        model.step()
        self.assertEqual(child.stat_dependent_costs, 0)

    def test_costs_inflate_over_time(self):
        # Fixed 3% inflation: a school-age cost grows by cumulative inflation each year.
        cfg = _fixture_config()
        cfg.apply_scenario("_infl", {"economy": {"mode": "fixed", "inflation": 3.0}})
        model = LifeModel(start_year=2026, end_year=2030, config=cfg)
        parent = Person(Family(model), "Parent", age=40, retirement_age=70, spending=Spending(model, base=0))
        child = Child(parent, "Kid", birth_year=2016)  # school band throughout
        model.step()  # 2026: cumulative inflation factor 1.0
        first = child.stat_dependent_costs
        model.step()  # 2027: factor 1.03
        second = child.stat_dependent_costs
        self.assertEqual(first, 5000)
        self.assertAlmostEqual(second, 5000 * 1.03, places=2)


class TestChildCollege529(unittest.TestCase):
    """College-band costs draw self-beneficiary 529 plans first (tax-free), shortfall from cash.

    Fixture: college_annual_cost 20000, college_start_age 18, college_years 4."""

    def _college_child_model(self, plan_balance):
        model = LifeModel(start_year=2026, end_year=2026, config=_fixture_config())
        parent = Person(Family(model), "Parent", age=50, retirement_age=70, spending=Spending(model, base=0))
        BankAccount(parent, "Bank", balance=100000, interest_rate=0)
        child = Child(parent, "Kid", birth_year=2008)  # age 18 -> college band
        plan = Plan529(owner=parent, beneficiary=child, balance=plan_balance, growth_rate=0)
        return model, parent, child, plan

    def test_funded_529_covers_tuition_tax_free(self):
        model, parent, child, plan = self._college_child_model(plan_balance=50000)
        model.step()
        # The 529 drew the full 20000 tuition tax-free; balance drops by exactly the tuition.
        self.assertEqual(plan.balance, 30000)
        self.assertEqual(child.stat_dependent_costs, 20000)
        # Qualified withdrawals are not ordinary income.
        self.assertEqual(parent.taxable_income, 0)
        # Bank: +20000 from the 529, -20000 tuition = net unchanged.
        self.assertEqual(parent.bank_account_balance, 100000)

    def test_underfunded_529_shortfall_paid_from_cash(self):
        model, parent, child, plan = self._college_child_model(plan_balance=5000)
        model.step()
        self.assertEqual(plan.balance, 0)  # 529 fully drained
        self.assertEqual(child.stat_dependent_costs, 20000)
        # Bank: +5000 from the 529, -20000 tuition = out-of-pocket shortfall of 15000.
        self.assertEqual(parent.bank_account_balance, 85000)

    def test_529_for_other_child_not_drawn(self):
        model, parent, child, plan = self._college_child_model(plan_balance=50000)
        # A 529 whose beneficiary is a different child must not fund this child's college.
        other = Child(parent, "Sibling", birth_year=2020)  # age 6 -> school band (5000)
        plan.change_beneficiary(other)
        model.step()
        self.assertEqual(plan.balance, 50000)  # untouched (beneficiary is the sibling, not in college)
        # Full college tuition (20000) plus the sibling's school cost (5000) fall to cash.
        self.assertEqual(parent.bank_account_balance, 75000)


class TestChildSurvivesParentDeath(unittest.TestCase):
    def test_death_reassigns_child_to_inheritor(self):
        model = LifeModel(start_year=2026, end_year=2027)
        family = Family(model)
        parent = Person(
            family,
            "Parent",
            age=40,
            retirement_age=65,
            spending=Spending(model, 0),
            mortality_mode=MortalityMode.FIXED_AGE,
            death_age=41,
        )
        guardian = Person(family, "Guardian", age=38, retirement_age=65, spending=Spending(model, 0))
        child = Child(parent, "Kid", birth_year=2020)
        self.assertIn(child, parent.children)

        model.step()  # parent turns 41 and dies

        self.assertTrue(parent.is_deceased)
        # The child is reassigned to the surviving family member and keeps stepping.
        self.assertIs(child.person, guardian)
        self.assertIn(child, guardian.children)
        self.assertNotIn(child, parent.children)


if __name__ == "__main__":
    unittest.main()
