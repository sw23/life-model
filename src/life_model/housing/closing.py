# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Size home closings funded from the household's available bank cash."""

from decimal import ROUND_DOWN, Decimal
from typing import TYPE_CHECKING

from ..model import snap_money
from ..people.tax_unit import TaxUnit

if TYPE_CHECKING:
    from ..people.person import Person


_CENT = Decimal("0.01")


class ClosingShortfall(ValueError):
    """Additional bank cash needed to close on the stated terms.

    ``required`` is the down payment the terms demand and ``available`` the bank cash left for it after
    closing costs and the retained floor, when the shortfall comes from sizing a down payment.
    """

    def __init__(self, amount: Decimal, *, required: Decimal | None = None, available: Decimal | None = None):
        self.amount = amount
        self.required = required
        self.available = available
        super().__init__(f"Home closing requires {amount:.2f} in additional bank cash")


def _money(value: Decimal | float, name: str) -> Decimal:
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0 or amount != amount.quantize(_CENT):
        raise ValueError(f"{name} must be a nonnegative amount in whole cents")
    return amount


def _bank_cash(owner: "Person") -> Decimal:
    balance = snap_money(TaxUnit.for_member(owner).bank_account_balance)
    return Decimal(str(balance)).quantize(_CENT, rounding=ROUND_DOWN)


def _bank_cash_after_tax(owner: "Person") -> Decimal:
    """The household's bank cash less the tax it still owes this year and from last year's return."""
    from ..policies import unit_tax_holdback

    unit = TaxUnit.for_member(owner)
    balance = snap_money(max(0.0, unit.bank_account_balance - unit_tax_holdback(unit)))
    return Decimal(str(balance)).quantize(_CENT, rounding=ROUND_DOWN)


def check_cash_purchase(
    owner: "Person",
    *,
    price: float,
    down_payment: float,
    principal: float,
    closing_costs: float,
    current_value: float | None,
) -> None:
    """Check purchase funding before registering a home or a mortgage."""
    price_amount = _money(price, "price")
    down = _money(down_payment, "down_payment")
    mortgage = _money(principal, "principal")
    if price_amount <= 0 or down + mortgage != price_amount or current_value not in (None, price):
        raise ValueError("A cash-funded purchase needs a positive price covered by the down payment and mortgage")
    shortfall = down + _money(closing_costs, "closing_costs") - _bank_cash(owner)
    if shortfall > 0:
        raise ClosingShortfall(shortfall)


def cash_funded_down_payment(
    owner: "Person",
    *,
    price: Decimal | float,
    closing_costs: Decimal | float,
    cash_floor: Decimal | float,
    minimum_down_payment: Decimal | float,
    mortgage_limit: Decimal | float,
    down_payment_fraction: Decimal | float = Decimal(1),
    extra_down_payment: Decimal | float = Decimal(0),
) -> Decimal:
    """Calculate a closing down payment from bank cash without moving balances or creating a loan.

    The required down payment (the minimum, or what the mortgage limit leaves) may use all bank cash
    above the closing costs and floor. The optional share above it (``down_payment_fraction`` and
    ``extra_down_payment``) comes only from cash left after the year's unpaid tax, so an optional
    payment doesn't leave that tax to forced sales.
    """
    price = _money(price, "price")
    costs = _money(closing_costs, "closing_costs")
    retained = _money(cash_floor, "cash_floor")
    minimum = _money(minimum_down_payment, "minimum_down_payment")
    limit = _money(mortgage_limit, "mortgage_limit")
    extra = _money(extra_down_payment, "extra_down_payment")
    fraction = Decimal(str(down_payment_fraction))
    if price <= 0 or minimum > price:
        raise ValueError("Price must be positive and the minimum down payment cannot exceed it")
    if not fraction.is_finite() or not 0 <= fraction <= 1:
        raise ValueError("down_payment_fraction must be between zero and one")

    available = _bank_cash(owner) - costs - retained
    required = max(minimum, price - limit)
    if available < required:
        raise ClosingShortfall(required - available, required=required, available=available)
    optional = max(Decimal(0), min(available, _bank_cash_after_tax(owner) - costs - retained))
    preferred = min(optional, (optional * fraction + extra).quantize(_CENT, rounding=ROUND_DOWN))
    return min(price, max(required, preferred))
