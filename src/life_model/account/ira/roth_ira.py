# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from .ira_account import IraAccount
from ...person import Person


class RothIra(IraAccount):
    """
    Roth IRA implementation.

    Key characteristics:
    - Contributions are made with after-tax dollars (no tax deduction)
    - Growth is tax-free
    - Qualified withdrawals are tax-free
    - Not subject to Required Minimum Distributions (RMDs)
    - Contributions (but not earnings) can be withdrawn at any time without penalty
    - Early withdrawal of earnings (before 59.5) may incur a 10% penalty
    """

    def __init__(self, owner: Person,
                 balance: float = 0,
                 yearly_contrib_amount: float = 0,
                 average_growth: float = 5):
        """Roth IRA Account

        Args:
            owner (Person): Person who owns the IRA.
            balance (float, optional): Initial balance of account. Defaults to 0.
            yearly_contrib_amount (float, optional): Yearly contribution amount. Defaults to 0.
            average_growth (float, optional): Average account growth rate as percentage. Defaults to 5.
        """
        super().__init__(owner, balance, yearly_contrib_amount, average_growth)
        # Track the owner's IRAs
        if not hasattr(owner, 'ira_accounts'):
            owner.ira_accounts = []
        owner.ira_accounts.append(self)

        # Track contributions separately for withdrawal rules
        self.total_contributions = 0

    def pre_step(self):
        """Pre-step phase, called for all agents before step phase."""
        # Apply investment growth
        self.apply_growth()

        # Make yearly contribution if under contribution limit
        contribution_amount = self.contribute()
        if contribution_amount > 0:
            self.total_contributions += contribution_amount

        # Update statistics
        self.stat_balance_history.append(self.balance)
        self.stat_401k_balance = self.balance  # Report as part of 401k for overall retirement tracking
        if self.owner.age > 59.5:
            self.stat_useable_balance = self.balance

    def withdraw(self, amount: float) -> float:
        """Withdraw money from the Roth IRA.

        For Roth IRAs:
        1. Contributions can be withdrawn tax and penalty-free at any time
        2. Earnings can be withdrawn tax-free after 59.5, or with penalty before that

        Args:
            amount (float): Amount to withdraw.

        Returns:
            float: Amount actually withdrawn.
        """
        # First determine how much of the withdrawal is contribution vs earnings
        remaining_amount = amount
        amount_from_contributions = min(remaining_amount, self.total_contributions)
        remaining_amount -= amount_from_contributions
        amount_from_earnings = min(remaining_amount, self.balance - self.total_contributions)

        # Total withdrawal amount
        amount_withdrawn = amount_from_contributions + amount_from_earnings

        # Deduct from balance
        self.balance -= amount_withdrawn

        # Reduce tracked contributions
        self.total_contributions -= amount_from_contributions

        # Check if early withdrawal penalties apply
        is_early = self.is_early_withdrawal()
        if is_early and amount_from_earnings > 0:
            # Only earnings are subject to penalty for early withdrawal
            self.owner.early_withdrawal_amount += amount_from_earnings

        # Deposit into bank account
        self.owner.deposit_into_bank_account(amount_withdrawn)

        return amount_withdrawn

    def _repr_html_(self):
        return f"Roth IRA balance: ${self.balance:,.2f} (contributions: ${self.total_contributions:,.2f})"
