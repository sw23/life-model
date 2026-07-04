# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from ..base_classes import TaxAdvantagedAccount, TaxTreatment
from ..limits import federal_retirement_age
from ..people.person import Person
from ..tax.income import IncomeType


class RothIRA(TaxAdvantagedAccount):
    tax_treatment = TaxTreatment.ROTH
    is_rmd_eligible = False
    limit_group = "ira"  # one IRA limit shared across Roth and Traditional

    def __init__(
        self,
        person: Person,
        balance: float = 0,
        growth_rate: float | None = None,
        contribution_limit: float | None = None,
    ):
        """Models a Roth IRA account for a person.

        Contributions are made with after-tax dollars; qualified withdrawals (and withdrawals of
        contribution basis at any time) are tax- and penalty-free. Contribution/withdraw/growth and
        the annual-limit reset are inherited from :class:`TaxAdvantagedAccount`.

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
        self.model.registries.roth_iras.register(person, self)

    def annual_contribution_limit(self) -> float:
        if self._contribution_limit_override is not None:
            return self._contribution_limit_override
        return self.person.model.config.retirement.ira.contribution_limit

    def withdraw(self, amount: float) -> float:
        """Withdraw contribution basis first (always tax-free), then earnings.

        Earnings withdrawn before the federal retirement age are a non-qualified distribution:
        ordinary income plus the early-withdrawal additional tax, both recorded on the owner's
        income ledger. On or after that age, withdrawals are qualified and tax-free. (The five-year
        holding rule is not modeled.)
        """
        basis_before = self.contribution_basis
        withdrawn = super().withdraw(amount)
        earnings_withdrawn = withdrawn - (basis_before - self.contribution_basis)
        config = self.model.config
        if earnings_withdrawn > 0 and self.person.age < federal_retirement_age(config):
            self.person.income.add(IncomeType.PRETAX_DISTRIBUTION, earnings_withdrawn)
            self.person.income.add_penalty(earnings_withdrawn * config.retirement.early_withdrawal_penalty_rate / 100)
        return withdrawn

    def tax_free_withdrawable(self) -> float:
        """Amount that can be withdrawn right now without creating taxable income."""
        if self.person.age >= federal_retirement_age(self.model.config):
            return self.balance
        return min(self.balance, self.contribution_basis)

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Balance: ${self.balance:,.2f}</li>"
        desc += f"<li>Growth Rate: {self.growth_rate}%</li>"
        desc += f"<li>Contribution Limit: ${self.annual_contribution_limit():,.2f}</li>"
        desc += f"<li>Contributions This Year: ${self.contributions_ytd:,.2f}</li>"
        desc += "</ul>"
        return desc
