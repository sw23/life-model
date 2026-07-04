# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from typing import Optional

from ..base_classes import TaxAdvantagedAccount, TaxTreatment
from ..people.person import Person


class TraditionalIRA(TaxAdvantagedAccount):
    tax_treatment = TaxTreatment.PRETAX
    is_rmd_eligible = True

    def __init__(
        self,
        person: Person,
        balance: float = 0,
        growth_rate: Optional[float] = None,
        contribution_limit: Optional[float] = None,
    ):
        """Models a Traditional IRA account for a person.

        Unlike a Roth IRA, contributions are pre-tax (deductible) and *all* withdrawals are ordinary
        income; the account is subject to required minimum distributions. Contribution/withdraw/
        growth and the annual-limit reset are inherited from :class:`TaxAdvantagedAccount`; the
        pre-tax deduction, distribution taxation, and RMDs are applied by the account tax semantics.

        Args:
            person: The person to which this IRA belongs
            balance: Current balance in the IRA
            growth_rate: Expected annual growth rate percentage. Uses configured default if None.
            contribution_limit: Override for the annual contribution limit. Uses the configured
                IRA limit when None. Note the IRA limit is shared across all of a person's IRAs.
        """
        ira_config = person.model.config.retirement.ira
        if growth_rate is None:
            growth_rate = ira_config.default_growth_rate
        super().__init__(person, balance, growth_rate)
        self._contribution_limit_override = contribution_limit

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
