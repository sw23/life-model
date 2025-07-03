# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from ..people.person import Person
from ..base_classes import Investment


class BrokerageAccount(Investment):
    def __init__(self, person: Person, company: str,
                 balance: float = 0, growth_rate: float = 7.0):
        """ Models a brokerage/investment account

        Args:
            person: The person who owns this account
            company: Brokerage company name
            balance: Current account balance
            growth_rate: Expected annual growth rate percentage
        """
        super().__init__(person, balance, growth_rate)
        self.company = company
        self.investments = []  # List of individual investments

    def calculate_growth(self) -> float:
        """Calculate investment growth based on growth rate"""
        return self.balance * (self.growth_rate / 100)

    def get_balance(self) -> float:
        return self.balance

    def deposit(self, amount: float) -> bool:
        self.balance += amount
        return True

    def withdraw(self, amount: float) -> float:
        actual_withdrawal = min(amount, self.balance)
        self.balance -= actual_withdrawal
        return actual_withdrawal

    def _repr_html_(self):
        desc = '<ul>'
        desc += f'<li>Company: {self.company}</li>'
        desc += f'<li>Balance: ${self.balance:,.2f}</li>'
        desc += f'<li>Growth Rate: {self.growth_rate}%</li>'
        desc += '</ul>'
        return desc
