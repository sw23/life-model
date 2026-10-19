# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Household validator: every error and warning, on specs and on Python-built models."""

import copy
import unittest

from ..account.bank import BankAccount
from ..housing.apartment import Apartment
from ..lifeevents import LifeEvent, LifeEvents
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..spec import ERROR, WARNING, Finding, build_model, load_example, validate_spec
from ..spec.schema import NYS_KEY
from ..spec.validate import not_yet_supported_findings
from ..work.job import Job, Salary
from .spec_helpers import minimal, not_yet_supported, spec_of


def codes(findings: list[Finding], level: str | None = None) -> list[str]:
    return [f.code for f in findings if level is None or f.level == level]


def _couple() -> dict:
    data = minimal()
    data["people"].append({**copy.deepcopy(data["people"][0]), "id": "bo", "name": "Bo"})
    data["people"][1]["jobs"][0]["id"] = "bo_job"
    data["relationships"] = {"marriages": [{"spouses": ["alex", "bo"]}]}
    return data


class TestSpecErrors(unittest.TestCase):
    def test_minimal_spec_is_clean(self):
        self.assertEqual(validate_spec(minimal()), [])

    def test_schema_errors_become_findings(self):
        data = minimal()
        data["people"][0]["accounts"][0]["balance"] = -10
        findings = validate_spec(data)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].level, ERROR)
        self.assertEqual(findings[0].path, "people[0].accounts[0].bank.balance")
        self.assertTrue(findings[0].code.startswith("schema."))
        self.assertEqual(codes(validate_spec('{"meta": {}}'))[:1], ["schema.missing"])

    def test_negative_debt_balance(self):
        data = minimal()
        data["people"][0]["debts"] = [{"kind": "credit_card", "credit_limit": 1000, "balance": -1}]
        self.assertTrue(all(f.level == ERROR for f in validate_spec(data)))
        self.assertIn("credit_card", validate_spec(data)[0].path)

    def test_unknown_state(self):
        data = minimal(state="ZZ")
        data["meta"]["default_state"] = "WY"  # no tax pack
        findings = validate_spec(data)
        self.assertEqual(codes(findings), ["unknown_state", "unknown_state"])
        self.assertEqual({f.path for f in findings}, {"meta.default_state", "people[0].state"})

    def test_person_without_bank_account(self):
        self.assertEqual(codes(validate_spec(minimal(accounts=[]))), ["no_bank_account"])

    def test_event_before_start_year(self):
        data = _couple()
        data["relationships"] = {}
        data["events"] = [{"at": 2024, "person": "alex", "spouse": "bo", "action": "marry"}]
        findings = validate_spec(data)
        self.assertIn("event_before_start", codes(findings, ERROR))
        data["events"] = [{"at": {"age": 30}, "person": "alex", "action": "one_time_expense", "amount": 1}]
        self.assertIn("event_before_start", codes(validate_spec(data), ERROR))

    def test_retirement_age_below_age(self):
        self.assertEqual(codes(validate_spec(minimal(retirement_age=35))), ["retirement_before_age"])
        # A retiree without a job is fine.
        self.assertEqual(validate_spec(minimal(retirement_age=35, jobs=[])), [])

    def test_social_security_claim_below_62(self):
        data = minimal(retirement_age=55, social_security={"earnings_history": {2020: 1}})
        self.assertEqual(codes(validate_spec(data)), ["ss_claim_too_early"])
        data = minimal(social_security={"claim_age": 60})
        self.assertEqual(codes(validate_spec(data)), ["ss_claim_too_early"])
        data = minimal(social_security={"claim_age": 67})
        data["meta"]["end_year"] = 2070
        data["events"] = [{"at": {"age": 61}, "person": "alex", "action": "claim_social_security"}]
        self.assertEqual(codes(validate_spec(data)), ["ss_claim_too_early"])

    def test_not_yet_supported_fields_and_kinds(self):
        data = minimal()
        data["people"][0]["birth"] = "1986-04"
        data["people"][0]["accounts"].append({"kind": "fixed_income", "instrument": "cd", "face": 10000, "rate_pct": 4})
        data["people"][0]["accounts"].append({"kind": "roth_ira", "id": "roth"})
        data["events"] = [
            {"at": 2027, "person": "alex", "action": "convert_to_roth", "amount": 1000},
            {"at": 2028, "person": "alex", "action": "divorce", "spouse": "alex"},
        ]
        data["meta"]["start"] = "2026-10"
        findings = [f for f in validate_spec(data) if f.code == "not_yet_supported"]
        # birth, meta.start, fixed income and Roth conversions are supported; divorce is rejected.
        self.assertEqual(codes(findings), ["not_yet_supported"])
        self.assertIn("not yet supported", findings[0].message.lower())
        self.assertIn("divorce", findings[0].message)

    def test_every_not_yet_supported_field_is_rejected(self):
        """Supporting a field means deleting its marker; until then setting it is an error."""
        from ..spec.docs import _models_in_order

        marked = [
            (model, name)
            for model in _models_in_order()
            for name, info in model.model_fields.items()
            if isinstance(info.json_schema_extra, dict) and NYS_KEY in info.json_schema_extra
        ]
        self.assertTrue(marked)  # shrinks as fields become supported
        spec = spec_of(not_yet_supported())
        self.assertEqual(codes(not_yet_supported_findings(spec)), ["not_yet_supported"])

    def test_standalone_401k(self):
        """A 401k without a job (an old employer's plan) is supported."""
        data = minimal()
        data["people"][0]["accounts"].append({"kind": "401k", "pretax_balance": 1000})
        self.assertNotIn("not_yet_supported", codes(validate_spec(data)))

    def test_duplicate_ids_and_dangling_references(self):
        data = minimal()
        data["people"][0]["accounts"].append({"kind": "brokerage", "id": "job"})
        data["people"][0]["accounts"].append({"kind": "401k", "job": "nope"})
        data["people"][0]["accounts"].append({"kind": "529", "beneficiary": "kid"})
        data["events"] = [
            {"at": {"relative": {"after": "missing"}}, "person": "alex", "action": "retire"},
            {"at": 2027, "person": "ghost", "action": "retire"},
            {"at": 2027, "person": "alex", "action": "sell_home", "home": "nowhere"},
            {"at": 2027, "person": "alex", "action": "contribute", "account": "missing", "amount": 1},
        ]
        found = codes(validate_spec(data), ERROR)
        self.assertEqual(found.count("duplicate_id"), 1)
        self.assertEqual(found.count("unknown_reference"), 6)

    def test_event_targets_must_have_the_right_kind(self):
        data = minimal()
        data["people"][0]["housing"] = [{"kind": "rental", "id": "apt", "rent_monthly": 900, "rent_growth_pct": 3}]
        data["events"] = [{"at": 2027, "person": "alex", "action": "sell_home", "home": "apt"}]
        self.assertEqual(codes(validate_spec(data)), ["unknown_reference"])

    def test_event_added_accounts_are_checked(self):
        data = minimal()
        data["events"] = [
            {"at": 2027, "person": "alex", "action": "add_account", "account": {"kind": "401k"}},
            {"at": 2027, "person": "alex", "action": "add_account", "account": {"kind": "401k", "job": "nope"}},
            {"at": 2027, "person": "alex", "action": "add_account", "account": {"kind": "529", "beneficiary": "kid"}},
        ]
        # A standalone 401k (the first event) is supported.
        self.assertEqual(sorted(codes(validate_spec(data))), ["unknown_reference", "unknown_reference"])

    def test_claim_age_relative_to_another_person(self):
        data = _couple()
        data["people"][0].update(age=60, birth="1966-01")
        data["people"][1].update(age=65, birth="1961-01")
        data["people"][0]["social_security"] = {"claim_age": 67}
        data["meta"]["end_year"] = 2040
        data["events"] = [
            {"at": {"age": 65, "person": "bo"}, "person": "alex", "action": "claim_social_security"},
        ]
        self.assertIn("ss_claim_too_early", codes(validate_spec(data)))

    def test_relative_cycle(self):
        data = minimal()
        data["events"] = [
            {"id": "a", "at": {"relative": {"after": "b"}}, "person": "alex", "action": "retire"},
            {"id": "b", "at": {"relative": {"after": "a"}}, "person": "alex", "action": "retire"},
        ]
        self.assertIn("event_cycle", codes(validate_spec(data)))


class TestSpecWarnings(unittest.TestCase):
    def test_fraction_looking_percent_names_the_field_and_value(self):
        data = minimal()
        data["people"][0]["accounts"].append({"kind": "brokerage", "balance": 1000, "growth_pct": 0.045})
        (finding,) = [f for f in validate_spec(data) if f.code == "fraction_percent"]
        self.assertEqual(finding.level, WARNING)
        self.assertEqual(finding.code, "fraction_percent")
        self.assertEqual(finding.path, "people[0].accounts[1].growth_pct")
        self.assertIn("did you mean 4.5", finding.fix)
        # A legitimately small rate on a field that is normally below 1 does not warn.
        data = minimal()
        data["people"][0]["accounts"][0]["interest_pct"] = 0.5
        self.assertEqual(validate_spec(data), [])

    def test_two_adults_not_married(self):
        data = _couple()
        data["relationships"] = {}
        self.assertEqual(codes(validate_spec(data)), ["unmarried_adults"])
        data["relationships"] = {"marriages": [{"spouses": ["alex", "bo"], "year": 2029}]}
        self.assertEqual(codes(validate_spec(data)), ["unmarried_adults"])  # single until 2029
        self.assertEqual(validate_spec(_couple()), [])

    def test_all_accounts_on_fixed_growth(self):
        data = minimal()
        data["people"][0]["accounts"] += [
            {"kind": "brokerage", "balance": 1, "growth_pct": 6},
            {"kind": "roth_ira", "balance": 1, "growth_pct": 6},
        ]
        self.assertEqual(codes(validate_spec(data)), ["fixed_growth"])
        data["people"][0]["accounts"][2]["growth_pct"] = "economy"
        self.assertEqual(validate_spec(data), [])

    def test_mortgage_inconsistencies(self):
        def home(mortgage):
            data = minimal()
            data["people"][0]["housing"] = [
                {
                    "kind": "home",
                    "purchase_price": 400000,
                    "mortgage": mortgage,
                    "expenses": {"property_tax_pct": 1, "insurance_pct": 0.5},
                }
            ]
            return codes(validate_spec(data))

        base = {"original_amount": 300000, "rate_pct": 6, "term_years": 30}
        self.assertEqual(home(base), [])
        self.assertEqual(home({**base, "start_year": 2018}), ["mortgage_inconsistent"])  # no balance
        self.assertEqual(home({**base, "start_year": 2018, "balance": 265000}), [])
        self.assertEqual(home({**base, "start_year": 2018, "balance": 120000}), ["mortgage_inconsistent"])
        self.assertEqual(home({**base, "start_year": 1990, "balance": 10000}), ["mortgage_inconsistent"])
        self.assertEqual(home({**base, "payment_monthly": 2600}), ["mortgage_inconsistent"])  # escrow included

    def test_rent_left_at_core_default(self):
        data = minimal()
        data["people"][0]["housing"] = [{"kind": "rental", "rent_monthly": 1500}]
        self.assertEqual(codes(validate_spec(data)), ["default_rent_growth"])
        data["people"][0]["housing"][0]["rent_growth_pct"] = 5
        self.assertEqual(validate_spec(data), [])

    def test_zero_growth_spending_and_salary(self):
        data = minimal()
        data["people"][0]["spending"] = {"amount_annual": 30000}
        data["people"][0]["jobs"][0]["raise_pct"] = 0
        findings = validate_spec(data)
        self.assertEqual(codes(findings), ["zero_growth", "zero_growth"])

    def test_bonds_as_bank_account_and_primary(self):
        data = minimal()
        data["people"][0]["accounts"].append({"kind": "bank", "company": "Treasury Direct", "type": "Bonds"})
        self.assertEqual(sorted(codes(validate_spec(data))), ["bonds_as_bank", "no_primary_bank"])
        data["people"][0]["accounts"][0]["primary"] = True
        data["people"][0]["accounts"][1]["primary"] = True
        self.assertIn("invalid", codes(validate_spec(data), ERROR))


def _python_household():
    """A household written in Python the way the original notebook did (synthetic data).

    It reproduces the notebook's problems: a marriage LifeEvent dated before the start year (so it
    never fires), core's 0% spending/salary growth defaults, and a bank account standing in for bonds.
    ``LifeEvents`` itself refuses a past-dated event, so the schedule here is mutated
    directly (as code that bypasses the constructor could) to show the validator still catches it.
    """
    model = LifeModel(start_year=2026, end_year=2030)
    family = Family(model)
    kim = Person(family, "Kim", age=41, retirement_age=60, spending=Spending(model, base_annual=24000))
    ray = Person(family, "Ray", age=43, retirement_age=62, spending=Spending(model, base_annual=20000))
    BankAccount(kim, company="Big Bank", balance=10000)
    BankAccount(kim, company="Treasury Direct", type="Bonds", balance=50000, interest_pct=4.0)
    BankAccount(ray, company="Big Bank", balance=8000)
    Job(kim, company="Example Co", role="Engineer", salary=Salary(model, base_annual=120000))
    Job(ray, company="Example Org", role="Teacher", salary=Salary(model, base_annual=60000, raise_pct=2))
    LifeEvents(model).life_events.append(LifeEvent(2024, "Kim and Ray get married", kim.get_married, ray))
    return model


class TestModelValidation(unittest.TestCase):
    def test_core_refuses_past_dated_life_events(self):
        model = LifeModel(start_year=2026, end_year=2030)
        family = Family(model)
        kim = Person(family, "Kim", age=41, retirement_age=60, spending=Spending(model, base_annual=1))
        ray = Person(family, "Ray", age=43, retirement_age=62, spending=Spending(model, base_annual=1))
        with self.assertRaises(ValueError):
            LifeEvents(model, [LifeEvent(2024, "Kim and Ray get married", kim.get_married, ray)])

    def test_python_household_reports_the_notebook_problems(self):
        findings = _python_household().validate()
        by_code = {f.code: f for f in findings}
        self.assertEqual(by_code["event_before_start"].level, ERROR)
        self.assertIn("2024", by_code["event_before_start"].message)
        self.assertEqual(by_code["bonds_as_bank"].level, WARNING)
        self.assertEqual(by_code["unmarried_adults"].level, WARNING)
        zero = [f for f in findings if f.code == "zero_growth"]
        self.assertEqual(len(zero), 3)  # two spending, one salary

    def test_model_errors(self):
        from ..config.models import UnknownStateError

        model = LifeModel(start_year=2026)
        family = Family(model)
        # A state without a tax pack is refused when the person is built (no silent flat rate).
        with self.assertRaises(UnknownStateError):
            Person(family, "Solo", age=70, retirement_age=65, spending=Spending(model, base_annual=1), state="ZZ")
        person = Person(family, "Solo", age=70, retirement_age=65, spending=Spending(model, base_annual=1), state="CA")
        person._residency = [(person._residency[0][0], "ZZ")]  # a timeline edited past the constructor's check
        Job(person, company="Co", role="Dev", salary=Salary(model, base_annual=1, raise_pct=0.03))
        Apartment(person, "Flat", 1000)
        found = codes(model.validate())
        for code in ("unknown_state", "no_bank_account", "retirement_before_age", "default_rent_growth"):
            self.assertIn(code, found)
        self.assertIn("fraction_percent", found)

    def test_deprecated_match_on_a_model(self):
        import warnings

        from ..account.job401k import Job401kAccount

        model = LifeModel(start_year=2026)
        person = Person(
            Family(model), "M", age=30, retirement_age=65, spending=Spending(model, base_annual=1, growth_pct=2)
        )
        BankAccount(person, company="Bank", balance=5)
        job = Job(person, company="Co", role="Dev", salary=Salary(model, base_annual=1, raise_pct=2))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            Job401kAccount(job=job, company_match_percent=6)
        self.assertIn("deprecated_match", codes(model.validate(), WARNING))

    def test_negative_balance(self):
        model = LifeModel(start_year=2026)
        person = Person(Family(model), "Neg", age=30, retirement_age=65, spending=Spending(model, base_annual=1))
        BankAccount(person, company="Bank", balance=-5)
        self.assertIn("negative_balance", codes(model.validate(), ERROR))

    def test_built_examples_validate_like_their_specs(self):
        for name in ("married_homeowners", "single_renter", "retiree_couple"):
            with self.subTest(example=name):
                model = build_model(load_example(name))
                self.assertEqual(codes(model.validate(), ERROR), [])

    def test_spec_rendering_of_the_python_household(self):
        """The same household as a spec reports the same problems before anything is built."""
        from ..spec import spec_from_model

        model = _python_household()
        spec = spec_from_model(model)
        data = spec.model_dump(mode="json", exclude_defaults=True)
        data["events"] = [{"at": 2024, "person": "kim", "spouse": "ray", "action": "marry"}]
        found = codes(validate_spec(data))
        for code in ("event_before_start", "bonds_as_bank", "zero_growth", "unmarried_adults"):
            self.assertIn(code, found)


if __name__ == "__main__":
    unittest.main()
