# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Table-driven amortization tests for the Loan ABC (via a concrete CarLoan subclass)."""

import unittest

from ..debt.car_loan import CarLoan
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending


def _person(model):
    family = Family(model)
    return Person(family, "Borrower", age=40, retirement_age=70, spending=Spending(model, 0))


class TestLoanAmortization(unittest.TestCase):
    def _make_loan(self, amount, rate, years):
        model = LifeModel(start_year=2020, end_year=2020)
        return CarLoan(_person(model), loan_amount=amount, length_years=years, yearly_interest_rate=rate, name="Car")

    def test_amortizes_to_exactly_zero_and_interest_matches_closed_form(self):
        """Across several loans, the scheduled payment amortizes to $0 with closed-form interest."""
        cases = [
            (30000, 6.0, 5),
            (20000, 4.5, 4),
            (50000, 7.25, 6),
        ]
        for amount, rate, years in cases:
            with self.subTest(amount=amount, rate=rate, years=years):
                loan = self._make_loan(amount, rate, years)
                payment = loan.monthly_payment
                for _ in range(years * 12):
                    loan.make_payment(payment)
                self.assertAlmostEqual(loan.principal, 0.0, places=2)
                cumulative_interest = sum(loan.stat_interest_payment_history)
                closed_form = payment * years * 12 - amount
                self.assertLess(abs(cumulative_interest - closed_form), 1.0)

    def test_zero_interest_loan(self):
        """A 0% loan's payment is amount/term and amortizes to zero without division-by-zero."""
        loan = self._make_loan(24000, 0.0, 4)
        self.assertAlmostEqual(loan.monthly_payment, 24000 / 48, places=6)
        for _ in range(48):
            loan.make_payment(loan.monthly_payment)
        self.assertAlmostEqual(loan.principal, 0.0, places=2)

    def test_extra_principal_pays_off_and_never_negative(self):
        loan = self._make_loan(30000, 6.0, 5)
        loan.make_payment(loan.monthly_payment, extra_to_principal=1_000_000)
        self.assertEqual(loan.principal, 0.0)
        # Paying again on a zero balance is a no-op, not a negative balance.
        self.assertEqual(loan.make_payment(loan.monthly_payment), 0.0)
        self.assertEqual(loan.principal, 0.0)

    def test_negative_amortization_when_payment_below_interest(self):
        """A payment below the month's interest capitalizes the shortfall onto the balance."""
        loan = self._make_loan(30000, 12.0, 5)
        monthly_interest = loan.get_interest_amount("month")
        start = loan.principal
        loan.make_payment(0.0)
        self.assertAlmostEqual(loan.principal, start + monthly_interest, places=6)

    def test_make_yearly_payment_runs_twelve_periods(self):
        loan = self._make_loan(30000, 6.0, 5)
        loan.make_yearly_payment(loan.monthly_payment)
        self.assertEqual(len(loan.stat_interest_payment_history), 12)
        self.assertGreater(loan.interest_paid_this_year, 0)

    def test_negative_payment_raises(self):
        loan = self._make_loan(30000, 6.0, 5)
        with self.assertRaises(ValueError):
            loan.make_payment(-1.0)
        with self.assertRaises(ValueError):
            loan.make_payment(100.0, extra_to_principal=-1.0)


if __name__ == "__main__":
    unittest.main()
