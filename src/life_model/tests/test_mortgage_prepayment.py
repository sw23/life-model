# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest

from pydantic import ValidationError

from ..checks import assert_conservation
from ..model import EventKind
from ..spec import build_household, spec_from_model, validate_spec
from .spec_helpers import fixture_config, minimal, spec_of


def prepayment_inputs(**prepayment):
    inputs = minimal(
        jobs=[],
        spending={"amount_annual": 6000, "growth_pct": 2},
        accounts=[
            {"kind": "bank", "id": "bank", "primary": True, "balance": 5000, "interest_pct": 0},
            {"kind": "bank", "id": "reserve", "reserve": True, "balance": 20000, "interest_pct": 0},
        ],
        housing=[
            {
                "kind": "home",
                "id": "home",
                "purchase_price": 200000,
                "value_growth_pct": 0,
                "expenses": {},
                "pmi": False,
                "mortgage": {"original_amount": 12000, "term_months": 12, "rate_pct": 0},
            },
            {
                "kind": "home",
                "id": "other-home",
                "purchase_price": 6000,
                "value_growth_pct": 0,
                "expenses": {},
                "pmi": False,
            },
        ],
    )
    inputs["events"] = [
        {
            "action": "sell_home",
            "person": "alex",
            "home": "other-home",
            "selling_cost_pct": 0,
            "at": {"year": 2026, "month": 1, "day": 31},
        },
        {
            "action": "prepay_mortgage",
            "person": "alex",
            "home": "home",
            "at": {"year": 2026, "month": 1, "day": 31},
            "cash_fraction": 0.5,
            "cash_floor": 3000,
            **prepayment,
        },
    ]
    return inputs


def taxable_prepayment_inputs(month, day, *, floor=0, fraction=1):
    inputs = prepayment_inputs(at={"year": 2026, "month": month, "day": day}, cash_floor=floor, cash_fraction=fraction)
    inputs["meta"]["accepted_warnings"] = ["fixed_growth"]
    del inputs["events"][0]
    person = inputs["people"][0]
    person["housing"].pop()
    person["housing"][0]["mortgage"].update(original_amount=120000, term_months=120)
    person["jobs"] = [{"id": "job", "company": "Co", "salary_annual": 80000, "raise_pct": 2}]
    person["spending"]["amount_annual"] = 26000
    person["accounts"].append({"kind": "brokerage", "id": "brokerage", "balance": 50000, "growth_pct": 0})
    return inputs


class TestMortgagePrepayment(unittest.TestCase):
    def test_prepayment_uses_settled_cash_after_bills_and_reopens_with_same_terms(self):
        inputs = prepayment_inputs()
        later = prepayment_inputs(at={"year": 2026, "month": 3, "day": 31})["events"][1]
        inputs["events"].append(later)
        built = build_household(spec_of(inputs), config=fixture_config(), collect="month")
        mortgage = built.items["home"].mortgage
        built.model.step()
        # Cash after sale, regular mortgage payment and spending: 5000 + 6000 - 1000 - 500.
        # Prepay half the cash above the 3000 floor: (9500 - 3000) / 2 = 3250.
        self.assertEqual(mortgage.principal, 7750)
        self.assertEqual(mortgage.payments_made, 1)
        self.assertEqual(mortgage.stat_principal_payment_history, [4250])
        self.assertEqual(mortgage.monthly_payment, 1000)
        self.assertEqual(built.items["bank"].balance, 6250)
        self.assertEqual(built.items["reserve"].balance, 20000)
        self.assertEqual(mortgage.person.stat_housing_costs, 4250)
        (prepayment,) = built.model.event_log.of_kind(EventKind.MORTGAGE_PREPAYMENT)
        self.assertEqual((prepayment.amount, prepayment.details["cash_before"]), (3250, 9500))
        self.assertEqual(prepayment.details["date"], "2026-01-31")
        records = built.model.ledger.to_records()
        principal_entries = [record for record in records if record["to_name"] == prepayment.account_name]
        self.assertEqual([record["amount"] for record in principal_entries], [1000, 3250])
        self.assertEqual(principal_entries[-1]["stage"], "post_step")

        snapshot = spec_from_model(built.model)
        self.assertEqual([(event.at.month, event.at.day) for event in snapshot.events], [(3, 31)])
        resumed = build_household(snapshot, config=fixture_config(), collect="month")
        for run in (built, resumed):
            run.model.step()
            self.assertEqual(run.items["home"].mortgage.principal, 6750)
            self.assertEqual(run.items["bank"].balance, 4750)
            run.model.step()
            self.assertEqual(run.items["home"].mortgage.principal, 5625)
            self.assertEqual(run.items["bank"].balance, 3125)
            assert_conservation(run.model, monthly=True)

    def test_floor_and_outstanding_principal_bound_the_payment(self):
        for wanted_floor, opening_cash, expected in (
            (10000, 5000, 0),
            (3000, 30000, 11000),
            (3000, 5000.01, 3250),
        ):
            with self.subTest(wanted_floor=wanted_floor, opening_cash=opening_cash):
                inputs = prepayment_inputs(cash_floor=wanted_floor, cash_fraction=0.5 if opening_cash < 6000 else 1)
                inputs["people"][0]["accounts"][0]["balance"] = opening_cash
                built = build_household(spec_of(inputs), config=fixture_config(), collect="month")
                built.model.step()
                (payment,) = built.model.event_log.of_kind(EventKind.MORTGAGE_PREPAYMENT)
                self.assertEqual(payment.amount, expected)
                self.assertEqual(built.items["home"].mortgage.principal, 11000 - expected)
                self.assertEqual(built.items["reserve"].balance, 20000)
                assert_conservation(built.model, monthly=True)

    def test_scheduled_maturity_payoff_runs_before_surplus_prepayment(self):
        inputs = prepayment_inputs()
        inputs["people"][0]["accounts"][0]["balance"] = 25000
        inputs["events"].append(
            {
                "action": "pay_mortgage_at_maturity",
                "person": "alex",
                "home": "home",
                "at": {"year": 2026, "month": 1, "day": 20},
                "interest_due": 100,
            }
        )
        built = build_household(spec_of(inputs), config=fixture_config(), collect="month")
        built.model.step()
        self.assertEqual(built.items["home"].mortgage.principal, 0)
        self.assertEqual(built.items["bank"].balance, 18400)
        self.assertEqual(built.items["reserve"].balance, 20000)
        self.assertFalse(built.model.event_log.of_kind(EventKind.MORTGAGE_PREPAYMENT))
        assert_conservation(built.model, monthly=True)

    def test_prepayment_holds_back_year_to_date_tax_and_applies_the_floor_to_surplus(self):
        inputs = taxable_prepayment_inputs(1, 31, floor=3000, fraction=0.5)
        built = build_household(spec_of(inputs), config=fixture_config(), collect="month")
        built.model.step()
        (payment,) = built.model.event_log.of_kind(EventKind.MORTGAGE_PREPAYMENT)
        # $21,120 annual tax: $11,500 federal, $3,500 state and $6,120 payroll.
        self.assertEqual(payment.amount, (8500 - 21120 / 12 - 3000) * 0.5)
        self.assertEqual(payment.details["tax_holdback"], 1760)
        self.assertEqual(built.items["bank"].balance, 6630)
        self.assertEqual(built.items["reserve"].balance, 20000)
        assert_conservation(built.model, monthly=True)

    def test_december_prepayment_keeps_cash_for_tax_without_selling_brokerage(self):
        inputs = taxable_prepayment_inputs(12, 31)
        built = build_household(spec_of(inputs), config=fixture_config(), collect="month")
        built.model.step_year()
        (payment,) = built.model.event_log.of_kind(EventKind.MORTGAGE_PREPAYMENT)
        self.assertEqual(payment.amount, 47000 - 21120)
        self.assertEqual(built.items["home"].mortgage.principal, 82120)
        self.assertAlmostEqual(built.items["bank"].balance, 0, places=2)
        self.assertEqual(built.items["brokerage"].balance, 50000)
        self.assertFalse(built.model.event_log.of_kind(EventKind.FORCED_SALE))
        assert_conservation(built.model, monthly=True)

    def test_prepayment_holds_back_last_years_unpaid_balance_until_april(self):
        inputs = taxable_prepayment_inputs(3, 31)
        inputs["events"][0]["at"]["year"] = 2027
        inputs["people"][0]["estimated_payments"] = {"quarterly": 0}
        built = build_household(spec_of(inputs), config=fixture_config(), collect="month")
        mortgage = built.items["home"].mortgage
        built.model.step_year()
        prior_balance = mortgage.person.taxes_owed
        self.assertGreater(prior_balance, 0)
        for _ in range(3):
            built.model.step()
        (payment,) = built.model.event_log.of_kind(EventKind.MORTGAGE_PREPAYMENT)
        # The new year's $81,600 salary has $21,722.40 of projected annual tax.
        self.assertAlmostEqual(payment.details["tax_holdback"], prior_balance + 21722.40 / 4, places=6)
        self.assertEqual(mortgage.person.taxes_owed, prior_balance)
        self.assertGreaterEqual(built.items["bank"].balance, prior_balance + 21722.40 / 4 - 1e-8)
        built.model.step()
        self.assertEqual(mortgage.person.taxes_owed, 0)
        self.assertFalse(built.model.event_log.of_kind(EventKind.FORCED_SALE))
        assert_conservation(built.model, monthly=True)

    def test_december_sweep_uses_its_own_floor_after_prepayment_and_taxes(self):
        inputs = taxable_prepayment_inputs(12, 31, floor=25000)
        inputs["people"][0]["savings_policy"] = {"cash_floor": 10000, "sweep_to": "brokerage"}
        built = build_household(spec_of(inputs), config=fixture_config(), collect="month")
        built.model.step_year()
        (payment,) = built.model.event_log.of_kind(EventKind.MORTGAGE_PREPAYMENT)
        self.assertEqual(payment.amount, 47000 - 21120 - 25000)
        self.assertAlmostEqual(built.items["bank"].balance, 10000, places=6)
        self.assertAlmostEqual(built.items["brokerage"].balance, 65000, places=6)
        assert_conservation(built.model, monthly=True)

    def test_prepayment_requires_month_end_and_an_owned_home_with_a_mortgage(self):
        with self.assertRaisesRegex(ValidationError, "last day"):
            spec_of(prepayment_inputs(at={"year": 2026, "month": 2, "day": 27}))
        inputs = prepayment_inputs(home="other-home")
        findings = validate_spec(spec_of(inputs), config=fixture_config())
        self.assertTrue(any(f.level == "error" and f.path == "events[1].home" for f in findings))


class TestPrepaymentAfterTheBorrowersDeath(unittest.TestCase):
    def _spec(self, *, married):
        import copy

        data = minimal(
            jobs=[],
            spending={"amount_annual": 0},
            accounts=[{"kind": "bank", "id": "bank", "balance": 50000, "interest_pct": 0}],
            housing=[
                {
                    "kind": "home",
                    "id": "home",
                    "purchase_price": 300000,
                    "value_growth_pct": 0,
                    "expenses": {"property_tax_pct": 0, "insurance_pct": 0},
                    "pmi": False,
                    "mortgage": {"original_amount": 120000, "term_years": 25, "rate_pct": 0},
                }
            ],
        )
        data["meta"]["end_year"] = 2027
        data["events"] = [
            {"action": "die", "person": "alex", "at": {"year": 2027}},
            {
                "id": "prepay",
                "action": "prepay_mortgage",
                "person": "alex",
                "home": "home",
                "at": {"year": 2027, "month": 6, "day": 30},
                "cash_fraction": 0.5,
            },
        ]
        if married:
            sam = copy.deepcopy(data["people"][0])
            sam.update(
                id="sam", name="Sam", accounts=[{"kind": "bank", "id": "sam_bank", "balance": 30000}], housing=[]
            )
            data["people"].append(sam)
            data["relationships"] = {"marriages": [{"spouses": ["alex", "sam"], "year": 2020}]}
        return spec_of(data)

    def _run(self, spec):
        built = build_household(spec, config=fixture_config(), collect="month")
        built.model.checks = "strict"
        built.model.run()
        assert_conservation(built.model, monthly=True)
        return built

    def test_prepayment_follows_the_home_to_the_surviving_spouse(self):
        built = self._run(self._spec(married=True))
        (event,) = built.model.event_log.of_kind(EventKind.MORTGAGE_PREPAYMENT)
        self.assertEqual(event.person_name, "Sam")
        self.assertGreater(event.amount, 0)

    def test_prepayment_after_a_single_borrowers_death_is_skipped(self):
        built = self._run(self._spec(married=False))
        self.assertEqual(built.model.event_log.of_kind(EventKind.MORTGAGE_PREPAYMENT), [])
        notes = [e.message for e in built.model.event_log.of_kind(EventKind.NOTE)]
        self.assertTrue(any("mortgage prepayment skipped" in n for n in notes), notes)

    def test_snapshot_after_the_death_resumes_the_survivors_prepayment(self):
        from ..spec.io import dumps, loads

        continuous = self._run(self._spec(married=True))
        partial = build_household(self._spec(married=True), config=fixture_config(), collect="month")
        for _ in range(15):
            partial.model.step()
        snapshot = loads(dumps(spec_from_model(partial.model), "yaml"), "yaml")
        (pending,) = [e for e in snapshot.events if e.action == "prepay_mortgage"]
        self.assertEqual(pending.person, "sam")
        resumed = self._run(snapshot)
        self.assertAlmostEqual(
            resumed.items["home"].mortgage.principal, continuous.items["home"].mortgage.principal, places=6
        )
