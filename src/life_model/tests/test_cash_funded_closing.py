# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest

from ..account.bank import BankAccount
from ..checks import account_residuals, assert_conservation
from ..housing.home import Home, HomeExpenses
from ..spec import build_household, spec_from_model
from ..spec.io import Format, dumps, loads
from .spec_helpers import fixture_config, minimal, spec_of


class TestCashFundedClosing(unittest.TestCase):
    def _spec(self, receipt_day):
        data = minimal(
            jobs=[],
            spending={"amount_annual": 0},
            accounts=[
                {"kind": "bank", "id": "bank", "balance": 120000, "interest_pct": 0},
                {"kind": "brokerage", "id": "investments", "balance": 100000, "growth_pct": 0},
            ],
        )
        data["events"] = [
            {
                "id": "a_receipt",
                "at": {"year": 2026, "month": 1, "day": receipt_day},
                "action": "add_account",
                "person": "alex",
                "account": {"kind": "bank", "id": "receipt_cash", "balance": 60000, "interest_pct": 0},
            },
            {
                "id": "b_closing",
                "at": {"year": 2026, "month": 1, "day": 28},
                "person": "alex",
                "action": "buy_home",
                "home": {
                    "kind": "home",
                    "id": "new_home",
                    "purchase_price": 500000,
                    "expenses": {"property_tax_pct": 0, "insurance_pct": 0},
                },
                "cash_funding": {
                    "closing_costs": 20000,
                    "cash_floor": 30000,
                    "minimum_down_payment": 100000,
                    "mortgage_limit": 400000,
                    "term_years": 25,
                    "rate_pct": 0,
                },
            },
        ]
        return spec_of(data)

    def _household(self, receipt_day):
        return build_household(self._spec(receipt_day), config=fixture_config(), collect="month", check=False)

    def test_closing_terms_round_trip_through_json_and_yaml(self):
        spec = self._spec(27)
        formats: tuple[Format, ...] = ("json", "yaml")
        for fmt in formats:
            with self.subTest(format=fmt):
                self.assertEqual(loads(dumps(spec, fmt), fmt), spec)

    def test_closing_uses_cash_that_arrived_before_the_closing_date(self):
        built = self._household(27)
        built.model.step()
        owner = built.people["alex"]
        home = built.items["new_home"]
        self.assertEqual(home.down_payment, 130000)
        self.assertEqual(home.mortgage.loan_amount, 370000)
        self.assertAlmostEqual(home.mortgage.principal, 370000 - 370000 / 300, places=6)
        self.assertAlmostEqual(owner.usable_bank_balance, 30000 - 370000 / 300, places=6)
        self.assertEqual((owner.debt, built.items["investments"].balance), (0, 100000))
        assert_conservation(built.model, monthly=True)
        self.assertEqual(account_residuals(built.model, 2026, month=1), {})

    def test_late_cash_falls_back_to_the_waterfall_and_logs_the_gap(self):
        # The receipt lands after the closing, so the bank holds $120,000 against $100,000 of required down
        # payment, $20,000 of costs and a $30,000 floor: $30,000 short. The purchase still closes on the
        # required down payment through the household waterfall, like a buy_home without cash_funding.
        built = self._household(31)
        model = built.model
        owner = built.people["alex"]
        model.step()
        (gap,) = model.event_log.of_kind("closing_shortfall")
        self.assertEqual((gap.amount, gap.details["required"], gap.details["available"]), (30000, 100000, 70000))
        home = built.items["new_home"]
        self.assertEqual((home.down_payment, home.mortgage.loan_amount), (100000, 400000))
        self.assertEqual((built.items["bank"].balance, built.items["investments"].balance, owner.debt), (0, 100000, 0))
        assert_conservation(model, monthly=True)
        self.assertEqual(account_residuals(model, 2026, month=1), {})

    def test_shortfall_beyond_every_account_becomes_debt(self):
        # With no brokerage to sell and a $110,000 minimum, the $130,000 of down payment and costs exceeds
        # the $120,000 bank balance; the waterfall carries the $10,000 as unpaid-bills debt.
        spec = self._spec(31)
        spec.people[0].accounts[1].balance = 0
        spec.events[1].cash_funding.minimum_down_payment = 110000
        built = build_household(spec, config=fixture_config(), collect="month", check=False)
        built.model.checks = "strict"
        built.model.step()
        (gap,) = built.model.event_log.of_kind("closing_shortfall")
        self.assertEqual(gap.amount, 40000)
        self.assertEqual(built.items["new_home"].down_payment, 110000)
        debts = built.model.event_log.of_kind("shortfall_debt")
        self.assertAlmostEqual(sum(d.amount for d in debts), 10000, places=2)
        assert_conservation(built.model, monthly=True)

    def test_december_fraction_closing_holds_back_the_years_tax(self):
        # $200,000 of salary with no withholding settles its tax in December. A December closing that puts
        # all available cash down leaves that tax to forced brokerage sales unless the down payment holds it back.
        data = minimal(
            jobs=[{"id": "job", "company": "Co", "salary_annual": 200000, "raise_pct": 0}],
            spending={"amount_annual": 0},
            accounts=[
                {"kind": "bank", "id": "bank", "balance": 150000, "interest_pct": 0},
                {"kind": "brokerage", "id": "investments", "balance": 100000, "growth_pct": 0},
            ],
        )
        data["meta"]["end_year"] = 2026
        data["events"] = [
            {
                "id": "closing",
                "at": {"year": 2026, "month": 12, "day": 10},
                "person": "alex",
                "action": "buy_home",
                "home": {
                    "kind": "home",
                    "id": "new_home",
                    "purchase_price": 500000,
                    "expenses": {"property_tax_pct": 0, "insurance_pct": 0},
                },
                "cash_funding": {
                    "closing_costs": 10000,
                    "cash_floor": 0,
                    "minimum_down_payment": 100000,
                    "mortgage_limit": 400000,
                    "term_years": 25,
                    "rate_pct": 5,
                },
            }
        ]
        built = build_household(spec_of(data), config=fixture_config(), collect="month")
        built.model.checks = "strict"
        built.model.run()
        home = built.items["new_home"]
        # The $60,615 of tax is held back; only December's first mortgage payment, paid from the bank after
        # the closing, reaches the brokerage account (all available cash put down sold $61,614).
        sales = sum(e.amount for e in built.model.event_log.of_kind("forced_sale"))
        self.assertLessEqual(sales, home.mortgage.monthly_payment)
        self.assertEqual(home.down_payment, 279280)
        assert_conservation(built.model, monthly=True)

    def test_mortgage_cap_sets_required_cash_even_when_minimum_down_is_lower(self):
        from ..housing.closing import ClosingShortfall, cash_funded_down_payment

        built = self._household(27)
        with self.assertRaises(ClosingShortfall) as failure:
            cash_funded_down_payment(
                built.people["alex"],
                price=500000,
                closing_costs=5000,
                cash_floor=0,
                minimum_down_payment=50000,
                mortgage_limit=375000,
            )
        self.assertEqual(failure.exception.amount, 10000)

    def test_cash_only_purchase_can_use_the_exact_total_of_multiple_bank_balances(self):
        data = minimal(jobs=[], spending={"amount_annual": 0}, accounts=[])
        built = build_household(spec_of(data), config=fixture_config(), check=False)
        owner = built.people["alex"]
        first = BankAccount(owner, balance=0.10, interest_pct=0)
        second = BankAccount(owner, balance=1002.26, interest_pct=0)
        home = Home(
            owner,
            name="Home",
            purchase_price=1000.13,
            value_growth_pct=0,
            down_payment=1000.13,
            mortgage=None,
            expenses=HomeExpenses(built.model),
            purchase=True,
            closing_cost_percent=100 * 2.23 / 1000.13,
            cash_only=True,
        )
        self.assertEqual((first.balance, second.balance, owner.debt, home.home_value), (0, 0, 0, 1000.13))
        self.assertAlmostEqual(sum(row.amount for row in built.model.ledger if row.sink == "closing costs"), 2.23)

    def test_a_semiannual_quote_converts_before_the_new_loan_amortizes(self):
        from ..debt.terms import mortgage_rate_on_monthly_basis

        spec = self._spec(27)
        spec.events[1].cash_funding.rate_pct = 5
        spec.events[1].cash_funding.rate_compounding = "semiannual"
        self.assertEqual(loads(dumps(spec, "yaml"), "yaml"), spec)
        built = build_household(spec, config=fixture_config(), collect="month", check=False)
        built.model.step()
        mortgage = built.items["new_home"].mortgage
        self.assertEqual((mortgage.quoted_rate_pct, mortgage.rate_compounding), (5, "semiannual"))
        self.assertAlmostEqual(mortgage.yearly_interest_rate, mortgage_rate_on_monthly_basis(5, "semiannual"))
        snapshot = spec_from_model(built.model)
        (home,) = [h for h in snapshot.people[0].housing if h.id == "new_home"]
        self.assertEqual(home.mortgage.rate_compounding, "semiannual")

    def test_cash_only_purchase_posts_any_unpaid_amount_as_debt(self):
        from unittest import mock

        from ..people.tax_unit import TaxUnit

        data = minimal(jobs=[], spending={"amount_annual": 0}, accounts=[])
        built = build_household(spec_of(data), config=fixture_config(), check=False, collect="month")
        owner = built.people["alex"]
        BankAccount(owner, balance=2000, interest_pct=0)
        pay = TaxUnit.pay_from_banks

        def short_by_a_dollar(unit, amount, **kwargs):
            return pay(unit, amount - 1.0, **kwargs) + 1.0

        with mock.patch.object(TaxUnit, "pay_from_banks", short_by_a_dollar):
            Home(
                owner,
                name="Home",
                purchase_price=1000,
                value_growth_pct=0,
                down_payment=1000,
                mortgage=None,
                expenses=HomeExpenses(built.model),
                purchase=True,
                closing_cost_percent=10,
                cash_only=True,
            )
        # The down payment and the closing costs each leave $1 unpaid, carried as debt rather than dropped.
        self.assertAlmostEqual(owner.debt, 2.0, places=9)
        built.model.step()
        assert_conservation(built.model, monthly=True)


class TestPurchaseAfterTheBuyersDeath(unittest.TestCase):
    def _spec(self, *, cash_funding, married):
        import copy

        data = minimal(
            jobs=[],
            spending={"amount_annual": 0},
            accounts=[
                {"kind": "bank", "id": "bank", "balance": 150000, "interest_pct": 0},
                {"kind": "brokerage", "id": "investments", "balance": 100000, "growth_pct": 0},
            ],
        )
        data["meta"]["end_year"] = 2028
        purchase = {
            "id": "closing",
            "at": {"year": 2027, "month": 3, "day": 10},
            "person": "alex",
            "action": "buy_home",
            "home": {
                "kind": "home",
                "id": "new_home",
                "purchase_price": 500000,
                "expenses": {"property_tax_pct": 0, "insurance_pct": 0},
            },
        }
        if cash_funding:
            purchase["cash_funding"] = {
                "closing_costs": 20000,
                "cash_floor": 30000,
                "minimum_down_payment": 100000,
                "mortgage_limit": 400000,
                "term_years": 25,
                "rate_pct": 5,
            }
        else:
            purchase["home"]["down_payment"] = 100000
            purchase["home"]["mortgage"] = {"original_amount": 400000, "rate_pct": 5, "term_years": 25}
        data["events"] = [
            purchase,
            {"action": "die", "person": "alex", "at": {"year": 2027}},
            {"action": "sell_home", "person": "alex", "home": "new_home", "at": {"year": 2028, "month": 6}},
        ]
        if married:
            sam = copy.deepcopy(data["people"][0])
            sam.update(id="sam", name="Sam", accounts=[{"kind": "bank", "id": "sam_bank", "balance": 30000}])
            data["people"].append(sam)
            data["relationships"] = {"marriages": [{"spouses": ["alex", "sam"], "year": 2020}]}
        return spec_of(data)

    def test_a_purchase_dated_after_the_buyers_death_is_skipped(self):
        for cash_funding in (False, True):
            for married in (False, True):
                with self.subTest(cash_funding=cash_funding, married=married):
                    built = build_household(
                        self._spec(cash_funding=cash_funding, married=married),
                        config=fixture_config(),
                        collect="month",
                    )
                    built.model.checks = "strict"
                    built.model.run()
                    assert_conservation(built.model, monthly=True)
                    self.assertNotIn("new_home", built.items)
                    self.assertEqual(built.model.event_log.of_kind("home_bought"), [])
                    notes = [e.message for e in built.model.event_log.of_kind("note")]
                    self.assertTrue(any("home purchase skipped" in n for n in notes), notes)
                    self.assertTrue(any("home sale skipped" in n for n in notes), notes)

    def test_snapshot_after_a_skipped_purchase_drops_events_on_that_home(self):
        from ..spec import validate_spec
        from ..spec.validate import errors

        spec = self._spec(cash_funding=True, married=True)
        continuous = build_household(spec, config=fixture_config(), collect="month")
        continuous.model.run()
        partial = build_household(spec, config=fixture_config(), collect="month")
        for _ in range(15):
            partial.model.step()
        snapshot = loads(dumps(spec_from_model(partial.model), "yaml"), "yaml")
        self.assertEqual(errors(validate_spec(snapshot)), [])
        self.assertNotIn("sell_home", [event.action for event in snapshot.events])
        resumed = build_household(snapshot, config=fixture_config(), collect="month")
        resumed.model.checks = "strict"
        resumed.model.run()
        assert_conservation(resumed.model, monthly=True)
        last = (2028, 12)
        self.assertAlmostEqual(
            resumed.model.month_balance_sheets[last].closing.net_worth,
            continuous.model.month_balance_sheets[last].closing.net_worth,
            places=6,
        )
