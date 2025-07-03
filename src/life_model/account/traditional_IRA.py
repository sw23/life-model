# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from ..people.person import Person
from ..base_classes import Investment


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
