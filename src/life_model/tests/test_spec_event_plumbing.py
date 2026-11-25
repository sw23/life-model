# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Dated event plumbing in the spec layer: event dates, snapshot re-dating, event order checks and the
schema's independence from the engine."""

import ast
import itertools
import typing
import unittest
import warnings
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from ..debt import terms
from ..lifeevents import LifeEvent
from ..model import EVENT_KIND_DOCS
from ..spec import SpecWarning, build_household, spec_from_model, validate_spec
from ..spec import events as spec_events
from ..spec import schema as s
from ..spec.validate import errors
from .spec_helpers import fixture_config, minimal, spec_of


def build(data: dict, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SpecWarning)
        return build_household(spec_of(data), config=fixture_config(), **kwargs)


class TestLifeEventDate(unittest.TestCase):
    def test_set_date_validates_and_sets_the_month_and_day(self):
        event = LifeEvent(2027, "test", lambda: None)
        event.set_date(3, 15)
        self.assertEqual((event.month, event.day), (3, 15))
        event.set_date(None, None)
        self.assertEqual((event.month, event.day), (None, None))
        for month, day, message in ((13, None, "1-12"), (None, 5, "explicit month"), (2, 30, "1-28 for 2027-02")):
            with self.subTest(month=month, day=day), self.assertRaisesRegex(ValueError, message):
                event.set_date(month, day)

    def test_dated_action_without_a_full_date_raises_a_value_error(self):
        event = s.MortgageMaturityEvent.model_construct(
            action="pay_mortgage_at_maturity", person="alex", home="home", at=s.At.model_construct(year=2027, month=3)
        )
        with self.assertRaisesRegex(ValueError, "pay_mortgage_at_maturity.*full calendar date"):
            spec_events.scheduled_date(event)
        self.assertEqual(spec_events.scheduled_date(event, day_required=False), date(2027, 3, 1))


class TestEventKindDocs(unittest.TestCase):
    def test_life_event_fired_documents_the_scheduled_day(self):
        self.assertIn("scheduled_day", EVENT_KIND_DOCS["life_event_fired"])


class TestSnapshotKeepsRelativeOrder(unittest.TestCase):
    def test_undated_relative_event_still_follows_its_anchor_after_a_snapshot(self):
        data = minimal()
        data["meta"]["end_year"] = 2028
        # The dependent's id sorts first, so only its anchor link makes it fire second.
        data["events"] = [
            {
                "id": "a_contribution",
                "at": {"relative": {"after": "b_account"}},
                "person": "alex",
                "action": "contribute",
                "account": "new_cash",
                "amount": 300,
            },
            {
                "id": "b_account",
                "at": {"year": 2027},
                "person": "alex",
                "action": "add_account",
                "account": {"id": "new_cash", "kind": "brokerage", "balance": 0},
            },
        ]
        continuous = build(data)
        continuous.model.step_year()
        snapshot = spec_from_model(continuous.model)
        relative = next(event for event in snapshot.events if event.id == "a_contribution")
        self.assertIsNotNone(relative.at.relative)
        self.assertEqual(relative.at.relative.after, "b_account")
        resumed = build_household(snapshot, config=fixture_config())
        self.assertEqual(
            [event.spec_source.id for event in resumed.life_events.life_events], ["b_account", "a_contribution"]
        )
        continuous.model.step_year()
        resumed.model.step_year()
        self.assertEqual(resumed.items["new_cash"].balance, continuous.items["new_cash"].balance)
        self.assertGreater(continuous.items["new_cash"].balance, 0)


def _home_purchase_inputs(dependent: dict, *, buy_at) -> dict:
    data = minimal()
    data["meta"]["end_year"] = 2029
    data["people"][0]["accounts"][0]["balance"] = 200000
    home = {
        "id": "new_home",
        "kind": "home",
        "purchase_price": 300000,
        "down_payment": 60000,
        "pmi": False,
        "expenses": {},
        "mortgage": {"original_amount": 240000, "rate_pct": 5, "term_years": 30},
    }
    data["events"] = [
        {"id": "m_buy", "action": "buy_home", "person": "alex", "home": home, "at": buy_at},
        {"person": "alex", **dependent},
    ]
    return data


#: Spec inputs and dates of each action that acts on an added home.
DEPENDENTS = {
    "renew_mortgage": {"home": "new_home", "rate_pct": 4},
    "refinance": {"debt": "new_home", "rate_pct": 4, "term_years": 15},
    "prepay_mortgage": {"home": "new_home"},
    "pay_mortgage_at_maturity": {"home": "new_home", "interest_due": 10},
    "sell_home": {"home": "new_home"},
}
DATES = {
    "renew_mortgage": {"year": 2027, "month": 3},
    "refinance": {"year": 2027, "month": 3},
    "prepay_mortgage": {"year": 2027, "month": 3, "day": 31},
    "pay_mortgage_at_maturity": {"year": 2027, "month": 3, "day": 5},
    "sell_home": {"year": 2027, "month": 3},
}


class TestEventsBeforeTheirHome(unittest.TestCase):
    def findings(self, action: str, *, buy_at, at=None, event_id: str = "z_dependent"):
        dependent = {"id": event_id, "action": action, "at": at or DATES[action], **DEPENDENTS[action]}
        data = _home_purchase_inputs(dependent, buy_at=buy_at)
        return data, [f for f in errors(validate_spec(data, config=fixture_config())) if f.code == "event_order"]

    def test_an_event_in_an_earlier_year_than_the_purchase_is_an_error(self):
        for action in DEPENDENTS:
            with self.subTest(action=action):
                _, found = self.findings(action, buy_at={"year": 2028})
                self.assertEqual(len(found), 1)
                self.assertIn("new_home", found[0].message)

    def test_same_month_order_follows_the_engine(self):
        buy_at = {"year": 2027, "month": 3, "day": 5}
        cases = [
            # (action, at, id, rejected): same day and stage fire in id order; prepayments fire after bills.
            ("renew_mortgage", {"year": 2027, "month": 3}, "a_renew", True),
            ("refinance", {"year": 2027, "month": 3, "day": 5}, "a_refinance", True),
            ("refinance", {"year": 2027, "month": 3, "day": 5}, "z_refinance", False),
            ("sell_home", {"year": 2027, "month": 3, "day": 20}, "a_sale", False),
            ("prepay_mortgage", {"year": 2027, "month": 3, "day": 31}, "a_prepay", False),
        ]
        for action, at, event_id, rejected in cases:
            with self.subTest(action=action, event_id=event_id):
                data, found = self.findings(action, buy_at=buy_at, at=at, event_id=event_id)
                self.assertEqual(bool(found), rejected)
                if not rejected:
                    build(data).model.run()

    def test_an_event_relative_to_the_purchase_follows_it(self):
        _, found = self.findings(
            "renew_mortgage", buy_at={"year": 2027, "month": 3}, at={"relative": {"after": "m_buy"}}, event_id="a"
        )
        self.assertEqual(found, [])

    def test_opening_homes_are_unaffected(self):
        data = minimal(
            housing=[
                {
                    "kind": "home",
                    "id": "home",
                    "purchase_price": 250000,
                    "pmi": False,
                    "expenses": {},
                    "mortgage": {"original_amount": 120000, "term_months": 120, "rate_pct": 3},
                }
            ]
        )
        data["events"] = [
            {
                "action": "renew_mortgage",
                "person": "alex",
                "home": "home",
                "at": {"year": 2026, "month": 7},
                "rate_pct": 4,
            }
        ]
        self.assertEqual(errors(validate_spec(data, config=fixture_config())), [])


#: Actions on an added home, by spec inputs (events stage, plus the post_step prepayment).
_ORDER_ACTIONS = {
    "renew_mortgage": {"home": "new_home", "rate_pct": 4},
    "refinance": {"debt": "new_home", "rate_pct": 4, "term_years": 15},
    "move": {"sell_home": "new_home"},
    "pay_mortgage_at_maturity": {"home": "new_home", "interest_due": 10},
    "prepay_mortgage": {"home": "new_home"},
}
#: Dates for the event adding the home: the start year's first month, explicit months and days (including a
#: month's last day, where only the stage orders it against a prepayment), and age timing.
_ADD_DATES = [
    {"year": 2026},
    {"year": 2026, "month": 4},
    {"year": 2027},
    {"year": 2027, "month": 3},
    {"year": 2027, "month": 3, "day": 10},
    {"year": 2027, "month": 3, "day": 31},
    {"age": 41},
]
#: Dates for the action: the same set, more days, and timing relative to the addition (which has its day or not).
_ACTION_DATES = [
    *_ADD_DATES,
    {"year": 2026, "month": 4, "day": 30},
    {"year": 2027, "month": 3, "day": 1},
    {"year": 2027, "month": 3, "day": 20},
    {"relative": {"after": "m_add"}},
    {"relative": {"after": "m_add", "years": 1}},
]


def _order_case(start, adder, add_at, action, at, action_id) -> dict:
    # Born March 1986: age-timed events fall in March, and the opening age matches either start month.
    data = minimal(age=40 if start else 39, birth="1986-03")
    data["meta"]["end_year"] = 2028
    if start is not None:
        data["meta"]["start"] = start
    data["people"][0]["accounts"][0]["balance"] = 500000
    home = {
        "id": "new_home",
        "kind": "home",
        "purchase_price": 300000,
        "down_payment": 60000,
        "pmi": False,
        "expenses": {},
        "mortgage": {"original_amount": 240000, "rate_pct": 5, "term_years": 30},
    }
    add = {"id": "m_add", "person": "alex", "at": add_at, "action": adder}
    add.update({"home": home} if adder == "buy_home" else {"buy_home": home})
    data["events"] = [add, {"id": action_id, "person": "alex", "action": action, "at": at, **_ORDER_ACTIONS[action]}]
    return data


def _engine_fires_action_first(data: dict, config) -> bool | None:
    """Whether the engine fires the action before the addition (None unless both fire in the run).

    Every compiled event's callable is replaced by a recorder, so the order is the engine's real
    firing order and an action on a missing home cannot fail."""
    built = build_household(spec_of(data), config=config, check=False, collect_data=False)
    fired: list[str] = []
    for life_event in built.life_events.life_events:
        life_event.event, life_event.event_args = (lambda source=life_event.spec_source: fired.append(source.id)), ()
    built.model.run()
    return None if len(fired) != 2 else fired[0] != "m_add"


class TestEventOrderMatchesEngine(unittest.TestCase):
    def test_event_order_errors_match_the_engine_firing_order(self):
        """The validator's event_order error appears exactly when the compiled events fire the action first."""
        config = fixture_config()
        compared = {True: 0, False: 0}
        mismatches = []
        grid = itertools.product(
            (None, "2026-04"), ("buy_home", "move"), _ADD_DATES, _ORDER_ACTIONS, _ACTION_DATES, ("a_action", "z_action")
        )
        for case in grid:
            data = _order_case(*case)
            try:
                spec = spec_of(data)
            except ValidationError:
                continue  # a date the action does not accept (e.g. a renewal not on the 1st)
            found = errors(validate_spec(spec, config=config))
            if any(f.code != "event_order" for f in found):
                continue
            first = _engine_fires_action_first(data, config)
            if first is None:
                continue
            compared[first] += 1
            if any(f.code == "event_order" for f in found) != first:
                mismatches.append(
                    (case, "engine fires the action first" if first else "engine fires the addition first")
                )
        self.assertEqual(mismatches, [])
        # Both outcomes are well covered, so the comparison cannot pass vacuously.
        self.assertGreater(compared[True], 300)
        self.assertGreater(compared[False], 300)


class TestSchemaIndependence(unittest.TestCase):
    def test_schema_module_imports_only_the_spec_package(self):
        tree = ast.parse(Path(s.__file__).read_text())
        outside_spec = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level > 1 or (node.level == 0 and module.split(".")[0] == "life_model"):
                    outside_spec.append("." * node.level + module)
            elif isinstance(node, ast.Import):
                outside_spec += [alias.name for alias in node.names if alias.name.split(".")[0] == "life_model"]
        self.assertEqual(outside_spec, [])

    def test_rate_compounding_matches_the_engine(self):
        self.assertEqual(typing.get_args(s.MortgageRateCompounding), typing.get_args(terms.MortgageRateCompounding))


if __name__ == "__main__":
    unittest.main()
