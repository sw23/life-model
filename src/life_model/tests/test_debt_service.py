# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""DebtService: the yearly convenience helpers must agree with twelve monthly payments.

The engine services debts monthly (``service_month_detail``); ``service_year`` and
``service_year_detail`` remain public helpers for direct callers, so they are pinned here against
the monthly path rather than left untested.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from ..debt.car_loan import CarLoan
from ..people.person import Person
from ..services.debt_service import DebtService


def _loan(amount: float) -> CarLoan:
    person = Mock(spec=Person)
    person.model = Mock()
    return CarLoan(person=person, loan_amount=amount, length_years=5, yearly_interest_rate=6.0, name="Car")


class TestDebtService(unittest.TestCase):
    def test_service_year_equals_twelve_monthly_payments(self):
        yearly = [_loan(30000.0), _loan(12000.0)]
        monthly = [_loan(30000.0), _loan(12000.0)]

        paid, interest = DebtService(SimpleNamespace(all_debts=yearly)).service_year()

        monthly_service = DebtService(SimpleNamespace(all_debts=monthly))
        month_paid = 0.0
        month_interest = 0.0
        for loan in monthly:
            loan.on_year_start()
        for _ in range(12):
            for _debt, line_paid, line_interest, _before, _after in monthly_service.service_month_detail():
                month_paid += line_paid
                month_interest += line_interest

        self.assertAlmostEqual(paid, month_paid, places=6)
        self.assertAlmostEqual(interest, month_interest, places=6)
        for a, b in zip(yearly, monthly):
            self.assertAlmostEqual(a.principal, b.principal, places=6)

    def test_service_year_detail_reports_each_debt(self):
        loans = [_loan(30000.0), _loan(12000.0)]
        before = [loan.principal for loan in loans]

        lines = DebtService(SimpleNamespace(all_debts=loans)).service_year_detail()

        self.assertEqual([line[0] for line in lines], loans)
        for (debt, paid, interest, principal_before, principal_after), start in zip(lines, before):
            self.assertEqual(principal_before, start)
            self.assertEqual(principal_after, debt.principal)
            self.assertAlmostEqual(paid, 12 * debt.monthly_payment, places=6)
            self.assertGreater(interest, 0)
            # Payments explain the whole change in balance for an ordinary amortizing loan.
            self.assertAlmostEqual(principal_after, principal_before - (paid - interest), places=6)

    def test_paid_off_loan_pays_nothing_more(self):
        loan = _loan(1000.0)
        service = DebtService(SimpleNamespace(all_debts=[loan]))
        for _ in range(5):
            service.service_year()
        self.assertEqual(loan.principal, 0)
        self.assertEqual(service.service_year(), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
