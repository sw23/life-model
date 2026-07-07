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
    """Models a defined-benefit pension plan that pays a person a flat annual benefit in retirement.

    The benefit is wired into the simulation like the :class:`~life_model.insurance.social_security.SocialSecurity`
    agent: once the person is eligible, each ``pre_step`` deposits the benefit as cash and records it
    in the income ledger as :class:`~life_model.tax.income.IncomeType.PENSION` — ordinary taxable
    income with **no FICA** (retirees pay no payroll tax on pension income). A cost-of-living
    adjustment compounds the benefit each year in ``post_step``.

    Simplifications (documented, backlog for later refinement):
      * ``benefit_amount`` is a flat annual figure; salary-linked formulas
        (percent x years x final salary) are not modeled.
      * Survivor benefits are a flat ``survivor_percent`` of the benefit continued to a surviving
        spouse at the retiree's death (see :meth:`Person.die`); no joint-life actuarial factor.
    """

    def __init__(
        self,
        person: Person,
        company: str,
        vesting_years: int,
        benefit_amount: float,
        *,
        start_age: Optional[float] = None,
        cola_percent: float = 0.0,
        survivor_percent: float = 0.0,
    ):
        """Models a pension plan for a person

        Args:
            person: The person to which this pension belongs
            company: The company providing the pension
            vesting_years: Number of years required for vesting
            benefit_amount: Flat annual benefit amount
            start_age: Age at which benefits begin. Defaults to None, meaning benefits start at the
                person's retirement age (today's eligibility rule).
            cola_percent: Annual cost-of-living adjustment applied to the benefit once in pay
                (e.g. 2.0 for +2% per year). Defaults to 0.0 (level benefit).
            survivor_percent: Percentage of the benefit continued to a surviving spouse when the
                retiree dies (e.g. 50.0 for a 50% joint-and-survivor election). Defaults to 0.0
                (single-life: the benefit terminates at death).
        """
        super().__init__(person, company)
        self.vesting_years = vesting_years
        self.benefit_amount = benefit_amount
        self.start_age = start_age
        self.cola_percent = cola_percent
        self.survivor_percent = survivor_percent
        self.stat_pension_income = 0.0

        # Register so the owner (and estate/death handling) can find this pension.
        self.model.registries.pensions.register(person, self)

    def is_eligible(self) -> bool:
        """Check if the person is currently eligible to receive benefits.

        Eligible once the person reaches ``start_age`` when set, otherwise once retired.
        """
        if self.start_age is not None:
            return self.person.age >= self.start_age
        return self.person.is_retired

    def get_annual_benefit(self) -> float:
        """Calculate the annual benefit amount payable this year (0 if not yet eligible)."""
        if self.is_eligible():
            return self.benefit_amount
        return 0.0

    def pre_step(self):
        # Deposit the benefit and record it as ordinary (non-FICA) income once eligible. This
        # mirrors the SocialSecurity agent: benefit -> income ledger + cash. Runs at the default
        # pre_step priority (0), after the person ages (-20) and jobs deposit wages (-10).
        benefit = self.get_annual_benefit()
        self.stat_pension_income = benefit
        if benefit > 0:
            self.person.income.add(IncomeType.PENSION, benefit)
            self.person.receive_cash(benefit, source=f"pension from {self.company}")

    def post_step(self):
        # Compound the cost-of-living adjustment while the benefit is in pay so it keeps pace with
        # inflation over a long retirement.
        if self.cola_percent and self.is_eligible():
            self.benefit_amount *= 1 + self.cola_percent / 100.0

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Company: {html.escape(self.company)}</li>"
        desc += f"<li>Vesting Years: {self.vesting_years}</li>"
        desc += f"<li>Benefit Amount: ${self.benefit_amount:,.2f}</li>"
        if self.start_age is not None:
            desc += f"<li>Start Age: {self.start_age}</li>"
        if self.cola_percent:
            desc += f"<li>COLA: {self.cola_percent}%</li>"
        if self.survivor_percent:
            desc += f"<li>Survivor Benefit: {self.survivor_percent}%</li>"
        desc += "</ul>"
        return desc
