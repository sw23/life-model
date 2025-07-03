# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from ..people.person import Person
from ..model import LifeModelAgent


class Apartment(LifeModelAgent):
    def __init__(self, person: Person, name: str, monthly_rent: float, yearly_increase: float = 5):
        """Apartment

        Args:
            person (Person): Primary resident or person paying apartment rent.
            name (string): Apartment Name.
            monthly_rent (float): Amount of rent charged monthly.
            yearly_increase (float, optional): Percentage of rent increase every year. Defaults to 5.
        """
        super().__init__(person.model)
        self.name = name
        self.monthly_rent = monthly_rent
        self.yearly_increase = yearly_increase
        person.apartments.append(self)

    @property
    def yearly_rent(self):
        return self.monthly_rent * 12

    def _repr_html_(self):
        return f"{self.name}, monthly rent ${self.monthly_rent:,}"

    def step(self):
        self.monthly_rent += self.monthly_rent * (self.yearly_increase / 100)
