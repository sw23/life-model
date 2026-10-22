# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The canonical constructor names (housing, debt, insurance, Social Security, spending), and the deprecated
names / positional arguments still working for one release with a DeprecationWarning."""

import unittest
import warnings

from ..account.bank import BankAccount
from ..account.pension import Pension
from ..debt.car_loan import CarLoan
from ..debt.credit_card import CreditCard
from ..debt.student_loan import StudentLoan, StudentLoanType
from ..housing.apartment import Apartment
from ..housing.home import Home, HomeExpenses, Mortgage
from ..insurance.annuity import Annuity, AnnuityType
from ..insurance.general_insurance import Insurance, InsuranceType
from ..insurance.life_insurance import LifeInsurance, LifeInsuranceType
from ..insurance.social_security import SocialSecurity
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending


def _person(model):
    person = Person(Family(model), "P", 40, 65, Spending(model, 0))
    BankAccount(person, company="Bank", balance=1000)
    return person


class TestDeprecatedNames(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(start_year=2026, end_year=2027)
        self.person = _person(self.model)

    def assert_deprecated(self, build, *fragments):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            agent = build()
        messages = [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]
        for fragment in fragments:
            self.assertTrue(any(fragment in m for m in messages), f"{fragment!r} not in {messages}")
        return agent

    def assert_clean(self, build):
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            return build()

    def test_loans(self):
        old = self.assert_deprecated(
            lambda: CarLoan(self.person, 20000, 5, 6.0, "Car"), "positional arguments after the first 1"
        )
        new = self.assert_clean(
            lambda: CarLoan(self.person, original_amount=20000, term_years=5, rate_pct=6.0, name="Car")
        )
        self.assertEqual(old.monthly_payment, new.monthly_payment)
        legacy = self.assert_deprecated(
            lambda: StudentLoan(
                person=self.person,
                loan_type=StudentLoanType.PRIVATE,
                loan_amount=10000,
                yearly_interest_rate=5.0,
                length_years=10,
                principal=8000,
                monthly_payment=120,
            ),
            "StudentLoan(person=)",
            "StudentLoan(loan_amount=)",
            "StudentLoan(principal=)",
        )
        self.assertEqual((legacy.principal, legacy.monthly_payment), (8000, 120))
        mortgage = self.assert_deprecated(lambda: Mortgage(300000, 2026, 30, 5.0), "positional arguments")
        self.assertEqual(mortgage.loan_amount, 300000)
        self.assert_deprecated(
            lambda: Mortgage(loan_amount=1, start_date=2026, length_years=1, yearly_interest_rate=1),
            "Mortgage(start_date=)",
        )
        card = self.assert_deprecated(
            lambda: CreditCard(self.person, "Card", 5000, current_balance=100, yearly_interest_rate=20),
            "positional arguments",
            "CreditCard(current_balance=)",
        )
        self.assertEqual((card.card_name, card.balance, card.yearly_interest_rate), ("Card", 100, 20))
        with self.assertRaises(TypeError):
            CarLoan(self.person, loan_amount=1, original_amount=1, rate_pct=1, term_years=1)

    def test_housing(self):
        expenses = self.assert_deprecated(
            lambda: HomeExpenses(self.model, property_tax_percent=1.0, hoa_amount=1200), "HomeExpenses(hoa_amount=)"
        )
        self.assertEqual((expenses.property_tax_percent, expenses.hoa_amount), (1.0, 1200))
        home = self.assert_deprecated(
            lambda: Home(
                person=self.person,
                name="H",
                purchase_price=300000,
                value_yearly_increase=2,
                down_payment=0,
                mortgage=None,
                expenses=HomeExpenses(self.model),
            ),
            "Home(person=)",
            "Home(value_yearly_increase=)",
        )
        self.assertEqual(home.value_yearly_increase, 2)
        rent = self.assert_deprecated(
            lambda: Apartment(self.person, "A", monthly_rent=1500), "Apartment(monthly_rent=)"
        )
        self.assertEqual(rent.monthly_rent, 1500)

    def test_insurance_benefits_and_spending(self):
        policy = self.assert_deprecated(
            lambda: LifeInsurance(self.person, LifeInsuranceType.TERM, 100000, monthly_premium=30, term_years=20),
            "LifeInsurance(monthly_premium=)",
        )
        self.assertEqual(policy.monthly_premium, 30)
        general = self.assert_deprecated(
            lambda: Insurance(self.person, InsuranceType.AUTO, "Co", annual_premium=900, coverage_amount=1),
            "Insurance(annual_premium=)",
        )
        self.assertEqual(general.annual_premium, 900)
        annuity = self.assert_deprecated(
            lambda: Annuity(self.person, AnnuityType.FIXED, 50000, interest_rate=4.0), "positional", "interest_rate"
        )
        self.assertEqual((annuity.balance, annuity.interest_rate), (50000, 4.0))
        pension = self.assert_deprecated(
            lambda: Pension(self.person, "Co", 5, 12000, cola_percent=2), "positional", "Pension(cola_percent=)"
        )
        self.assertEqual((pension.benefit_amount, pension.cola_percent), (12000, 2))
        ss = self.assert_deprecated(
            lambda: SocialSecurity(self.person, withdrawal_start_age=67, income_history=[(2020, 50000)]),
            "SocialSecurity(withdrawal_start_age=)",
        )
        self.assertEqual(ss.withdrawal_start_age, 67)
        spending = self.assert_deprecated(lambda: Spending(self.model, base=1000, yearly_increase=3), "Spending(base=)")
        self.assertEqual((spending.base, spending.yearly_increase), (1000, 3))


if __name__ == "__main__":
    unittest.main()
