# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html
from typing import Optional

from ..base_classes import Benefit
from ..people.person import Person
from ..tax.income import IncomeType


class Pension(Benefit):
    # Deposit the benefit before the tax unit settles the year (so it is taxed this year).
    STEP_PRIORITY = {"pre_step": -10}

    def __init__(
        self,
        person: Person,
        company: str,
        vesting_years: int,
        benefit_amount: float = 0,
        *,
        election_age: Optional[float] = None,
        years_of_service: Optional[int] = None,
        benefit_multiplier: Optional[float] = None,
        final_salary: Optional[float] = None,
    ):
        """Models a defined-benefit pension.

        The annual benefit is either given directly (``benefit_amount``) or accrued from a formula
        (``years_of_service`` x ``benefit_multiplier`` percent x ``final_salary``). Benefits are paid
        once the participant is vested and has reached the election age (defaulting to the person's
        retirement age); each annual payment is deposited into the bank and taxed as ordinary income.

        Args:
            person: The person to which this pension belongs.
            company: The company providing the pension.
            vesting_years: Years of service required to vest.
            benefit_amount: Flat annual benefit (used when no accrual formula is supplied).
            election_age: Age at which benefits begin. Defaults to the person's retirement age.
            years_of_service: Years of credited service. Defaults to ``vesting_years`` (vested).
            benefit_multiplier: Percent of final salary accrued per year of service.
            final_salary: Final (or final-average) salary used by the accrual formula.
        """
        super().__init__(person, company)
        self.vesting_years = vesting_years
        self.benefit_amount = benefit_amount
        self.election_age = election_age if election_age is not None else person.retirement_age
        self.years_of_service = years_of_service if years_of_service is not None else vesting_years
        self.benefit_multiplier = benefit_multiplier
        self.final_salary = final_salary
        self.stat_pension_income = 0.0
        self.model.registries.pensions.register(person, self)

    @property
    def is_vested(self) -> bool:
        """Whether the participant has met the vesting requirement."""
        return self.years_of_service >= self.vesting_years

    def is_eligible(self) -> bool:
        """Eligible to draw benefits once vested and at/after the election age."""
        return self.is_vested and self.person.age >= self.election_age

    def get_annual_benefit(self) -> float:
        """Annual benefit amount (0 until eligible)."""
        if not self.is_eligible():
            return 0.0
        if self.benefit_multiplier is not None and self.final_salary is not None:
            return self.years_of_service * (self.benefit_multiplier / 100) * self.final_salary
        return self.benefit_amount

    def pre_step(self):
        """Pay this year's benefit (if eligible) into the bank as taxable ordinary income."""
        benefit = self.get_annual_benefit()
        self.stat_pension_income = benefit
        if benefit > 0:
            self.person.deposit_into_bank_account(benefit)
            self.person.income.add(IncomeType.PRETAX_DISTRIBUTION, benefit)

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Company: {html.escape(self.company)}</li>"
        desc += f"<li>Vesting Years: {self.vesting_years}</li>"
        desc += f"<li>Years of Service: {self.years_of_service}</li>"
        desc += f"<li>Annual Benefit: ${self.get_annual_benefit():,.2f}</li>"
        desc += "</ul>"
        return desc
