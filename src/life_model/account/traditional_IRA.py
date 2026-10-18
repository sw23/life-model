# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import ClassVar

from ..base_classes import TaxAdvantagedAccount, TaxTreatment
from ..ledger import FlowKind
from ..limits import required_rmd_for_year
from ..model import Event, EventKind, snap_money
from ..people.person import Person
from ..tax.income import IncomeType


class TraditionalIRA(TaxAdvantagedAccount):
    STATS_OWNED = frozenset({"stat_required_min_distrib", "stat_traditional_ira_balance"})
    BALANCE_STAT = "stat_traditional_ira_balance"

    tax_treatment = TaxTreatment.PRETAX
    is_rmd_eligible = True
    limit_group = "ira"  # one IRA limit shared across Roth and Traditional
    # A twelfth of the year's RMD (set at the year start from the prior year-end balance) in each
    # month's pre_step (same ordering as Job401kAccount); growth stays in step.
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
        # This year's required minimum distribution (set at the year start; paid in twelfths).
        self.rmd_for_year = 0.0
        # The year's RMDs by recipient (an account can change hands mid-year), for the event log.
        self._rmd_by_person: dict = {}
        self.model.registries.traditional_iras.register(person, self)

    def contribute(self, amount: float, **kwargs) -> float:
        """Contribute pre-tax dollars, recording an above-the-line deduction for the amount.

        Deductibility phase-outs for owners covered by a workplace plan are not modeled.
        """
        actual = super().contribute(amount, **kwargs)
        self.person.income.add_deduction(actual, source="ira_deduction")
        return actual

    def on_year_start(self):
        # The year's RMD from the balance at the start of the year (the prior year-end balance).
        self.rmd_for_year = required_rmd_for_year(self.person, self.balance)

    def pre_step(self):
        """Take this month's share of the year's required minimum distribution (ordinary income, no
        FICA, never penalized)."""
        if self.rmd_for_year <= 0:
            return
        rmd = self.withdraw(self.rmd_for_year / 12)
        if rmd > 0:
            self.person.deposit_into_bank_account(
                rmd, kind=FlowKind.RMD, from_account=self, cause=f"{self.model.year} required minimum distribution"
            )
            self.person.income.add(IncomeType.PRETAX_DISTRIBUTION, rmd, source="rmd")
            self.stat_required_min_distrib = snap_money(self.stat_required_min_distrib + rmd)
            self._rmd_by_person[self.person] = self._rmd_by_person.get(self.person, 0.0) + rmd

    def on_year_end(self):
        super().on_year_end()
        # One RMD event per recipient a year (with the year's total).
        for person, amount in self._rmd_by_person.items():
            self.model.event_log.add(Event(EventKind.RMD, person=person, amount=amount, account=self))
        self._rmd_by_person = {}

    def annual_contribution_limit(self) -> float:
        if self._contribution_limit_override is not None:
            return self._contribution_limit_override
        return self.model.year_config.retirement.ira.contribution_limit

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Balance: ${self.balance:,.2f}</li>"
        desc += f"<li>Growth Rate: {self.growth_rate}%</li>"
        desc += f"<li>Contribution Limit: ${self.annual_contribution_limit():,.2f}</li>"
        desc += f"<li>Contributions This Year: ${self.contributions_ytd:,.2f}</li>"
        desc += "</ul>"
        return desc
