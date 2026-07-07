# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest

from ..dependents.child import Child
from ..model import LifeModel
from ..people.family import Family
from ..people.person import MortalityMode, Person, Spending


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
