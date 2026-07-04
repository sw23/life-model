# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Integration tests for Plan 07 — personal debt is serviced by the simulation loop.

These tests exercise the full year-step settlement (no manual ``make_payment`` calls): a person's
car loan, credit card, and student loan accrue interest and receive payments through the tax
unit's bills, exactly like housing.
"""

import unittest

from ..account.bank import BankAccount
from ..debt.car_loan import CarLoan
from ..debt.credit_card import CreditCard, PaymentStrategy
from ..debt.student_loan import StudentLoan, StudentLoanType
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending


def _make_person(model, bank_balance=500000):
    family = Family(model)
    person = Person(family, "Deb", age=40, retirement_age=70, spending=Spending(model, 0))
    BankAccount(person, "Bank", balance=bank_balance, interest_rate=0)
    return person


class TestDebtServicing(unittest.TestCase):
    def test_debts_serviced_without_manual_calls(self):
        """A car loan, credit card, and student loan are all paid down by the yearly loop."""
        model = LifeModel(start_year=2020, end_year=2020)
        person = _make_person(model)
        car = CarLoan(person, loan_amount=30000, length_years=5, yearly_interest_rate=6.0, name="Civic")
        card = CreditCard(person, "Visa", credit_limit=10000, current_balance=2000)
        loan = StudentLoan(person, StudentLoanType.FEDERAL_UNSUBSIDIZED, 20000, 5.0, 10, "State U")

        car_start, card_start, loan_start = car.principal, card.balance, loan.principal
        model.run()

        # Every debt was paid down without any user code calling make_payment.
        self.assertLess(car.principal, car_start)
        self.assertLess(card.balance, card_start)
        self.assertLess(loan.principal, loan_start)

        # Interest was accrued and attributed to the interest statistic.
        self.assertGreater(car.interest_paid_this_year, 0)
        self.assertGreater(person.stat_interest_paid, 0)

    def test_car_loan_pays_off_over_term(self):
        """A 5-year car loan is fully paid off within the loan term (6 yearly steps)."""
        model = LifeModel(start_year=2020, end_year=2025)
        person = _make_person(model)
        car = CarLoan(person, loan_amount=30000, length_years=5, yearly_interest_rate=6.0, name="Civic")
        model.run()
        self.assertAlmostEqual(car.principal, 0.0, places=2)

    def test_outstanding_debt_visible_in_stat(self):
        """Registered debt balances show up in the family's debt statistic."""
        model = LifeModel(start_year=2020, end_year=2020)
        person = _make_person(model, bank_balance=0)
        CarLoan(person, loan_amount=30000, length_years=5, yearly_interest_rate=6.0, name="Civic")
        model.run()
        df = model.datacollector.get_model_vars_dataframe()
        self.assertGreater(df.iloc[-1]["Debt"], 0)

    def test_minimum_payment_strategy_never_repays_in_horizon(self):
        """A high-APR card on minimum payments still carries a balance after 30 years."""
        model = LifeModel(start_year=2020, end_year=2049)
        person = _make_person(model)
        card = CreditCard(
            person,
            "Visa",
            credit_limit=50000,
            current_balance=10000,
            yearly_interest_rate=20.0,
            payment_strategy=PaymentStrategy.MINIMUM,
        )
        model.run()
        self.assertGreater(card.balance, 0)

    def test_full_balance_strategy_clears_each_year(self):
        """The full-balance strategy pays the card off entirely each year."""
        model = LifeModel(start_year=2020, end_year=2020)
        person = _make_person(model)
        card = CreditCard(
            person,
            "Visa",
            credit_limit=50000,
            current_balance=5000,
            yearly_interest_rate=20.0,
            payment_strategy=PaymentStrategy.FULL_BALANCE,
        )
        model.run()
        self.assertAlmostEqual(card.balance, 0.0, places=2)

    def test_unattended_card_balance_grows(self):
        """A card serviced with a $0 fixed payment grows via capitalized interest."""
        model = LifeModel(start_year=2020, end_year=2020)
        person = _make_person(model)
        card = CreditCard(
            person,
            "Visa",
            credit_limit=50000,
            current_balance=5000,
            yearly_interest_rate=20.0,
            payment_strategy=PaymentStrategy.FIXED,
            fixed_payment=0.0,
        )
        start = card.balance
        model.run()
        self.assertGreater(card.balance, start)


if __name__ == "__main__":
    unittest.main()
