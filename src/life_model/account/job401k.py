# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import TYPE_CHECKING, Optional

from ..base_classes import RetirementAccount
from ..limits import required_min_distrib, rmd_start_age
from ..model import compound_interest
from ..tax.income import IncomeType

if TYPE_CHECKING:
    from ..work.job import Job


class Job401kAccount(RetirementAccount):
    is_rmd_eligible = True

    def __init__(
        self,
        job: "Job",
        pretax_balance: float = 0,
        pretax_contrib_percent: float = 0,
        roth_balance: float = 0,
        roth_contrib_percent: float = 0,
        average_growth: float = 0,
        company_match_percent: float = 0,
    ):
        """401k Account

        Args:
            job (Job): Job offering the 401k plan.
            pretax_balance (float, optional): Initial pre-tax balance of account. Defaults to 0.
            pretax_contrib_percent (float, optional): Pre-tax contribution percentage. Defaults to 0.
            roth_balance (float, optional): Initial roth balance of account. Defaults to 0.
            roth_contrib_percent (float, optional): Roth contribution percentage. Defaults to 0.
            average_growth (float, optional): Average account growth every year. Defaults to 0.
            company_match_percent (float, optional): Percentage that company matches contributions. Defaults to 0.
        """
        # Balance is derived from pretax + roth; grow via average_growth (annual compounding).
        super().__init__(job.owner, growth_rate=average_growth)
        self.job: Optional["Job"] = job
        self.pretax_balance = pretax_balance
        self.roth_balance = roth_balance
        self.pretax_contrib_percent = pretax_contrib_percent
        self.roth_contrib_percent = roth_contrib_percent
        self.average_growth = average_growth
        self.company_match_percent = company_match_percent

        self.stat_required_min_distrib = 0
        self.stat_401k_balance = 0

        job.retirement_account = self

    def pretax_contrib(self, salary: float):
        return salary * (self.pretax_contrib_percent / 100)

    def roth_contrib(self, salary: float):
        return salary * (self.roth_contrib_percent / 100)

    def company_match(self, contribution: float):
        return contribution * (self.company_match_percent / 100)

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
        pretax_growth = compound_interest(self.pretax_balance, self.growth_rate, 1, 1)
        roth_growth = compound_interest(self.roth_balance, self.growth_rate, 1, 1)
        self.pretax_balance += pretax_growth
        self.roth_balance += roth_growth
        growth = pretax_growth + roth_growth
        self.stat_growth_history.append(growth)
        return growth

    def step(self):
        # Runs in the step phase before tax-unit settlement (Investment priority -10), and after
        # the job deposits this year's contributions in pre_step, so contributions land before
        # growth. RetirementAccount.step applies growth and tracks balance/useable history.
        super().step()
        self._take_required_min_distribution()
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
