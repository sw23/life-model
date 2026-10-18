# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import warnings
from collections.abc import Sequence
from typing import TYPE_CHECKING, ClassVar

from ..base_classes import RetirementAccount
from ..deprecated_names import deprecated_arguments
from ..ledger import FlowKind
from ..limits import required_rmd_for_year
from ..model import Event, EventKind, snap_money
from ..tax.income import IncomeType

if TYPE_CHECKING:
    from ..people.person import Person
    from ..work.job import Job


class Job401kAccount(RetirementAccount):
    """A 401k whose balance is derived from separate pre-tax and Roth sub-balances.

    Timing:

    * ``on_year_start``: the year's required minimum distribution is set from the balance at the
      start of the year (the prior December 31 balance, as the IRS rule works) and the owner's age
      at the end of the year.
    * ``pre_step`` (priority -10), monthly: a twelfth of the year's RMD is distributed.
    * The job deposits each paycheck's contributions in its own ``pre_step`` (and trues them up at
      step priority -30 after a mid-month change).
    * ``step`` (priority -10, before the month's bills): the month's growth.
    """

    STATS_OWNED = frozenset({"stat_401k_balance", "stat_required_min_distrib"})

    is_rmd_eligible = True
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"pre_step": -10, "step": -10}

    @deprecated_arguments(
        {
            "pretax_contrib_percent": "pretax_contrib_pct",
            "roth_contrib_percent": "roth_contrib_pct",
            "average_growth": "growth_pct",
            "person": "owner",
        },
        positional=(
            "pretax_balance",
            "pretax_contrib_pct",
            "roth_balance",
            "roth_contrib_pct",
            "growth_pct",
            "company_match_percent",
        ),
    )
    def __init__(
        self,
        job: "Job | None" = None,
        *,
        owner: "Person | None" = None,
        pretax_balance: float = 0,
        roth_balance: float = 0,
        after_tax_balance: float = 0,
        pretax_contrib_pct: float = 0,
        roth_contrib_pct: float = 0,
        after_tax_contrib_pct: float = 0,
        growth_pct: float | None = None,
        company_match_percent: float = 0,
        match_tiers: "Sequence[tuple[float, float]] | None" = None,
        match_on_bonus: bool = False,
        match_vesting_years: int = 0,
        match_true_up: bool = True,
        roth_basis: float | None = None,
        after_tax_basis: float | None = None,
        in_plan_roth_conversion: bool = False,
        allocation: "dict[str, float] | None" = None,
        expense_ratio_pct: float = 0.0,
    ):
        """401k Account

        Args:
            job (Job, optional): Job offering the plan. None for a standalone plan (an old employer's
                401(k), Plan 27 D3): pass ``owner``; it grows, pays RMDs and is drawn by the waterfall
                but receives no contributions.
            owner (Person, optional): The participant, for a standalone plan (defaults to ``job.owner``).
            pretax_balance (float, optional): Initial pre-tax balance of account. Defaults to 0.
            roth_balance (float, optional): Initial roth balance of account. Defaults to 0.
            after_tax_balance (float, optional): After-tax (non-Roth) bucket: contributions plus their
                earnings, which are pre-tax money (Plan 27 D3). Defaults to 0.
            pretax_contrib_pct (float, optional): Pre-tax deferral, percent of plan pay (deprecated alias
                ``pretax_contrib_percent``). Defaults to 0.
            roth_contrib_pct (float, optional): Roth deferral, percent of plan pay (deprecated alias
                ``roth_contrib_percent``). Defaults to 0.
            after_tax_contrib_pct (float, optional): After-tax (non-Roth) contributions, percent of plan
                pay: out of take-home pay, outside the 402(g) limit but inside 415(c). Defaults to 0.
            growth_pct (float, optional): Annual growth rate (percent; deprecated alias
                ``average_growth``). Defaults to None, which defers to the economy's equity return.
            company_match_percent (float, optional): **Deprecated.** The legacy formula: a match of
                this percent *of the employee's deferral*, capped at this percent of salary (so
                ``6`` with a 6% deferral on $100k is $360). Warns with the equivalent
                ``match_tiers``. Defaults to 0. Mutually exclusive with ``match_tiers``.
            match_tiers (sequence of (match_percent, pay_percent), optional): The employer formula as
                plan documents state it, tier by tier over the employee's deferral rate:
                ``[(100, 3), (50, 2)]`` is "100% of the first 3% of pay deferred plus 50% of the
                next 2%" (4% of pay at a 5% or higher deferral).
            match_on_bonus (bool, optional): Whether plan pay includes the bonus. When True both the
                deferral percentages and the match tiers apply to salary + bonus; when False
                (default) to base salary only.
            match_vesting_years (int, optional): Cliff vesting for employer money: the match vests
                after this many years of service at the job, and unvested match is forfeited when the
                job ends before then. 0 (default) means immediately vested.
            match_true_up (bool, optional): The match is paid per paycheck on that paycheck's
                deferral; with a true-up (default True) the December paycheck tops it up to the plan
                formula on the year's totals, so front-loading deferrals (reaching the 402(g) limit
                before December) loses no match. False models a plan without a true-up.
            roth_basis (float, optional): Roth contributions in ``roth_balance`` (Plan 27 D3). A Roth 401(k)
                distribution before 59.5 is taxed and penalized on its earnings share, pro rata (IRC §72).
                None (default) treats the whole Roth balance as basis (no earnings tracked).
            after_tax_basis (float, optional): After-tax contributions in ``after_tax_balance`` (defaults to
                the whole bucket).
            in_plan_roth_conversion (bool, optional): Convert each after-tax contribution to Roth as it is
                made (the "mega backdoor" in-plan conversion): it lands in the Roth bucket as basis.

        Every argument after ``job`` is keyword-only (positional use is deprecated, Plan 27 D8).
        """
        if job is None and owner is None:
            raise ValueError("Job401kAccount needs a job, or an owner for a standalone plan")
        if job is not None and owner is not None and owner is not job.owner:
            raise ValueError("owner must be the job's owner")
        participant = owner if owner is not None else job.owner
        # Balance is derived from the buckets; growth via growth_pct (monthly).
        super().__init__(
            participant, growth_rate=growth_pct, allocation=allocation, expense_ratio_pct=expense_ratio_pct
        )
        self.job: Job | None = job
        self.pretax_balance = pretax_balance
        self.roth_balance = roth_balance
        self.after_tax_balance = after_tax_balance
        if roth_basis is not None and not 0 <= roth_basis <= roth_balance + 1e-9:
            raise ValueError("roth_basis must be between 0 and roth_balance")
        if after_tax_basis is not None and not 0 <= after_tax_basis <= after_tax_balance + 1e-9:
            raise ValueError("after_tax_basis must be between 0 and after_tax_balance")
        #: Roth contributions still in the Roth bucket, or None when untracked (the whole bucket is basis).
        self.roth_basis: float | None = roth_basis
        #: After-tax contributions still in the after-tax bucket (its earnings are pre-tax money).
        self.after_tax_basis = after_tax_balance if after_tax_basis is None else after_tax_basis
        self.model.ledger.post_opening(self, pretax_balance + roth_balance + after_tax_balance)
        self.pretax_contrib_percent = pretax_contrib_pct
        self.roth_contrib_percent = roth_contrib_pct
        self.after_tax_contrib_percent = after_tax_contrib_pct
        self.in_plan_roth_conversion = in_plan_roth_conversion
        if company_match_percent and match_tiers is not None:
            raise ValueError("Pass either match_tiers or the deprecated company_match_percent, not both")
        if company_match_percent:
            warnings.warn(
                f"company_match_percent={company_match_percent:g} is deprecated. It means a "
                f"{company_match_percent:g}% match on every deferred dollar, capped at "
                f"{company_match_percent:g}% of salary: match_tiers=[({company_match_percent:g}, 100)] "
                "with that cap. A plan that matches dollar-for-dollar up to "
                f"{company_match_percent:g}% of pay is match_tiers=[(100, {company_match_percent:g})].",
                DeprecationWarning,
                stacklevel=2,
            )
        self.company_match_percent = company_match_percent
        self.match_tiers: tuple[tuple[float, float], ...] | None = (
            None if match_tiers is None else self._validate_tiers(match_tiers)
        )
        self.match_on_bonus = match_on_bonus
        self.match_true_up = match_true_up
        if match_vesting_years < 0:
            raise ValueError("match_vesting_years must be >= 0")
        self.match_vesting_years = match_vesting_years
        # Employer match (with its growth) not yet vested; part of pretax_balance. See vest_match.
        self.unvested_match = 0.0

        self.stat_required_min_distrib = 0
        self.stat_401k_balance = 0
        # This year's required minimum distribution (set at the year start; paid in twelfths).
        self.rmd_for_year = 0.0
        # The year's RMDs by recipient (an account can change hands mid-year), for the event log.
        self._rmd_by_person: dict = {}

        if job is not None:
            job.retirement_account = self
        self.model.registries.job_401k_accounts.register(participant, self)

    @property
    def is_standalone(self) -> bool:
        """Whether this is a plan without a job (an old employer's 401(k))."""
        return self.job is None

    def pretax_contrib(self, salary: float):
        return salary * (self.pretax_contrib_percent / 100)

    def roth_contrib(self, salary: float):
        return salary * (self.roth_contrib_percent / 100)

    def company_match(self, contribution: float):
        """Legacy (deprecated ``company_match_percent``) match on ``contribution``, before the pay cap."""
        return contribution * (self.company_match_percent / 100)

    @staticmethod
    def _validate_tiers(tiers: "Sequence[tuple[float, float]]") -> tuple[tuple[float, float], ...]:
        validated = tuple((float(rate), float(width)) for rate, width in tiers)
        if any(rate < 0 or width <= 0 for rate, width in validated):
            raise ValueError(f"match_tiers need a match percent >= 0 and a pay percent > 0 per tier, got {tiers}")
        return validated

    def plan_compensation(self, salary: float, bonus: float) -> float:
        """Pay the plan's deferral percentages and match apply to (``match_on_bonus`` adds the bonus)."""
        return salary + bonus if self.match_on_bonus else salary

    def employer_match(self, elective: float, compensation: float) -> float:
        """The employer match on a year's ``elective`` deferral out of ``compensation`` plan pay.

        With ``match_tiers``, each tier matches its rate on the slice of the deferral rate it
        covers. With the deprecated ``company_match_percent``, the legacy formula (that percent of
        the deferral, capped at that percent of pay). The 415(c) cap is applied by the job.
        """
        if compensation <= 0 or elective <= 0:
            return 0.0
        if self.match_tiers is not None:
            deferral_percent = elective / compensation * 100
            match = 0.0
            start = 0.0
            for rate, width in self.match_tiers:
                covered = min(max(deferral_percent - start, 0.0), width)
                match += compensation * (covered / 100) * (rate / 100)
                start += width
            return match
        return min(self.company_match(elective), (self.company_match_percent / 100) * compensation)

    def receive_match(self, amount: float) -> None:
        """Deposit employer match (pre-tax). Unvested until ``match_vesting_years`` of service."""
        self.pretax_balance += amount
        if self.job is not None and not self.is_match_vested:
            self.unvested_match = max(0.0, self.unvested_match + amount)

    @property
    def is_match_vested(self) -> bool:
        """Whether employer money is vested (service at the job has reached ``match_vesting_years``)."""
        service = self.job.years_of_service if self.job is not None else 0
        return service >= self.match_vesting_years

    def vest_match(self) -> None:
        """Vest employer money once the service requirement is met (called by the job at year end)."""
        if self.unvested_match > 0 and self.is_match_vested:
            self.unvested_match = 0.0

    def forfeit_unvested_match(self) -> float:
        """Forfeit unvested employer money when the job ends. Returns the amount forfeited."""
        forfeited = min(self.unvested_match, self.pretax_balance)
        self.unvested_match = 0.0
        if forfeited > 0:
            self.pretax_balance -= forfeited
            self.model.ledger.post(
                forfeited,
                FlowKind.FORFEIT,
                from_account=self,
                sink=self.job.company if self.job is not None else "employer",
                cause="unvested 401k match forfeited",
                agent=self.person,
            )
            self.model.event_log.add(
                Event(f"{self.person.name} forfeited ${forfeited:,.0f} of unvested 401k match on leaving")
            )
        return forfeited

    @property
    def average_growth(self) -> float:
        """Annual growth rate (percent); an alias of ``growth_rate`` kept for backward compatibility."""
        return self.growth_rate

    @average_growth.setter
    def average_growth(self, value: float) -> None:
        self.growth_rate = value

    @property
    def balance(self):
        return self.pretax_balance + self.roth_balance + self.after_tax_balance

    @balance.setter
    def balance(self, value):
        # Balance is derived; never silently discard a write (fixes the silent-discard bug).
        raise AttributeError(
            "Job401kAccount.balance is derived from pretax_balance + roth_balance + after_tax_balance; "
            "set those directly instead of assigning balance."
        )

    def deposit(self, amount: float) -> bool:
        """Deposit amount into account. Returns success status"""
        if amount < 0:
            raise ValueError("Deposit amount cannot be negative")
        # For 401k, deposits go to pretax by default
        self.pretax_balance += amount
        return True

    def withdraw(self, amount: float) -> float:
        """Withdraw amount from account. Returns actual amount withdrawn"""
        if amount <= 0:
            return 0.0
        # Withdraw from pretax first, then roth
        total_withdrawn = 0.0

        if self.pretax_balance > 0:
            pretax_withdrawn = min(self.pretax_balance, amount)
            self.pretax_balance -= pretax_withdrawn
            total_withdrawn += pretax_withdrawn
            amount -= pretax_withdrawn

        if amount > 0 and self.after_tax_balance > 0:
            taken, _taxable = self._take_after_tax(amount)
            total_withdrawn += taken
            amount -= taken

        if amount > 0 and self.roth_balance > 0:
            total_withdrawn += self.deduct_roth(amount)

        return total_withdrawn

    def _repr_html_(self):
        company = self.job.company if self.job is not None else "a former employer"
        return f"401k at {company} balance: ${self.balance:,}"

    def apply_growth(self):
        """Grow the pre-tax and roth sub-balances by the month's rate.

        Uses the same monthly growth as every other ``Investment`` so accounts with the same rate
        grow identically.
        """
        rate = self.monthly_growth_rate / 100
        pretax_growth = self.pretax_balance * rate
        roth_growth = self.roth_balance * rate
        after_tax_growth = self.after_tax_balance * rate
        self.pretax_balance += pretax_growth
        self.roth_balance += roth_growth
        self.after_tax_balance += after_tax_growth
        self.unvested_match = min(self.unvested_match * (1 + rate), self.pretax_balance)
        growth = pretax_growth + roth_growth + after_tax_growth
        self.stat_growth_history.append(growth)
        self._post_growth(growth)
        self._drift_allocation()
        return growth

    def on_year_start(self):
        # The year's RMD from the balance at the start of the year (the prior year-end balance).
        self.rmd_for_year = required_rmd_for_year(self.person, self.pretax_balance)

    def pre_step(self):
        # A twelfth of the year's RMD, before Social Security computes provisional income.
        self._take_required_min_distribution()

    def collect_stats(self):
        super().collect_stats()
        self.stat_401k_balance = self.balance

    def on_year_end(self):
        super().on_year_end()
        # One RMD event per recipient a year (with the year's total).
        for person, amount in self._rmd_by_person.items():
            self.model.event_log.add(Event(EventKind.RMD, person=person, amount=amount, account=self))
        self._rmd_by_person = {}

    def _take_required_min_distribution(self):
        """Force-withdraw this month's share of the year's required minimum distribution (pre-tax,
        ordinary income, no FICA)."""
        if self.rmd_for_year <= 0:
            return
        required_min_dist_amount = self.deduct_pretax(self.rmd_for_year / 12)
        self.person.deposit_into_bank_account(
            required_min_dist_amount,
            kind=FlowKind.RMD,
            from_account=self,
            cause=f"{self.model.year} required minimum distribution",
        )
        # RMDs are ordinary income, not FICA wages.
        self.person.income.add(IncomeType.PRETAX_DISTRIBUTION, required_min_dist_amount, source="rmd")
        self.stat_required_min_distrib = snap_money(self.stat_required_min_distrib + required_min_dist_amount)
        if required_min_dist_amount > 0:
            self._rmd_by_person[self.person] = self._rmd_by_person.get(self.person, 0.0) + required_min_dist_amount

    def deduct_pretax(self, amount: float):
        """Deduct from pre-tax balance

        Args:
            amount (float): Amount to deduct.

        Returns:
            float: Amount deducted. Will not be less than the account balance.
        """
        amount_deducted = min(self.pretax_balance, amount)
        self.pretax_balance -= amount_deducted
        self.unvested_match = min(self.unvested_match, self.pretax_balance)
        return amount_deducted

    def deduct_roth(self, amount: float) -> float:
        """Deduct from roth balance (a primitive: no tax). Tracked Roth basis is reduced pro rata.

        Args:
            amount (float): Amount to deduct.

        Returns:
            float: Amount deducted. Will not be less than the account balance.
        """
        amount_deducted = min(self.roth_balance, amount)
        if amount_deducted > 0 and self.roth_basis is not None and self.roth_balance > 0:
            self.roth_basis = max(0.0, self.roth_basis * (1 - amount_deducted / self.roth_balance))
        self.roth_balance -= amount_deducted
        return amount_deducted

    @property
    def roth_earnings_fraction(self) -> float:
        """Share of the Roth bucket that is earnings (0 when the basis is untracked)."""
        if self.roth_basis is None or self.roth_balance <= 0:
            return 0.0
        return max(0.0, 1 - self.roth_basis / self.roth_balance)

    def distribute_roth(self, amount: float) -> float:
        """A Roth 401(k) distribution of up to ``amount``. Before 59.5 it is non-qualified: the earnings
        share (pro rata, IRC §72(e)(8)) is ordinary income plus the 10% additional tax. Qualified (59.5+;
        the five-year rule is not modeled) and untracked-basis distributions are tax-free. Returns the
        amount withdrawn (the caller moves and posts the cash)."""
        fraction = 0.0 if self.is_useable else self.roth_earnings_fraction
        taken = self.deduct_roth(amount)
        taxable = taken * fraction
        if taxable > 0:
            self.person.income.add(IncomeType.PRETAX_DISTRIBUTION, taxable, source="roth_401k_earnings")
            self.person.income.add_penalty(self.person.early_withdrawal_penalty(taxable), source="roth_401k_earnings")
        return taken

    def receive_roth(self, amount: float, *, basis: bool = True) -> None:
        """Credit ``amount`` to the Roth bucket (a Roth deferral or conversion: basis when ``basis``)."""
        self.roth_balance = snap_money(self.roth_balance + amount)
        if basis and self.roth_basis is not None:
            self.roth_basis = max(0.0, self.roth_basis + amount)

    @property
    def after_tax_earnings_fraction(self) -> float:
        """Share of the after-tax bucket that is earnings (pre-tax money)."""
        if self.after_tax_balance <= 0:
            return 0.0
        return max(0.0, 1 - self.after_tax_basis / self.after_tax_balance)

    def _take_after_tax(self, amount: float) -> "tuple[float, float]":
        """Take up to ``amount`` from the after-tax bucket: ``(taken, taxable earnings share)``."""
        fraction = self.after_tax_earnings_fraction
        taken = min(self.after_tax_balance, amount)
        if taken <= 0:
            return 0.0, 0.0
        self.after_tax_basis = max(0.0, self.after_tax_basis - taken * (1 - fraction))
        self.after_tax_balance -= taken
        return taken, taken * fraction

    def distribute_after_tax(self, amount: float) -> float:
        """Distribute up to ``amount`` from the after-tax bucket: the contributions come back tax-free and
        the earnings share (pro rata) is ordinary income, plus the 10% additional tax before 59.5. Returns
        the amount withdrawn (the caller moves and posts the cash)."""
        taken, taxable = self._take_after_tax(amount)
        if taxable > 0:
            self.person.income.add(IncomeType.PRETAX_DISTRIBUTION, taxable, source="401k")
            self.person.income.add_penalty(self.person.early_withdrawal_penalty(taxable))
        return taken

    def receive_after_tax(self, amount: float) -> None:
        """Credit an after-tax (non-Roth) contribution: to the Roth bucket as basis when converted in plan
        (no earnings yet, so the conversion is tax-free), else to the after-tax bucket."""
        if self.in_plan_roth_conversion:
            self.receive_roth(amount)
        else:
            self.after_tax_balance = snap_money(self.after_tax_balance + amount)
            self.after_tax_basis = max(0.0, self.after_tax_basis + amount)

    def after_tax_contrib(self, salary: float) -> float:
        return salary * (self.after_tax_contrib_percent / 100)

    def convert_pretax_to_roth(self, amount: float) -> float:
        """In-plan Roth rollover of up to ``amount`` of pre-tax money (IRC §402A(c)(4)): ordinary income
        this year (no 10% additional tax), credited to the Roth bucket as basis. Returns the amount
        converted; posts nothing (the caller records the year's conversion)."""
        taken = self.deduct_pretax(amount)
        if taken > 0:
            self.person.income.add(IncomeType.PRETAX_DISTRIBUTION, taken, source="roth_conversion")
            self.receive_roth(taken)
        return taken
