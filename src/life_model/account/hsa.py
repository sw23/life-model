# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from enum import Enum
from typing import Optional

from ..base_classes import TaxAdvantagedAccount, TaxTreatment
from ..people.person import Person


class HSAType(Enum):
    """Types of Health Savings Accounts"""

    INDIVIDUAL = "Individual"
    FAMILY = "Family"


class HealthSavingsAccount(TaxAdvantagedAccount):
    tax_treatment = TaxTreatment.HSA
    is_rmd_eligible = False

    def __init__(
        self,
        person: Person,
        hsa_type: HSAType,
        balance: float = 0,
        growth_rate: Optional[float] = None,
        contribution_limit: Optional[float] = None,
        employer_contribution: Optional[float] = None,
    ):
        """Models a Health Savings Account (HSA).

        The HSA now grows like any other investment, uses the correct self-only/family contribution
        limit (including the age-55 catch-up), counts employer contributions against that limit, and
        deposits the employer contribution once per year (not 1/12).

        Args:
            person: The person who owns this HSA
            hsa_type: Type of HSA (Individual or Family)
            balance: Current HSA balance
            growth_rate: Expected annual growth rate percentage. Uses configured default if None.
            contribution_limit: Override for the annual contribution limit. Uses the year/age/tier
                indexed limit when None.
            employer_contribution: Annual employer contribution. Uses configured default if None.
        """
        hsa_config = person.model.config.accounts.hsa
        if growth_rate is None:
            # HSAs are typically invested; reuse the brokerage default growth rate.
            growth_rate = person.model.config.accounts.brokerage.default_growth_rate
        if employer_contribution is None:
            employer_contribution = hsa_config.default_employer_contribution
        super().__init__(person, balance, growth_rate)
        self.hsa_type = hsa_type
        self._contribution_limit_override = contribution_limit
        self.employer_contribution = employer_contribution

    def annual_contribution_limit(self) -> float:
        """Self-only or family limit for the year, plus the age-55 catch-up.

        Employer contributions count against this same limit (they are deducted from the room in
        :meth:`step`).
        """
        if self._contribution_limit_override is not None:
            return self._contribution_limit_override
        hsa_config = self.person.model.config.accounts.hsa
        base = (
            hsa_config.contribution_limit_family if self.hsa_type == HSAType.FAMILY else hsa_config.contribution_limit
        )
        if self.person.age >= hsa_config.catch_up_age:
            base += hsa_config.catch_up_amount
        return base

    def withdraw_medical(self, amount: float) -> float:
        """Withdraw for qualified medical expenses (always tax-free)."""
        return self.withdraw(amount)

    def withdraw_non_medical(self, amount: float) -> float:
        """Withdraw for non-medical expenses (taxable + 20% penalty under 65).

        Tax/penalty ledger reporting is added with the account tax semantics.
        """
        return self.withdraw(amount)

    def _repr_html_(self):
        limit = self.annual_contribution_limit()
        desc = "<ul>"
        desc += f"<li>HSA Type: {self.hsa_type.value}</li>"
        desc += f"<li>Balance: ${self.balance:,.2f}</li>"
        desc += f"<li>Contribution Limit: ${limit:,.2f}</li>"
        desc += f"<li>Contributions This Year: ${self.contributions_ytd:,.2f}</li>"
        desc += f"<li>Remaining Limit: ${self.remaining_contribution_room():,.2f}</li>"
        desc += "</ul>"
        return desc

    def step(self):
        """Add the employer contribution (once per year, counted against the limit), then grow."""
        if self.employer_contribution > 0:
            employer_room = min(self.employer_contribution, self.remaining_contribution_room())
            if employer_room > 0:
                self.balance += employer_room
                self.contributions_ytd += employer_room
                self.contribution_basis += employer_room
        super().step()
