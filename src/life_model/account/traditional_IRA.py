# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import ClassVar

from ..base_classes import TaxAdvantagedAccount, TaxTreatment
from ..limits import required_min_distrib, rmd_start_age
from ..people.person import Person
from ..tax.income import IncomeType


class TraditionalIRA(TaxAdvantagedAccount):
    tax_treatment = TaxTreatment.PRETAX
    is_rmd_eligible = True
    limit_group = "ira"  # one IRA limit shared across Roth and Traditional
    # RMD in pre_step from the prior year-end balance, ahead of Social Security's provisional-income
    # calculation (same ordering as Job401kAccount); growth stays in step.
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"pre_step": -10, "step": -10}

    def __init__(
        self,
        person: Person,
        balance: float = 0,
        growth_rate: float | None = None,
        contribution_limit: float | None = None,
    ):
        """Models a Traditional IRA account for a person.

        Unlike a Roth IRA, contributions are pre-tax (deductible) and *all* withdrawals are ordinary
        income; the account is subject to required minimum distributions. Contribution/withdraw/
        growth and the annual-limit reset are inherited from :class:`TaxAdvantagedAccount`; the
        pre-tax deduction, distribution taxation, and RMDs are applied by the account tax semantics.

        Args:
            person: The person to which this IRA belongs
            balance: Current balance in the IRA
            growth_rate: Expected annual growth rate percentage. Defers to the economy's equity
                return when None.
            contribution_limit: Override for the annual contribution limit. Uses the configured
                IRA limit when None. Note the IRA limit is shared across all of a person's IRAs.
        """
        super().__init__(person, balance, growth_rate)
        self._contribution_limit_override = contribution_limit
        self.stat_required_min_distrib = 0
        self.model.registries.traditional_iras.register(person, self)

    def contribute(self, amount: float) -> float:
        """Contribute pre-tax dollars, recording an above-the-line deduction for the amount.

        Deductibility phase-outs for owners covered by a workplace plan are not modeled.
        """
        actual = super().contribute(amount)
        self.person.income.add_deduction(actual)
        return actual

    def pre_step(self):
        """Take any required minimum distribution (ordinary income, no FICA, never penalized)."""
        config = self.model.config
        birth_year = self.model.year - self.person.age
        start_age = rmd_start_age(birth_year, config=config, year=self.model.year)
        rmd = self.withdraw(required_min_distrib(self.person.age, self.balance, config=config, start_age=start_age))
        if rmd > 0:
            self.person.deposit_into_bank_account(rmd)
            self.person.income.add(IncomeType.PRETAX_DISTRIBUTION, rmd)
        self.stat_required_min_distrib = rmd

    def annual_contribution_limit(self) -> float:
        if self._contribution_limit_override is not None:
            return self._contribution_limit_override
        return self.person.model.config.retirement.ira.contribution_limit

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Balance: ${self.balance:,.2f}</li>"
        desc += f"<li>Growth Rate: {self.growth_rate}%</li>"
        desc += f"<li>Contribution Limit: ${self.annual_contribution_limit():,.2f}</li>"
        desc += f"<li>Contributions This Year: ${self.contributions_ytd:,.2f}</li>"
        desc += "</ul>"
        return desc
