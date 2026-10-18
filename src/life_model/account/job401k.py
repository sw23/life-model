# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import warnings
from collections.abc import Sequence
from typing import TYPE_CHECKING, ClassVar

from ..base_classes import RetirementAccount
from ..limits import required_min_distrib, rmd_start_age
from ..model import Event
from ..tax.income import IncomeType

if TYPE_CHECKING:
    from ..work.job import Job


class Job401kAccount(RetirementAccount):
    """A 401k whose balance is derived from separate pre-tax and Roth sub-balances.

    Ordering within a simulated year:

    * ``pre_step`` (priority -10): take this year's required minimum distribution from the prior
      year-end balance (the IRS rule). This runs before Social Security's ``pre_step`` so the RMD
      is already in the income ledger when the taxable share of benefits is computed.
    * The job deposits this year's contributions in its own ``pre_step``.
    * ``step`` (priority -10, before tax-unit settlement): apply growth, so contributions land
      before growth.
    """

    STATS_OWNED = frozenset({"stat_401k_balance", "stat_required_min_distrib"})

    is_rmd_eligible = True
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"pre_step": -10, "step": -10}

    def __init__(
        self,
        job: "Job",
        pretax_balance: float = 0,
        pretax_contrib_percent: float = 0,
        roth_balance: float = 0,
        roth_contrib_percent: float = 0,
        average_growth: float | None = None,
        company_match_percent: float = 0,
        *,
        match_tiers: "Sequence[tuple[float, float]] | None" = None,
        match_on_bonus: bool = False,
        match_vesting_years: int = 0,
    ):
        """401k Account

        Args:
            job (Job): Job offering the 401k plan.
            pretax_balance (float, optional): Initial pre-tax balance of account. Defaults to 0.
            pretax_contrib_percent (float, optional): Pre-tax contribution, percent of plan pay. Defaults to 0.
            roth_balance (float, optional): Initial roth balance of account. Defaults to 0.
            roth_contrib_percent (float, optional): Roth contribution, percent of plan pay. Defaults to 0.
            average_growth (float, optional): Annual growth rate (percent). Defaults to None, which
                defers to the economy's equity return each year like every other investment account.
            company_match_percent (float, optional): **Deprecated.** The legacy formula: a match of
                this percent *of the employee's deferral*, capped at this percent of salary (so
                ``6`` with a 6% deferral on $100k is $360). Warns with the equivalent
                ``match_tiers``. Defaults to 0. Mutually exclusive with ``match_tiers``.
            match_tiers (sequence of (match_percent, pay_percent), optional): The employer formula as
                plan documents state it, tier by tier over the employee's deferral rate:
                ``[(100, 3), (50, 2)]`` is "100% of the first 3% of pay deferred plus 50% of the
                next 2%" (4% of pay at a 5% or higher deferral). Keyword-only.
            match_on_bonus (bool, optional): Whether plan pay includes the bonus. When True both the
                deferral percentages and the match tiers apply to salary + bonus; when False
                (default) to base salary only. Keyword-only.
            match_vesting_years (int, optional): Cliff vesting for employer money: the match vests
                after this many years of service at the job, and unvested match is forfeited when the
                job ends before then. 0 (default) means immediately vested. Keyword-only.
        """
        # Balance is derived from pretax + roth; grow via average_growth (annual compounding).
        super().__init__(job.owner, growth_rate=average_growth)
        self.job: Job | None = job
        self.pretax_balance = pretax_balance
        self.roth_balance = roth_balance
        self.pretax_contrib_percent = pretax_contrib_percent
        self.roth_contrib_percent = roth_contrib_percent
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
        if match_vesting_years < 0:
            raise ValueError("match_vesting_years must be >= 0")
        self.match_vesting_years = match_vesting_years
        # Employer match (with its growth) not yet vested; part of pretax_balance. See vest_match.
        self.unvested_match = 0.0

        self.stat_required_min_distrib = 0
        self.stat_401k_balance = 0

        job.retirement_account = self
        self.model.registries.job_401k_accounts.register(job.owner, self)

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
        return self.pretax_balance + self.roth_balance

    @balance.setter
    def balance(self, value):
        # Balance is derived; never silently discard a write (fixes the silent-discard bug).
        raise AttributeError(
            "Job401kAccount.balance is derived from pretax_balance + roth_balance; "
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

        if amount > 0 and self.roth_balance > 0:
            roth_withdrawn = min(self.roth_balance, amount)
            self.roth_balance -= roth_withdrawn
            total_withdrawn += roth_withdrawn

        return total_withdrawn

    def _repr_html_(self):
        company = self.job.company if self.job is not None else "<None>"
        return f"401k at {company} balance: ${self.balance:,}"

    def apply_growth(self):
        """Grow the pre-tax and roth sub-balances with annual compounding (APY).

        Uses the same annual-compounding growth as every other ``Investment`` so accounts with the
        same nominal rate grow identically.
        """
        rate = self.growth_rate / 100
        pretax_growth = self.pretax_balance * rate
        roth_growth = self.roth_balance * rate
        self.pretax_balance += pretax_growth
        self.roth_balance += roth_growth
        self.unvested_match = min(self.unvested_match * (1 + rate), self.pretax_balance)
        growth = pretax_growth + roth_growth
        self.stat_growth_history.append(growth)
        return growth

    def pre_step(self):
        # RMD from the prior year-end balance, before Social Security computes provisional income.
        self._take_required_min_distribution()

    def step(self):
        # After the job deposited this year's contributions in pre_step, so contributions land
        # before growth. RetirementAccount.step applies growth and tracks balance/useable history.
        super().step()
        self.stat_401k_balance = self.balance

    def _take_required_min_distribution(self):
        """Force-withdraw the required minimum distribution (pre-tax, ordinary income, no FICA)."""
        config = self.person.model.config
        birth_year = self.person.model.year - self.person.age
        start_age = rmd_start_age(birth_year, config=config, year=self.person.model.year)
        required_min_dist_amount = self.deduct_pretax(
            required_min_distrib(self.person.age, self.pretax_balance, config=config, start_age=start_age)
        )
        self.person.deposit_into_bank_account(required_min_dist_amount)
        # RMDs are ordinary income, not FICA wages.
        self.person.income.add(IncomeType.PRETAX_DISTRIBUTION, required_min_dist_amount)
        self.stat_required_min_distrib = required_min_dist_amount

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
        """Deduct from roth balance

        Args:
            amount (float): Amount to deduct.

        Returns:
            float: Amount deducted. Will not be less than the account balance.
        """
        amount_deducted = min(self.roth_balance, amount)
        self.roth_balance -= amount_deducted
        return amount_deducted
