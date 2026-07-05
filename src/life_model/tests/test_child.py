# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest

from ..dependents.child import Child
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending


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


if __name__ == "__main__":
    unittest.main()
