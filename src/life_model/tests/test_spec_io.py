# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Household spec: schema, YAML/JSON IO, examples, round trip, CLI and generated docs."""

import contextlib
import io
import json
import tomllib
import unittest
import warnings
from pathlib import Path

from pydantic import ValidationError

from ..spec import (
    EXAMPLES,
    HouseholdSpec,
    build_model,
    canonical,
    dumps,
    json_schema,
    load_example,
    loads,
    spec_from_model,
    validate_spec,
)
from ..spec.__main__ import main as cli_main
from ..spec.docs import render_markdown
from ..spec.schema import NYS_KEY, At
from .spec_helpers import minimal, spec_of

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNABLE_EXAMPLES = tuple(name for name in EXAMPLES if name != "self_employed")


class TestSchema(unittest.TestCase):
    def test_extra_keys_are_rejected_everywhere(self):
        data = minimal()
        data["people"][0]["accounts"][0]["intrest_pct"] = 4.0
        with self.assertRaises(ValidationError):
            spec_of(data)
        data = minimal()
        data["meta"]["strat_year"] = 2026
        with self.assertRaises(ValidationError):
            spec_of(data)

    def test_negative_balances_are_rejected(self):
        data = minimal()
        data["people"][0]["debts"] = [
            {"kind": "car", "original_amount": 20000, "balance": -5, "rate_pct": 5, "term_years": 5}
        ]
        with self.assertRaises(ValidationError):
            spec_of(data)

    def test_at_accepts_shorthand_and_needs_exactly_one_time(self):
        self.assertEqual(At.model_validate(2030).year, 2030)
        self.assertEqual(At.model_validate("2031").year, 2031)
        with self.assertRaises(ValidationError):
            At.model_validate({"year": 2030, "age": 50})
        with self.assertRaises(ValidationError):
            At.model_validate({})

    def test_integer_529_kind_from_yaml(self):
        # YAML reads `kind: 529` as an integer; the account still resolves to a 529 plan.
        text = dumps(spec_of(minimal())).replace(
            "  - kind: bank\n", "  - kind: 529\n    balance: 100\n  - kind: bank\n"
        )
        spec = loads(text)
        self.assertEqual([a.kind for a in spec.people[0].accounts], ["529", "bank"])
        self.assertIn("kind: '529'", dumps(spec))

    def test_json_schema_is_embeddable(self):
        schema = json_schema()
        self.assertEqual(schema["title"], "HouseholdSpec")
        self.assertIn("$defs", schema)
        json.dumps(schema)  # serializable as-is
        # Not-yet-supported fields are flagged in the schema itself.
        self.assertIn(NYS_KEY, json.dumps(schema["$defs"]["Mortgage"]))

    def test_every_rate_field_ends_in_pct(self):
        for model in _all_models():
            for name, info in model.model_fields.items():
                extra = info.json_schema_extra if isinstance(info.json_schema_extra, dict) else {}
                if extra.get("x-unit") == "percent":
                    self.assertTrue(name.endswith("_pct"), f"{model.__name__}.{name} is a percent but not *_pct")
                if name.endswith("_pct"):
                    self.assertEqual(extra.get("x-unit"), "percent", f"{model.__name__}.{name} lacks unit percent")

    def test_every_flow_states_its_period(self):
        for model in _all_models():
            for name, info in model.model_fields.items():
                extra = info.json_schema_extra if isinstance(info.json_schema_extra, dict) else {}
                unit = extra.get("x-unit")
                if unit == "USD/year":
                    self.assertTrue(name.endswith("_annual") or name == "earnings_history", f"{model.__name__}.{name}")
                if unit == "USD/month":
                    self.assertTrue(name.endswith("_monthly"), f"{model.__name__}.{name}")
                if name.endswith("_annual"):
                    self.assertEqual(unit, "USD/year", f"{model.__name__}.{name}")
                if name.endswith("_monthly"):
                    self.assertEqual(unit, "USD/month", f"{model.__name__}.{name}")


def _all_models():
    from ..spec.docs import _models_in_order

    return _models_in_order()


class TestIO(unittest.TestCase):
    def test_yaml_and_json_round_trip_byte_stably(self):
        for name in EXAMPLES:
            spec = load_example(name)
            for fmt in ("yaml", "json"):
                with self.subTest(example=name, fmt=fmt):
                    text = dumps(spec, fmt)
                    again = loads(text, fmt)
                    self.assertEqual(again, spec)
                    self.assertEqual(dumps(again, fmt), text)

    def test_format_is_detected(self):
        spec = load_example("single_renter")
        self.assertEqual(loads(dumps(spec, "json")), spec)
        self.assertEqual(loads(dumps(spec, "yaml")), spec)

    def test_dump_omits_defaults_and_writes_whole_dollars_as_ints(self):
        text = dumps(spec_of(minimal()))
        self.assertIn("balance: 20000\n", text)
        self.assertNotIn("primary", text)
        self.assertTrue(text.startswith("spec_version: 1\n"))


class TestExamples(unittest.TestCase):
    def test_examples_are_synthetic_and_documented(self):
        for name in EXAMPLES:
            text = (REPO_ROOT / "src" / "life_model" / "spec" / "examples" / f"{name}.yaml").read_text()
            self.assertIn("Synthetic example", text, name)

    def test_runnable_examples_validate_cleanly(self):
        for name in RUNNABLE_EXAMPLES:
            with self.subTest(example=name):
                self.assertEqual([str(f) for f in validate_spec(load_example(name))], [])

    def test_self_employed_is_marked_not_yet_supported(self):
        findings = validate_spec(load_example("self_employed"))
        self.assertTrue(findings)
        self.assertTrue(all(f.code == "not_yet_supported" for f in findings), findings)
        self.assertTrue(any("Plan 31" in f.message for f in findings))

    def test_load_build_extract_dump_is_stable(self):
        for name in RUNNABLE_EXAMPLES:
            with self.subTest(example=name):
                spec = load_example(name)
                model = build_model(spec)
                self.assertEqual(dumps(spec_from_model(model)), dumps(canonical(spec)))
                self.assertEqual(dumps(spec_from_model(model), "json"), dumps(canonical(spec), "json"))

    def test_examples_run_and_extract_after_running(self):
        for name in RUNNABLE_EXAMPLES:
            with self.subTest(example=name):
                spec = load_example(name)
                short = spec.model_copy(update={"meta": spec.meta.model_copy(update={"end_year": 2035})})
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")  # later-dated events never fire in the short run
                    model = build_model(short)
                model.run()
                self.assertEqual(model.year, 2036)
                after = spec_from_model(model)
                self.assertIsInstance(after, HouseholdSpec)
                self.assertEqual(after.meta.start_year, 2036)

    def test_extract_mid_run_is_a_valid_fresh_start(self):
        for name in RUNNABLE_EXAMPLES:
            with self.subTest(example=name):
                model = build_model(load_example(name))
                for _ in range(5):
                    model.step()
                after = spec_from_model(model)
                self.assertEqual(after.meta.start_year, 2031)
                self.assertEqual([f for f in validate_spec(after) if f.level == "error"], [])
                build_model(after, check=False)

    def test_married_homeowners_meets_the_acceptance_household(self):
        spec = load_example("married_homeowners")
        john, jane = spec.people
        self.assertEqual([j.salary_annual > 0 for j in (*john.jobs, *jane.jobs)], [True, True])
        self.assertEqual(spec.relationships.marriages[0].spouses, ("john", "jane"))
        mortgage = john.housing[0].mortgage
        self.assertLess(mortgage.balance, mortgage.original_amount)  # in progress
        brokerage = next(a for a in jane.accounts if a.kind == "brokerage")
        self.assertTrue(any(lot.value > lot.cost_basis for lot in brokerage.lots))  # embedded gains
        self.assertEqual(jane.debts[0].kind, "car")
        self.assertEqual(john.insurance[0].policy, "term")
        self.assertTrue(john.social_security.earnings_history and jane.social_security.earnings_history)
        self.assertEqual(len(spec.events), 5)
        john_401k = next(a for a in john.accounts if a.kind == "401k")
        self.assertEqual([(t.match_pct, t.up_to_pay_pct) for t in john_401k.match_tiers], [(50, 6)])  # tiered
        model = build_model(spec)
        self.assertEqual(model.household.people["john"].all_retirement_accounts[0].match_tiers, ((50, 6),))
        # The deprecated legacy field still builds, with a validator warning naming the tiers equivalent.
        data = json.loads(dumps(spec, "json"))
        data["people"][0]["accounts"][1].pop("match_tiers")
        data["people"][0]["accounts"][1]["company_match_pct"] = 6
        findings = validate_spec(data)
        self.assertEqual([f.code for f in findings], ["deprecated_match"])
        self.assertIn("up_to_pay_pct: 6", findings[0].fix)

    def test_married_homeowners_builds_without_warnings(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            build_model(load_example("married_homeowners"))


class TestCli(unittest.TestCase):
    def _run(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli_main(list(argv))
        return code, out.getvalue()

    def test_schema_command_prints_the_json_schema(self):
        code, out = self._run("schema")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), json_schema())

    def test_validate_command(self):
        from ..spec import example_path

        code, out = self._run("validate", str(example_path("married_homeowners")))
        self.assertEqual((code, out.strip()), (0, "no findings"))
        code, out = self._run("validate", str(example_path("self_employed")))
        self.assertEqual(code, 1)
        self.assertIn("not yet supported", out)

    def test_examples_command(self):
        code, out = self._run("examples")
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().splitlines()), len(EXAMPLES))


class TestDocsAndPackaging(unittest.TestCase):
    def test_generated_docs_are_up_to_date(self):
        committed = (REPO_ROOT / "docs" / "household-spec.md").read_text(encoding="utf-8")
        self.assertEqual(committed, render_markdown(), "run python scripts/generate_household_spec_docs.py")

    def test_examples_ship_in_the_wheel(self):
        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
        package_data = pyproject["tool"]["setuptools"]["package-data"]
        self.assertIn("examples/*.yaml", package_data.get("life_model.spec", []))

    def test_real_household_files_are_git_ignored(self):
        ignore = (REPO_ROOT / ".gitignore").read_text().splitlines()
        self.assertIn("my-models/*.yaml", ignore)
        self.assertIn("my-models/*.json", ignore)


if __name__ == "__main__":
    unittest.main()


def _kitchen_sink() -> dict:
    """A spec using every supported kind, with non-default values, for the round-trip test."""
    data = minimal()
    data["meta"].update({"end_year": 2060, "seed": 3, "default_state": "NY", "scenario": "recession"})
    # recession already runs a path economy; the override changes one path year and the base inflation.
    data["economy"] = {"inflation_pct": 2.5, "paths": {"equity_return_pct": {2027: -10.0}}}
    alex = data["people"][0]
    alex.update({"gender": "female", "mortality": "fixed_age", "death_age": 95, "state": "CA"})
    alex["jobs"][0].update({"bonus_pct": 10, "stock_plan": {"signon_value": 40000, "refresher_value": 20000}})
    alex["accounts"] = [
        {"kind": "bank", "id": "checking", "balance": 20000, "interest_pct": 0.5, "primary": True},
        {
            "kind": "bank",
            "company": "Online Bank",
            "type": "Savings",
            "balance": 5000,
            "interest_pct": 4.0,
            "compounding": "annual",
        },
        {
            "kind": "401k",
            "job": "job",
            "pretax_balance": 1000,
            "roth_balance": 2000,
            "pretax_contrib_pct": 6,
            "match_tiers": [{"match_pct": 100, "up_to_pay_pct": 3}, {"match_pct": 50, "up_to_pay_pct": 2}],
            "match_on_bonus": True,
            "match_vesting_years": 3,
        },
        {"kind": "annuity", "annuity_type": "fixed", "balance": 20000, "interest_pct": 4},
        {"kind": "brokerage", "balance": 10000, "growth_pct": 6, "dividend_yield_pct": 1.5},
        {"kind": "traditional_ira", "balance": 3000, "contribution_limit_annual": 6000},
        {"kind": "roth_ira", "balance": 4000},
        {"kind": "hsa", "coverage": "family", "balance": 500, "employer_contribution_annual": 1000},
        {"kind": "inherited_pretax", "balance": 50000, "decedent_name": "Aunt", "years": 8},
        {
            "kind": "pension",
            "company": "City",
            "vesting_years": 5,
            "years_of_service": 12,
            "benefit_multiplier_pct": 1.5,
            "final_salary_annual": 70000,
            "start_age": 62,
            "cola_pct": 1,
            "survivor_pct": 50,
        },
        {"kind": "pension", "company": "Old Co", "vesting_years": 3, "benefit_annual": 6000, "accrues_service": False},
        {"kind": "pension", "company": "Union", "vesting_years": 5, "benefit_annual": 3000, "job": "job"},
        {
            "kind": "annuity",
            "annuity_type": "deferred",
            "balance": 80000,
            "interest_pct": 4,
            "payout_type": "joint_and_survivor",
            "joint_annuitant": "bo",
            "survivor_pct": 50,
        },
        {"kind": "daf", "name": "Giving Fund", "balance": 7000, "growth_pct": 6},
        {
            "kind": "trust",
            "trust_type": "irrevocable",
            "beneficiaries": ["bo"],
            "name": "Family Trust",
            "balance": 9000,
        },
        {"kind": "529", "beneficiary": "kid", "balance": 2500, "contribution_limit_annual": 15000},
    ]
    alex["debts"] = [
        {"kind": "car", "original_amount": 25000, "balance": 12000, "rate_pct": 7, "term_years": 5},
        {
            "kind": "student",
            "loan_type": "federal_subsidized",
            "original_amount": 20000,
            "rate_pct": 4,
            "term_years": 10,
            "in_deferment": True,
            "repayment_plan": "repayment_assistance_plan",
        },
        {"kind": "credit_card", "credit_limit": 9000, "balance": 1200, "rate_pct": 22, "card_type": "visa"},
    ]
    alex["housing"] = [
        {
            "kind": "home",
            "id": "house",
            "purchase_price": 500000,
            "value_growth_pct": 3,
            "down_payment": 100000,
            "mortgage": {
                "original_amount": 400000,
                "balance": 380000,
                "rate_pct": 6.5,
                "term_years": 30,
                "start_year": 2024,
            },
            "expenses": {"property_tax_pct": 1.2, "insurance_pct": 0.4, "hoa_monthly": 200, "hoa_growth_pct": 3},
        },
        {"kind": "rental", "name": "Studio", "rent_monthly": 900, "rent_growth_pct": "economy"},
    ]
    alex["insurance"] = [
        {
            "kind": "life",
            "policy": "term",
            "death_benefit": 1e6,
            "premium_monthly": 60,
            "term_years": 30,
            "beneficiary": "bo",
        },
        {
            "kind": "life",
            "policy": "term",
            "death_benefit": 2e5,
            "premium_monthly": 20,
            "term_years": 10,
            "premium_schedule": "yearly_increase",
            "premium_increase_pct": 2,
        },
        {
            "kind": "life",
            "policy": "term",
            "death_benefit": 1e5,
            "premium_monthly": 15,
            "term_years": 10,
            "premium_schedule": "age_banded",
        },
        {"kind": "life", "policy": "whole", "death_benefit": 3e5, "premium_monthly": 250, "cash_value_growth_pct": 3},
        {"kind": "ltc", "company": "LTC Co", "premium_annual": 2500, "coverage_amount": 150000, "coverage_end_age": 95},
        {"kind": "umbrella", "premium_annual": 300, "coverage_amount": 1e6, "premium_increase_pct": 1},
    ]
    alex["social_security"] = {"claim_age": 68, "earnings_history": {2018: 50000, 2019: 52000}}
    alex["healthcare"] = {"medical_costs": True, "long_term_care": True}
    alex["giving"] = [
        {"kind": "donation", "charity": "Library", "amount_annual": 500, "frequency_years": 2, "end_year": 2040}
    ]
    alex["children"] = [{"id": "kid", "name": "Kid", "birth_year": 2018}]
    bo = {
        "id": "bo",
        "name": "Bo",
        "age": 42,
        "retirement_age": 64,
        "spending": {"amount_annual": 20000, "growth_pct": 2},
        "accounts": [{"kind": "bank", "balance": 3000}],
    }
    data["people"].append(bo)
    data["relationships"] = {"marriages": [{"spouses": ["alex", "bo"], "filing_status": "separate"}]}
    data["withdrawal_order"] = ["bank", "roth_basis", "brokerage", "pretax", "roth_earnings"]
    data["events"] = [
        {"id": "raise", "at": 2028, "person": "alex", "action": "change_job", "job": "job", "salary_annual": 90000},
        {"at": {"relative": {"after": "raise", "years": 2}}, "person": "alex", "action": "sell_home", "home": "house"},
        {"at": {"age": 50}, "person": "bo", "action": "one_time_expense", "amount": 3000},
        {"at": {"age": 70}, "person": "alex", "action": "claim_social_security"},
        {"at": 2055, "person": "bo", "action": "die"},
    ]
    return data


class TestKitchenSinkRoundTrip(unittest.TestCase):
    def test_every_supported_kind_extracts_back_to_its_spec(self):
        spec = spec_of(_kitchen_sink())
        model = build_model(spec, check=False)
        self.assertEqual(dumps(spec_from_model(model)), dumps(canonical(spec)))

    def test_python_built_model_extracts_and_rebuilds_identically(self):
        """spec_from_model on a hand-built model gives a spec whose build matches it (migration path)."""
        model = build_model(spec_of(_kitchen_sink()), check=False)
        extracted = spec_from_model(model)
        rebuilt = build_model(extracted, check=False)
        self.assertEqual(dumps(spec_from_model(rebuilt)), dumps(extracted))
