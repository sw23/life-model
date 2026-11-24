# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Secured short-term credit with simple daily interest and dated cash payments."""

from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from math import isfinite
from typing import TYPE_CHECKING

from ..ledger import FlowKind
from ..model import snap_money
from .heloc import HomeEquityLine

if TYPE_CHECKING:
    from ..housing.home import Home
    from ..people.person import Person

_CENT = Decimal("0.01")
_ZERO = Decimal(0)


def _cents(amount: Decimal) -> Decimal:
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


class DatedBridgeLine(HomeEquityLine):
    """Approved credit secured by the borrower's home.

    Accrued interest counts as a liability. The credit limit and the simple actual-days/365
    interest calculation apply to drawn principal.
    """

    def __init__(
        self,
        owner: "Person",
        *,
        home: "Home",
        credit_limit: float,
        rate_pct: float,
        name: str | None = None,
        drawn_principal: float = 0.0,
        accrued_interest: float | Decimal = _ZERO,
        accrued_through: date | None = None,
    ):
        if home.person is not owner or home.sold:
            raise ValueError("A bridge line must be secured by the borrower's active home")
        if not isfinite(rate_pct) or rate_pct < 0:
            raise ValueError("A bridge rate must be finite and non-negative")
        limit, principal = Decimal(str(credit_limit)), Decimal(str(drawn_principal))
        interest = Decimal(str(accrued_interest))
        if (
            not limit.is_finite()
            or not principal.is_finite()
            or not 0 <= principal <= limit
            or limit != _cents(limit)
            or principal != _cents(principal)
        ):
            raise ValueError("Opening principal and approved credit must be non-negative cents, within the limit")
        if not interest.is_finite() or interest < 0 or (interest and not principal):
            raise ValueError("Opening bridge interest must be non-negative and requires drawn principal")
        if (principal > 0) != (accrued_through is not None):
            raise ValueError("Supply an accrued-through date exactly when there is opening principal")
        if accrued_through is not None and accrued_through > date(owner.model.year, owner.model.month, 1):
            raise ValueError("Opening interest cannot be accrued past the simulation start")
        super().__init__(
            owner,
            home=home,
            credit_limit=credit_limit,
            rate_pct=rate_pct,
            balance=float(principal + _cents(interest)),
            name=name or f"Bridge on {home.name}",
        )
        self.drawn_principal = principal
        self.accrued_interest = interest
        self.accrued_through = accrued_through

    def get_available_credit(self) -> float:
        return 0.0 if self.home.sold else float(max(_ZERO, Decimal(str(self.credit_limit)) - self.drawn_principal))

    def _interest_at(self, when: date) -> Decimal:
        if self.accrued_through is None:
            return _ZERO
        days = (when - self.accrued_through).days
        if days < 0:
            raise ValueError("A bridge transaction cannot precede accrued-through")
        rate = Decimal(str(self.yearly_interest_rate)) / 100
        return self.accrued_interest + self.drawn_principal * rate * days / 365

    def _accrue(self, when: date) -> None:
        """Book interest through ``when``: it is charged, and counted in the interest stats, as it accrues."""
        interest = self._interest_at(when)
        increment = _cents(interest) - _cents(self.accrued_interest)
        self.accrued_interest = interest
        self.accrued_through = when if self.drawn_principal else None
        self.balance = float(self.drawn_principal + _cents(interest))
        charged = float(increment)
        self.interest_paid_this_year += charged
        self.person.stat_interest_paid = snap_money(self.person.stat_interest_paid + charged)
        self.model.ledger.post(
            charged,
            FlowKind.DEBT_SERVICE,
            from_account=self,
            sink="bridge interest",
            cause=f"Bridge interest accrued through {when.isoformat()}",
            agent=self.person,
        )

    def _check_month(self, when: date) -> None:
        if (self.model.year, self.model.month) != (when.year, when.month):
            raise ValueError("A bridge transaction must execute in its scheduled month")

    def draw(self, amount: float, *, for_improvements: bool = False, when: date | None = None) -> float:
        if when is None or for_improvements:
            raise ValueError("A bridge draw requires an explicit date and a bank cash destination")
        self._check_month(when)
        bank = self.person.primary_bank_account
        if bank is None or bank.reserve:
            raise ValueError("A bridge draw requires a spendable bank account")
        requested = Decimal(str(amount))
        capacity = Decimal(str(self.get_available_credit()))
        if not requested.is_finite() or not 0 < requested <= capacity or requested != _cents(requested):
            raise ValueError("Bridge draw must be positive whole cents within available approved credit")
        self._accrue(when)
        drawn = super().draw(float(requested))
        self.drawn_principal += requested
        self.accrued_through = when
        self.balance = float(self.drawn_principal + _cents(self.accrued_interest))
        return drawn

    def make_payment(self, payment_amount: float, extra_to_principal: float = 0.0) -> float:
        raise ValueError("Use the bridge line's dated repayment")

    def charge(self, amount: float, *, sink: str = "card purchase", post: bool = True, grace: bool = False) -> bool:
        raise ValueError("Use an explicit dated bridge draw")

    @property
    def monthly_payment(self) -> float:
        return 0.0

    def service_month(self) -> float:
        """Cash service occurs on the explicit repayment date."""
        return 0.0

    def post_step(self) -> None:
        # A line still owned by a decedent was discharged with an estate that had no heir (an heir or
        # surviving spouse takes the line over); like the estate's other debts, it is frozen.
        if self.drawn_principal and not self.person.is_deceased:
            year, month = self.model.year, self.model.month
            boundary = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
            self._accrue(boundary)

    def repay(self, when: date, *, cash_floor: float = 0.0) -> None:
        """Repay from spendable cash above the floor and carry any gap as debt due next month."""
        self._check_month(when)
        floor = Decimal(str(cash_floor))
        if not floor.is_finite() or floor < 0 or floor != _cents(floor):
            raise ValueError("The cash floor must be a non-negative amount in whole cents")
        if not self.drawn_principal:
            return
        self._accrue(when)
        payoff = self.drawn_principal + _cents(self.accrued_interest)
        cash = Decimal(str(snap_money(self.person.usable_bank_balance))).quantize(_CENT, rounding=ROUND_DOWN)
        cash_payment = min(payoff, max(_ZERO, cash - floor))
        cause = f"Repay bridge on {when.isoformat()}"
        undrawn = self.person.deduct_from_bank_accounts(
            float(cash_payment), kind=FlowKind.DEBT_SERVICE, to_account=self, include_reserve=False, cause=cause
        )
        self.person.add_debt(
            snap_money(float(payoff - cash_payment) + undrawn),
            kind=FlowKind.DEBT_SERVICE,
            to_account=self,
            cause=cause,
            defer_until_next_month=True,
        )
        self._clear()

    def _clear(self) -> None:
        if self.drawn_principal:
            self.stat_principal_payment_history.append(float(self.drawn_principal))
            self.stat_interest_payment_history.append(float(_cents(self.accrued_interest)))
        self.drawn_principal = self.accrued_interest = _ZERO
        self.accrued_through = None
        self.balance = 0.0

    def sale_payoff_amount(self, when: date) -> float:
        return float(self.drawn_principal + _cents(self._interest_at(when)))

    def pay_off_from_sale(self, cause: str, *, when: date | None = None) -> float:
        sale_date = when if when is not None else date(self.model.year, self.model.month, 1)
        self._accrue(sale_date)
        paid = super().pay_off_from_sale(cause, when=sale_date)
        self._clear()
        return paid
