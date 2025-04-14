# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from ...model import LifeModelAgent, continuous_interest
from ...person import Person


class IraAccount(LifeModelAgent):
    """
    Base class for IRA accounts. Both Traditional and Roth IRAs
    inherit from this class.
    """
    # 2023 IRA contribution limits (will need updates over time)
    CONTRIBUTION_LIMIT = 6500
    CONTRIBUTION_LIMIT_AGE_50_PLUS = 7500
    AGE_LIMIT_FOR_EXTRA = 50

    def __init__(self, owner: Person,
                 balance: float = 0,
                 yearly_contrib_amount: float = 0,
                 average_growth: float = 5):
        """IRA Account Base Class

        Args:
            owner (Person): Person who owns the IRA.
            balance (float, optional): Initial balance of account. Defaults to 0.
            yearly_contrib_amount (float, optional): Yearly contribution amount. Defaults to 0.
            average_growth (float, optional): Average account growth rate as percentage. Defaults to 5.
        """
        super().__init__(owner.model)
        self.owner = owner
        self.balance = balance
        self.yearly_contrib_amount = yearly_contrib_amount
        self.average_growth = average_growth

        # Statistics
        self.stat_balance_history = []
        self.stat_useable_balance = 0
        self.stat_required_min_distrib = 0
        self.stat_401k_balance = 0  # Track with 401k balance for stats purposes

    @property
    def contribution_limit(self) -> float:
        """Get the current contribution limit based on owner's age."""
        if self.owner.age >= self.AGE_LIMIT_FOR_EXTRA:
            return self.CONTRIBUTION_LIMIT_AGE_50_PLUS
        return self.CONTRIBUTION_LIMIT

    def apply_growth(self):
        """Apply investment growth to the account."""
        self.balance += continuous_interest(self.balance, self.average_growth)

    def contribute(self) -> float:
        """Make yearly contribution to the account.

        Returns:
            float: The amount actually contributed (may be limited by contribution limits)
        """
        # Limit contribution to the legal maximum
        actual_contribution = min(self.yearly_contrib_amount, self.contribution_limit)

        # Attempt to deduct from bank accounts
        remainder = self.owner.deduct_from_bank_accounts(actual_contribution)
        actual_contribution -= remainder

        # Add the contribution to the balance
        self.balance += actual_contribution
        return actual_contribution

    def deduct(self, amount: float) -> float:
        """Deduct from the balance.

        Args:
            amount (float): Amount to deduct.

        Returns:
            float: Amount actually deducted (won't exceed balance).
        """
        amount_deducted = min(self.balance, amount)
        self.balance -= amount_deducted
        return amount_deducted

    def is_early_withdrawal(self) -> bool:
        """Determine if a withdrawal would be considered early.

        Returns:
            bool: True if the owner is under 59.5 years old, False otherwise.
        """
        return self.owner.age < 59.5

    def _repr_html_(self):
        return f"IRA balance: ${self.balance:,.2f}"
