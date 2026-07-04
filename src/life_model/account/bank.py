# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import html
from typing import Optional

from ..base_classes import FinancialAccount
from ..model import compound_interest
from ..people.person import Person


class BankAccount(FinancialAccount):
    def __init__(
        self, owner: Person, company: str, type: str = "Bank", balance: float = 0, interest_rate: Optional[float] = None
    ):
        """Class modeling bank accounts

        Args:
            owner (Person): Person that owns the Bank Account.
            company (str): Company at which the bank account belongs.
            type (str, optional): Type of account. Defaults to 'Bank'.
            balance (float, optional): Balance of account. Defaults to 0.
            interest_rate (float, optional): Interest rate. Uses configured default if None.
        """
        super().__init__(owner, balance)
        self.company = company
        self.type = type
        bank_config = self.model.config.accounts.bank
        # An explicit interest_rate overrides the economy (back-compat); None defers to the
        # economy's cash yield, re-read each year.
        self._interest_rate_override = interest_rate
        self.compound_rate = bank_config.compound_rate

        self.stat_total_interest = 0
        self.stat_useable_balance = 0

        # Register with the model registry
        self.model.registries.bank_accounts.register(owner, self)

    @property
    def interest_rate(self) -> float:
        """Annual interest rate (percent): the explicit override if set, else the economy's yield."""
        if self._interest_rate_override is not None:
            return self._interest_rate_override
        return self.model.economy.cash_yield(self.model.year)

    @interest_rate.setter
    def interest_rate(self, value: Optional[float]) -> None:
        self._interest_rate_override = value

    def get_balance(self) -> float:
        """Get current account balance"""
        return self.balance

    def deposit(self, amount: float) -> bool:
        """Deposit amount into account. Returns success status"""
        if amount <= 0:
            return False
        self.balance += amount
        return True

    def withdraw(self, amount: float) -> float:
        """Withdraw amount from account. Returns actual amount withdrawn"""
        if amount <= 0:
            return 0.0
        amount_withdrawn = min(self.balance, amount)
        self.balance -= amount_withdrawn
        return amount_withdrawn

    def _repr_html_(self):
        return f"{self.type} account at {html.escape(self.company)} balance: ${self.balance:,}"

    def step(self):
        # Apply interest
        interest = compound_interest(self.balance, self.interest_rate, self.compound_rate)
        self.balance += interest
        self.stat_total_interest += interest
        self.stat_useable_balance = self.balance

        # Call parent step method to track balance history
        super().step()
