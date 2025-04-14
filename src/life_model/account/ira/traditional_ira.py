# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from ...limits import required_min_distrib
from .ira_account import IraAccount
from ...person import Person
from ...model import Event


class TraditionalIra(IraAccount):
    """
    Traditional IRA implementation.

    Key characteristics:
    - Contributions may be tax-deductible (reducing current year taxes)
    - Growth is tax-deferred
    - Withdrawals are taxed as income
    - Subject to Required Minimum Distributions (RMDs) after age 72
    - Early withdrawals (before 59.5) incur a 10% penalty
    """

    def __init__(self, owner: Person,
                 balance: float = 0,
                 yearly_contrib_amount: float = 0,
                 average_growth: float = 5):
        """Traditional IRA Account

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

    def pre_step(self):
        """Pre-step phase, called for all agents before step phase."""
        # Apply investment growth
        self.apply_growth()

        # Make yearly contribution if under contribution limit
        self.contribute()

        # Required minimum distributions after age 72
        if self.owner.age >= 72:
            required_min_dist_amount = self.deduct(required_min_distrib(self.owner.age, self.balance))
            if required_min_dist_amount > 0:
                self.owner.deposit_into_bank_account(required_min_dist_amount)
                self.owner.taxable_income += required_min_dist_amount
                self.stat_required_min_distrib = required_min_dist_amount

                # Add event for first RMD
                if self.owner.age == 72:
                    self.model.event_log.add(
                        Event(f"{self.owner.name} took first Required Minimum Distribution of "
                              f"${required_min_dist_amount:,.2f} from Traditional IRA")
                    )

        # Update statistics
        self.stat_balance_history.append(self.balance)
        self.stat_401k_balance = self.balance  # Report as part of 401k for overall retirement tracking
        if self.owner.age > 59.5:
            self.stat_useable_balance = self.balance

    def withdraw(self, amount: float) -> float:
        """Withdraw money from the Traditional IRA.

        Args:
            amount (float): Amount to withdraw.

        Returns:
            float: Amount actually withdrawn.
        """
        is_early = self.is_early_withdrawal()
        amount_withdrawn = self.deduct(amount)

        # Add to owner's taxable income
        self.owner.taxable_income += amount_withdrawn

        # Track early withdrawal penalty if applicable
        if is_early:
            self.owner.early_withdrawal_amount += amount_withdrawn

        # Deposit into bank account
        self.owner.deposit_into_bank_account(amount_withdrawn)

        return amount_withdrawn

    def _repr_html_(self):
        return f"Traditional IRA balance: ${self.balance:,.2f}"
