# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Household spec builder: construction order, field mapping, core workarounds and events."""

import copy
import json
import random
import unittest
import warnings
from unittest import mock

from ..insurance.life_insurance import PremiumIncreaseType
from ..lifeevents import LifeEvents
from ..model import LifeModel
from ..people.person import Person
from ..people.tax_unit import TaxUnit
from ..people.types import MortalityMode
from ..spec import (
    SpecValidationError,
    SpecWarning,
    build_household,
    build_model,
    canonical,
    create_model,
    dumps,
    load_example,
    populate_model,
)
from ..tax.federal import FilingStatus
from .spec_helpers import fixture_config, minimal, spec_of


def build(data: dict, **kwargs):
    """Build raw spec data, ignoring validator warnings."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SpecWarning)
        return build_household(spec_of(data), **kwargs)


#: Lists whose order is part of the value (not a collection of entities).
_ORDERED_VALUES = {
    "spouses",
    "vesting_schedule_pct",
    "signon_vesting_schedule_pct",
    "beneficiaries",
    "withdrawal_order",
}


def _shuffled(data, rng: random.Random):
    """Every list in ``data`` shuffled (recursively), except ordered values such as marriage spouses."""
    if isinstance(data, dict):
        return {key: (value if key in _ORDERED_VALUES else _shuffled(value, rng)) for key, value in data.items()}
    if isinstance(data, list):
        items = [_shuffled(item, rng) for item in data]
        rng.shuffle(items)
        return items
    return data


class TestConstructionOrderIndependence(unittest.TestCase):
    """D5: the builder owns construction order, so list order never changes the result."""

    def _frames(self, data: dict):
        model = build(data).model
        model.run()
        collector = model.datacollector
        return collector.get_model_vars_dataframe(), collector.get_agent_vars_dataframe()

    def test_shuffled_specs_produce_identical_frames(self):
        for name in ("married_homeowners", "retiree_couple", "single_renter"):
            spec = load_example(name)
            data = json.loads(dumps(spec, "json"))
            data["meta"]["end_year"] = 2040
            base_model, base_agents = self._frames(data)
            for trial in range(5):
                with self.subTest(example=name, trial=trial):
                    shuffled = _shuffled(copy.deepcopy(data), random.Random(trial))
                    self.assertEqual(dumps(canonical(spec_of(shuffled))), dumps(canonical(spec_of(data))))
                    model_df, agent_df = self._frames(shuffled)
                    self.assertTrue(model_df.equals(base_model))
                    self.assertTrue(agent_df.equals(base_agents))

    def test_head_of_married_unit_is_first_listed_spouse(self):
        data = json.loads(dumps(load_example("married_homeowners"), "json"))
        data["people"].reverse()
        built = build(data)
        self.assertEqual([m.name for m in built.family.members], ["John", "Jane"])
        data["relationships"]["marriages"][0]["spouses"] = ["jane", "john"]
        built = build(data)
        self.assertEqual([m.name for m in built.family.members], ["Jane", "John"])

    def test_primary_bank_receives_income(self):
        data = minimal()
        data["people"][0]["accounts"] = [
            {"kind": "bank", "id": "a_savings", "company": "A", "type": "Savings", "balance": 1},
            {"kind": "bank", "id": "z_checking", "company": "Z", "balance": 2, "primary": True},
        ]
        built = build(data)
        self.assertIs(built.people["alex"].bank_accounts[0], built.items["z_checking"])


class TestFieldMapping(unittest.TestCase):
    def test_person_and_meta(self):
        data = minimal(gender="female", mortality="fixed_age", death_age=90)
        data["meta"].update({"seed": 3, "default_state": "CA"})
        built = build(data)
        person = built.people["alex"]
        self.assertEqual((person.name, person.age, person.retirement_age), ("Alex", 40, 65))
        self.assertEqual(person.mortality_mode, MortalityMode.FIXED_AGE)
        self.assertEqual(person.death_age, 90)
        self.assertEqual(person.state, "CA")
        self.assertIsNone(person.spending._yearly_increase_override)  # "economy"
        self.assertEqual((built.model.start_year, built.model.end_year), (2026, 2030))
        data["people"][0]["state"] = "NY"
        self.assertEqual(build(data).people["alex"].state, "NY")

    def test_seed_and_economy_overrides(self):
        data = minimal()
        data["meta"].update({"seed": 5, "scenario": "recession"})
        data["economy"] = {"inflation_pct": 4.5, "stochastic": {"equity_vol_pct": 20}}
        model = build(data).model
        self.assertEqual(model.config.scenario, "recession")
        self.assertEqual(model.config.economy.inflation, 4.5)
        self.assertEqual(model.config.economy.stochastic.equity_vol, 20)
        # The simulation's economy (not just the config) runs on the overrides.
        self.assertEqual(model.economy.inflation(2026), 4.5)
        fixed = minimal()
        fixed["economy"] = {"mode": "fixed", "equity_return_pct": 1.5, "inflation_pct": 9}
        economy = build(fixed).model.economy
        self.assertEqual((economy.rate("equity_return", 2026), economy.inflation(2027)), (1.5, 9))
        a = LifeModel(seed=5).random.random()
        self.assertEqual(build(minimal() | {"meta": data["meta"]}).model.random.random(), a)
        self.assertEqual(build(data, seed=9).model.random.random(), LifeModel(seed=9).random.random())

    def test_brokerage_lots_use_deposit_with_basis(self):
        data = minimal()
        data["people"][0]["accounts"].append(
            {
                "kind": "brokerage",
                "id": "taxable",
                "lots": [
                    {"value": 100000, "cost_basis": 40000, "acquired_year": 2010},
                    {"value": 20000, "cost_basis": 20000},
                ],
            }
        )
        brokerage = build(data).items["taxable"]
        self.assertEqual(brokerage.balance, 120000)
        self.assertEqual(brokerage.unrealized_gain, 60000)
        self.assertEqual([lot.acquired_year for lot in brokerage.lots], [2010, 2026])

    def test_loan_in_progress_keeps_the_original_payment(self):
        data = minimal()
        data["people"][0]["debts"] = [
            {"kind": "car", "id": "car", "original_amount": 30000, "balance": 18000, "rate_pct": 6, "term_years": 5}
        ]
        loan = build(data).items["car"]
        self.assertEqual((loan.loan_amount, loan.principal), (30000, 18000))
        self.assertAlmostEqual(loan.monthly_payment, 579.98, places=2)

    def test_level_term_premium_stays_level(self):
        data = minimal()
        data["people"][0]["insurance"] = [
            {
                "kind": "life",
                "id": "level",
                "policy": "term",
                "death_benefit": 5e5,
                "premium_monthly": 50,
                "term_years": 20,
            },
            {
                "kind": "life",
                "id": "banded",
                "policy": "term",
                "death_benefit": 5e5,
                "premium_monthly": 50,
                "term_years": 20,
                "premium_schedule": "age_banded",
            },
        ]
        built = build(data, config=fixture_config())
        built.model.step()
        built.model.step()
        self.assertEqual(built.items["level"].monthly_premium, 50)
        self.assertEqual(built.items["level"].premium_increase_type, PremiumIncreaseType.AGE_BASED)
        self.assertEqual(built.items["level"].age_multipliers, {})
        self.assertGreater(built.items["banded"].monthly_premium, 50)

    def test_home_mortgage_and_expenses(self):
        data = minimal()
        data["people"][0]["housing"] = [
            {
                "kind": "home",
                "id": "house",
                "purchase_price": 400000,
                "down_payment": 80000,
                "mortgage": {"original_amount": 320000, "balance": 300000, "rate_pct": 6, "term_years": 30},
                "expenses": {"property_tax_pct": 1, "insurance_pct": 0.5, "hoa_monthly": 125},
            }
        ]
        home = build(data).items["house"]
        self.assertEqual(home.expenses.hoa_amount, 1500)
        self.assertEqual(home.mortgage.principal, 300000)
        self.assertEqual(home.mortgage.start_date, 2026)
        self.assertIsNone(home._value_yearly_increase_override)

    def test_married_filing_separately(self):
        data = minimal()
        data["people"].append({**copy.deepcopy(data["people"][0]), "id": "bo", "name": "Bo"})
        data["people"][1]["jobs"][0]["id"] = "bo_job"
        data["relationships"] = {"marriages": [{"spouses": ["alex", "bo"], "filing_status": "separate"}]}
        built = build(data)
        a, b = built.people["alex"], built.people["bo"]
        self.assertIs(a.spouse, b)
        self.assertEqual((a.filing_status, b.filing_status), (FilingStatus.MARRIED_FILING_SEPARATELY,) * 2)
        self.assertEqual(len(TaxUnit.build_units(built.family)), 2)
        data["relationships"]["marriages"][0]["filing_status"] = "joint"
        self.assertEqual(len(TaxUnit.build_units(build(data).family)), 1)

    def test_future_marriage_is_an_event(self):
        data = minimal()
        data["people"].append({**copy.deepcopy(data["people"][0]), "id": "bo", "name": "Bo"})
        data["people"][1]["jobs"][0]["id"] = "bo_job"
        data["relationships"] = {"marriages": [{"spouses": ["alex", "bo"], "year": 2028}]}
        built = build(data)
        self.assertIsNone(built.people["alex"].spouse)
        (life_event,) = built.life_events.life_events
        self.assertEqual(life_event.year, 2028)
        life_event.eval_event(2028)
        self.assertEqual(built.people["alex"].filing_status, FilingStatus.MARRIED_FILING_JOINTLY)

    def test_social_security_synthesized_history(self):
        data = minimal()
        data["people"][0]["social_security"] = {"claim_age": 67, "assumed_career_start_age": 22}
        built = build(data)
        ss = built.people["alex"].social_security
        years = [income.year for income in ss.income_history]
        self.assertEqual(years, list(range(2026 - 18, 2026)))
        self.assertEqual(ss.withdrawal_start_age, 67)
        cap = built.model.config_for_year(2025).tax.fica.social_security_max_income
        self.assertTrue(all(income.amount <= cap for income in ss.income_history))

    def test_handles_and_spec_ids(self):
        built = build(json.loads(dumps(load_example("married_homeowners"), "json")))
        self.assertEqual(set(built.people), {"john", "jane"})
        self.assertIs(built.items["jane_brokerage"], built.people["jane"].brokerage_accounts[0])
        self.assertEqual(built.items["jane_brokerage"].spec_id, "jane_brokerage")
        self.assertIn("john.accounts[0]", built.items)  # generated key for an item without an id
        self.assertIs(built.model.household, built)

    def test_populate_into_a_model_subclass(self):
        class Custom(LifeModel):
            pass

        spec = spec_of(minimal())
        model = create_model(spec, model_cls=Custom)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SpecWarning)
            built = populate_model(model, spec)
        self.assertIsInstance(built.model, Custom)
        self.assertEqual(len(built.people["alex"].jobs), 1)


class TestBuildChecks(unittest.TestCase):
    def test_errors_raise_and_warnings_warn(self):
        data = minimal(accounts=[])
        with self.assertRaises(SpecValidationError) as ctx:
            build_model(spec_of(data))
        self.assertEqual([f.code for f in ctx.exception.findings], ["no_bank_account"])
        data = minimal()
        data["people"][0]["spending"]["growth_pct"] = 0
        with self.assertWarns(SpecWarning):
            build_model(spec_of(data))

    def test_not_yet_supported_is_rejected_even_without_checks(self):
        data = minimal()
        data["people"][0]["accounts"][0]["compounding"] = "monthly"
        with self.assertRaises(SpecValidationError):
            build_model(spec_of(data), check=False)
        data = minimal(accounts=[])  # an ordinary error is skipped with check=False
        build_model(spec_of(data), check=False)


class TestEventTiming(unittest.TestCase):
    def test_age_events_resolve_through_get_year_at_age(self):
        """No age arithmetic of its own: the builder defers to Person.get_year_at_age (Plan 26 item 1)."""
        data = minimal()
        data["meta"]["end_year"] = 2100
        data["events"] = [{"at": {"age": 50}, "person": "alex", "action": "one_time_expense", "amount": 1}]
        built = build(data)
        (life_event,) = built.life_events.life_events
        self.assertEqual(life_event.year, built.people["alex"].get_year_at_age(50))
        with mock.patch.object(Person, "get_year_at_age", lambda self, age: 2077):
            built = build(data)
        self.assertEqual(built.life_events.life_events[0].year, 2077)

    def test_relative_events_follow_their_anchor_and_fire_after_it(self):
        data = minimal()
        data["events"] = [
            {"id": "b", "at": {"relative": {"after": "a", "years": 0}}, "person": "alex", "action": "retire"},
            {"id": "a", "at": {"year": 2027}, "person": "alex", "action": "one_time_expense", "amount": 5},
            {"at": {"relative": {"after": "a", "years": 2}}, "person": "alex", "action": "retire"},
        ]
        events = build(data).life_events.life_events
        self.assertEqual(
            [(e.year, e.spec_source.action) for e in events],
            [(2027, "one_time_expense"), (2027, "retire"), (2029, "retire")],
        )

    def test_life_events_agent_only_when_needed(self):
        built = build(minimal())
        self.assertIsNone(built.life_events)
        self.assertFalse(any(isinstance(a, LifeEvents) for a in built.model.agents))


class TestEventActions(unittest.TestCase):
    """Each action compiles to a LifeEvent whose effect is checked by firing it directly (the engine's
    firing stage is Plan 26's concern)."""

    def _fire(self, data: dict, events: list[dict]):
        data["meta"]["end_year"] = 2035
        data["events"] = events
        built = build(data)
        for life_event in list(built.life_events.life_events) if built.life_events else []:
            life_event.eval_event(life_event.year)
        return built

    def _couple(self) -> dict:
        data = minimal()
        data["people"].append({**copy.deepcopy(data["people"][0]), "id": "bo", "name": "Bo"})
        data["people"][1]["jobs"][0]["id"] = "bo_job"
        return data

    def test_marry(self):
        built = self._fire(self._couple(), [{"at": 2027, "person": "bo", "spouse": "alex", "action": "marry"}])
        self.assertIs(built.people["bo"].spouse, built.people["alex"])
        self.assertEqual(built.family.members[0].name, "Bo")  # the marrying person heads the unit

    def test_retire(self):
        built = self._fire(minimal(), [{"at": 2028, "person": "alex", "action": "retire"}])
        self.assertTrue(all(job.retired for job in built.people["alex"].jobs))
        self.assertTrue(built.people["alex"].retirement_triggered)

    def test_change_job(self):
        data = minimal()
        events = [
            {"at": 2027, "person": "alex", "action": "change_job", "job": "job", "salary_annual": 95000},
            {
                "at": 2028,
                "person": "alex",
                "action": "change_job",
                "new_job": {"id": "job2", "company": "New Co", "salary_annual": 70000},
            },
        ]
        built = self._fire(data, events)
        self.assertEqual(built.items["job"].salary.base, 95000)
        self.assertEqual([j.company for j in built.people["alex"].jobs], ["Co", "New Co"])
        self.assertIs(built.items["job2"], built.people["alex"].jobs[1])

    def test_layoff_with_severance(self):
        built = self._fire(
            minimal(),
            [{"at": 2027, "person": "alex", "action": "change_job", "job": "job", "stop": True, "severance": 9000}],
        )
        alex = built.people["alex"]
        self.assertTrue(built.items["job"].retired)
        self.assertEqual(alex.bank_account_balance, 29000)
        self.assertEqual(alex.fica_wages, 9000)

    def test_move_sell_buy_and_rentals(self):
        data = self._couple()
        data["relationships"] = {"marriages": [{"spouses": ["alex", "bo"]}]}
        data["people"][0]["accounts"][0]["balance"] = 200000
        data["people"][0]["housing"] = [
            {
                "kind": "home",
                "id": "old",
                "purchase_price": 300000,
                "expenses": {"property_tax_pct": 1, "insurance_pct": 0.5},
            },
            {"kind": "rental", "id": "flat", "rent_monthly": 1000, "rent_growth_pct": 3},
        ]
        new_home = {
            "kind": "home",
            "id": "new",
            "purchase_price": 250000,
            "down_payment": 50000,
            "expenses": {"property_tax_pct": 1, "insurance_pct": 0.5},
        }
        events = [
            {"at": 2027, "person": "alex", "action": "move", "state": "TX", "end_rental": "flat", "sell_home": "old"},
            {"at": 2028, "person": "alex", "action": "buy_home", "home": new_home},
            {
                "at": 2029,
                "person": "alex",
                "action": "move",
                "new_rental": {"kind": "rental", "id": "beach", "rent_monthly": 900, "rent_growth_pct": 3},
            },
            {"at": 2030, "person": "alex", "action": "sell_home", "home": "new"},
        ]
        built = self._fire(data, events)
        alex = built.people["alex"]
        self.assertEqual((alex.state, built.people["bo"].state), ("TX", "TX"))
        self.assertTrue(built.items["old"].sold and built.items["new"].sold)
        self.assertEqual([a.name for a in alex.apartments], ["Apartment"])
        self.assertIs(alex.apartments[0], built.items["beach"])
        self.assertTrue(any("bought" in e.message for e in built.model.event_log.list))

    def test_expenses_and_spending(self):
        data = minimal()
        events = [
            {"id": "lump", "at": 2027, "person": "alex", "action": "one_time_expense", "amount": 1234},
            {"at": 2028, "person": "alex", "action": "recurring_expense", "amount_annual": 100, "until": 2030},
            {"at": 2031, "person": "alex", "action": "recurring_expense", "amount_annual": 10},
            {"at": 2032, "person": "alex", "action": "change_spending", "change_pct": -50},
            {"at": 2033, "person": "alex", "action": "change_spending", "amount_annual": 7000},
        ]
        data["meta"]["end_year"] = 2035
        data["events"] = events
        built = build(data)
        alex = built.people["alex"]
        by_action: dict[str, list] = {}
        for life_event in built.life_events.life_events:
            by_action.setdefault(life_event.spec_source.action, []).append(life_event.year)
        self.assertEqual(by_action["one_time_expense"], [2027])
        self.assertEqual(by_action["recurring_expense"], [2028, 2029, 2030, 2031, 2032, 2033, 2034, 2035])
        for life_event in built.life_events.life_events[:4]:
            life_event.eval_event(life_event.year)
        self.assertEqual(alex.spending.one_time_expenses, 1234 + 300)
        changes = [e for e in built.life_events.life_events if e.spec_source.action == "change_spending"]
        changes[0].eval_event(changes[0].year)
        self.assertEqual(alex.spending.base, 15000)
        changes[1].eval_event(changes[1].year)
        self.assertEqual(alex.spending.base, 7000)

    def test_add_account_and_contribute(self):
        data = minimal()
        data["people"][0]["accounts"].append({"kind": "roth_ira", "id": "roth"})
        events = [
            {"at": 2027, "person": "alex", "action": "add_account", "account": {"kind": "brokerage", "id": "taxable"}},
            {"at": 2028, "person": "alex", "action": "contribute", "account": "taxable", "amount": 5000},
            {"at": 2028, "person": "alex", "action": "contribute", "account": "roth", "amount": 50000},
        ]
        built = self._fire(data, events)
        alex = built.people["alex"]
        roth = built.items["roth"]
        self.assertEqual(built.items["taxable"].balance, 5000)
        self.assertGreater(roth.balance, 0)
        self.assertEqual(roth.balance, roth.annual_contribution_limit())  # capped at the limit
        self.assertAlmostEqual(alex.bank_account_balance, 20000 - 5000 - roth.balance)

    def test_claim_and_die_are_build_time(self):
        data = minimal()
        data["people"][0]["social_security"] = {"claim_age": 67, "earnings_history": {2020: 50000}}
        data["meta"]["end_year"] = 2080
        data["events"] = [
            {"at": {"age": 70}, "person": "alex", "action": "claim_social_security"},
            {"at": 2060, "person": "alex", "action": "die"},
        ]
        built = build(data)
        alex = built.people["alex"]
        self.assertEqual(alex.social_security.withdrawal_start_age, 70)  # an age is the engine's age
        self.assertEqual(alex.mortality_mode, MortalityMode.FIXED_AGE)
        self.assertIsNone(built.life_events)
        # A year takes effect in that year: the person is alive through 2059 and dies in 2060.
        model = built.model
        while model.year < 2060:
            model.step()
        self.assertFalse(alex.is_deceased)
        model.step()
        self.assertTrue(alex.is_deceased)

    def test_claim_by_year_starts_benefits_that_year(self):
        data = minimal(retirement_age=62, jobs=[])
        data["people"][0]["age"] = 60
        data["people"][0]["social_security"] = {
            "claim_age": 67,
            "earnings_history": {y: 60000 for y in range(1990, 2026)},
        }
        data["events"] = [{"at": 2029, "person": "alex", "action": "claim_social_security"}]
        model = build(data).model
        incomes = {}
        for _ in range(5):
            year = model.year
            model.step()
            incomes[year] = model.household.people["alex"].stat_ss_income
        self.assertEqual([y for y, v in incomes.items() if v > 0], [2029, 2030])


if __name__ == "__main__":
    unittest.main()
