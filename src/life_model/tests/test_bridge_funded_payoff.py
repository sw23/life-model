# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from decimal import ROUND_HALF_UP, Decimal

from ..checks import account_residuals, assert_conservation
from ..housing.home import qualified_residence_interest
from ..model import EventKind
from ..spec import build_household, spec_from_model, validate_spec
from ..spec.io import dumps, loads
from .spec_helpers import fixture_config, spec_of
from .test_dated_bridge import booked_bridge_interest, bridge_inputs
from .test_mortgage_maturity import inherited_mortgage_inputs


def automatic_inputs(*, receipt_month=1, receipt_day=31, limit=60000):
    inputs = bridge_inputs(receipt_month=receipt_month, receipt_day=receipt_day, limit=limit)
    inputs["events"] = [event for event in inputs["events"] if event["action"] != "draw_bridge"]
    inputs["events"][1]["bridge"] = "line"
    return inputs


class TestBridgeFundedPayoff(unittest.TestCase):
    def build(self, inputs):
        return build_household(spec_of(inputs), config=fixture_config(), collect="month")

    def test_draws_only_the_gap_and_replays_the_later_repayment(self):
        built = self.build(automatic_inputs(receipt_month=2, receipt_day=5))
        built.model.step()
        self.assertEqual(built.items["home"].mortgage.principal, 0)
        self.assertEqual(built.items["cash"].balance, 10000)
        self.assertEqual(built.items["reserve"].balance, 80000)
        self.assertAlmostEqual(built.items["line"].balance, 53530.49, places=2)
        (payoff,) = built.model.event_log.of_kind(EventKind.MORTGAGE_PAID_AT_MATURITY)
        self.assertEqual(payoff.details["bridge_draw"], 53500)
        self.assertEqual(
            [line["amount"] for line in built.model.ledger.to_records() if line["kind"] == "borrow"], [53500]
        )
        reloaded = build_household(spec_from_model(built.model), config=fixture_config(), collect="month")
        for run in (built, reloaded):
            run.model.step()
            self.assertEqual(run.items["line"].balance, 0)
            # A resumed run opens with January's interest as a liability and charges only February's.
            line = run.items["line"]
            self.assertAlmostEqual(line.interest_paid_this_year, 60.98 if run is built else 30.49, places=2)
            self.assertEqual(line.interest_paid_this_year, booked_bridge_interest(run.model, 2026))
            self.assertAlmostEqual(run.items["cash"].balance, 16439.02, places=2)
            assert_conservation(run.model, monthly=True)
        self.assertEqual(qualified_residence_interest(built.items["line"].person), 500)

    def test_earlier_receipt_avoids_the_draw(self):
        built = self.build(automatic_inputs(receipt_day=27))
        built.model.step()
        self.assertEqual(built.items["home"].mortgage.principal, 0)
        self.assertEqual(built.items["line"].balance, 0)
        self.assertEqual(built.items["cash"].balance, 16500)
        self.assertEqual(built.items["reserve"].balance, 80000)
        self.assertFalse([line for line in built.model.ledger.to_records() if line["kind"] == "borrow"])
        (payoff,) = built.model.event_log.of_kind(EventKind.MORTGAGE_PAID_AT_MATURITY)
        self.assertEqual(payoff.details["bridge_draw"], 0)
        assert_conservation(built.model, monthly=True)

    def test_insufficient_headroom_draws_available_credit_and_carries_the_gap(self):
        inputs = automatic_inputs(receipt_month=2, receipt_day=5, limit=60000)
        # Approved principal limit is $60,000, but $7,000 is already drawn.
        person = inputs["people"][0]
        person["debts"][0].update(drawn_principal=7000, accrued_through="2026-01-01")
        person["housing"][1]["purchase_price"] = 65000
        built = self.build(inputs)
        built.model.step()
        line = built.items["line"]
        self.assertEqual(built.items["cash"].balance, 10000)
        self.assertEqual(built.items["reserve"].balance, 80000)
        self.assertEqual(built.items["home"].mortgage.principal, 0)
        self.assertEqual((line.drawn_principal, line.balance, line.person.debt), (60000, 60061.12, 500))
        (payoff,) = built.model.event_log.of_kind(EventKind.MORTGAGE_PAID_AT_MATURITY)
        self.assertEqual((payoff.details["bridge_draw"], payoff.details["shortfall_debt"]), (53000, 500))
        (shortfall,) = built.model.event_log.of_kind(EventKind.SHORTFALL_DEBT)
        self.assertEqual(shortfall.amount, 500)
        self.assertEqual(account_residuals(built.model, 2026, month=1), {})

        snapshot = loads(dumps(spec_from_model(built.model), "json"))
        resumed = build_household(snapshot, config=fixture_config(), collect="month")
        interest = ((7000 * 27 + 60000 * 8) * Decimal("0.052") / 365).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rate = fixture_config().debt.effective_unpaid_balance_interest_rate / 1200
        for run in (built, resumed):
            run.model.step()
            self.assertEqual(run.items["line"].balance, 0)
            self.assertEqual(run.items["line"].person.debt, 0)
            self.assertAlmostEqual(run.items["cash"].balance, 75000 - 60000 - float(interest) - 500 * (1 + rate))
            self.assertEqual(account_residuals(run.model, 2026, month=2), {})
            assert_conservation(run.model, monthly=True)

    def test_inherited_home_and_line_can_fund_the_payoff(self):
        inputs = inherited_mortgage_inputs()
        inputs["people"][0]["debts"] = [
            {"kind": "bridge_line", "id": "line", "home": "home", "credit_limit": 120000, "rate_pct": 5.2}
        ]
        inputs["events"].pop(0)
        inputs["events"][0].update(bridge="line", at={"year": 2027, "month": 6, "day": 5})
        built = self.build(inputs)
        built.model.step_year()
        for _ in range(6):
            built.model.step()
        self.assertEqual(built.items["home"].mortgage.principal, 0)
        self.assertEqual(built.items["line"].person.name, "Bo")
        (payoff,) = built.model.event_log.of_kind(EventKind.MORTGAGE_PAID_AT_MATURITY)
        self.assertEqual(payoff.person_name, "Bo")
        self.assertGreater(payoff.details["bridge_draw"], 0)
        self.assertFalse(built.model.event_log.of_kind(EventKind.SHORTFALL_DEBT))
        assert_conservation(built.model, monthly=True)

    def test_payoff_can_carry_debt_when_the_only_bank_is_a_reserve(self):
        inputs = automatic_inputs(limit=120000)
        inputs["events"] = [inputs["events"][1]]
        built = self.build(inputs)
        built.items["cash"].reserve = True
        built.model.step()
        mortgage = built.items["home"].mortgage
        self.assertEqual((mortgage.principal, mortgage.person.debt), (0, 75500))
        self.assertEqual(built.items["line"].balance, 0)
        self.assertEqual(built.items["cash"].balance, 32000)
        self.assertEqual(built.items["reserve"].balance, 80000)
        assert_conservation(built.model, monthly=True)

    def test_fractional_cent_gap_draws_the_smallest_whole_cent(self):
        inputs = automatic_inputs()
        inputs["events"] = [inputs["events"][1]]
        inputs["people"][0]["accounts"][0]["balance"] = 85499.996
        for limit in (0.01, 0):
            with self.subTest(limit=limit):
                inputs["people"][0]["debts"][0]["credit_limit"] = limit
                built = self.build(inputs)
                if limit:
                    built.model.step()
                    self.assertEqual(
                        [line["amount"] for line in built.model.ledger.to_records() if line["kind"] == "borrow"],
                        [0.01],
                    )
                    self.assertAlmostEqual(built.items["cash"].balance, 10000.006, places=8)
                    assert_conservation(built.model, monthly=True)
                else:
                    built.model.step()
                    self.assertEqual(built.items["home"].mortgage.principal, 0)
                    self.assertAlmostEqual(built.items["home"].mortgage.person.debt, 0.004, places=8)
                    self.assertEqual(built.items["cash"].balance, 10000)
                    self.assertFalse([entry for entry in built.model.ledger.to_records() if entry["kind"] == "borrow"])
                    assert_conservation(built.model, monthly=True)

    def test_payoff_rejects_a_missing_or_unowned_bridge(self):
        missing = automatic_inputs()
        missing["events"][1]["bridge"] = "missing"
        unowned = automatic_inputs()
        owner = unowned["people"][0]
        unowned["people"].append(
            {
                "id": "jane",
                "name": "Jane",
                "age": 45,
                "retirement_age": 65,
                "debts": owner.pop("debts"),
                "housing": [owner["housing"].pop()],
            }
        )
        unowned["people"][1]["debts"][0]["home"] = "other-home"
        unowned["events"] = [unowned["events"][1]]
        for inputs, path in ((missing, "events[1].bridge"), (unowned, "events[0].bridge")):
            with self.subTest(path=path):
                findings = validate_spec(spec_of(inputs), config=fixture_config())
                self.assertTrue(any(f.level == "error" and f.path == path for f in findings))

    def test_resumed_payoff_can_use_cash_after_different_collateral_is_sold(self):
        inputs = automatic_inputs()
        owner = inputs["people"][0]
        owner["debts"][0]["home"] = "other-home"
        mortgage = owner["housing"][0]["mortgage"]
        mortgage.pop("term_years")
        mortgage.update(rate_pct=0, term_months=75)
        inputs["events"][1]["at"].update(month=2, day=5)
        built = self.build(inputs)
        built.model.step()
        snapshot = spec_from_model(built.model)
        self.assertEqual(snapshot.people[0].debts, [])
        self.assertEqual([event.bridge for event in snapshot.events], [None])
        reloaded = build_household(snapshot, config=fixture_config(), collect="month")
        for run in (built, reloaded):
            run.model.step()
            self.assertEqual(run.items["home"].mortgage.principal, 0)
            self.assertEqual(run.items["cash"].balance, 16500)
            assert_conservation(run.model, monthly=True)
