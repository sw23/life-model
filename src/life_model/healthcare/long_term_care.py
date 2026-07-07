# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Long-term-care need as a seeded hazard plus a care state (Plan 15 D5).

``LongTermCare`` is an opt-in per-person agent. From a configured start age it draws care-need
each year from an age-banded annual hazard table using ``model.random`` (reproducible under a
seed, the same pattern as stochastic mortality). On trigger, the person enters a care episode
whose duration is drawn from an exponential distribution with the configured mean (rounded up to
whole years). While in care, the annual care cost (indexed by medical inflation) is charged
through ``person.spending.add_expense``; any active ``InsuranceType.LONG_TERM_CARE`` policies
offset the cost up to their annual benefit via the existing claim machinery.

Documented simplifications (v1):

* Mortality stays independent of the care state.
* At most one episode is active at a time; a new episode can begin after one ends.
* The insurance benefit cap is the policy's ``coverage_amount`` per year (an annual benefit).
"""

import math
from typing import cast

from ..insurance.general_insurance import InsuranceType
from ..model import Event, LifeModel, LifeModelAgent
from ..people.person import Person


class LongTermCare(LifeModelAgent):
    def __init__(self, person: Person):
        """Model long-term-care need and costs for a person.

        Args:
            person: The person at risk of needing long-term care.
        """
        super().__init__(cast(LifeModel, person.model))
        self.model: LifeModel = cast(LifeModel, self.model)
        self.person = person
        self.config = self.model.config.healthcare.long_term_care
        self.in_care = False
        self.care_years_remaining = 0
        self.episodes_started = 0
        # Net (after insurance offset) care cost incurred this year; feeds the "Medical Costs"
        # stat and the unreimbursed-medical itemized deduction.
        self.stat_medical_costs = 0.0
        self.model.registries.long_term_care.register(person, self)

    def _annual_hazard(self, age: int) -> float:
        """Annual probability of a care episode starting at the given age."""
        if age < self.config.start_age:
            return 0.0
        bands = self.config.hazard_bands
        for band in bands:
            if age <= band.max_age:
                return band.annual_hazard
        return bands[-1].annual_hazard if bands else 0.0

    def _medical_inflation_factor(self) -> float:
        """Cumulative medical price level (CPI + premium) from the start year, as in MedicalCosts."""
        premium = self.model.config.healthcare.medical_inflation_premium
        factor = 1.0
        for y in range(self.model.start_year, self.model.year):
            factor *= 1 + (self.model.economy.inflation(y) + premium) / 100
        return factor

    def _draw_episode_duration(self) -> int:
        """Episode length in whole years: exponential with the configured mean, at least 1."""
        drawn = self.model.random.expovariate(1.0 / self.config.mean_duration_years)
        return max(1, math.ceil(drawn))

    def _start_episode(self):
        self.in_care = True
        self.care_years_remaining = self._draw_episode_duration()
        self.episodes_started += 1
        self.model.event_log.add(
            Event(
                f"{self.person.name} entered long-term care at age {self.person.age} "
                f"({self.care_years_remaining} year(s) expected)"
            )
        )

    def _charge_care_year(self):
        """Charge this year's care cost through the bill path, net of any LTC insurance offset."""
        gross = self.config.annual_cost * self._medical_inflation_factor()
        self.person.spending.add_expense(gross)

        # Offset with active LTC policies via the claim machinery. The loss is already charged
        # through the bill path, so the claim only credits the payout (charge_loss=False). The
        # claim is capped at the policy's coverage (its annual benefit) so an expensive care year
        # is paid up to the benefit instead of being denied for exceeding coverage; any policy
        # deductible reduces the payout per the machinery's single-deductible convention.
        payout = 0.0
        for policy in self.person.model.registries.general_insurance_policies.get_items(self.person):
            if policy.insurance_type != InsuranceType.LONG_TERM_CARE or not policy.is_coverage_active:
                continue
            claimable = min(gross, policy.coverage_amount)
            claim = policy.file_claim(claimable, "Long-term care", charge_loss=False)
            if claim is not None:
                payout += claim.payout_amount

        self.stat_medical_costs = gross - payout

    def pre_step(self):
        self.stat_medical_costs = 0.0
        if self.person.is_deceased:
            return

        if not self.in_care and self.person.age >= self.config.start_age:
            # Seeded hazard draw (same RNG pattern as stochastic mortality).
            if self.model.random.random() <= self._annual_hazard(self.person.age):
                self._start_episode()

        if self.in_care:
            self._charge_care_year()
            self.care_years_remaining -= 1
            if self.care_years_remaining <= 0:
                self.in_care = False
                self.model.event_log.add(Event(f"{self.person.name} left long-term care at age {self.person.age}"))

    def _repr_html_(self):
        return (
            "<b>Long-Term Care</b><ul>"
            f"<li>Person: {self.person.name}</li>"
            f"<li>In care: {self.in_care}</li>"
            f"<li>Episodes: {self.episodes_started}</li>"
            f"<li>This year's net cost: ${self.stat_medical_costs:,.0f}</li>"
            "</ul>"
        )
