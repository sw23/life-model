# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from ..checks import account_residuals, assert_conservation
from ..model import EventKind
from ..spec import build_household, spec_from_model, validate_spec
from ..spec.io import Format, dumps, loads
from .spec_helpers import fixture_config, spec_of
from .test_mortgage_maturity import maturity_inputs


def booked_bridge_interest(model, year):
    """The bridge interest the run's ledger charged in ``year``."""
    records = model.ledger.to_records()
    return round(sum(r["amount"] for r in records if r["sink"] == "bridge interest" and r["year"] == year), 2)


def bridge_inputs(*, receipt_month=1, receipt_day=31, limit=60000):
    inputs = maturity_inputs(receipt_day)
    inputs["meta"]["end_year"] = 2026
    inputs["people"][0]["debts"] = [
        {"kind": "bridge_line", "id": "line", "home": "home", "credit_limit": limit, "rate_pct": 5.2},
    ]
    receipt, payoff = inputs["events"]
    receipt["id"] = "03-receipt"
    receipt["at"]["month"] = receipt_month
    inputs["events"] = [
        receipt,
        payoff,
        {
            "action": "draw_bridge",
            "id": "01-draw",
            "person": "alex",
            "bridge": "line",
            "at": {"year": 2026, "month": 1, "day": 28},
            "amount": 53500,
        },
        {
            "action": "repay_bridge",
            "id": "04-repay",
            "person": "alex",
            "bridge": "line",
            "at": {"year": 2026, "month": receipt_month, "day": receipt_day},
            "cash_floor": 10000,
        },
    ]
    return inputs


class TestDatedBridge(unittest.TestCase):
    def build(self, inputs):
        return build_household(spec_of(inputs), config=fixture_config(), collect="month")

    def test_explicit_draw_and_repayment_in_one_month(self):
        built = self.build(bridge_inputs())
        built.model.step()
        line = built.items["line"]
        self.assertEqual(line.balance, 0)
        # 53,500 * 5.2% * 3 / 365, rounded at payoff.
        self.assertAlmostEqual(line.interest_paid_this_year, 22.87, places=2)
        self.assertAlmostEqual(built.items["cash"].balance, 16477.13, places=2)
        self.assertEqual(built.items["reserve"].balance, 80000)
        self.assertEqual(built.items["home"].mortgage.principal, 0)
        ledger = built.model.ledger.to_records()
        self.assertEqual([entry["amount"] for entry in ledger if entry["kind"] == "borrow"], [53500])
        self.assertEqual([entry["amount"] for entry in ledger if entry["cause"].startswith("Repay bridge")], [53522.87])
        assert_conservation(built.model, monthly=True)

    def test_accrual_carries_across_months_and_a_snapshot(self):
        built = self.build(bridge_inputs(receipt_month=2, receipt_day=5))
        built.model.step()
        line = built.items["line"]
        self.assertAlmostEqual(line.balance, 53530.49, places=2)
        self.assertEqual(line.get_available_credit(), 6500)
        snapshot = spec_from_model(built.model)
        self.assertEqual(snapshot.people[0].debts[0].accrued_through, date(2026, 2, 1))
        self.assertIsInstance(snapshot.people[0].debts[0].accrued_interest, float)
        formats: tuple[Format, ...] = ("json", "yaml")
        reloaded = [
            build_household(loads(dumps(snapshot, fmt), fmt), config=fixture_config(), collect="month")
            for fmt in formats
        ]
        for current in (built, *reloaded):
            current.model.step()
            self.assertEqual(current.items["line"].balance, 0)
            # A resumed run opens with January's interest as a liability and charges only February's.
            line = current.items["line"]
            self.assertAlmostEqual(line.interest_paid_this_year, 60.98 if current is built else 30.49, places=2)
            self.assertEqual(line.interest_paid_this_year, booked_bridge_interest(current.model, 2026))
            self.assertAlmostEqual(current.items["cash"].balance, 16439.02, places=2)
            assert_conservation(current.model, monthly=True)

    def test_interest_stats_follow_the_ledger_across_a_year_boundary(self):
        inputs = bridge_inputs()
        inputs["meta"]["end_year"] = 2027
        inputs["events"] = [
            {
                "action": "draw_bridge",
                "person": "alex",
                "bridge": "line",
                "at": {"year": 2026, "month": 12, "day": 15},
                "amount": 10000,
            },
            {"action": "repay_bridge", "person": "alex", "bridge": "line", "at": {"year": 2027, "month": 1, "day": 10}},
        ]
        built = self.build(inputs)
        built.model.checks = "strict"
        line = built.items["line"]
        recorded = {}
        for year in (2026, 2027):
            built.model.step_year()
            recorded[year] = line.interest_paid_this_year
        result = built.model.result()
        booked: dict[int, float] = {}
        for record in built.model.ledger.to_records():
            if record["sink"] == "bridge interest":
                booked[record["year"]] = round(booked.get(record["year"], 0.0) + record["amount"], 2)
        # 10,000 * 5.2% * 17 / 365 accrues in 2026 and 9 more days in 2027, 37.04 in all.
        self.assertEqual(booked, {2026: 24.22, 2027: 12.82})
        self.assertEqual(recorded, booked)
        self.assertEqual(line.stat_interest_payment_history, [37.04])
        interest_paid = dict(zip(result.model_frame["Year"], result.model_frame["Interest Paid"], strict=True))
        returns = {year: tax_return.to_dict() for (year, _unit), tax_return in built.model.tax_returns.items()}
        for year, interest in booked.items():
            # The mortgage interest is the whole itemized deduction here; bridge interest is not deductible.
            self.assertAlmostEqual(interest_paid[year], returns[year]["itemized_deductions"] + interest, places=2)
        assert_conservation(built.model, monthly=True)

    def test_accrued_interest_does_not_consume_credit_headroom(self):
        inputs = bridge_inputs()
        inputs["events"].append(
            {
                "action": "draw_bridge",
                "person": "alex",
                "bridge": "line",
                "at": {"year": 2026, "month": 1, "day": 30},
                "amount": 6500,
            }
        )
        built = self.build(inputs)
        built.model.step()
        line = built.items["line"]
        self.assertEqual(line.stat_principal_payment_history, [60000])
        # The original draw accrues three days and the final $6,500 accrues one day.
        self.assertEqual(line.stat_interest_payment_history, [23.79])
        self.assertAlmostEqual(built.items["cash"].balance, 16476.21, places=2)
        assert_conservation(built.model, monthly=True)

    def test_draw_above_limit_fails_without_posting(self):
        built = self.build(bridge_inputs(limit=53499.99))
        with self.assertRaisesRegex(ValueError, "approved credit"):
            built.model.step()
        self.assertEqual(built.items["line"].balance, 0)
        self.assertEqual(built.items["cash"].balance, 32000)
        self.assertFalse(built.model.ledger.to_records())

    def test_early_repayment_retires_the_bridge_and_carries_the_unfunded_balance(self):
        inputs = bridge_inputs()
        inputs["events"][-1]["at"]["day"] = 30
        inputs["events"][-1]["cash_floor"] = 5000
        built = self.build(inputs)
        built.model.step()
        line = built.items["line"]
        self.assertEqual(line.balance, 0)
        self.assertEqual(line.interest_paid_this_year, 15.24)
        self.assertEqual(line.person.debt, 48515.24)
        self.assertEqual(built.items["cash"].balance, 65000)
        self.assertEqual(built.items["reserve"].balance, 80000)
        (shortfall,) = built.model.event_log.of_kind(EventKind.SHORTFALL_DEBT)
        self.assertEqual((shortfall.amount, shortfall.cause), (48515.24, "Repay bridge on 2026-01-30"))
        self.assertEqual(account_residuals(built.model, 2026, month=1), {})
        snapshot = loads(dumps(spec_from_model(built.model), "json"))
        self.assertEqual(snapshot.people[0].unpaid_bills_debt, 48515.24)
        resumed = build_household(snapshot, config=fixture_config(), collect="month")
        rate = fixture_config().debt.effective_unpaid_balance_interest_rate / 1200
        for run in (built, resumed):
            run.model.step()
            self.assertEqual(run.items["line"].person.debt, 0)
            self.assertAlmostEqual(run.items["cash"].balance, 65000 - 48515.24 * (1 + rate), places=6)
            self.assertEqual(account_residuals(run.model, 2026, month=2), {})
            assert_conservation(run.model, monthly=True)

    def test_repayment_follows_the_line_to_the_surviving_spouse(self):
        inputs = bridge_inputs()
        inputs["meta"]["end_year"] = 2027
        inputs["people"].append(
            {
                "id": "bo",
                "name": "Bo",
                "age": 41,
                "birth": "1985-01",
                "retirement_age": 65,
                "accounts": [{"kind": "bank", "balance": 0, "interest_pct": 0}],
                "spending": {"amount_annual": 0, "growth_pct": 2},
            }
        )
        inputs["relationships"] = {"marriages": [{"spouses": ["alex", "bo"]}]}
        inputs["events"] = [event for event in inputs["events"] if event["action"] in ("draw_bridge", "repay_bridge")]
        inputs["events"][-1]["at"] = {"year": 2027, "month": 6, "day": 5}
        inputs["events"].append({"action": "die", "person": "alex", "at": 2027})
        built = self.build(inputs)
        built.model.step_year()
        built.model.step()
        snapshot = spec_from_model(built.model)
        self.assertEqual([event.person for event in snapshot.events], ["bo"])
        resumed = build_household(loads(dumps(snapshot, "json")), config=fixture_config(), collect="month")

        def cents(through):
            interest = Decimal(53500) * Decimal("0.052") * (through - date(2026, 1, 28)).days / 365
            return interest.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # 2027's interest: from the year start, or from the snapshot for the resumed run.
        repaid = date(2027, 6, 5)
        expected = {
            "built": cents(repaid) - cents(date(2027, 1, 1)),
            "resumed": cents(repaid) - cents(date(2027, 2, 1)),
        }
        for label, run in (("built", built), ("resumed", resumed)):
            for _ in range(5):
                run.model.step()
            line = run.items["line"]
            self.assertEqual(line.person.name, "Bo")
            self.assertEqual(line.balance, 0)
            self.assertEqual(line.stat_interest_payment_history[-1], float(cents(repaid)))
            self.assertEqual(line.interest_paid_this_year, float(expected[label]))
            self.assertEqual(line.interest_paid_this_year, booked_bridge_interest(run.model, 2027))
            self.assertFalse(run.model.event_log.of_kind(EventKind.SHORTFALL_DEBT))
            assert_conservation(run.model, monthly=True)

    def test_an_estate_with_no_heir_discharges_the_bridge_and_it_stops_accruing(self):
        inputs = bridge_inputs()
        inputs["meta"]["end_year"] = 2028
        inputs["events"] = [event for event in inputs["events"] if event["action"] == "draw_bridge"]
        inputs["events"].append({"action": "die", "person": "alex", "at": 2027})
        built = self.build(inputs)
        built.model.checks = "strict"
        line = built.items["line"]
        built.model.step_year()
        owed_at_death = line.balance
        built.model.run()
        self.assertEqual(line.balance, owed_at_death)
        records = built.model.ledger.to_records()
        self.assertFalse([r for r in records if r["sink"] == "bridge interest" and r["year"] > 2026])
        (discharged,) = [
            r for r in records if r["kind"] == "forfeit" and str(r["to_account"]).startswith("DatedBridgeLine:")
        ]
        self.assertAlmostEqual(discharged["amount"], owed_at_death, places=2)
        assert_conservation(built.model, monthly=True)

    def test_collateral_sale_retires_the_line_at_the_sale_date(self):
        inputs = bridge_inputs()
        inputs["events"][0]["home"] = "home"
        inputs["events"][-1]["at"] = {"year": 2026, "month": 2, "day": 1}
        built = self.build(inputs)
        built.model.step()
        line = built.items["line"]
        self.assertEqual((line.balance, line.credit_limit), (0, 0))
        self.assertAlmostEqual(line.interest_paid_this_year, 22.87, places=2)
        self.assertAlmostEqual(built.items["cash"].balance, 356477.13, places=2)
        snapshot = spec_from_model(built.model)
        self.assertEqual(snapshot.people[0].debts, [])
        self.assertFalse(snapshot.events)
        assert_conservation(built.model, monthly=True)

    def test_bridge_must_be_owned_and_opening_accrual_cannot_be_future(self):
        inputs = bridge_inputs()
        inputs["people"][0]["debts"][0].update(drawn_principal=1000, accrued_through="2026-02-01")
        inputs["events"][-1]["bridge"] = "missing"
        findings = validate_spec(spec_of(inputs), config=fixture_config())
        self.assertTrue(any(f.level == "error" and f.path.endswith(".accrued_through") for f in findings))
        self.assertTrue(any(f.level == "error" and f.path == "events[3].bridge" for f in findings))
