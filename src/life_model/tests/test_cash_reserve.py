# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from datetime import date

from ..account.bank import BankAccount
from ..checks import account_residuals, assert_conservation
from ..lifeevents import LifeEvent, LifeEvents
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..policies import move_from_bank
from ..spec import build_household, spec_from_model
from ..spec.io import Format, dumps, loads
from .spec_helpers import fixture_config, minimal, spec_of


class TestCashReserve(unittest.TestCase):
    def _household(self, spending=0):
        model = LifeModel(start_year=2026, end_year=2026, config=fixture_config(), collect="month", checks="strict")
        owner = Person(Family(model), "Pat", 40, 65, Spending(model, base_annual=spending))
        bank = BankAccount(owner, balance=1000, interest_pct=0)
        return model, owner, bank, LifeEvents(model)

    def test_bills_leave_earmarked_cash_alone_and_release_runs_first_on_its_day(self):
        from ..account.cash_reserve import CashReserve

        model, owner, bank, schedule = self._household(spending=2400)
        snapshots = []
        schedule.add(LifeEvent(2026, "Before release", lambda: snapshots.append(bank.balance), month=2, day=14))
        schedule.add(LifeEvent(2026, "On release day", lambda: snapshots.append(bank.balance), month=2, day=15))
        reserve = CashReserve(
            owner, name="Earmark", amount=900, schedule=schedule, release_on=date(2026, 2, 15), bank=bank
        )
        self.assertEqual((bank.balance, reserve.balance), (100, 900))
        model.step()
        self.assertEqual((bank.balance, reserve.balance, owner.debt), (0, 900, 100))
        model.step()
        self.assertEqual(snapshots, [0, 900])
        self.assertEqual((reserve.balance, owner.debt), (0, 0))
        assert_conservation(model, monthly=True)
        self.assertEqual(account_residuals(model, 2026, month=2), {})

    def test_failed_funding_leaves_the_bank_ledger_and_schedule_unchanged(self):
        from ..account.cash_reserve import CashReserve

        model, owner, bank, schedule = self._household()
        before = len(model.agents), len(model.ledger)
        with self.assertRaisesRegex(ValueError, "insufficient cash"):
            CashReserve(owner, name="Earmark", amount=1001, schedule=schedule, release_on=date(2026, 2, 15), bank=bank)
        self.assertEqual((len(model.agents), len(model.ledger)), before)
        self.assertEqual((bank.balance, schedule.life_events), (1000, []))

    def test_regular_contribution_rejects_cash_reserve_before_debiting_bank(self):
        from ..account.cash_reserve import CashReserve

        model, owner, bank, schedule = self._household()
        reserve = CashReserve(owner, name="Earmark", amount=100, schedule=schedule, release_on=date(2026, 2, 15))
        ledger_size = len(model.ledger)
        with self.assertRaisesRegex(TypeError, "funded at creation"):
            move_from_bank(owner, reserve, 50, cause="Ordinary contribution")
        self.assertEqual((bank.balance, reserve.balance, len(model.ledger)), (1000, 100, ledger_size))

    def test_spec_round_trip_keeps_cash_earmarked_until_its_dated_release(self):
        data = minimal(
            jobs=[],
            spending={"amount_annual": 0},
            accounts=[
                {"id": "cash", "kind": "bank", "balance": 1000, "interest_pct": 0},
                {"id": "investments", "kind": "brokerage", "growth_pct": 0},
            ],
        )
        data["events"] = [
            {
                "id": "earmark",
                "action": "reserve_cash",
                "at": {"year": 2026, "month": 12, "day": 10},
                "person": "alex",
                "bank": "cash",
                "amount": 900,
                "release_on": "2027-02-15",
            },
            {
                "id": "contribution",
                "action": "contribute",
                "at": {"year": 2027, "month": 2, "day": 15},
                "person": "alex",
                "account": "investments",
                "amount": 1000,
            },
        ]
        spec = spec_of(data)
        formats: tuple[Format, ...] = ("json", "yaml")
        for fmt in formats:
            self.assertEqual(loads(dumps(spec, fmt), fmt), spec)
        built = build_household(spec, config=fixture_config(), check=False, collect="month")
        built.model.step_year()
        self.assertEqual((built.items["cash"].balance, built.items["earmark"].balance), (100, 900))
        self.assertEqual(account_residuals(built.model, 2026, month=12), {})
        snapshot = spec_from_model(built.model)
        for fmt in formats:
            with self.subTest(format=fmt):
                rebuilt = build_household(loads(dumps(snapshot, fmt), fmt), config=fixture_config(), collect="month")
                rebuilt.model.step()
                self.assertEqual(rebuilt.items["investments"].balance, 0)
                rebuilt.model.step()
                self.assertEqual((rebuilt.items["earmark"].balance, rebuilt.items["investments"].balance), (0, 1000))
                assert_conservation(rebuilt.model, monthly=True)
                self.assertEqual(account_residuals(rebuilt.model, 2027, month=2), {})


def _reserve_spec(*, bank=50000, amount=60000, at=(2026, 3, 10), release_on="2026-08-15", jobs=(), end=2026):
    data = minimal(
        jobs=list(jobs),
        spending={"amount_annual": 12000},
        accounts=[
            {"kind": "bank", "id": "bank", "balance": bank, "interest_pct": 0},
            {"kind": "brokerage", "id": "investments", "balance": 100000, "growth_pct": 0},
        ],
    )
    data["meta"]["end_year"] = end
    data["events"] = [
        {
            "id": "earmark",
            "action": "reserve_cash",
            "person": "alex",
            "at": {"year": at[0], "month": at[1], "day": at[2]},
            "bank": "bank",
            "amount": amount,
            "release_on": release_on,
        }
    ]
    return data


def _married(data, *, spouse_bank=30000):
    import copy

    sam = copy.deepcopy(data["people"][0])
    sam.update(id="sam", name="Sam", accounts=[{"kind": "bank", "id": "sam_bank", "balance": spouse_bank}])
    data["people"].append(sam)
    data["relationships"] = {"marriages": [{"spouses": ["alex", "sam"], "year": 2020}]}
    return data


class TestReserveCashEvent(unittest.TestCase):
    def _run(self, data):
        built = build_household(spec_of(data), config=fixture_config(), collect="month")
        built.model.checks = "strict"
        built.model.run()
        assert_conservation(built.model, monthly=True)
        return built

    def _reserve_events(self, model):
        return model.event_log.of_kind("cash_reserved")

    def test_reserve_beyond_bank_cash_earmarks_what_is_available(self):
        built = self._run(_reserve_spec())
        (event,) = self._reserve_events(built.model)
        # Two months of $1,000 spending have left $48,000 in the bank by March's events.
        self.assertEqual((event.amount, event.details["requested"]), (48000, 60000))
        self.assertEqual(event.details["available"], 48000)
        self.assertEqual(event.details["release_on"], "2026-08-15")

    def test_reserve_holds_back_the_years_unpaid_tax(self):
        job = {"id": "job", "company": "Co", "salary_annual": 120000, "raise_pct": 0}
        data = _reserve_spec(amount=1_000_000, at=(2026, 12, 5), release_on="2027-02-01", jobs=[job])
        built = self._run(data)
        (event,) = self._reserve_events(built.model)
        (tax_return,) = built.model.tax_returns.values()
        # The holdback is the whole year's unwithheld tax, so December's settlement is paid from the bank.
        self.assertAlmostEqual(event.details["tax_holdback"], tax_return.total_tax, places=2)
        self.assertLess(event.amount, event.details["requested"])
        # Only December's own $1,000 of spending, paid after the earmark, reaches the brokerage account.
        sales = sum(e.amount for e in built.model.event_log.of_kind("forced_sale"))
        self.assertAlmostEqual(sales, 1000, places=2)

    def test_reserve_with_no_spare_cash_is_skipped_and_logged(self):
        built = self._run(_reserve_spec(bank=0))
        (event,) = self._reserve_events(built.model)
        self.assertEqual((event.amount, event.details["requested"]), (0, 60000))
        self.assertNotIn("earmark", built.items)

    def test_reserve_after_the_owner_dies_follows_the_bank_to_the_spouse(self):
        data = _married(_reserve_spec(amount=5000, at=(2027, 3, 10), release_on="2027-06-15", end=2027))
        data["events"].append({"action": "die", "person": "alex", "at": {"year": 2027}})
        built = self._run(data)
        (event,) = self._reserve_events(built.model)
        self.assertEqual((event.person_name, event.amount), ("Sam", 5000))
        self.assertEqual(built.items["earmark"].owner.name, "Sam")

    def test_reserve_after_a_single_owner_dies_is_skipped(self):
        data = _reserve_spec(amount=5000, at=(2027, 3, 10), release_on="2027-06-15", end=2027)
        data["events"].append({"action": "die", "person": "alex", "at": {"year": 2027}})
        built = self._run(data)
        self.assertEqual(self._reserve_events(built.model), [])
        self.assertTrue(any("reserve skipped" in e.message for e in built.model.event_log.of_kind("note")))

    def test_earmarked_cash_has_its_own_model_frame_column(self):
        built = self._run(_reserve_spec(amount=20000, release_on="2027-02-15", end=2026))
        frame = built.model.datacollector.get_model_vars_dataframe()
        row = frame.iloc[-1]
        self.assertEqual(row["Cash Reserve Balance"], 20000)
        sheet = built.model.month_balance_sheets[(2026, 12)].closing
        self.assertAlmostEqual(row["Bank Balance"] + row["Cash Reserve Balance"] + 100000, sheet.net_worth, places=6)

    def test_validator_warns_when_a_release_falls_after_the_run(self):
        from ..spec.validate import validate_spec, warnings_of

        data = _reserve_spec(amount=1000, release_on="2028-01-15", end=2026)
        data["people"][0]["accounts"].append(
            {"kind": "cash_reserve", "id": "held", "balance": 500, "release_on": "2027-05-01"}
        )
        codes = {(f.path, f.code) for f in warnings_of(validate_spec(spec_of(data)))}
        self.assertIn(("events[0].release_on", "release_after_run"), codes)
        self.assertIn(("people[0].accounts[2].release_on", "release_after_run"), codes)
