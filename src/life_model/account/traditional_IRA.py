# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import ClassVar

from ..base_classes import TaxAdvantagedAccount, TaxTreatment
from ..ledger import FlowKind
from ..limits import required_min_distrib, rmd_start_age
from ..model import Event, EventKind
from ..people.person import Person
from ..tax.income import IncomeType


class TraditionalIRA(TaxAdvantagedAccount):
    STATS_OWNED = frozenset({"stat_required_min_distrib", "stat_traditional_ira_balance"})
    BALANCE_STAT = "stat_traditional_ira_balance"

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
        *,
        nondeductible_basis: float = 0.0,
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
            nondeductible_basis: Form 8606 basis (nondeductible contributions) at the start. Plan 31 adds
                the year's nondeductible contributions (the deduction phase-out) to it; distributions are
                still fully taxable (the pro-rata rule lands with Plan 27 D1).
        """
        super().__init__(person, balance, growth_rate)
        self._contribution_limit_override = contribution_limit
        #: Form 8606 line 14: nondeductible contributions not yet recovered.
        self.nondeductible_basis = nondeductible_basis
        self.stat_required_min_distrib = 0
        self.model.registries.traditional_iras.register(person, self)

    def contribute(self, amount: float, **kwargs) -> float:
        """Contribute pre-tax dollars, recording an above-the-line deduction for the amount.

        At settlement the tax unit phases the deduction out for an owner (or spouse) covered by a
        workplace plan (IRC §219(g)); the nondeductible part becomes ``nondeductible_basis``.
        """
        actual = super().contribute(amount, **kwargs)
        self.person.income.add_deduction(actual, source="ira_deduction")
        return actual

    def pre_step(self):
        """Take any required minimum distribution (ordinary income, no FICA, never penalized)."""
        config = self.model.config
        birth_year = self.model.year - self.person.age
        start_age = rmd_start_age(birth_year, config=config, year=self.model.year)
        required = required_min_distrib(self.person.age, self.balance, config=config, start_age=start_age)
        # Qualified charitable distributions go first and count toward the RMD (IRC §408(d)(8)).
        qcd = self._make_qualified_charitable_distributions()
        rmd = self.withdraw(max(0.0, required - qcd))
        if rmd > 0:
            self.person.deposit_into_bank_account(
                rmd, kind=FlowKind.RMD, from_account=self, cause=f"{self.model.year} required minimum distribution"
            )
            self.person.income.add(IncomeType.PRETAX_DISTRIBUTION, rmd, source="rmd")
        self.stat_required_min_distrib = rmd
        if rmd > 0:
            self.model.event_log.add(Event(EventKind.RMD, person=self.person, amount=rmd, account=self))

    #: Age from which a distribution may be a qualified charitable distribution (70½; whole-year ages
    #: in the model, so the year the owner is 71).
    QCD_MIN_AGE = 71

    def _make_qualified_charitable_distributions(self) -> float:
        """Pay this year's QCD donations of the owner from this IRA (up to the year's per-person limit
        across their IRAs). Returns the amount distributed to charity from this account."""
        if self.person.age < self.QCD_MIN_AGE or self.balance <= 0:
            return 0.0
        limit = self.model.year_config.tax.federal.qcd_limit
        if limit is None:
            return 0.0
        total = 0.0
        for donation in self.person.donations:
            make = getattr(donation, "make_qcd", None)
            if make is None:
                continue
            room = limit - sum(getattr(d, "qcd_this_year", 0.0) for d in self.person.donations)
            total += make(self, room)
        return total

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
