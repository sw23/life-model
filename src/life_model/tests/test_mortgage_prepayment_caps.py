# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from datetime import date
from decimal import Decimal

from pydantic import ValidationError

from ..checks import assert_conservation
from ..housing.prepayment import MortgagePrepaymentPrivilege
from ..model import EventKind
from ..spec import build_household, spec_from_model, validate_spec
from ..spec.io import Format, dumps, loads
from .spec_helpers import fixture_config, spec_of
from .test_mortgage_prepayment import prepayment_inputs


def capped_inputs():
    inputs = prepayment_inputs()
    inputs["meta"]["end_year"] = 2026
    owner = inputs["people"][0]
    owner["spending"]["amount_annual"] = 0
    owner["accounts"][0]["balance"] = 100000
    owner["housing"] = owner["housing"][:1]
    owner["housing"][0]["mortgage"].update(
        original_amount=120000,
        term_months=120,
        prepayment_privilege={"anniversary": "2025-05-15", "annual_limit_pct": 10, "used": 2000},
    )
    inputs["events"] = []
    return inputs


def prepay(month, day, **options):
    return {
        "action": "prepay_mortgage",
        "person": "alex",
        "home": "home",
        "at": {"year": 2026, "month": month, "day": day},
        **options,
    }


class TestMortgagePrepaymentCaps(unittest.TestCase):
    def test_core_constructor_accepts_plain_numbers_as_keywords(self):
        as_of = date(2026, 1, 1)
        cap = MortgagePrepaymentPrivilege(
            anniversary=date(2025, 5, 15), annual_limit_pct=10, basis_amount=100000.13, as_of=as_of, used=2500.02
        )
        self.assertEqual(cap.basis_amount, Decimal("100000.13"))
        self.assertEqual(cap.annual_limit, Decimal("10000.01"))
        self.assertEqual(cap.remaining(as_of), Decimal("7499.99"))
        with self.assertRaises(TypeError):
            MortgagePrepaymentPrivilege(date(2025, 5, 15), Decimal(10), Decimal(100000), as_of)

    def test_used_amount_survives_resume_and_resets_on_anniversary(self):
        inputs = capped_inputs()
        inputs["events"] = [prepay(1, 31), prepay(4, 30), prepay(5, 31), prepay(12, 31)]
        built = build_household(spec_of(inputs), config=fixture_config(), collect="month")
        built.model.step()
        self.assertEqual(built.items["home"].mortgage.principal, 109000)
        self.assertEqual(built.items["bank"].balance, 89000)
        snapshot = spec_from_model(built.model)
        cap = snapshot.people[0].housing[0].mortgage.prepayment_privilege
        self.assertEqual((cap.anniversary, cap.basis_amount, cap.used), (date(2025, 5, 15), 120000, 12000))
        runs = [("continuous", built, [10000, 0, 12000, 0])]
        formats: tuple[Format, ...] = ("json", "yaml")
        for fmt in formats:
            serialized = dumps(snapshot, fmt)
            loaded = loads(serialized, fmt)
            self.assertEqual(dumps(loaded, fmt), serialized)
            self.assertEqual(loaded.people[0].housing[0].mortgage.prepayment_privilege, cap)
            resumed = build_household(loaded, config=fixture_config(), collect="month")
            runs.append((fmt, resumed, [0, 12000, 0]))
        for label, run, expected in runs:
            with self.subTest(run=label):
                run.model.run()
                events = run.model.event_log.of_kind(EventKind.MORTGAGE_PREPAYMENT)
                self.assertEqual([event.amount for event in events], expected)
                self.assertEqual([event.details["limit_remaining"] for event in events], expected)
                self.assertEqual(run.items["home"].mortgage.principal, 86000)
                self.assertEqual(run.items["bank"].balance, 66000)
                self.assertEqual(run.items["reserve"].balance, 20000)
                assert_conservation(run.model, monthly=True)

    def test_renewal_can_keep_replace_or_remove_the_cap(self):
        replacement = {"anniversary": "2026-07-01", "annual_limit_pct": 10}
        for new_terms, basis, paid in ((None, 120000, 0), (replacement, 102000, 10200), ("uncapped", None, 11000)):
            with self.subTest(new_terms=new_terms):
                inputs = capped_inputs()
                inputs["people"][0]["housing"][0]["mortgage"]["prepayment_privilege"].update(
                    anniversary="2025-01-01", used=0
                )
                renewal = {
                    "action": "renew_mortgage",
                    "person": "alex",
                    "home": "home",
                    "at": "2026-07",
                    "rate_pct": 0,
                    "amortization_months": 102,
                }
                if new_terms is not None:
                    renewal["prepayment_privilege"] = new_terms
                inputs["events"] = [prepay(3, 31), renewal, prepay(8, 31, cash_floor=69000)]
                built = build_household(spec_of(inputs), config=fixture_config(), collect="month")
                for _ in range(7):
                    built.model.step()
                snapshot = spec_from_model(built.model)
                cap = snapshot.people[0].housing[0].mortgage.prepayment_privilege
                self.assertEqual(None if cap is None else cap.basis_amount, basis)
                if cap is not None:
                    self.assertEqual(cap.used, 12000 if new_terms is None else 0)
                resumed = build_household(snapshot, config=fixture_config(), collect="month")
                for run in (built, resumed):
                    run.model.step()
                    self.assertEqual(run.items["home"].mortgage.principal, 100000 - paid)
                    self.assertEqual(run.items["bank"].balance, 80000 - paid)
                    event = run.model.event_log.of_kind(EventKind.MORTGAGE_PREPAYMENT)[-1]
                    self.assertEqual(event.amount, paid)
                    self.assertFalse([line for line in run.model.ledger.to_records() if line["kind"] == "borrow"])
                    assert_conservation(run.model, monthly=True)

    def test_a_renewal_basis_is_whole_cents_in_the_engine_and_the_snapshot(self):
        inputs = capped_inputs()
        inputs["people"][0]["housing"][0]["mortgage"].update(rate_pct=4.5)
        inputs["people"][0]["housing"][0]["mortgage"]["prepayment_privilege"].update(anniversary="2025-01-01", used=0)
        inputs["events"] = [
            {
                "action": "renew_mortgage",
                "person": "alex",
                "home": "home",
                "at": "2026-07",
                "rate_pct": 5.1,
                "prepayment_privilege": {"anniversary": "2026-07-01", "annual_limit_pct": 15},
            },
            prepay(8, 31),
        ]
        built = build_household(spec_of(inputs), config=fixture_config(), collect="month")
        for _ in range(7):
            built.model.step()
        engine_cap = built.items["home"].mortgage.prepayment_privilege
        self.assertEqual(engine_cap.basis_amount, engine_cap.basis_amount.quantize(Decimal("0.01")))
        snapshot = spec_from_model(built.model)
        basis = snapshot.people[0].housing[0].mortgage.prepayment_privilege.basis_amount
        self.assertEqual(Decimal(str(basis)), engine_cap.basis_amount)
        resumed = build_household(loads(dumps(snapshot, "yaml"), "yaml"), config=fixture_config(), collect="month")
        for run in (built, resumed):
            run.model.step()
        paid = [run.model.event_log.of_kind(EventKind.MORTGAGE_PREPAYMENT)[-1].amount for run in (built, resumed)]
        self.assertEqual(paid[0], paid[1])
        self.assertEqual(paid[0], float(engine_cap.annual_limit))

    def test_invalid_contract_inputs_are_rejected(self):
        for changes in ({"annual_limit_pct": 1}, {"anniversary": "2026-02-01"}):
            with self.subTest(changes=changes):
                inputs = capped_inputs()
                inputs["people"][0]["housing"][0]["mortgage"]["prepayment_privilege"].update(changes)
                findings = validate_spec(spec_of(inputs), config=fixture_config())
                self.assertTrue(any(f.level == "error" and "prepayment_privilege" in f.path for f in findings))
        inputs = capped_inputs()
        inputs["people"][0]["housing"][0]["mortgage"]["extra_principal_monthly"] = 100
        with self.assertRaisesRegex(ValidationError, "automatic extra principal"):
            spec_of(inputs)

    def test_cap_starts_at_first_eligible_date_and_a_refinance_replaces_the_contract(self):
        inputs = capped_inputs()
        mortgage = inputs["people"][0]["housing"][0]["mortgage"]
        mortgage["prepayment_privilege"].update(anniversary="2026-02-01", used=0, basis_amount=100000)
        inputs["events"] = [
            prepay(1, 31),
            prepay(2, 28),
            {
                "action": "refinance",
                "person": "alex",
                "debt": "home",
                "at": "2026-03",
                "rate_pct": 0,
                "term_months": 108,
            },
        ]
        built = build_household(spec_of(inputs), config=fixture_config(), collect="month")
        for _ in range(3):
            built.model.step()
        payments = built.model.event_log.of_kind(EventKind.MORTGAGE_PREPAYMENT)
        self.assertEqual([payment.amount for payment in payments], [0, 10000])
        self.assertIsNone(spec_from_model(built.model).people[0].housing[0].mortgage.prepayment_privilege)
        assert_conservation(built.model, monthly=True)
