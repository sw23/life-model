# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import Optional, TYPE_CHECKING
from ..model import LifeModelAgent, continuous_interest, Event
from ..limits import federal_retirement_age, required_min_distrib

if TYPE_CHECKING:
    from ..job import Job


class Job401kAccount(LifeModelAgent):
    def __init__(self, job: 'Job',
                 pretax_balance: float = 0, pretax_contrib_percent: float = 0,
                 roth_balance: float = 0, roth_contrib_percent: float = 0,
                 average_growth: float = 0, company_match_percent: float = 0):
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
        super().__init__(job.model)
        self.job: Optional['Job'] = job
        self.owner = job.owner
        self.pretax_balance = pretax_balance
        self.pretax_contrib_percent = pretax_contrib_percent
        self.roth_balance = roth_balance
        self.roth_contrib_percent = roth_contrib_percent
        self.average_growth = average_growth
        self.company_match_percent = company_match_percent

        self.stat_balance_history = []
        self.stat_useable_balance = 0
        self.stat_required_min_distrib = 0
        self.stat_401k_balance = 0
        self.stat_early_withdrawal_penalty = 0  # Track early withdrawal penalties

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

    def _repr_html_(self):
        company = self.job.company if self.job is not None else "<None>"
        return f"401k at {company} balance: ${self.balance:,}"

    # Using pre_step() so taxable_income will be set before person's step() is called
    def pre_step(self):
        # Note: Contributions are handled by job, after this is called.
        # This isn't 100% accurate since contributions aren't included in the
        # growth, which is a little pessimistic but that should be fine.

        self.pretax_balance += continuous_interest(self.pretax_balance, self.average_growth)
        self.roth_balance += continuous_interest(self.roth_balance, self.average_growth)

        self.stat_balance_history.append(self.balance)
        if (self.owner.age > federal_retirement_age()):
            self.stat_useable_balance = self.balance

        # Required minimum distributions
        # - Based on the owner's age, force withdraw the required minium
        required_min_dist_amount = self.deduct_pretax(required_min_distrib(self.owner.age, self.pretax_balance))
        self.owner.deposit_into_bank_account(required_min_dist_amount)
        self.owner.taxable_income += required_min_dist_amount

        self.stat_required_min_distrib = required_min_dist_amount
        self.stat_401k_balance = self.balance

    def deduct_pretax(self, amount: float, is_early_withdrawal: bool = None):
        """Deduct from pre-tax balance

        Args:
            amount (float): Amount to deduct.
            is_early_withdrawal (bool, optional): Whether this is an early withdrawal (before age 59.5).
                If None, automatically determined based on owner's age. Defaults to None.

        Returns:
            float: Amount deducted. Will not be more than the account balance.
        """
        # Check if this is an early withdrawal (if not explicitly specified)
        if is_early_withdrawal is None:
            is_early_withdrawal = self.is_early_withdrawal()

        amount_deducted = min(self.pretax_balance, amount)
        self.pretax_balance -= amount_deducted

        # Apply early withdrawal penalty if applicable (10% of withdrawal amount)
        if is_early_withdrawal and amount_deducted > 0:
            penalty = amount_deducted * 0.1  # 10% penalty
            self.stat_early_withdrawal_penalty += penalty

            # Add penalty to owner's tax liability
            if hasattr(self.owner, 'early_withdrawal_penalty'):
                self.owner.early_withdrawal_penalty += penalty
            else:
                self.owner.early_withdrawal_penalty = penalty

            # Log an event for the early withdrawal
            self.model.event_log.add(
                Event(f"{self.owner.name} took early withdrawal of ${amount_deducted:,.2f} "
                      f"from 401k, with penalty of ${penalty:,.2f}")
            )

        return amount_deducted

    def deduct_roth(self, amount: float, is_early_withdrawal: bool = None) -> float:
        """Deduct from roth balance

        Args:
            amount (float): Amount to deduct.
            is_early_withdrawal (bool, optional): Whether this is an early withdrawal (before age 59.5).
                If None, automatically determined based on owner's age. Defaults to None.

        Returns:
            float: Amount deducted. Will not be more than the account balance.
        """
        # For Roth 401k:
        # - Contributions can always be withdrawn tax and penalty-free
        # - Earnings withdrawn before 59.5 may be subject to taxes and penalties

        # Simplification: Since we don't track contributions vs. earnings separately,
        # we'll treat all early withdrawals from Roth 401k as earnings
        # (this is conservative but could be enhanced in future versions)

        # Check if this is an early withdrawal (if not explicitly specified)
        if is_early_withdrawal is None:
            is_early_withdrawal = self.is_early_withdrawal()

        amount_deducted = min(self.roth_balance, amount)
        self.roth_balance -= amount_deducted

        # Apply early withdrawal penalty if applicable (10% of withdrawal amount)
        if is_early_withdrawal and amount_deducted > 0:
            penalty = amount_deducted * 0.1  # 10% penalty
            self.stat_early_withdrawal_penalty += penalty

            # Add penalty to owner's tax liability
            if hasattr(self.owner, 'early_withdrawal_penalty'):
                self.owner.early_withdrawal_penalty += penalty
            else:
                self.owner.early_withdrawal_penalty = penalty

            # Log an event for the early withdrawal
            self.model.event_log.add(
                Event(f"{self.owner.name} took early withdrawal of ${amount_deducted:,.2f} "
                      f"from Roth 401k, with penalty of ${penalty:,.2f}")
            )

        return amount_deducted

    def is_early_withdrawal(self) -> bool:
        """Determine if a withdrawal would be considered early.

        Returns:
            bool: True if the owner is under 59.5 years old, False otherwise.
        """
        return self.owner.age < 59.5

    def withdraw(self, amount: float, from_roth_first: bool = True) -> float:
        """Withdraw money from the 401k account, optionally prioritizing Roth or pre-tax funds.

        Args:
            amount (float): Amount to withdraw.
            from_roth_first (bool, optional): Whether to withdraw from Roth balance first.
                Defaults to True, as Roth withdrawals are generally more tax-advantaged.

        Returns:
            float: Total amount actually withdrawn.
        """
        is_early = self.is_early_withdrawal()
        amount_withdrawn = 0

        if from_roth_first:
            # First try to withdraw from Roth
            roth_amount = self.deduct_roth(amount, is_early_withdrawal=is_early)
            amount_withdrawn += roth_amount

            # If more is needed, withdraw from pre-tax
            if amount_withdrawn < amount:
                remaining = amount - amount_withdrawn
                pretax_amount = self.deduct_pretax(remaining, is_early_withdrawal=is_early)
                amount_withdrawn += pretax_amount

                # Pre-tax withdrawals are taxable income
                self.owner.taxable_income += pretax_amount
        else:
            # First try to withdraw from pre-tax
            pretax_amount = self.deduct_pretax(amount, is_early_withdrawal=is_early)
            amount_withdrawn += pretax_amount

            # Pre-tax withdrawals are taxable income
            self.owner.taxable_income += pretax_amount

            # If more is needed, withdraw from Roth
            if amount_withdrawn < amount:
                remaining = amount - amount_withdrawn
                roth_amount = self.deduct_roth(remaining, is_early_withdrawal=is_early)
                amount_withdrawn += roth_amount

        # Deposit withdrawn amount to bank account
        self.owner.deposit_into_bank_account(amount_withdrawn)

        return amount_withdrawn
