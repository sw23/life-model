# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..base_classes import Investment
from ..people.person import Person
from ..tax.income import IncomeType


@dataclass
class TaxLot:
    """One acquisition of value in a taxable account, tracked for basis and holding period.

    Lots are denominated in dollars of current market value (``value``) rather than share counts —
    the model has no share price — with ``cost_basis`` recording what was paid. Growth raises
    ``value`` and leaves ``cost_basis`` alone, so the unrealized gain is the difference.
    """

    #: Current market value of the lot.
    value: float
    #: What was paid for the lot; the untaxed portion of a sale.
    cost_basis: float
    #: Simulated year the lot was acquired, which fixes its holding period.
    acquired_year: int

    @property
    def gain(self) -> float:
        """Unrealized gain (negative when the lot is underwater)."""
        return self.value - self.cost_basis


class BrokerageAccount(Investment):
    """A taxable brokerage account with FIFO cost-basis tracking.

    Every credit to the account creates a :class:`TaxLot`; withdrawals consume lots oldest-first
    (FIFO, the IRS default when no other method is elected) and post the realized gain to the
    owner's income ledger, classified long- or short-term by how long the lot was held. Growth
    accrues to lots pro rata by value and is untaxed until a sale — the realization principle.

    Specific-identification lot selection is not modeled (it needs a per-sale optimizer), and
    wash-sale disallowance (§1091) is structurally unrepresentable at year granularity: any
    tax-loss-harvesting strategy evaluated on this model will overstate its benefit.
    """

    def __init__(
        self,
        person: Person,
        company: str,
        balance: float = 0,
        growth_rate: Optional[float] = None,
        *,
        dividend_yield: Optional[float] = None,
    ):
        """Models a brokerage/investment account

        Args:
            person: The person who owns this account
            company: Brokerage company name
            balance: Current account balance. Seeded as a single lot with basis equal to the
                balance and acquired in the model's start year, i.e. an account opened with no
                embedded gain.
            growth_rate: Expected annual growth rate percentage. Defers to the economy's equity
                return when None.
            dividend_yield: Percentage of the balance paid out as qualified dividends each year,
                carved *out of* ``growth_rate`` rather than added on top. Defers to the config
                default when None.
        """
        super().__init__(person, balance, growth_rate)
        self.company = company
        self.investments: List = []  # List of individual investments
        self._dividend_yield_override = dividend_yield
        # Basis is tracked per lot; an opening balance is treated as freshly purchased at cost.
        self.lots: List[TaxLot] = []
        if balance > 0:
            self.lots.append(TaxLot(value=balance, cost_basis=balance, acquired_year=self.model.year))

    @property
    def dividend_yield(self) -> float:
        """Annual qualified-dividend yield (percent): the explicit override, else the config default."""
        if self._dividend_yield_override is not None:
            return self._dividend_yield_override
        return self.model.config.accounts.brokerage.dividend_yield

    @dividend_yield.setter
    def dividend_yield(self, value: Optional[float]) -> None:
        self._dividend_yield_override = value

    @property
    def cost_basis(self) -> float:
        """Total cost basis across all lots."""
        return sum(lot.cost_basis for lot in self.lots)

    @property
    def unrealized_gain(self) -> float:
        """Gain that would be realized if the whole account were sold today."""
        return self.balance - self.cost_basis

    def calculate_growth(self) -> float:
        """Calculate investment growth based on growth rate"""
        return self.balance * (self.growth_rate / 100)

    def get_balance(self) -> float:
        return self.balance

    def apply_growth(self):
        """Grow the account, splitting the return into untaxed appreciation and taxable dividends.

        The dividend slice is carved out of the total return rather than added to it, so total
        return is unchanged by ``dividend_yield`` — only the tax character of that slice changes.
        Price appreciation accrues to existing lots pro rata by value; the dividend is posted as
        qualified-dividend income and reinvested as a new full-basis lot, the reinvestment default.
        """
        dividend_rate = self.dividend_yield if self.lots else 0.0
        dividend = self.balance * (dividend_rate / 100)
        appreciation = self.balance * ((self.growth_rate - dividend_rate) / 100)

        self._accrue_to_lots(appreciation)
        self.balance += appreciation

        if dividend > 0:
            self.person.income.add(IncomeType.QUALIFIED_DIVIDEND, dividend)
            self.deposit(dividend)

        growth = appreciation + dividend
        self.stat_growth_history.append(growth)
        return growth

    def _accrue_to_lots(self, amount: float) -> None:
        """Spread ``amount`` of appreciation across lots in proportion to their current value."""
        total = sum(lot.value for lot in self.lots)
        if total <= 0:
            return
        for lot in self.lots:
            lot.value += amount * (lot.value / total)

    def deposit(self, amount: float) -> bool:
        """Credit ``amount`` to the account as a new full-basis lot acquired this year.

        Every credit path must go through here: a bare ``balance +=`` would silently drive basis
        below balance and manufacture phantom taxable gain on the next sale.
        """
        if amount < 0:
            raise ValueError("Deposit amount cannot be negative")
        if amount == 0:
            return True
        self.balance += amount
        self.lots.append(TaxLot(value=amount, cost_basis=amount, acquired_year=self.model.year))
        return True

    def deposit_with_basis(self, amount: float, cost_basis: float, acquired_year: Optional[int] = None) -> None:
        """Credit ``amount`` as a lot with an explicit basis and acquisition year.

        Used where the transferred property carries a basis or holding period that differs from a
        fresh purchase (e.g. a basis step-up at death).
        """
        if amount <= 0:
            return
        self.balance += amount
        self.lots.append(
            TaxLot(
                value=amount,
                cost_basis=cost_basis,
                acquired_year=self.model.year if acquired_year is None else acquired_year,
            )
        )

    def withdraw(self, amount: float) -> float:
        """Sell ``amount`` of the account, consuming lots FIFO and posting the realized gain.

        Each consumed lot's gain is classified long-term when it was acquired in an earlier
        simulated year and short-term otherwise, then posted to the owner's income ledger so the
        tax unit settles it at year end.

        Returns:
            float: Amount actually withdrawn.
        """
        withdrawn, long_term_gain, short_term_gain = self.sell(amount)
        if long_term_gain != 0:
            self.person.income.add(IncomeType.LONG_TERM_CAPITAL_GAIN, long_term_gain)
        if short_term_gain != 0:
            self.person.income.add(IncomeType.SHORT_TERM_CAPITAL_GAIN, short_term_gain)
        return withdrawn

    def sell(self, amount: float) -> Tuple[float, float, float]:
        """Consume lots FIFO for ``amount`` without posting anything to the income ledger.

        Returns:
            tuple: ``(withdrawn, long_term_gain, short_term_gain)``. Gains may be negative when
            lots are sold at a loss.
        """
        if amount < 0:
            return 0.0, 0.0, 0.0  # Cannot withdraw negative amounts
        actual_withdrawal = min(amount, self.balance)
        self.balance -= actual_withdrawal

        remaining = actual_withdrawal
        long_term_gain = 0.0
        short_term_gain = 0.0
        while remaining > 0 and self.lots:
            lot = self.lots[0]
            take = min(remaining, lot.value)
            # Basis is consumed in the same proportion as value, so a partial sale of a lot
            # realizes a proportional slice of its gain and leaves the rest embedded.
            basis_used = lot.cost_basis * (take / lot.value) if lot.value > 0 else lot.cost_basis
            gain = take - basis_used
            if self.model.year - lot.acquired_year >= 1:
                long_term_gain += gain
            else:
                short_term_gain += gain
            lot.value -= take
            lot.cost_basis -= basis_used
            remaining -= take
            if lot.value <= 0:
                self.lots.pop(0)

        return actual_withdrawal, long_term_gain, short_term_gain

    def preview_gain(self, amount: float) -> Tuple[float, float]:
        """Preview the gains selling ``amount`` would realize, WITHOUT mutating any lots.

        Walks the same FIFO path as :meth:`sell` but consumes nothing, returning
        ``(long_term_gain, short_term_gain)``. The settlement solver uses this to size a
        brokerage draw — and the capital-gains tax that draw itself triggers — before committing
        the sale, so the account is sold exactly once.
        """
        if amount <= 0:
            return 0.0, 0.0
        remaining = min(amount, self.balance)
        long_term_gain = 0.0
        short_term_gain = 0.0
        for lot in self.lots:
            if remaining <= 0:
                break
            take = min(remaining, lot.value)
            basis_used = lot.cost_basis * (take / lot.value) if lot.value > 0 else lot.cost_basis
            gain = take - basis_used
            if self.model.year - lot.acquired_year >= 1:
                long_term_gain += gain
            else:
                short_term_gain += gain
            remaining -= take
        return long_term_gain, short_term_gain

    def step_up_basis_at_death(self) -> None:
        """Reset basis to fair market value at the owner's death (IRC §1014).

        The lots collapse to a single lot with basis equal to the current balance, so gains that
        accrued during the decedent's lifetime are never taxed to the heir. Inherited property is
        long-term regardless of how long anyone actually held it, which the sentinel acquisition
        year below guarantees.
        """
        self.lots = []
        if self.balance > 0:
            self.lots.append(TaxLot(value=self.balance, cost_basis=self.balance, acquired_year=self.model.year - 1))

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Company: {html.escape(self.company)}</li>"
        desc += f"<li>Balance: ${self.balance:,.2f}</li>"
        desc += f"<li>Cost Basis: ${self.cost_basis:,.2f}</li>"
        desc += f"<li>Growth Rate: {self.growth_rate}%</li>"
        desc += "</ul>"
        return desc
