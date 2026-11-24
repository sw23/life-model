# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Dated event plumbing in the spec layer: event dates, snapshot re-dating, event order checks and the
schema's independence from the engine."""

import unittest
import warnings
from datetime import date

from ..lifeevents import LifeEvent
from ..model import EVENT_KIND_DOCS
from ..spec import SpecWarning, build_household
from ..spec import events as spec_events
from ..spec import schema as s
from .spec_helpers import fixture_config, spec_of


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
        for month, day, message in ((13, None, "1-12"), (None, 5, "explicit month"), (2, 30, "day is out of range")):
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


if __name__ == "__main__":
    unittest.main()
