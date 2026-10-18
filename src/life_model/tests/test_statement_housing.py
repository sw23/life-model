# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Plan 27 PR C: homes, mortgages and loans entered from their statements (D1), loans in months,
extra principal, refinancing, home equity lines and card charges (D7).

Dollar assertions use the frozen fixture config. The amortization figures are checked against an
independent computation (the closed-form schedule in decimal arithmetic, and a lender's schedule
rounded to cents: 480,000 at 6.5% for 360 months is $3,033.93 a month and leaves $470,376.52 after 21
payments).
"""

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..config.financial_config import FinancialConfig
from ..debt.car_loan import CarLoan
from ..debt.credit_card import CreditCard, PaymentStrategy
from ..debt.heloc import HomeEquityLine
from ..debt.student_loan import StudentLoan, StudentLoanType
from ..debt.terms import LoanTermsError, amortizing_payment, resolve_loan_terms, scheduled_balance
from ..housing.home import Home, HomeExpenses, Mortgage, qualified_residence_interest
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..tax.federal import FilingStatus

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")

#: Lender's schedule (cents): 480,000 at 6.5% over 360 months.
PAYMENT_480K = 3033.93
BALANCE_480K_AFTER_21 = 470376.52


def _model(start="2026-01", end_year=2030, checks="off"):
    return LifeModel(start=start, end_year=end_year, config=FinancialConfig(config_file=TEST_CONFIG), checks=checks)


def _person(model, bank=500000.0, spending=0.0, name="Owner"):
    person = Person(Family(model), name, age=40, retirement_age=70, spending=Spending(model, spending))
    BankAccount(person, company="Bank", balance=bank, interest_pct=0)
    return person


def _home(person, mortgage, price=600000.0, **kwargs):
    return Home(person, "House", price, 0.0, 120000, mortgage, HomeExpenses(person.model), **kwargs)


class TestLoanTerms(unittest.TestCase):
    def test_origination_gives_balance_and_payment(self):
        terms = resolve_loan_terms(
            rate_pct=6.5, as_of=(2026, 1), original_amount=480000, term_months=360, origination="2024-03"
        )
        self.assertEqual(terms.payments_made, 21)
        self.assertEqual(terms.remaining_months, 339)
        self.assertAlmostEqual(terms.monthly_payment, PAYMENT_480K, places=2)
        self.assertAlmostEqual(terms.current_balance, BALANCE_480K_AFTER_21, delta=0.5)

    def test_balance_and_remaining_months_give_the_payment(self):
        terms = resolve_loan_terms(rate_pct=6.5, current_balance=470376.60, remaining_months=339)
        self.assertAlmostEqual(terms.monthly_payment, PAYMENT_480K, places=2)
        self.assertEqual(terms.term_months, 339)

    def test_balance_and_payment_give_the_months(self):
        terms = resolve_loan_terms(rate_pct=6.5, current_balance=470376.60, monthly_payment=3033.93)
        self.assertEqual(terms.remaining_months, 339)

    def test_payment_and_months_give_the_balance(self):
        terms = resolve_loan_terms(rate_pct=6.5, monthly_payment=3033.926512766226, remaining_months=339)
        self.assertAlmostEqual(terms.current_balance, 470376.60, delta=0.01)

    def test_balance_above_the_schedule_is_an_error_naming_the_field(self):
        with self.assertRaises(LoanTermsError) as caught:
            resolve_loan_terms(
                rate_pct=6.5,
                as_of=(2026, 1),
                original_amount=480000,
                term_months=360,
                origination="2024-03",
                current_balance=490000,
                names={"current_balance": "balance"},
            )
        self.assertEqual(caught.exception.field, "balance")

    def test_prepaid_balance_is_accepted_and_pays_off_early(self):
        terms = resolve_loan_terms(
            rate_pct=6.5,
            as_of=(2026, 1),
            original_amount=480000,
            term_months=360,
            origination="2024-03",
            current_balance=400000,
        )
        self.assertAlmostEqual(terms.monthly_payment, PAYMENT_480K, places=2)
        self.assertEqual(terms.current_balance, 400000)

    def test_remaining_months_disagreeing_with_origination(self):
        with self.assertRaises(LoanTermsError) as caught:
            resolve_loan_terms(
                rate_pct=6.5,
                as_of=(2026, 1),
                original_amount=480000,
                term_months=360,
                origination="2024-03",
                remaining_months=300,
            )
        self.assertEqual(caught.exception.field, "remaining_months")

    def test_payment_too_small_for_the_statement(self):
        with self.assertRaises(LoanTermsError) as caught:
            resolve_loan_terms(rate_pct=6.5, current_balance=470376.60, remaining_months=339, monthly_payment=2500)
        self.assertEqual(caught.exception.field, "monthly_payment")

    def test_future_origination_is_an_error(self):
        with self.assertRaises(LoanTermsError):
            resolve_loan_terms(rate_pct=5, as_of=(2026, 1), original_amount=1000, term_months=12, origination="2027-01")


class TestMortgageFromStatement(unittest.TestCase):
    """Acceptance (Plan 27 PR C)."""

    def test_origination_alone_gives_the_2026_balance_and_payment(self):
        model = _model()
        person = _person(model)
        mortgage = Mortgage(original_amount=480000, term_years=30, rate_pct=6.5, origination="2024-03")
        _home(person, mortgage)
        self.assertAlmostEqual(mortgage.monthly_payment, PAYMENT_480K, places=2)
        self.assertAlmostEqual(mortgage.principal, BALANCE_480K_AFTER_21, delta=0.5)
        self.assertEqual(mortgage.remaining_months, 339)
        model.step_year()
        # Twelve more payments: the closed-form schedule after 33.
        expected = scheduled_balance(480000, 6.5, mortgage.monthly_payment, 33)
        self.assertAlmostEqual(mortgage.principal, expected, places=2)

    def test_current_balance_and_remaining_months_match(self):
        dated, statement = _model(), _model()
        first = Mortgage(original_amount=480000, term_years=30, rate_pct=6.5, origination="2024-03")
        _home(_person(dated), first)
        second = Mortgage(rate_pct=6.5, current_balance=first.principal, remaining_months=339)
        _home(_person(statement), second)
        self.assertAlmostEqual(second.monthly_payment, first.monthly_payment, places=6)
        for _ in range(3):
            dated.step_year()
            statement.step_year()
            self.assertAlmostEqual(second.principal, first.principal, places=4)

    def test_escrow_is_taken_out_of_the_statement_payment(self):
        model = _model()
        mortgage = Mortgage(
            rate_pct=6.5,
            current_balance=BALANCE_480K_AFTER_21,
            remaining_months=339,
            payment_monthly=3600.0,
            escrow_monthly=566.07,
        )
        _home(_person(model), mortgage)
        self.assertAlmostEqual(mortgage.monthly_payment, 3033.93, places=2)

    def test_past_start_year_without_a_balance_amortizes_from_origination(self):
        model = _model()
        mortgage = Mortgage(original_amount=400000, start_year=2024, term_years=30, rate_pct=6.0)
        _home(_person(model), mortgage)
        # Originated January 2024: 23 payments (Feb 2024 - Dec 2025) before the run.
        self.assertEqual(mortgage.payments_made, 23)
        self.assertAlmostEqual(
            mortgage.principal, scheduled_balance(400000, 6.0, amortizing_payment(400000, 6.0, 360), 23), places=6
        )

    def test_extra_principal_pays_off_early_and_conserves(self):
        model = _model(end_year=2030, checks="strict")
        person = _person(model, bank=2000000)
        mortgage = Mortgage(original_amount=100000, term_years=10, rate_pct=6.0, extra_principal_monthly=1000.0)
        _home(person, mortgage, price=300000)
        model.run()
        self.assertEqual(mortgage.principal, 0.0)
        # 1,110.21 + 1,000 a month retires 100,000 in about four years, well inside the 10-year term.
        self.assertLess(mortgage.payments_made, 60)

    def test_grandfathered_mortgage_keeps_the_million_dollar_limit(self):
        model = _model()
        person = _person(model)
        old = Mortgage(original_amount=950000, term_years=30, rate_pct=4.0, origination="2015-06")
        _home(person, old, price=1200000)
        model.step_year()
        # $950k originated before 2017-12-16: under the $1M limit, all interest is deductible.
        self.assertAlmostEqual(qualified_residence_interest(person), old.interest_paid_this_year, places=6)

    def test_new_jumbo_mortgage_uses_the_average_balance(self):
        model = _model()
        person = _person(model)
        new = Mortgage(original_amount=1500000, term_years=30, rate_pct=5.0)
        _home(person, new, price=1800000)
        model.step_year()
        expected = new.interest_paid_this_year * 750000 / new.average_balance_this_year
        self.assertAlmostEqual(qualified_residence_interest(person), expected, places=6)

    def test_separate_return_halves_the_limits(self):
        model = _model()
        person = _person(model)
        person.filing_status = FilingStatus.MARRIED_FILING_SEPARATELY
        mortgage = Mortgage(original_amount=600000, term_years=30, rate_pct=5.0)
        _home(person, mortgage, price=800000)
        model.step_year()
        expected = mortgage.interest_paid_this_year * 375000 / mortgage.average_balance_this_year
        self.assertAlmostEqual(qualified_residence_interest(person), expected, places=6)


class TestLoansInMonths(unittest.TestCase):
    def test_66_month_car_loan_ends_in_month_66(self):
        """Acceptance (Plan 27 PR C)."""
        model = _model(end_year=2032)
        person = _person(model)
        loan = CarLoan(person, original_amount=30000, rate_pct=7.0, name="Car", term_months=66)
        self.assertEqual(loan.length_years, 5.5)
        months = 0
        while loan.principal > 0:
            model.step()
            months += 1
            self.assertLessEqual(months, 66)
        self.assertEqual(months, 66)
        self.assertEqual(loan.payments_made, 66)

    def test_car_loan_from_payments_made(self):
        model = _model()
        loan = CarLoan(_person(model), original_amount=30000, rate_pct=7.0, term_months=72, payments_made=12)
        self.assertEqual(loan.remaining_months, 60)
        payment = amortizing_payment(30000, 7.0, 72)
        self.assertAlmostEqual(loan.principal, scheduled_balance(30000, 7.0, payment, 12), places=6)

    def test_length_years_and_term_months_must_agree(self):
        model = _model()
        with self.assertRaises(ValueError):
            CarLoan(_person(model), original_amount=1000, term_years=5, rate_pct=5, term_months=66)

    def test_student_loan_deferment_until_and_prior_qualifying_payments(self):
        model = _model(end_year=2028)
        person = _person(model)
        loan = StudentLoan(
            person,
            loan_type=StudentLoanType.FEDERAL_UNSUBSIDIZED,
            original_amount=20000,
            rate_pct=6.0,
            term_years=10,
            deferment_until=2026,
            qualifying_payments=48,
        )
        self.assertTrue(loan.in_deferment)
        self.assertEqual(loan.qualifying_payments, 48)
        model.step_year()
        # A year of 6% simple interest capitalized, then repayment over the full 120 months from 2027.
        self.assertAlmostEqual(loan.principal, 21200.0, places=6)
        self.assertFalse(loan.in_deferment)
        self.assertAlmostEqual(loan.monthly_payment, amortizing_payment(21200.0, 6.0, 120), places=6)
        model.step()
        self.assertEqual(loan.payments_made, 1)


class TestRefinance(unittest.TestCase):
    def test_rate_and_term_refinance_with_costs_and_cash_out(self):
        model = _model(checks="strict")
        person = _person(model, bank=50000)
        mortgage = Mortgage(original_amount=400000, term_years=30, rate_pct=7.0)
        _home(person, mortgage)
        model.step_year()
        balance = mortgage.principal
        bank_before = person.bank_account_balance
        mortgage.refinance(5.5, term_years=15, costs=4000, cash_out=20000)
        self.assertAlmostEqual(mortgage.principal, balance + 20000, places=6)
        self.assertAlmostEqual(mortgage.monthly_payment, amortizing_payment(balance + 20000, 5.5, 180), places=6)
        self.assertAlmostEqual(person.bank_account_balance, bank_before + 20000 - 4000, places=6)
        # The cash-out is not acquisition debt: the cap stays at the old balance.
        self.assertAlmostEqual(mortgage.acquisition_cap, balance, places=6)
        model.run()

    def test_refinance_keeps_grandfathered_debt(self):
        model = _model()
        person = _person(model)
        mortgage = Mortgage(original_amount=900000, term_years=30, rate_pct=4.5, origination="2016-04")
        _home(person, mortgage, price=1200000)
        balance = mortgage.principal
        mortgage.refinance(3.0, term_years=30)
        self.assertAlmostEqual(mortgage.grandfathered_cap, balance, places=6)
        model.step_year()
        self.assertAlmostEqual(qualified_residence_interest(person), mortgage.interest_paid_this_year, places=6)


class TestHomeEquityLine(unittest.TestCase):
    def test_improvement_interest_is_deductible_and_the_rest_is_not(self):
        model = _model(checks="strict")
        person = _person(model)
        home = _home(person, None, price=500000)
        heloc = HomeEquityLine(person, home=home, credit_limit=100000, balance=0, rate_pct=8.0)
        heloc.draw(30000, for_improvements=True)
        heloc.draw(10000)
        self.assertAlmostEqual(home.total_improvements, 30000, places=6)
        model.step_year()
        self.assertGreater(heloc.interest_paid_this_year, 0)
        # Interest-only: the balance stays; 3/4 of it paid for improvements.
        self.assertAlmostEqual(heloc.balance, 40000, places=6)
        self.assertAlmostEqual(qualified_residence_interest(person), heloc.interest_paid_this_year * 0.75, places=6)

    def test_sale_pays_off_the_line(self):
        model = _model(checks="strict")
        person = _person(model)
        home = _home(person, None, price=500000)
        heloc = HomeEquityLine(person, home=home, credit_limit=100000, balance=25000, rate_pct=8.0)
        model.step_year()
        bank = person.bank_account_balance
        proceeds = home.sell(selling_cost_percent=0)
        self.assertEqual(heloc.balance, 0.0)
        self.assertAlmostEqual(proceeds, 500000 - 25000, places=6)
        self.assertAlmostEqual(person.bank_account_balance, bank + proceeds, places=6)
        model.run()


class TestCardCharges(unittest.TestCase):
    def test_spending_charged_to_a_card_paid_in_full_carries_no_interest(self):
        model = _model(end_year=2027, checks="strict")
        person = _person(model, bank=100000, spending=24000)
        card = CreditCard(
            person,
            name="Card",
            credit_limit=10000,
            payment_strategy=PaymentStrategy.FULL_BALANCE,
            spending_charge_pct=50,
        )
        model.step_year()
        self.assertAlmostEqual(card.charges_this_year, 12000, places=6)
        self.assertEqual(card.interest_paid_this_year, 0.0)
        self.assertEqual(card.balance, 0.0)
        self.assertAlmostEqual(person.stat_money_spent, 24000, places=6)
        model.run()

    def test_minimum_payments_carry_a_balance_with_interest(self):
        model = _model(end_year=2027, checks="strict")
        person = _person(model, bank=100000, spending=24000)
        card = CreditCard(person, name="Card", credit_limit=50000, spending_charge_pct=100)
        model.step_year()
        self.assertGreater(card.balance, 0)
        self.assertGreater(card.interest_paid_this_year, 0)
        model.run()


class TestHomeFromStatement(unittest.TestCase):
    def test_current_value_and_cost_basis(self):
        model = _model()
        person = _person(model)
        home = _home(person, None, price=300000, current_value=550000, cost_basis=320000, purchase_year=2010)
        self.assertEqual(home.home_value, 550000)
        self.assertEqual(home.cost_basis, 320000)
        self.assertEqual(home.original_value, 300000)

    def test_two_year_ownership_test(self):
        model = _model()
        person = _person(model)
        home = _home(person, None, price=300000, current_value=420000, purchase_year=2025)
        # Owned since (January) 2025: in January 2026 that is 12 months, so no §121 exclusion.
        self.assertEqual(home.section_121_exclusion(), 0.0)
        model.year = 2027
        self.assertGreater(home.section_121_exclusion(), 0.0)

    def test_pmi_opt_out_and_statement_premium(self):
        model = _model()
        person = _person(model)
        insured = _home(person, Mortgage(original_amount=570000, term_years=30, rate_pct=6.0), pmi_monthly=210)
        self.assertAlmostEqual(insured._pmi_for_year(), 2520.0, places=6)
        none = _home(_person(model, name="B"), Mortgage(original_amount=570000, term_years=30, rate_pct=6.0), pmi=False)
        self.assertEqual(none._pmi_for_year(), 0.0)

    def test_pmi_ends_at_78_percent_of_the_original_schedule(self):
        model = _model()
        person = _person(model)
        mortgage = Mortgage(original_amount=570000, term_years=30, rate_pct=6.0)
        home = _home(person, mortgage)
        payment = mortgage.monthly_payment
        # Find the first payment count whose scheduled balance is at or below 78% of $600k.
        k = next(n for n in range(360) if scheduled_balance(570000, 6.0, payment, n) <= 0.78 * 600000)
        mortgage.payments_made = k - 1
        # Keep the actual balance above 80% (missed principal) so only the schedule can end PMI.
        mortgage.principal = 0.85 * 600000
        self.assertTrue(home.pmi_active())
        mortgage.payments_made = k
        self.assertFalse(home.pmi_active())

    def test_dollar_property_tax_and_insurance_with_growth(self):
        model = _model(end_year=2027)
        person = _person(model)
        expenses = HomeExpenses(
            model, property_tax_annual=6000, property_tax_growth_pct=2, insurance_annual=1800, insurance_growth_pct=5
        )
        home = Home(person, "House", 500000, 0.0, 100000, None, expenses)
        self.assertEqual(home.property_tax_for_year, 6000)
        model.step_year()
        self.assertAlmostEqual(home.property_tax_for_year, 6120, places=6)
        self.assertAlmostEqual(expenses.insurance_for_year(), 1890, places=6)

    def test_assessed_value_growth_is_capped(self):
        model = _model(end_year=2027)
        person = _person(model)
        expenses = HomeExpenses(model, property_tax_pct=1.0, assessed_value=400000, assessment_growth_cap_pct=2)
        home = Home(person, "House", 700000, 6.0, 100000, None, expenses)
        self.assertAlmostEqual(home.property_tax_for_year, 4000, places=6)
        model.step_year()
        self.assertAlmostEqual(home.property_tax_for_year, 4080, places=6)

    def test_inflation_option(self):
        model = _model(end_year=2027)
        expenses = HomeExpenses(model, maintenance_annual=1000, maintenance_growth_pct=10, inflation=True)
        self.assertEqual(expenses.maintenance_increase, model.economy.inflation(model.year))


if __name__ == "__main__":
    unittest.main()
