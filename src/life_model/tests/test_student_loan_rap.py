# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Income-driven repayment: the Repayment Assistance Plan (Plan 07 D5)."""

import unittest

from ..account.bank import BankAccount
from ..debt.student_loan import StudentLoan, StudentLoanRepaymentPlan, StudentLoanType
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending

RAP = StudentLoanRepaymentPlan.REPAYMENT_ASSISTANCE_PLAN


def _borrower(prior_agi: float | None = 40000):
    model = LifeModel(start_year=2027, end_year=2027)
    person = Person(Family(model), "Grad", age=28, retirement_age=67, spending=Spending(model, 0))
    BankAccount(person, "Bank", balance=100000, interest_rate=0)
    if prior_agi is not None:
        person.agi_history[2026] = prior_agi
    return model, person


def _loan(person, amount=50000.0, rate=6.0, loan_type=StudentLoanType.FEDERAL_UNSUBSIDIZED):
    return StudentLoan(person, loan_type, amount, rate, 10, "State U", repayment_plan=RAP)


class TestRapPaymentFormula(unittest.TestCase):
    def test_income_tiers(self):
        _model, person = _borrower()
        loan = _loan(person)
        cases = [(9000, 120), (15000, 150), (55000, 2750), (100000, 9000), (150000, 15000)]
        for agi, expected in cases:
            with self.subTest(agi=agi):
                self.assertAlmostEqual(loan.rap_annual_payment(agi), expected, places=2)

    def test_dependent_credit_and_monthly_floor(self):
        _model, person = _borrower()
        person.add_child("A", birth_year=2020)
        person.add_child("B", birth_year=2022)
        loan = _loan(person)
        # 5% x 55,000 = 2,750 less $50/month x 2 dependents = 1,550.
        self.assertAlmostEqual(loan.rap_annual_payment(55000), 1550, places=2)
        # Credits can't push below $10/month.
        self.assertAlmostEqual(loan.rap_annual_payment(15000), 120, places=2)

    def test_private_loans_are_ineligible(self):
        _model, person = _borrower()
        with self.assertRaises(ValueError):
            _loan(person, loan_type=StudentLoanType.PRIVATE)


class TestRapServicing(unittest.TestCase):
    def test_interest_waived_and_principal_matched(self):
        """$50k at 6% with $40k AGI: $100/month against $250 of interest.

        Each month $100 goes to interest, the other $150 of interest is waived, and the $50 match
        cuts principal by $50: after a year the balance is $49,400 and the borrower paid $1,200.
        """
        _model, person = _borrower(prior_agi=40000)
        loan = _loan(person)
        paid = loan.service_year()
        self.assertAlmostEqual(paid, 1200.0, places=2)
        self.assertAlmostEqual(loan.principal, 50000 - 12 * 50, delta=0.01)
        self.assertAlmostEqual(loan.interest_paid_this_year, 1200.0, places=2)

    def test_balance_forgiven_after_thirty_years_as_taxable_income(self):
        _model, person = _borrower(prior_agi=40000)
        loan = _loan(person)
        loan.qualifying_payments = 12 * 30 - 12  # this year's 12 payments complete the horizon
        loan.service_year()
        self.assertEqual(loan.principal, 0.0)
        self.assertAlmostEqual(loan.forgiven_amount, 50000 - 12 * 50, delta=0.01)
        self.assertAlmostEqual(person.income.ordinary_taxable, loan.forgiven_amount, places=2)

    def test_in_simulation_the_payment_follows_last_years_agi(self):
        model, person = _borrower(prior_agi=40000)
        loan = _loan(person)
        model.step()
        self.assertAlmostEqual(loan.principal, 49400.0, delta=0.01)
        self.assertEqual(person.debt, 0)


if __name__ == "__main__":
    unittest.main()
