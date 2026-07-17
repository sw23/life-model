# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for housing: mortgage amortization, purchase/sale cash flows, §121, and PMI."""

import unittest

from ..account.bank import BankAccount
from ..housing.home import Home, HomeExpenses, Mortgage
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending


def _expenses(model, **overrides):
    kwargs = dict(
        model=model,
        property_tax_percent=0.0,
        home_insurance_percent=0.0,
        maintenance_amount=0.0,
        maintenance_increase=0.0,
        improvement_amount=0.0,
        improvement_increase=0.0,
        hoa_amount=0.0,
        hoa_increase=0.0,
    )
    kwargs.update(overrides)
    return HomeExpenses(**kwargs)


def _person(model, bank_balance=0.0, married_to=None):
    family = Family(model)
    person = Person(family, "Owner", age=40, retirement_age=70, spending=Spending(model, 0))
    BankAccount(person, "Bank", balance=bank_balance, interest_rate=0)
    return person


class TestMortgageAmortization(unittest.TestCase):
    def test_thirty_year_amortizes_to_zero_with_closed_form_interest(self):
        """A 30yr $400k/6.5% mortgage amortizes to $0 in exactly 360 monthly periods."""
        mortgage = Mortgage(loan_amount=400000, start_date=2020, length_years=30, yearly_interest_rate=6.5)
        payment = mortgage.monthly_payment
        for _ in range(30):
            mortgage.make_yearly_payment(payment)
        self.assertEqual(len(mortgage.stat_interest_payment_history), 360)
        self.assertAlmostEqual(mortgage.principal, 0.0, places=2)
        cumulative_interest = sum(mortgage.stat_interest_payment_history)
        closed_form = payment * 360 - 400000
        self.assertLess(abs(cumulative_interest - closed_form), 5.0)

    def test_zero_interest_mortgage_no_division_by_zero(self):
        """A 0% mortgage computes a payment and amortizes to zero (no div-by-zero)."""
        mortgage = Mortgage(loan_amount=120000, start_date=2020, length_years=10, yearly_interest_rate=0.0)
        self.assertAlmostEqual(mortgage.monthly_payment, 1000.0, places=2)
        for _ in range(10):
            mortgage.make_yearly_payment(mortgage.monthly_payment)
        self.assertAlmostEqual(mortgage.principal, 0.0, places=2)

    def test_extra_principal_never_drives_principal_negative(self):
        """Paying more than the remaining balance pays off the loan; principal never goes negative."""
        mortgage = Mortgage(loan_amount=100000, start_date=2020, length_years=30, yearly_interest_rate=5.0)
        paid = mortgage.make_payment(mortgage.monthly_payment, extra_to_principal=1_000_000)
        self.assertEqual(mortgage.principal, 0.0)
        self.assertGreater(paid, 0)
        # A subsequent payment on a zero balance neither pays nor goes negative.
        self.assertEqual(mortgage.make_payment(mortgage.monthly_payment), 0.0)
        self.assertEqual(mortgage.principal, 0.0)


class TestHomePurchase(unittest.TestCase):
    def test_buying_debits_down_payment_and_closing_costs(self):
        model = LifeModel(start_year=2020, end_year=2020)
        person = _person(model, bank_balance=500000)
        mortgage = Mortgage(loan_amount=300000, start_date=2020, length_years=30, yearly_interest_rate=5.0)
        closing_pct = model.config.housing.closing_cost_percent
        Home(
            person=person,
            name="New House",
            purchase_price=400000,
            value_yearly_increase=0.0,
            down_payment=80000,
            mortgage=mortgage,
            expenses=_expenses(model),
            purchase=True,
        )
        expected_cash_out = 80000 + 400000 * (closing_pct / 100)
        self.assertAlmostEqual(person.bank_account_balance, 500000 - expected_cash_out, places=2)

    def test_already_owned_home_costs_nothing_at_construction(self):
        model = LifeModel(start_year=2020, end_year=2020)
        person = _person(model, bank_balance=500000)
        mortgage = Mortgage(loan_amount=300000, start_date=2020, length_years=30, yearly_interest_rate=5.0)
        Home(
            person=person,
            name="Existing House",
            purchase_price=400000,
            value_yearly_increase=0.0,
            down_payment=80000,
            mortgage=mortgage,
            expenses=_expenses(model),
        )
        self.assertEqual(person.bank_account_balance, 500000)


class TestHomeSale(unittest.TestCase):
    def test_sale_credits_net_proceeds_and_pays_off_mortgage(self):
        model = LifeModel(start_year=2020, end_year=2020)
        person = _person(model, bank_balance=0.0)
        mortgage = Mortgage(loan_amount=300000, start_date=2020, length_years=30, yearly_interest_rate=5.0)
        home = Home(
            person=person,
            name="House",
            purchase_price=200000,
            value_yearly_increase=0.0,
            down_payment=0.0,
            mortgage=mortgage,
            expenses=_expenses(model),
        )
        home.home_value = 500000
        net = home.sell(selling_cost_percent=0.0)
        # Net proceeds = sale price - mortgage payoff.
        self.assertAlmostEqual(net, 500000 - 300000, places=2)
        self.assertAlmostEqual(person.bank_account_balance, 200000, places=2)
        self.assertEqual(mortgage.principal, 0.0)
        self.assertTrue(home.sold)
        self.assertNotIn(home, person.homes)

    def test_section_121_under_exclusion_is_untaxed_single(self):
        model = LifeModel(start_year=2020, end_year=2020)
        person = _person(model, bank_balance=0.0)
        home = Home(
            person=person,
            name="House",
            purchase_price=200000,
            value_yearly_increase=0.0,
            down_payment=0.0,
            mortgage=None,
            expenses=_expenses(model),
        )
        home.home_value = 400000  # $200k gain, under the $250k single exclusion
        home.sell(selling_cost_percent=0.0)
        self.assertEqual(person.income.ordinary_taxable, 0.0)

    def test_section_121_over_exclusion_taxes_only_excess_mfj(self):
        model = LifeModel(start_year=2020, end_year=2020)
        family = Family(model)
        a = Person(family, "A", age=40, retirement_age=70, spending=Spending(model, 0))
        b = Person(family, "B", age=40, retirement_age=70, spending=Spending(model, 0))
        a.get_married(b)
        home = Home(
            person=a,
            name="House",
            purchase_price=200000,
            value_yearly_increase=0.0,
            down_payment=0.0,
            mortgage=None,
            expenses=_expenses(model),
        )
        home.home_value = 800000  # $600k gain MFJ, $500k exclusion -> $100k taxable
        home.sell(selling_cost_percent=0.0)
        self.assertAlmostEqual(a.income.ordinary_taxable, 100000.0, places=2)


class TestPMI(unittest.TestCase):
    def test_pmi_charged_above_threshold_and_dropped_at_or_below(self):
        model = LifeModel(start_year=2020, end_year=2020)
        person = _person(model)
        mortgage = Mortgage(loan_amount=360000, start_date=2020, length_years=30, yearly_interest_rate=5.0)
        home = Home(
            person=person,
            name="House",
            purchase_price=400000,
            value_yearly_increase=0.0,
            down_payment=40000,
            mortgage=mortgage,
            expenses=_expenses(model),
        )
        pmi_rate = model.config.housing.pmi_rate
        # LTV 90% (> 80%): PMI is charged on the balance.
        self.assertAlmostEqual(home._pmi_for_year(), 360000 * (pmi_rate / 100), places=2)
        # At exactly 80% LTV PMI is dropped.
        mortgage.principal = 0.80 * 400000
        self.assertEqual(home._pmi_for_year(), 0.0)


if __name__ == "__main__":
    unittest.main()
