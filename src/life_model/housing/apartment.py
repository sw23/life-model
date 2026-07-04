# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import html
from typing import Optional

from ..model import LifeModelAgent
from ..people.person import Person


class Apartment(LifeModelAgent):
    def __init__(self, person: Person, name: str, monthly_rent: float, yearly_increase: Optional[float] = 5):
        """Apartment

        Args:
            person (Person): Primary resident or person paying apartment rent.
            name (string): Apartment Name.
            monthly_rent (float): Amount of rent charged monthly.
            yearly_increase (float, optional): Percentage of rent increase every year. Pass None to
                increase with the economy's inflation each year. Defaults to 5.
        """
        super().__init__(person.model)
        self.name = name
        self.monthly_rent = monthly_rent
        self._yearly_increase_override = yearly_increase

        # Register with the model registry
        self.model.registries.apartments.register(person, self)

    @property
    def yearly_increase(self) -> float:
        """Yearly percentage rent increase: the explicit override if set, else the economy's inflation."""
        if self._yearly_increase_override is not None:
            return self._yearly_increase_override
        return self.model.economy.inflation(self.model.year)

    @yearly_increase.setter
    def yearly_increase(self, value: Optional[float]) -> None:
        self._yearly_increase_override = value

    @property
    def yearly_rent(self):
        return self.monthly_rent * 12

    def _repr_html_(self):
        return f"{html.escape(self.name)}, monthly rent ${self.monthly_rent:,}"

    def post_step(self):
        # Rent escalator runs after the year's rent has been paid (consume-then-advance).
        self.monthly_rent += self.monthly_rent * (self.yearly_increase / 100)
