# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Medicare premiums with IRMAA income surcharges (Plan 15 D4).

``Medicare`` is an opt-in per-person agent. From the configured eligibility age (65) it charges
Part B and Part D premiums each year through ``person.spending.add_expense`` so they settle with
every other bill. The premium tier is selected by IRMAA: the person's modified adjusted gross
income with a **two-year lookback** (``person.agi_history[year - 2]``, recorded by
``TaxUnit.settle_year``) is compared against the configured MAGI thresholds for the person's
filing status.

Documented simplifications (v1):

* Part A is premium-free (assumes sufficient work history).
* MAGI is approximated by AGI (no tax-exempt-interest add-back — the model has none).
* IRMAA thresholds are indexed by CPI (they are CPI-U indexed in law); premiums are indexed by
  medical inflation (CPI + the configured premium) from the model start year, since the configured
  premiums are start-year dollars like every other config dollar value.
* The threshold column follows the person's *current* filing status.
* Employer coverage before 65 is out of scope (backlog).
* Prescription-drug coverage is modeled via the Part D premium (per plan; finer detail backlog).
"""

from typing import cast

from ..model import Event, LifeModel, LifeModelAgent
from ..people.person import Person
from ..tax.federal import FilingStatus


class Medicare(LifeModelAgent):
    def __init__(self, person: Person):
        """Model Medicare enrollment and premiums for a person.

        Args:
            person: The person enrolled in Medicare (from the configured eligibility age).
        """
        super().__init__(cast(LifeModel, person.model))
        self.model: LifeModel = cast(LifeModel, self.model)
        self.person = person
        self.config = self.model.config.healthcare.medicare
        self._enrollment_logged = False
        self.stat_medical_costs = 0.0
        self.model.registries.medicare.register(person, self)

    @property
    def is_eligible(self) -> bool:
        """Whether the person has reached the Medicare eligibility age."""
        return self.person.age >= self.config.eligibility_age

    def lookback_magi(self) -> float:
        """MAGI for IRMAA: the person's AGI from two years ago.

        Falls back to the earliest recorded AGI when the two-year-lookback year predates the
        history (e.g. the first two simulated years), and to 0 (base premium) when no history
        exists at all.
        """
        history = self.person.agi_history
        if not history:
            return 0.0
        lookback_year = self.model.year - 2
        if lookback_year in history:
            return history[lookback_year]
        return history[min(history)]

    def _tier(self, magi: float):
        """The IRMAA tier whose (CPI-indexed) MAGI lower bound this MAGI exceeds."""
        mfj = self.person.filing_status == FilingStatus.MARRIED_FILING_JOINTLY
        cpi = self.model.economy.cumulative_inflation(self.model.year)
        tiers = self.config.irmaa_tiers
        selected = tiers[0]
        for tier in tiers[1:]:
            threshold = tier.magi_min_married_filing_jointly if mfj else tier.magi_min_single
            if magi > threshold * cpi:
                selected = tier
        return selected

    def _medical_inflation_factor(self) -> float:
        """Cumulative medical price level (CPI + premium) from the start year, as in MedicalCosts."""
        premium = self.model.config.healthcare.medical_inflation_premium
        factor = 1.0
        for y in range(self.model.start_year, self.model.year):
            factor *= 1 + (self.model.economy.inflation(y) + premium) / 100
        return factor

    def annual_premium(self) -> float:
        """This year's total Medicare premium (Part B + Part D base + Part D IRMAA surcharge)."""
        tier = self._tier(self.lookback_magi())
        monthly = tier.part_b_monthly + self.config.part_d_base_monthly_premium + tier.part_d_monthly_surcharge
        return monthly * 12 * self._medical_inflation_factor()

    def pre_step(self):
        if self.person.is_deceased or not self.is_eligible:
            self.stat_medical_costs = 0.0
            return
        if not self._enrollment_logged:
            self.model.event_log.add(Event(f"{self.person.name} enrolled in Medicare at age {self.person.age}"))
            self._enrollment_logged = True
        premium = self.annual_premium()
        self.stat_medical_costs = premium
        self.person.spending.add_expense(premium)

    def _repr_html_(self):
        return (
            "<b>Medicare</b><ul>"
            f"<li>Person: {self.person.name}</li>"
            f"<li>Eligible: {self.is_eligible}</li>"
            f"<li>This year's premiums: ${self.stat_medical_costs:,.0f}</li>"
            "</ul>"
        )
