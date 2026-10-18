# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""A home equity line of credit (Plan 27 D7): revolving debt secured by a home."""

import html
from typing import TYPE_CHECKING

from ..ledger import FlowKind
from .credit_card import PaymentStrategy, RevolvingDebt

if TYPE_CHECKING:
    from ..housing.home import Home
    from ..people.person import Person


class HomeEquityLine(RevolvingDebt):
    """A home equity line of credit secured by ``home``.

    Revolving debt with an interest-only payment by default (a draw period). Interest is deductible
    only on the part of the balance used to buy, build or substantially improve the home that secures
    it (acquisition debt, within the mortgage debt limit); interest on the rest (home-equity debt) is
    not deductible for years after 2017 (IRC §163(h)(3)(F)(i)(I); see
    :func:`~life_model.housing.home.qualified_residence_interest`). Draws for improvements
    (:meth:`draw` with ``for_improvements=True``, or ``improvement_balance`` at construction) are
    tracked; payments reduce the improvement part and the rest in proportion. The line is paid off
    from the proceeds when the home is sold.
    """

    REGISTRY = "home_equity_lines"

    def __init__(
        self,
        person: "Person",
        home: "Home",
        credit_limit: float,
        balance: float = 0.0,
        yearly_interest_rate: float | None = None,
        *,
        improvement_balance: float = 0.0,
        payment_strategy: PaymentStrategy = PaymentStrategy.INTEREST_ONLY,
        fixed_payment: float = 0.0,
        minimum_payment_percent: float | None = None,
        name: str | None = None,
    ):
        """Home equity line of credit.

        Args:
            person: The borrower.
            home: The home securing the line.
            credit_limit: The line's limit.
            balance: Current balance owed.
            yearly_interest_rate: APR, percent (required: a HELOC has no configured default).
            improvement_balance: Part of ``balance`` that paid for improvements to ``home`` (its interest
                is deductible acquisition-debt interest). Keyword-only.
            payment_strategy: How it is paid down (default interest-only). Keyword-only.
            fixed_payment: Monthly payment for ``FIXED``. Keyword-only.
            minimum_payment_percent: Minimum payment percent for ``MINIMUM`` (configured default when None).
            name: Display name (defaults to ``"HELOC on <home>"``).
        """
        if yearly_interest_rate is None:
            raise TypeError("HomeEquityLine needs yearly_interest_rate (a HELOC has no configured default)")
        if not 0 <= improvement_balance <= balance + 1e-9:
            raise ValueError("improvement_balance must be between 0 and balance")
        super().__init__(
            person,
            name or f"HELOC on {home.name}",
            credit_limit,
            balance=balance,
            yearly_interest_rate=yearly_interest_rate,
            minimum_payment_percent=minimum_payment_percent,
            payment_strategy=payment_strategy,
            fixed_payment=fixed_payment,
        )
        self.home = home
        self.improvement_balance = float(improvement_balance)
        self._month_start_balances: list[float] = []
        #: Not part of qualified residence interest's grandfathered debt (assumed incurred after 2017).
        self.grandfathered_cap = 0.0

    @property
    def secured_by(self) -> "Home":
        """The home securing the line."""
        return self.home

    def draw(self, amount: float, *, for_improvements: bool = False) -> float:
        """Draw on the line (up to the available credit). Returns the amount drawn.

        A draw for improvements is spent on the home at once (added to its cost basis, its interest
        deductible); any other draw is paid to the borrower.
        """
        amount = min(max(0.0, amount), self.get_available_credit())
        if amount <= 0:
            return 0.0
        self.balance += amount
        cause = f"draw on {self.name}"
        if for_improvements:
            self.improvement_balance += amount
            self.home.total_improvements += amount
            self.model.ledger.post(
                amount,
                FlowKind.BORROW,
                from_account=self,
                sink=f"improvements: {self.home.name}",
                cause=cause,
                agent=self.person,
            )
        else:
            self.person.receive_cash(amount, source=cause, kind=FlowKind.BORROW, from_account=self, cause=cause)
        return amount

    def make_payment(self, payment_amount: float, extra_to_principal: float = 0) -> float:
        before = self.balance
        paid = super().make_payment(payment_amount, extra_to_principal)
        if before > 0 and self.balance < before:
            # Principal repaid reduces the improvement part in proportion.
            self.improvement_balance *= self.balance / before
        return paid

    def service_month(self) -> float:
        if self.balance > 0:
            self._month_start_balances.append(self.balance)
        return super().service_month()

    def on_year_start(self):
        super().on_year_start()
        self._month_start_balances = []

    @property
    def average_balance_this_year(self) -> float:
        """The year's average balance (month-start balances; the current balance before the first)."""
        balances = self._month_start_balances
        return sum(balances) / len(balances) if balances else self.balance

    def acquisition_split(self) -> tuple[float, float]:
        """``(acquisition, grandfathered)`` average balances: the improvement share of the average."""
        average = self.average_balance_this_year
        share = self.improvement_balance / self.balance if self.balance > 0 else 0.0
        return average * min(1.0, share), 0.0

    def pay_off_from_sale(self, cause: str) -> float:
        """Repay the whole balance out of the home's sale price (called by :meth:`Home.sell`)."""
        payoff = self.balance
        if payoff > 0:
            self.model.ledger.post(
                payoff,
                FlowKind.HOUSING,
                from_account=self.home,
                to_account=self,
                cause=f"{cause}: {self.name} payoff",
                agent=self.person,
            )
        self.balance = 0.0
        self.improvement_balance = 0.0
        self.credit_limit = 0.0
        return payoff

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Line: {html.escape(self.name)}</li>"
        desc += f"<li>Credit Limit: ${self.credit_limit:,.2f}</li>"
        desc += f"<li>Balance: ${self.balance:,.2f} (improvements ${self.improvement_balance:,.2f})</li>"
        desc += f"<li>Interest Rate: {self.yearly_interest_rate}%</li>"
        desc += "</ul>"
        return desc
