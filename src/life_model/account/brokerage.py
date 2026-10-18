# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html
from dataclasses import dataclass

from ..base_classes import Investment
from ..ledger import FlowKind
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
    #: Year the lot was acquired, which (with ``acquired_month``) fixes its holding period.
    acquired_year: int
    #: Month (1-12) the lot was acquired. A lot held 12 months or more is long-term.
    acquired_month: int = 1

    @property
    def gain(self) -> float:
        """Unrealized gain (negative when the lot is underwater)."""
        return self.value - self.cost_basis

    def months_held(self, year: int, month: int) -> int:
        """Whole months the lot has been held at ``(year, month)``."""
        return (year * 12 + month) - (self.acquired_year * 12 + self.acquired_month)


class BrokerageAccount(Investment):
    """A taxable brokerage account with FIFO cost-basis tracking.

    Every credit to the account creates a :class:`TaxLot`; withdrawals consume lots oldest-first
    (FIFO, the IRS default when no other method is elected) and post the realized gain to the
    owner's income ledger, classified long- or short-term by how long the lot was held. Growth
    accrues to lots pro rata by value and is untaxed until a sale — the realization principle.

    Specific-identification lot selection is not modeled (it needs a per-sale optimizer), and
    wash-sale disallowance (§1091) is not modeled: any tax-loss-harvesting strategy evaluated on
    this model will overstate its benefit.

    Growth is monthly. Dividends (``dividend_yield``, carved out of the month's total return) are
    paid quarterly by default (``accounts.brokerage.dividend_frequency``) and reinvested as new lots;
    a lot held 12 months or more sells at a long-term gain.
    """

    def __init__(
        self,
        person: Person,
        company: str,
        balance: float = 0,
        growth_rate: float | None = None,
        *,
        dividend_yield: float | None = None,
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
        self._dividend_yield_override = dividend_yield
        # Basis is tracked per lot; an opening balance is treated as freshly purchased at cost.
        self.lots: list[TaxLot] = []
        if balance > 0:
            self.lots.append(self._lot(balance, balance))
        self.model.registries.brokerage_accounts.register(person, self)

    def _lot(self, value: float, cost_basis: float, acquired_year: int | None = None, acquired_month=None) -> TaxLot:
        """A lot acquired now (or in ``acquired_year``: in ``acquired_month``, else January of an
        earlier year / the current month of this year)."""
        if acquired_year is None:
            acquired_year = self.model.year
        if acquired_month is None:
            acquired_month = self.model.month if acquired_year == self.model.year else 1
        return TaxLot(value=value, cost_basis=cost_basis, acquired_year=acquired_year, acquired_month=acquired_month)

    def _is_long_term(self, lot: TaxLot) -> bool:
        return lot.months_held(self.model.year, self.model.month) >= 12

    @property
    def dividend_yield(self) -> float:
        """Annual qualified-dividend yield (percent): the explicit override, else the config default."""
        if self._dividend_yield_override is not None:
            return self._dividend_yield_override
        return self.model.config.accounts.brokerage.dividend_yield

    @dividend_yield.setter
    def dividend_yield(self, value: float | None) -> None:
        self._dividend_yield_override = value

    @property
    def cost_basis(self) -> float:
        """Total cost basis across all lots."""
        return sum(lot.cost_basis for lot in self.lots)

    @property
    def unrealized_gain(self) -> float:
        """Gain that would be realized if the whole account were sold today."""
        return self.balance - self.cost_basis

    @property
    def is_dividend_month(self) -> bool:
        """Whether dividends are paid this month (every month, or quarter ends)."""
        if self.model.config.accounts.brokerage.dividend_frequency == "monthly":
            return True
        return self.model.month % 3 == 0

    def apply_growth(self):
        """Grow the account by the month's return, splitting it into untaxed appreciation and taxable
        dividends in dividend months.

        The dividend slice is carved out of the total return rather than added to it, so total
        return is unchanged by ``dividend_yield`` — only the tax character of that slice changes.
        Price appreciation accrues to existing lots pro rata by value; the dividend (a quarter, or
        a twelfth, of the yield on the balance) is posted as qualified-dividend income and
        reinvested as a new full-basis lot, the reinvestment default.
        """
        payments = 12 if self.model.config.accounts.brokerage.dividend_frequency == "monthly" else 4
        dividend_rate = self.dividend_yield / payments if self.lots and self.is_dividend_month else 0.0
        dividend = self.balance * (dividend_rate / 100)
        appreciation = self.balance * ((self.monthly_growth_rate - dividend_rate) / 100)

        self._accrue_to_lots(appreciation)
        self.balance += appreciation
        self._post_growth(appreciation)

        if dividend > 0:
            self.person.income.add(IncomeType.QUALIFIED_DIVIDEND, dividend, source="dividend")
            self.deposit(dividend)
            self.model.ledger.post(
                dividend, FlowKind.DIVIDEND, to_account=self, source="dividends (reinvested)", agent=self.person
            )

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
        """Credit ``amount`` to the account as a new full-basis lot acquired this month.

        Every credit path must go through here: a bare ``balance +=`` would silently drive basis
        below balance and manufacture phantom taxable gain on the next sale.
        """
        if amount < 0:
            raise ValueError("Deposit amount cannot be negative")
        if amount == 0:
            return True
        self.balance += amount
        self.lots.append(self._lot(amount, amount))
        return True

    def deposit_with_basis(
        self,
        amount: float,
        cost_basis: float,
        acquired_year: int | None = None,
        acquired_month: int | None = None,
    ) -> None:
        """Credit ``amount`` as a lot with an explicit basis and acquisition date (default: now; a year
        without a month is January of an earlier year, or this month of the current one).

        Used where the transferred property carries a basis or holding period that differs from a
        fresh purchase (e.g. a basis step-up at death).
        """
        if amount <= 0:
            return
        self.balance += amount
        self.lots.append(self._lot(amount, cost_basis, acquired_year, acquired_month))

    def withdraw(self, amount: float) -> float:
        """Sell ``amount`` of the account, consuming lots FIFO and posting the realized gain.

        Each consumed lot's gain is classified long-term when the lot has been held 12 months or
        more and short-term otherwise, then posted to the owner's income ledger so the tax unit
        settles it at year end.

        Returns:
            float: Amount actually withdrawn.
        """
        withdrawn, long_term_gain, short_term_gain = self.sell(amount)
        if long_term_gain != 0:
            self.person.income.add(IncomeType.LONG_TERM_CAPITAL_GAIN, long_term_gain, source="brokerage_sale")
        if short_term_gain != 0:
            self.person.income.add(IncomeType.SHORT_TERM_CAPITAL_GAIN, short_term_gain, source="brokerage_sale")
        return withdrawn

    def sell(self, amount: float) -> tuple[float, float, float]:
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
            if self._is_long_term(lot):
                long_term_gain += gain
            else:
                short_term_gain += gain
            lot.value -= take
            lot.cost_basis -= basis_used
            remaining -= take
            if lot.value <= 0:
                self.lots.pop(0)

        return actual_withdrawal, long_term_gain, short_term_gain

    def transfer_long_term_in_kind(self, amount: float) -> float:
        """Give up to ``amount`` of long-term lots away in kind (a charitable gift of appreciated shares):
        the lots leave the account without a sale, so no gain is realized. The most appreciated lots (by
        gain per dollar) go first. Returns the market value transferred; nothing is posted (the caller
        posts the gift)."""
        if amount <= 0:
            return 0.0
        year = self.model.year
        candidates = sorted(
            (lot for lot in self.lots if year - lot.acquired_year >= 1 and lot.value > 0),
            key=lambda lot: -(lot.gain / lot.value),
        )
        remaining = amount
        for lot in candidates:
            if remaining <= 0:
                break
            take = min(remaining, lot.value)
            lot.cost_basis -= lot.cost_basis * (take / lot.value)
            lot.value -= take
            remaining -= take
        self.lots = [lot for lot in self.lots if lot.value > 1e-9]
        given = amount - remaining
        self.balance -= given
        return given

    def preview_gain(self, amount: float) -> tuple[float, float]:
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
            if self._is_long_term(lot):
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
        date below (twelve months ago) guarantees.
        """
        self.lots = []
        if self.balance > 0:
            self.lots.append(self._lot(self.balance, self.balance, self.model.year - 1, self.model.month))

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Company: {html.escape(self.company)}</li>"
        desc += f"<li>Balance: ${self.balance:,.2f}</li>"
        desc += f"<li>Cost Basis: ${self.cost_basis:,.2f}</li>"
        desc += f"<li>Growth Rate: {self.growth_rate}%</li>"
        desc += "</ul>"
        return desc
