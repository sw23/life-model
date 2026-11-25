# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest

from pydantic import ValidationError

from ..checks import assert_conservation
from ..ledger import account_label
from ..spec import build_household, spec_from_model, validate_spec
from .spec_helpers import fixture_config, minimal, spec_of


def sweep_inputs():
    data = minimal(
        jobs=[],
        spending={"amount_annual": 0, "growth_pct": 2},
        accounts=[
            {"kind": "bank", "id": "source", "primary": True, "balance": 10000, "interest_pct": 0},
            {"kind": "bank", "id": "target", "balance": 20000, "interest_pct": 0},
            {"kind": "bank", "id": "other-cash", "balance": 12000, "interest_pct": 0},
            {"kind": "bank", "id": "reserve", "reserve": True, "balance": 40000, "interest_pct": 0},
        ],
        housing=[
            {
                "kind": "home",
                "id": "home",
                "purchase_price": 6000,
                "value_growth_pct": 0,
                "expenses": {},
                "pmi": False,
            }
        ],
        savings_policy={
            "source_bank": "source",
            "sweep_to": "target",
            "cash_floor": 5000,
            "start_year": 2027,
            "end_year": 2027,
        },
    )
    data["meta"]["end_year"] = 2028
    data["events"] = [
        {
            "action": "sell_home",
            "person": "alex",
            "home": "home",
            "selling_cost_pct": 0,
            "at": {"year": 2028, "month": 6},
        }
    ]
    return data


class TestSavingsSweepControls(unittest.TestCase):
    def build(self, inputs):
        return build_household(spec_of(inputs), config=fixture_config(), collect="month")

    def test_named_source_and_inclusive_year_window_survive_resume(self):
        built = self.build(sweep_inputs())
        built.model.step_year()
        self.assertEqual((built.items["source"].balance, built.items["target"].balance), (10000, 20000))
        restored_spec = spec_from_model(built.model)
        plan = restored_spec.people[0].savings_policy
        self.assertEqual((plan.source_bank, plan.start_year, plan.end_year), ("source", 2027, 2027))
        restored = build_household(restored_spec, config=fixture_config(), collect="month")
        for run in (built, restored):
            run.model.step_year()
            self.assertEqual((run.items["source"].balance, run.items["target"].balance), (5000, 25000))
            run.model.step_year()
            self.assertEqual((run.items["source"].balance, run.items["target"].balance), (11000, 25000))
            self.assertEqual((run.items["other-cash"].balance, run.items["reserve"].balance), (12000, 40000))
            (entry,) = [row for row in run.model.ledger.to_records() if row["cause"] == "savings sweep"]
            self.assertEqual((entry["year"], entry["month"], entry["amount"]), (2027, 12, 5000))
            self.assertEqual(entry["from_account"], account_label(run.items["source"]))
            self.assertEqual(entry["to_account"], account_label(run.items["target"]))
            assert_conservation(run.model, monthly=True)

    def test_named_source_below_floor_does_not_draw_from_other_banks(self):
        inputs = sweep_inputs()
        inputs["people"][0]["accounts"][0]["balance"] = 4000
        built = self.build(inputs)
        built.model.run()
        self.assertEqual((built.items["source"].balance, built.items["target"].balance), (10000, 20000))
        self.assertFalse([row for row in built.model.ledger.to_records() if row["cause"] == "savings sweep"])
        assert_conservation(built.model, monthly=True)

    def test_ira_uses_the_transfer_year_and_preserves_contribution_room(self):
        inputs = sweep_inputs()
        inputs["events"] = []
        owner = inputs["people"][0]
        owner["housing"] = []
        owner["jobs"] = [{"id": "job", "company": "Co", "salary_annual": 60000, "raise_pct": "economy"}]
        owner["accounts"][0].update(primary=False, balance=50000)
        owner["accounts"][2]["primary"] = True
        owner["accounts"].append({"kind": "traditional_ira", "id": "ira", "growth_pct": 0})
        owner["savings_policy"].update(sweep_to="ira")
        built = self.build(inputs)
        built.model.step_year()
        self.assertEqual(built.items["ira"].balance, 0)
        room = built.items["ira"].annual_contribution_limit()
        built.model.step_year()
        self.assertEqual(built.items["ira"].balance, room)
        self.assertEqual(built.model.tax_returns[2027].adjustments["ira_deduction"], room)
        built.model.step_year()
        self.assertEqual(built.items["ira"].balance, room)
        (entry,) = [row for row in built.model.ledger.to_records() if row["cause"] == "savings sweep"]
        self.assertEqual((entry["year"], entry["month"], entry["amount"]), (2027, 1, room))
        self.assertEqual(entry["from_account"], account_label(built.items["source"]))
        assert_conservation(built.model, monthly=True)

    def test_invalid_windows_and_sources_are_rejected(self):
        for changes, pattern in (({"end_year": 2026}, "end before"), ({"source_bank": "target"}, "distinct")):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValidationError, pattern):
                inputs = sweep_inputs()
                inputs["people"][0]["savings_policy"].update(changes)
                spec_of(inputs)
        for source in ("reserve", "future-bank"):
            with self.subTest(source=source):
                inputs = sweep_inputs()
                inputs["events"].append(
                    {
                        "action": "add_account",
                        "person": "alex",
                        "at": "2027-01",
                        "account": {"kind": "bank", "id": "future-bank", "balance": 10000},
                    }
                )
                inputs["people"][0]["savings_policy"]["source_bank"] = source
                findings = validate_spec(spec_of(inputs), config=fixture_config())
                self.assertTrue(any(f.level == "error" and f.path.endswith(".source_bank") for f in findings))


class TestSavingsPolicySourceBank(unittest.TestCase):
    def test_assignment_requires_a_spendable_bank_the_person_owns(self):
        from ..account.bank import BankAccount
        from ..account.brokerage import BrokerageAccount
        from ..model import LifeModel
        from ..people.family import Family
        from ..people.person import Person, Spending
        from ..policies import SavingsPolicy

        model = LifeModel(start_year=2026, end_year=2026, config=fixture_config())
        family = Family(model)
        alex = Person(family, "Alex", 40, 65, Spending(model, base_annual=0))
        sam = Person(family, "Sam", 40, 65, Spending(model, base_annual=0))
        alex.get_married(sam)
        own = BankAccount(alex, balance=1000, interest_pct=0)
        reserve = BankAccount(alex, balance=1000, interest_pct=0, reserve=True)
        spouses = BankAccount(sam, balance=1000, interest_pct=0)
        brokerage, other_brokerage = BrokerageAccount(alex), BrokerageAccount(alex)
        cases = ((reserve, "reserve"), (spouses, "Alex does not own"), (other_brokerage, "bank account"))
        for source, pattern in cases:
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, pattern):
                alex.savings_policy = SavingsPolicy(cash_floor=0, sweep_to=brokerage, source_bank=source)
            self.assertIsNone(alex.savings_policy)
        alex.savings_policy = SavingsPolicy(cash_floor=0, sweep_to=brokerage, source_bank=own)
        self.assertIs(alex.savings_policy.source_bank, own)
