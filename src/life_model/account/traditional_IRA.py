# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from ..people.person import Person
from ..base_classes import Investment
from ..model import compound_interest


class TraditionalIRA(Investment):
    def __init__(self, person: Person, balance: float = 0, growth_rate: float = 7.0,
                 contribution_limit: float = 6500):
        """ Models a Traditional IRA account for a person

        Args:
            person: The person to which this IRA belongs
            balance: Current balance in the IRA
            growth_rate: Expected annual growth rate percentage
            contribution_limit: Annual contribution limit
        """
        super().__init__(person, balance, growth_rate)
        self.contribution_limit = contribution_limit
        self.contributions_this_year = 0

    def contribute(self, amount: float) -> float:
        """Make a contribution to the IRA

        Args:
            amount: Amount to contribute

        Returns:
            Amount actually contributed (limited by contribution limit)
        """
        available_limit = self.contribution_limit - self.contributions_this_year
        actual_contribution = min(amount, available_limit)

        if actual_contribution > 0:
            self.balance += actual_contribution
            self.contributions_this_year += actual_contribution

        return actual_contribution

    def get_balance(self) -> float:
        """Get current account balance"""
        return self.balance

    def deposit(self, amount: float) -> bool:
        """Deposit amount into account. Returns success status"""
        if amount <= 0:
            return False
        contribution = self.contribute(amount)
        return contribution > 0

    def withdraw(self, amount: float) -> float:
        """Withdraw amount from account. Returns actual amount withdrawn"""
        if amount <= 0:
            return 0.0
        # Traditional IRA withdrawals may have penalties, but for simplicity
        # we'll just allow withdrawals up to the balance
        amount_withdrawn = min(self.balance, amount)
        self.balance -= amount_withdrawn
        return amount_withdrawn

    def calculate_growth(self) -> float:
        """Calculate investment growth for the period"""
        return compound_interest(self.balance, self.growth_rate, 1, 1)

    def reset_annual_contributions(self):
        """Reset annual contribution tracking (called at year end)"""
        self.contributions_this_year = 0

    def _repr_html_(self):
        desc = '<ul>'
        desc += f'<li>Balance: ${self.balance:,.2f}</li>'
        desc += f'<li>Growth Rate: {self.growth_rate}%</li>'
        desc += f'<li>Contribution Limit: ${self.contribution_limit:,.2f}</li>'
        desc += f'<li>Contributions This Year: ${self.contributions_this_year:,.2f}</li>'
        desc += '</ul>'
        return desc
