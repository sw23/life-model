# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Age-related out-of-pocket medical cost curve.

``MedicalCosts`` is an opt-in per-person agent. Each year it looks up the person's age band in the
configured cost curve, indexes it by cumulative *medical* inflation (CPI plus a health-spending
premium), and charges the result through ``person.spending.add_expense`` so it settles with every
other bill. The curve captures chronic-care and general medical spend inside a single age band
rather than modeling each condition separately (documented v1 simplification).
"""

from typing import cast

from ..model import LifeModel, LifeModelAgent, snap_money
from ..people.person import Person
from .inflation import medical_inflation_factor


class MedicalCosts(LifeModelAgent):
    """Age-banded out-of-pocket medical costs, charged a twelfth of the year's cost each month."""

    STATS_OWNED = frozenset({"stat_medical_costs"})

    def __init__(self, person: Person, *, annual_cost: float | None = None):
        """Model age-related medical costs for a person.

        Args:
            person: The person who incurs these costs.
            annual_cost: The person's own yearly medical cost in start-year dollars instead of the
                configured age bands (keyword-only; Plan 27 D9), indexed by medical inflation.

        A HEALTH :class:`~life_model.insurance.general_insurance.Insurance` policy with an out-of-pocket
        maximum or coinsurance caps the charge: the cost is then what the plan covers, and the person
        pays the deductible, the coinsurance share above it and nothing past the out-of-pocket maximum
        (tracked over the calendar year).
        """
        super().__init__(cast(LifeModel, person.model))
        self.model: LifeModel = cast(LifeModel, self.model)
        self.person = person
        self.annual_cost_override = annual_cost
        self.stat_medical_costs = 0.0
        #: This year's covered costs before cost sharing, and the share charged (health policy years).
        self.gross_costs_ytd = 0.0
        self.oop_ytd = 0.0
        self.model.registries.medical_costs.register(person, self)

    def _band_cost(self, age: int) -> float:
        """Real (start-year-dollar) annual cost for a person of the given age."""
        if self.annual_cost_override is not None:
            return self.annual_cost_override
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
        Cached per model+year (see healthcare.inflation).
        """
        return medical_inflation_factor(self.model, year)

    def annual_cost(self, year: int | None = None) -> float:
        """This person's nominal medical cost for ``year`` (defaults to the current model year).

        Computed (not charged): the age-band base cost indexed by cumulative medical inflation.
        """
        year = self.model.year if year is None else year
        return self._band_cost(self.person.age) * self._medical_inflation_factor(year)

    def health_policy(self):
        """The person's active HEALTH policy with cost sharing, if any."""
        for policy in self.model.registries.general_insurance_policies.get_items(self.person):
            if policy.caps_medical_costs and policy.is_coverage_active:
                return policy
        return None

    def on_year_start(self):
        self.gross_costs_ytd = 0.0
        self.oop_ytd = 0.0

    def pre_step(self):
        if self.person.is_deceased:
            return
        cost = self.annual_cost() / 12
        policy = self.health_policy()
        if policy is not None:
            gross = self.gross_costs_ytd + cost
            charged = policy.out_of_pocket(gross) - self.oop_ytd
            self.gross_costs_ytd = gross
            self.oop_ytd += charged
            cost = charged
        if cost <= 0:
            return
        self.stat_medical_costs = snap_money(self.stat_medical_costs + cost)
        self.person.spending.add_expense(cost, category="medical")

    def _repr_html_(self):
        return (
            "<b>Medical Costs</b><ul>"
            f"<li>Person: {self.person.name}</li>"
            f"<li>This year: ${self.stat_medical_costs:,.0f}</li>"
            "</ul>"
        )
