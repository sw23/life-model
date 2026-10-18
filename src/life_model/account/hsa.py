# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from enum import Enum

from ..base_classes import TaxAdvantagedAccount, TaxTreatment
from ..deprecated_names import deprecated_arguments
from ..ledger import FlowKind
from ..people.person import Person


class HSAType(Enum):
    """Types of Health Savings Accounts"""

    INDIVIDUAL = "Individual"
    FAMILY = "Family"


class HealthSavingsAccount(TaxAdvantagedAccount):
    STATS_OWNED = frozenset({"stat_hsa_balance"})
    BALANCE_STAT = "stat_hsa_balance"
    tax_treatment = TaxTreatment.HSA
    is_rmd_eligible = False

    @deprecated_arguments(
        {
            "person": "owner",
            "contribution_limit": "contribution_limit_annual",
            "employer_contribution": "employer_contribution_annual",
            "growth_rate": "growth_pct",
        },
        positional=("hsa_type", "balance", "contribution_limit_annual", "employer_contribution_annual"),
    )
    def __init__(
        self,
        owner: Person,
        *,
        hsa_type: HSAType = HSAType.INDIVIDUAL,
        balance: float = 0,
        contribution_limit_annual: float | None = None,
        employer_contribution_annual: float | None = None,
        growth_pct: float | None = None,
        basis: float | None = None,
        allocation: "dict[str, float] | None" = None,
        expense_ratio_pct: float = 0.0,
    ):
        """Models a Health Savings Account (HSA).

        The HSA grows like any other investment (monthly), uses the correct self-only/family
        contribution limit (including the age-55 catch-up), and counts employer contributions against
        that limit. Payroll contributions (employee and employer, Plan 27 D3) come through the job's
        :class:`~life_model.work.payroll.PayrollDeductions`.

        Args:
            owner: The person who owns this HSA (deprecated alias ``person``).
            hsa_type: Type of HSA (Individual or Family).
            balance: Current HSA balance.
            contribution_limit_annual: Override for the annual contribution limit (deprecated alias
                ``contribution_limit``). Uses the year/age/tier indexed limit when None.
            employer_contribution_annual: A yearly employer contribution deposited at each year start
                while the owner has an active W-2 job (deprecated alias ``employer_contribution``; prefer
                ``PayrollDeductions(hsa_employer_annual=)``, paid per paycheck). Uses the configured
                default if None.
            growth_pct: Expected annual growth rate percentage (deprecated alias ``growth_rate``).
                Defers to the economy's equity return when None (HSAs are typically invested).
            basis: Contribution basis (Plan 27 D1); the whole balance when None. Informational: every
                HSA distribution is tax-free for medical costs and fully taxable otherwise.
            allocation: Target allocation in percent by asset class (Plan 27 D5).
            expense_ratio_pct: Fund expense ratio (percent a year).
        """
        person = owner
        contribution_limit = contribution_limit_annual
        employer_contribution = employer_contribution_annual
        hsa_config = person.model.config.accounts.hsa
        if employer_contribution is None:
            employer_contribution = hsa_config.default_employer_contribution
        super().__init__(
            person,
            balance,
            growth_pct,
            basis=basis,
            allocation=allocation,
            expense_ratio_pct=expense_ratio_pct,
        )
        self.hsa_type = hsa_type
        self._contribution_limit_override = contribution_limit
        self.employer_contribution = employer_contribution
        self.model.registries.hsa_accounts.register(person, self)

    def annual_contribution_limit(self) -> float:
        """Self-only or family limit for the year, plus the age-55 catch-up.

        Employer contributions count against this same limit (they are deducted from the room in
        :meth:`step`).
        """
        if self._contribution_limit_override is not None:
            return self._contribution_limit_override
        hsa_config = self.model.year_config.accounts.hsa
        base = (
            hsa_config.contribution_limit_family if self.hsa_type == HSAType.FAMILY else hsa_config.contribution_limit
        )
        if self.person.age_in(self.model.year) >= hsa_config.catch_up_age:  # by the end of the year
            base += hsa_config.catch_up_amount
        return base

    def contribute(self, amount: float, **kwargs) -> float:
        """Contribute up to the remaining limit; the owner's contribution is deductible.

        Employer contributions (see :meth:`step`) never entered the owner's income, so they are
        not deducted. ``kwargs`` (``from_account``, ``source``) say where the money came from (see
        :meth:`TaxAdvantagedAccount.contribute`).
        """
        actual = super().contribute(amount, **kwargs)
        self.person.income.add_deduction(actual, source="hsa_deduction")
        return actual

    def withdraw_medical(self, amount: float) -> float:
        """Withdraw for qualified medical expenses (always tax-free)."""
        return self.withdraw(amount)

    def withdraw_non_medical(self, amount: float) -> float:
        """Withdraw for non-medical expenses.

        The distribution is ordinary income; below the penalty age (65) it also incurs the 20%
        additional tax. Both are recorded on the owner's income ledger and settled at year end.
        """
        from ..tax.income import IncomeType

        withdrawn = self.withdraw(amount)
        if withdrawn > 0:
            hsa_config = self.model.config.accounts.hsa
            self.person.income.add(IncomeType.PRETAX_DISTRIBUTION, withdrawn, source="hsa")
            if self.person.age_years_fractional < hsa_config.non_medical_penalty_age:
                self.person.income.add_penalty(
                    withdrawn * hsa_config.non_medical_penalty_rate / 100, source="hsa_non_medical"
                )
        return withdrawn

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

    def credit_payroll(self, amount: float) -> None:
        """Credit payroll HSA money (employee and employer; a negative true-up claws it back): counted
        against the limit, never an above-the-line deduction (it was kept out of wages). The job posts it."""
        self.balance += amount
        self.contributions_ytd += amount
        self.contribution_basis = max(0.0, self.contribution_basis + amount)

    def receive_employer_contribution(self, amount: float, employer: str) -> float:
        """Deposit up to ``amount`` of employer money (counted against the limit; never in the owner's
        income). Returns what was deposited."""
        employer_room = min(amount, self.remaining_contribution_room())
        if employer_room <= 0:
            return 0.0
        self.balance += employer_room
        self.contributions_ytd += employer_room
        self.contribution_basis += employer_room
        self.model.ledger.post(
            employer_room,
            FlowKind.CONTRIBUTION,
            to_account=self,
            source=employer,
            cause="employer HSA contribution",
            agent=self.person,
        )
        return employer_room

    def on_year_start(self):
        """Add the legacy yearly employer contribution (at the year start, counted against the limit).
        Plan 27 D3: it stops once the owner's jobs have all ended (an owner modeled without any job keeps
        receiving it, the legacy behavior)."""
        if self.employer_contribution <= 0:
            return
        jobs = [job for job in self.person.jobs if job.kind == "w2"]
        if jobs and not any(job.is_active_in(self.model.year) for job in jobs):
            return
        self.receive_employer_contribution(self.employer_contribution, "employer HSA contribution")
