# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from ..people.person import Person


class DebtService:
    """Services a person's personal debts (car loans, credit cards, student loans) each year.

    The simulation steps annually, but debts accrue interest and are paid monthly, so each debt
    amortizes twelve internal monthly periods per simulated year (see ``service_year`` on the
    debt classes). The cash paid is returned so the caller can fold it into the tax unit's bills;
    the accrued interest is returned so it can be attributed to the interest-paid statistic.
    """

    def __init__(self, person: "Person"):
        self.person = person

    def service_year(self) -> Tuple[float, float]:
        """Service every personal debt for one simulated year.

        Returns:
            Tuple[float, float]: ``(total_paid, total_interest)`` across all of the person's debts.
        """
        total_paid = 0.0
        total_interest = 0.0
        for debt in self.person.all_debts:
            total_paid += debt.service_year()
            total_interest += debt.interest_paid_this_year
        return total_paid, total_interest
