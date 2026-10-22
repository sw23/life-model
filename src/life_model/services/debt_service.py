# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..people.person import Person


class DebtService:
    """Services a person's personal debts (car loans, credit cards, student loans).

    The tax unit services every debt once a month with the month's bills (:meth:`service_month_detail`;
    see ``service_month`` on the debt classes). The cash paid is returned so the caller can fold it
    into the bills; the interest charged so it can be attributed to the interest-paid statistic.
    ``service_year`` runs twelve payments at once for direct callers.
    """

    def __init__(self, person: "Person"):
        self.person = person

    def service_year(self) -> tuple[float, float]:
        """Service every personal debt for one simulated year.

        Returns:
            Tuple[float, float]: ``(total_paid, total_interest)`` across all of the person's debts.
        """
        lines = self.service_year_detail()
        return sum(line[1] for line in lines), sum(line[2] for line in lines)

    def service_year_detail(self) -> list[tuple[object, float, float, float, float]]:
        """Service every personal debt for one simulated year, per debt.

        Returns:
            One ``(debt, paid, interest, principal_before, principal_after)`` per debt: the cash the
            borrower paid, the interest charged within it, and the balance before and after the
            year. ``principal_after - (principal_before - (paid - interest))`` is any change the
            payments don't explain (interest capitalized, an income-driven plan's principal match,
            forgiveness).
        """
        lines = []
        for debt in self.person.all_debts:
            before = debt.principal
            paid = debt.service_year()
            lines.append((debt, paid, debt.interest_paid_this_year, before, debt.principal))
        return lines

    def service_month_detail(self) -> list[tuple[object, float, float, float, float]]:
        """Service every personal debt for one month, per debt.

        Returns:
            One ``(debt, paid, interest, principal_before, principal_after)`` per debt (see
            :meth:`service_year_detail`), for this month's payment.
        """
        lines = []
        for debt in self.person.all_debts:
            before = debt.principal
            interest_before = debt.interest_paid_this_year
            paid = debt.service_month()
            lines.append((debt, paid, debt.interest_paid_this_year - interest_before, before, debt.principal))
        return lines
