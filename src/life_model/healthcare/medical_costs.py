# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Age-related out-of-pocket medical cost curve (Plan 15 D2).

``MedicalCosts`` is an opt-in per-person agent. Each year it looks up the person's age band in the
configured cost curve, indexes it by cumulative *medical* inflation (CPI plus a health-spending
premium), and charges the result through ``person.spending.add_expense`` so it settles with every
other bill. The curve captures chronic-care and general medical spend inside a single age band
rather than modeling each condition separately (documented v1 simplification).
"""

from typing import Optional, cast

from ..model import LifeModel, LifeModelAgent
from ..people.person import Person


class MedicalCosts(LifeModelAgent):
    def __init__(self, person: Person):
        """Model age-related medical costs for a person.

        Args:
            person: The person who incurs these costs.
        """
        super().__init__(cast(LifeModel, person.model))
        self.model: LifeModel = cast(LifeModel, self.model)
        self.person = person
        self.stat_medical_costs = 0.0
        self.model.registries.medical_costs.register(person, self)

    def _band_cost(self, age: int) -> float:
        """Real (start-year-dollar) annual cost for a person of the given age."""
        bands = self.model.config.healthcare.medical_cost_bands
        for band in bands:
            if age <= band.max_age:
                return band.annual_cost
        # Above the last band's max_age: use the last (highest) band.
        return bands[-1].annual_cost if bands else 0.0

    def _medical_inflation_factor(self, year: int) -> float:
        """Cumulative medical price level from the start year through ``year``.

        Each year compounds ``(CPI inflation + medical_inflation_premium)``, so medical costs
        outpace ordinary CPI by the configured premium. The start year has a factor of 1.0.
        """
        premium = self.model.config.healthcare.medical_inflation_premium
        factor = 1.0
        for y in range(self.model.start_year, year):
            factor *= 1 + (self.model.economy.inflation(y) + premium) / 100
        return factor

    def annual_cost(self, year: Optional[int] = None) -> float:
        """This person's nominal medical cost for ``year`` (defaults to the current model year).

        Computed (not charged): the age-band base cost indexed by cumulative medical inflation.
        """
        year = self.model.year if year is None else year
        return self._band_cost(self.person.age) * self._medical_inflation_factor(year)

    def pre_step(self):
        if self.person.is_deceased:
            return
        cost = self.annual_cost()
        self.stat_medical_costs = cost
        self.person.spending.add_expense(cost)

    def _repr_html_(self):
        return (
            "<b>Medical Costs</b><ul>"
            f"<li>Person: {self.person.name}</li>"
            f"<li>This year: ${self.stat_medical_costs:,.0f}</li>"
            "</ul>"
        )
