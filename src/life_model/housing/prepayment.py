# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The remaining lump-sum mortgage privilege in an annual contract period."""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

_CENT = Decimal("0.01")
_ZERO = Decimal(0)


@dataclass(init=False)
class MortgagePrepaymentPrivilege:
    """A fixed contract basis and the amount used in the period containing `as_of`.

    Accepts integers, floats, and decimals as numeric inputs and computes the cap with decimals.
    The basis is rounded to whole cents.
    """

    anniversary: date
    annual_limit_pct: Decimal
    basis_amount: Decimal
    as_of: date
    used: Decimal

    def __init__(
        self,
        *,
        anniversary: date,
        annual_limit_pct: float | Decimal,
        basis_amount: float | Decimal,
        as_of: date,
        used: float | Decimal = _ZERO,
    ) -> None:
        self.anniversary = anniversary
        self.annual_limit_pct = Decimal(str(annual_limit_pct))
        self.basis_amount = Decimal(str(basis_amount))
        if self.basis_amount.is_finite():
            self.basis_amount = self.basis_amount.quantize(_CENT, rounding=ROUND_HALF_UP)
        self.as_of = as_of
        self.used = Decimal(str(used))
        if not self.annual_limit_pct.is_finite() or not 0 <= self.annual_limit_pct <= 100:
            raise ValueError("The annual lump-sum percentage must be between zero and 100")
        if not self.basis_amount.is_finite() or self.basis_amount <= 0:
            raise ValueError("The prepayment basis must be finite and positive")
        if not self.used.is_finite() or not 0 <= self.used <= self.annual_limit:
            raise ValueError("Used prepayment privilege must be between zero and the annual limit")
        if self.used and self.as_of < self.anniversary:
            raise ValueError("Prepayment privilege cannot be used before its first eligible date")

    @property
    def annual_limit(self) -> Decimal:
        return (self.basis_amount * self.annual_limit_pct / 100).quantize(_CENT, rounding=ROUND_DOWN)

    def _period(self, when: date) -> int:
        month = self.anniversary.month
        reset_day = min(self.anniversary.day, monthrange(when.year, month)[1])
        return when.year - (when < date(when.year, month, reset_day))

    def used_for(self, when: date) -> Decimal:
        if when >= self.anniversary and self._period(when) == self._period(self.as_of):
            return self.used
        return _ZERO

    def remaining(self, when: date) -> Decimal:
        if when < self.anniversary:
            return _ZERO
        return self.annual_limit - self.used_for(when)

    def record(self, when: date, paid: Decimal) -> None:
        self.used = min(self.annual_limit, self.used_for(when) + paid)
        self.as_of = when
