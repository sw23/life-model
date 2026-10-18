# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Typed events (Plan 28, task 4)."""

import unittest

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount
from ..account.job401k import Job401kAccount
from ..account.traditional_IRA import TraditionalIRA
from ..lifeevents import LifeEvent, LifeEventRecord, LifeEvents
from ..model import EVENT_COLUMNS, Event, EventKind, EventLog, LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..work.job import Job, Salary


def _person(model, age=40, spending=0, name="Pat"):
    return Person(Family(model), name, age, 65, Spending(model, base_annual=spending))


class TestEventConstruction(unittest.TestCase):
    def test_free_text_event_is_unchanged(self):
        model = LifeModel(start_year=2026, end_year=2026)
        event = Event("Something happened")
        self.assertEqual(event.kind, EventKind.NOTE)
        self.assertEqual(event.message, "Something happened")
        self.assertIsNone(event.year)
        model.event_log.add(event)
        self.assertEqual(event.year, 2026)
        self.assertEqual(event._repr_html_(), "<tr><td>2026</td><td>Something happened</td></tr>\n")

    def test_typed_event_generates_its_message(self):
        model = LifeModel(start_year=2026, end_year=2026)
        person = _person(model)
        account = BrokerageAccount(person, company="Broker", balance=1000)
        event = Event(EventKind.FORCED_SALE, person=person, amount=1234.5, account=account, cause="pay the bills")
        self.assertEqual(event.message, "Pat sold $1,234 of Pat's BrokerageAccount (Broker) to pay the bills")
        self.assertEqual(event.person_name, "Pat")
        self.assertEqual(event.person_id, person.unique_id)
        self.assertEqual(event.account, f"BrokerageAccount:{account.unique_id}")
        self.assertTrue(event.is_detail)
        withdrawal = Event(EventKind.PRETAX_WITHDRAWAL, person=person, amount=500, cause="fund bills", target=750)
        self.assertIn("solver target $750", withdrawal.message)
        self.assertEqual(withdrawal.details, {"target": 750})

    def test_explicit_year_is_kept(self):
        model = LifeModel(start_year=2026, end_year=2026)
        event = Event(EventKind.MARRIED, 2020, "Pat", message="Pat married")
        model.event_log.add(event)
        self.assertEqual(event.year, 2020)


class TestEventLog(unittest.TestCase):
    def test_html_table_shows_the_life_story_only(self):
        model = LifeModel(start_year=2026, end_year=2026)
        log = EventLog(model)
        log.add(Event("Got a dog"))
        log.add(Event(EventKind.RMD, person="Pat", amount=100))
        log.add(Event(EventKind.DIED, person="Pat", message="Pat died at age 90"))
        self.assertEqual(
            log._repr_html_(),
            "<table><tr><th>Year:</th><th>Event:</th></tr>\n"
            "<tr><td>2026</td><td>Got a dog</td></tr>\n"
            "<tr><td>2026</td><td>Pat died at age 90</td></tr>\n"
            "</table>",
        )
        self.assertEqual(len(log.list), 3)
        self.assertEqual([e.kind for e in log.of_kind("rmd")], [EventKind.RMD])
        frame = log.to_frame()
        self.assertEqual(list(frame.columns), list(EVENT_COLUMNS))
        self.assertEqual(frame.kind.tolist(), ["note", "rmd", "died"])


class TestEngineEvents(unittest.TestCase):
    def test_settlement_logs_forced_sales_and_pretax_withdrawals_with_cause(self):
        model = LifeModel(start_year=2026, end_year=2026)
        person = _person(model, age=50, spending=120000)
        BankAccount(person, company="Bank", balance=1000)
        BrokerageAccount(person, company="Broker", balance=40000)
        job = Job(person, company="Old job", role="Retired", salary=Salary(model, base_annual=0))
        job.retired = True
        Job401kAccount(job, pretax_balance=500000)
        model.run()
        # Plan 32: the month's bills sell the brokerage until it is gone, then draw pre-tax money,
        # month by month; December's tax settlement draws a sized pre-tax amount for the taxes.
        sales = model.event_log.of_kind(EventKind.FORCED_SALE)
        self.assertGreater(sum(sale.amount for sale in sales), 40000)  # the whole (grown) brokerage account
        self.assertEqual(person.brokerage_balance, 0)
        for sale in sales:
            self.assertRegex(sale.cause, r"^pay 2026-\d\d bills$")
        withdrawals = model.event_log.of_kind(EventKind.PRETAX_WITHDRAWAL)
        *monthly, taxes = withdrawals
        for withdrawal in monthly:
            self.assertRegex(withdrawal.cause, r"^pay 2026-\d\d bills$")
        self.assertEqual(taxes.cause, "fund 2026 taxes")
        self.assertAlmostEqual(taxes.amount, taxes.details["target"], places=2)
        total = sum(withdrawal.amount for withdrawal in withdrawals)
        self.assertGreater(total, 120000 - 41000)
        (penalty,) = model.event_log.of_kind(EventKind.PENALTY)  # 10% early-withdrawal tax at 50
        self.assertAlmostEqual(penalty.amount, total * 0.10, places=2)

    def test_rmds_shortfalls_and_life_events_are_logged(self):
        model = LifeModel(start_year=2026, end_year=2027)
        retiree = _person(model, age=80, spending=90000)
        BankAccount(retiree, company="Bank", balance=1000)
        TraditionalIRA(retiree, balance=20000)
        LifeEvents(model, [LifeEvent(2027, "Trip", retiree.spending.add_expense, 5000)])
        model.run()
        rmds = model.event_log.of_kind(EventKind.RMD)
        self.assertEqual([e.year for e in rmds], [2026])  # the IRA is drained in the first year
        self.assertTrue(model.event_log.of_kind(EventKind.SHORTFALL_DEBT))
        (fired,) = model.event_log.of_kind(EventKind.LIFE_EVENT_FIRED)
        self.assertIsInstance(fired, LifeEventRecord)
        self.assertEqual(
            (fired.year, fired.name, fired.stage, fired.message), (2027, "Trip", "events", "Life event: Trip")
        )

    def test_legacy_messages_keep_their_text(self):
        model = LifeModel(start_year=2026, end_year=2027)
        family = Family(model)
        a = Person(family, "A", 64, 65, Spending(model, base_annual=0))
        b = Person(family, "B", 60, 65, Spending(model, base_annual=0))
        BankAccount(a, company="Bank", balance=1000)
        Job(a, company="Co", role="Dev", salary=Salary(model, base_annual=50000))
        a.get_married(b)
        model.run()
        messages = {e.kind: e.message for e in model.event_log.list}
        self.assertEqual(messages[EventKind.MARRIED], "A and B got married at age 64 and 60")
        self.assertEqual(messages[EventKind.RETIRED], "A retired from Co")

    def test_eval_event_can_log(self):
        model = LifeModel(start_year=2026, end_year=2026)
        fired = []
        event = LifeEvent(2026, "Direct", fired.append, 1)
        self.assertTrue(event.eval_event(2026, model=model))
        self.assertEqual(fired, [1])
        self.assertEqual(model.event_log.list[-1].kind, EventKind.LIFE_EVENT_FIRED)


if __name__ == "__main__":
    unittest.main()
