# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html
from typing import Optional

from ..base_classes import Investment
from ..people.person import Person


class BrokerageAccount(Investment):
    def __init__(self, person: Person, company: str, balance: float = 0, growth_rate: Optional[float] = None):
        """Models a taxable brokerage/investment account.

        Cost basis is tracked on an average-cost basis: an opening balance is assumed to be entirely
        basis (no embedded gain), deposits add to basis dollar-for-dollar, growth accrues as
        unrealized gain, and a sale realizes a proportional share of the embedded gain as a
        long-term capital gain (reported to the owner's income ledger via :meth:`sell`).

        Args:
            person: The person who owns this account
            company: Brokerage company name
            balance: Current account balance
            growth_rate: Expected annual growth rate percentage. Uses configured default if None.
        """
        if growth_rate is None:
            growth_rate = person.model.config.accounts.brokerage.default_growth_rate
        super().__init__(person, balance, growth_rate)
        self.company = company
        # Average-cost basis: an opening balance is treated as fully basis (no embedded gain).
        self.cost_basis = float(balance)
        self.model.registries.brokerage_accounts.register(person, self)

    @property
    def unrealized_gain(self) -> float:
        """Balance in excess of cost basis (unrealized capital gain)."""
        return max(0.0, self.balance - self.cost_basis)

    def deposit(self, amount: float) -> bool:
        """Deposit cash, adding dollar-for-dollar to cost basis."""
        result = super().deposit(amount)
        if amount > 0:
            self.cost_basis += amount
        return result

    def withdraw(self, amount: float) -> float:
        """Withdraw cash, reducing cost basis proportionally (average-cost).

        The realized gain is *not* reported to the ledger here; use :meth:`sell` when the
        withdrawal should be taxed.
        """
        if amount <= 0 or self.balance <= 0:
            return super().withdraw(amount)
        basis_fraction = self.cost_basis / self.balance
        withdrawn = super().withdraw(amount)
        self.cost_basis -= withdrawn * basis_fraction
        return withdrawn

    def gain_fraction(self) -> float:
        """Fraction of a sale that would be realized as taxable gain (0 if no embedded gain)."""
        if self.balance <= 0:
            return 0.0
        return self.unrealized_gain / self.balance

    def sell(self, amount: float) -> float:
        """Sell (withdraw) ``amount``, realizing the proportional gain as a long-term capital gain.

        The realized gain is added to the owner's income ledger so it is taxed. Returns the cash
        proceeds.
        """
        from ..tax.income import IncomeType

        if amount <= 0 or self.balance <= 0:
            return 0.0
        gain = min(amount, self.balance) * self.gain_fraction()
        proceeds = self.withdraw(amount)
        if gain > 0:
            self.person.income.add(IncomeType.LONG_TERM_CAPITAL_GAINS, gain)
        return proceeds

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Company: {html.escape(self.company)}</li>"
        desc += f"<li>Balance: ${self.balance:,.2f}</li>"
        desc += f"<li>Cost Basis: ${self.cost_basis:,.2f}</li>"
        desc += f"<li>Growth Rate: {self.growth_rate}%</li>"
        desc += "</ul>"
        return desc
