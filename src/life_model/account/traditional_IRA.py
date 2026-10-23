# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import ClassVar

from ..base_classes import TaxAdvantagedAccount, TaxTreatment
from ..deprecated_names import deprecated_arguments
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

    @deprecated_arguments(
        {"person": "owner", "growth_rate": "growth_pct", "contribution_limit": "contribution_limit_annual"},
        positional=("balance", "growth_pct", "contribution_limit_annual"),
    )
    def __init__(
        self,
        owner: Person,
        *,
        balance: float = 0,
        growth_pct: float | None = None,
        contribution_limit_annual: float | None = None,
        nondeductible_basis: float = 0.0,
        allocation: "dict[str, float] | None" = None,
        expense_ratio_pct: float = 0.0,
    ):
        """Models a Traditional IRA account for a person.

        Contributions are pre-tax (deductible, phased out at settlement for a covered worker); the
        account is subject to required minimum distributions. Distributions are ordinary income except
        the share that returns Form 8606 basis: the pro-rata rule (IRC §72, §408(d)(2)) applies the
        ratio of the owner's basis to the value of all their traditional IRAs to each distribution and
        Roth conversion. Contribution/withdraw/growth and the annual-limit reset are inherited from
        :class:`TaxAdvantagedAccount`.

        Args:
            owner: The person to which this IRA belongs (deprecated alias ``person``).
            balance: Current balance in the IRA
            growth_pct: Expected annual growth rate percentage (deprecated alias ``growth_rate``).
                Defers to the economy's equity return when None.
            contribution_limit_annual: Override for the annual contribution limit (deprecated alias
                ``contribution_limit``). Uses the year's IRA limit plus the age-50 catch-up when None.
                The limit is shared across all of a person's IRAs.
            nondeductible_basis: Form 8606 basis (nondeductible contributions not yet recovered, line
                14 of the last filed 8606). The year's nondeductible contributions (the deduction
                phase-out) are added at settlement; distributions recover it pro rata.
            allocation: Target allocation in percent by asset class, rebalanced yearly.
            expense_ratio_pct: Fund expense ratio (percent a year).
        """
        person = owner
        growth_rate = growth_pct
        contribution_limit = contribution_limit_annual
        if nondeductible_basis < 0 or nondeductible_basis > balance + 1e-9:
            raise ValueError("nondeductible_basis must be between 0 and the balance")
        super().__init__(person, balance, growth_rate, allocation=allocation, expense_ratio_pct=expense_ratio_pct)
        self._contribution_limit_override = contribution_limit
        #: Form 8606 line 14: nondeductible contributions not yet recovered.
        self.nondeductible_basis = nondeductible_basis
        #: Basis at the start of each year and basis recovered by distributions and conversions, by year
        #: (Form 8606 lines 2 and 13; the reconciliation reads them).
        self.basis_at_year_start: dict[int, float] = {}
        self.basis_recovered: dict[int, float] = {}
        self.stat_required_min_distrib = 0
        # This year's required minimum distribution (set at the year start; paid in twelfths).
        self.rmd_for_year = 0.0
        # The year's RMDs by recipient (an account can change hands mid-year), for the event log.
        self._rmd_by_person: dict = {}
        self.model.registries.traditional_iras.register(person, self)

    def contribute(self, amount: float, **kwargs) -> float:
        """Contribute pre-tax dollars, recording an above-the-line deduction for the amount.

        At settlement the tax unit phases the deduction out for an owner (or spouse) covered by a
        workplace plan (IRC §219(g)); the nondeductible part becomes ``nondeductible_basis``.
        """
        actual = super().contribute(amount, **kwargs)
        self.person.income.add_deduction(actual, source="ira_deduction")
        return actual

    def on_year_start(self):
        self.basis_at_year_start[self.model.year] = self.nondeductible_basis
        # The year's RMD from the balance at the start of the year (the prior year-end balance).
        required = required_rmd_for_year(self.person, self.balance)
        # Qualified charitable distributions are made now, with the year's donations, and count toward
        # the RMD (IRC §408(d)(8)); the rest of the RMD is paid in monthly twelfths.
        qcd = self._make_qualified_charitable_distributions()
        self.rmd_for_year = max(0.0, required - qcd)

    def pre_step(self):
        """Take this month's share of the year's required minimum distribution (ordinary income, no
        FICA, never penalized)."""
        if self.rmd_for_year <= 0:
            return
        rmd = self.distribute(self.rmd_for_year / 12, source="rmd", penalize=False)
        if rmd > 0:
            self.person.deposit_into_bank_account(
                rmd, kind=FlowKind.RMD, from_account=self, cause=f"{self.model.year} required minimum distribution"
            )
            self.stat_required_min_distrib = snap_money(self.stat_required_min_distrib + rmd)
            self._rmd_by_person[self.person] = self._rmd_by_person.get(self.person, 0.0) + rmd

    def on_year_end(self):
        super().on_year_end()
        # One RMD event per recipient a year (with the year's total).
        for person, amount in self._rmd_by_person.items():
            self.model.event_log.add(Event(EventKind.RMD, person=person, amount=amount, account=self))
        self._rmd_by_person = {}

    #: Exact age from which a distribution may be a qualified charitable distribution (IRC §408(d)(8)(B)(ii)).
    QCD_MIN_AGE = 70.5

    def _make_qualified_charitable_distributions(self) -> float:
        """Pay this year's QCD donations of the owner from this IRA (up to the year's per-person limit
        across their IRAs), in the year's first month. The owner must be 70½ at the distribution (exact
        age that month); a donor not yet 70½ gives in cash. Returns the amount distributed to charity."""
        if self.person.is_deceased or self.person.age_years_fractional < self.QCD_MIN_AGE or self.balance <= 0:
            return 0.0
        limit = self.model.year_config.tax.federal.qcd_limit
        if limit is None:
            return 0.0
        year = self.model.year
        total = 0.0
        for donation in self.person.donations:
            make = getattr(donation, "make_qcd", None)
            if make is None:
                continue
            # Only this year's QCDs use the room: a donation's counter keeps last year's figure until it
            # resets (in its make_qcd, or its pre_step after this).
            given = sum(d.qcd_this_year for d in self.person.donations if getattr(d, "_qcd_year", None) == year)
            total += make(self, limit - given)
        return total

    def annual_contribution_limit(self) -> float:
        if self._contribution_limit_override is not None:
            return self._contribution_limit_override
        return ira_contribution_limit(self.person, self.model.year)

    def basis_ratio(self) -> float:
        """The pro-rata share of a distribution that returns basis now: the owner's basis over the value
        of all their traditional IRAs (Form 8606 lines 6-10, read at the distribution rather than at the
        year end, a simplification)."""
        return ira_basis_ratio(self.person)

    def distribute(self, amount: float, *, source: str = "ira", penalize: bool = True) -> float:
        """Withdraw up to ``amount`` as a distribution: the pro-rata basis share is tax-free (it reduces
        the owner's basis across their IRAs); the rest is ordinary income on the owner's ledger, plus the
        10% additional tax before 59.5 when ``penalize``. Returns the amount withdrawn (the caller moves
        and posts the cash)."""
        ratio = self.basis_ratio()
        withdrawn = self.withdraw(amount)
        if withdrawn <= 0:
            return 0.0
        nontaxable = withdrawn * ratio
        if nontaxable > 0:
            _reduce_ira_basis(self.person, nontaxable)
        taxable = withdrawn - nontaxable
        if taxable > 0:
            self.person.income.add(IncomeType.PRETAX_DISTRIBUTION, taxable, source=source)
            if penalize:
                self.person.income.add_penalty(self.person.early_withdrawal_penalty(taxable))
        return withdrawn

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Balance: ${self.balance:,.2f}</li>"
        desc += f"<li>Growth Rate: {self.growth_rate}%</li>"
        desc += f"<li>Contribution Limit: ${self.annual_contribution_limit():,.2f}</li>"
        desc += f"<li>Contributions This Year: ${self.contributions_ytd:,.2f}</li>"
        desc += "</ul>"
        return desc


def ira_contribution_limit(person: Person, year: int) -> float:
    """The year's IRA contribution limit for ``person``: the base limit plus the age-50 catch-up
    (IRC §219(b)(5)(B), by the age reached by the end of the year; ``tax_years.limit_ira_catch_up``)."""
    model = person.model
    limit = model.year_config.retirement.ira.contribution_limit
    if person.age_in(year) >= IRA_CATCH_UP_AGE:
        limit += model.tax_params_for_year(year).limit_ira_catch_up
    return limit


#: Age (by the end of the year) from which the IRA catch-up applies (IRC §219(b)(5)(B)).
IRA_CATCH_UP_AGE = 50


def ira_basis_ratio(person: Person) -> float:
    """The owner's Form 8606 basis over the value of all their traditional IRAs (0 without basis)."""
    iras = person.traditional_iras
    basis = sum(getattr(ira, "nondeductible_basis", 0.0) for ira in iras)
    if basis <= 0:
        return 0.0
    value = sum(ira.balance for ira in iras)
    return min(1.0, basis / value) if value > 0 else 1.0


def _reduce_ira_basis(person: Person, amount: float) -> None:
    """Recover ``amount`` of basis across the owner's IRAs, in proportion to each one's basis."""
    iras = [ira for ira in person.traditional_iras if ira.nondeductible_basis > 0]
    total = sum(ira.nondeductible_basis for ira in iras)
    if total <= 0:
        return
    year = person.model.year
    for ira in iras:
        recovered = min(ira.nondeductible_basis, amount * ira.nondeductible_basis / total)
        ira.nondeductible_basis -= recovered
        ira.basis_recovered[year] = ira.basis_recovered.get(year, 0.0) + recovered


def ira_taxable_capacity(person: Person) -> float:
    """How much taxable income draining the owner's traditional IRAs would produce (value less basis)."""
    return max(0.0, sum(ira.balance for ira in person.traditional_iras) * (1 - ira_basis_ratio(person)))
