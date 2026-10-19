# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Plan 27 PR D in the household spec: existing policies, annuities and pensions, health and disability
insurance, Social Security statement fields and the spending model (validate, build, extract, run)."""

import unittest

from ..spec import build_model, dumps, spec_from_model, validate_spec
from ..spec.builder import canonical
from ..spec.validate import ERROR
from .spec_helpers import fixture_config, minimal, spec_of


def _codes(findings, level=None):
    return [(f.code, f.path) for f in findings if level is None or f.level == level]


def _rich() -> dict:
    data = minimal()
    data["meta"]["end_year"] = 2030
    alex = data["people"][0]
    alex["accounts"][0]["balance"] = 300000
    alex["spending"] = {
        "amount_annual": 20000,
        "growth_pct": "economy",
        "categories": {
            "groceries": {"amount_monthly": 700},
            "travel": {"amount_annual": 5000, "essential": False, "start_year": 2027, "end_year": 2029},
        },
        "schedule": [[75, 80]],
    }
    alex["accounts"] += [
        {"kind": "traditional_ira", "id": "ira", "balance": 50000, "growth_pct": "economy"},
        {
            "kind": "pension",
            "company": "Co",
            "vesting_years": 5,
            "benefit_annual": 0,
            "benefit_multiplier_pct": 1.5,
            "salary_history_annual": {2022: 70000, 2023: 75000, 2024: 80000, 2025: 82000},
            "final_average_years": 3,
            "normal_retirement_age": 65,
            "early_retirement_reduction_pct": 5,
            "start_age": 62,
            "employee_basis": 10000,
        },
        {
            "kind": "annuity",
            "annuity_type": "immediate",
            "payout_monthly": 900,
            "basis": 90000,
            "purchase_year": 2022,
            "in_payout": True,
        },
    ]
    alex["insurance"] = [
        {
            "kind": "life",
            "policy": "whole",
            "death_benefit": 250000,
            "premium_monthly": 150,
            "issue_year": 2015,
            "cash_value": 20000,
            "loan_balance": 5000,
        },
        {
            "kind": "health",
            "premium_annual": 6000,
            "coverage_amount": 1000000,
            "deductible": 1500,
            "oop_max_annual": 6000,
            "coinsurance_pct": 20,
        },
        {
            "kind": "disability",
            "premium_annual": 900,
            "coverage_amount": 0,
            "benefit_pct": 60,
            "benefit_max_monthly": 6000,
        },
    ]
    alex["healthcare"] = {"medical_costs_annual": 9000}
    alex["children"] = [{"name": "Kid", "birth_year": 2018, "cost_override_annual": 14000}]
    alex["social_security"] = {"claim_age": 67, "pia_override_monthly": 2400}
    return data


class TestPlan27PrDSpec(unittest.TestCase):
    def test_validates_builds_round_trips_and_conserves(self):
        data = _rich()
        self.assertEqual(_codes(validate_spec(data, config=fixture_config()), ERROR), [])
        spec = spec_of(data)
        model = build_model(spec, config=fixture_config())
        self.assertEqual(dumps(spec_from_model(model)), dumps(canonical(spec)))
        model.checks = "strict"
        model.run()

    def test_disability_event_starts_the_benefit(self):
        data = _rich()
        data["events"] = [{"at": {"year": 2027, "month": 3}, "person": "alex", "action": "disability"}]
        model = build_model(spec_of(data), config=fixture_config())
        model.checks = "strict"
        result = model.run()
        policy = next(
            p
            for p in model.registries.general_insurance_policies.get_all_items()
            if p.insurance_type.name == "DISABILITY"
        )
        self.assertIsNotNone(policy.disability_claim)
        self.assertGreater(policy.stat_disability_benefits, 0)
        self.assertTrue(all(job.retired for job in model.household.people["alex"].jobs))
        self.assertGreater(len(result.events), 0)

    def test_rollover_must_name_an_ira_and_qualified_has_no_basis(self):
        data = _rich()
        pension = data["people"][0]["accounts"][2]
        pension.update({"lump_sum_option": True, "rollover_account": "nope"})
        data["people"][0]["accounts"][3].update({"qualified": True})
        codes = _codes(validate_spec(data), ERROR)
        self.assertIn(("unknown_reference", "people[0].accounts[2].rollover_account"), codes)
        self.assertIn(("invalid", "people[0].accounts[3].basis"), codes)

    def test_fra_warning_for_births_before_1960(self):
        data = minimal(age=68)
        data["people"][0]["jobs"] = []
        data["people"][0]["retirement_age"] = 65
        data["people"][0]["social_security"] = {"claim_age": 70, "pia_override_monthly": 2000}
        self.assertIn("ss_fra_by_birth_year", [code for code, _ in _codes(validate_spec(data))])
        data["people"][0]["social_security"]["fra_from_birth_year"] = True
        self.assertNotIn("ss_fra_by_birth_year", [code for code, _ in _codes(validate_spec(data))])

    def test_pia_override_excludes_a_synthesized_record(self):
        # The dogfood fixes allow the statement's earnings_history with the override (it scales the override for
        # the years not worked); a synthesized record is still exclusive with it.
        data = minimal()
        data["people"][0]["social_security"] = {"pia_override_monthly": 2000, "earnings_history": {2020: 1}}
        spec_of(data)
        data["people"][0]["social_security"] = {"pia_override_monthly": 2000, "assumed_career_start_age": 22}
        with self.assertRaises(ValueError):
            spec_of(data)


if __name__ == "__main__":
    unittest.main()
