# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""A household entered from its statements without workarounds.

A synthetic household with the owner's shape: bonds as fixed-income holdings (not a "Bonds" bank account),
the 401(k) match as tiers, a brokerage with real basis, a pre-tax health premium and an RSU plan with existing
unvested grants, plus the other statement account and payroll inputs. ``validate()`` is clean, it runs under the strict
invariant checker, and the spec survives build -> extract unchanged.
"""

import copy
import unittest

from ..spec import HouseholdSpec, dumps
from ..spec.builder import build_model, canonical
from ..spec.extract import spec_from_model
from ..spec.validate import validate_spec

HOUSEHOLD = {
    "meta": {"name": "statement-faithful", "start_year": 2026, "end_year": 2040, "seed": 7, "default_state": "CA"},
    "people": [
        {
            "id": "alex",
            "name": "Alex",
            "age": 44,
            "birth": "1981-03",
            "retirement_age": 60,
            "spending": {"amount_annual": 70000, "growth_pct": "economy"},
            "jobs": [
                {
                    "id": "job",
                    "company": "Example Analytics",
                    "salary_annual": 180000,
                    "raise_pct": "economy",
                    "bonus_pct": 10,
                    "bonus_fixed_annual": 5000,
                    "raises": [[2028, 6]],
                    "payroll": {
                        "health_premium_monthly": 250,
                        "dental_vision_monthly": 40,
                        "fsa_annual": 1000,
                        "hsa_employee_annual": 3000,
                        "hsa_employer_annual": 1000,
                        "commuter_monthly": 100,
                    },
                    "stock_plan": {
                        "refresher_value": 30000,
                        "existing_grants": [
                            {
                                "grant_year": 2024,
                                "value": 80000,
                                "vesting_schedule_pct": [25, 25, 25, 25],
                                "unvested_value": 50000,
                            }
                        ],
                        "espp_contribution_pct": 5,
                        "espp_discount_pct": 15,
                    },
                }
            ],
            "accounts": [
                {"kind": "bank", "id": "checking", "company": "Bank", "balance": 30000, "primary": True},
                {
                    "kind": "bank",
                    "id": "emergency",
                    "company": "Credit Union",
                    "type": "Savings",
                    "balance": 20000,
                    "reserve": True,
                    "interest_pct": 4,
                },
                {
                    "kind": "fixed_income",
                    "id": "tbond",
                    "instrument": "treasury",
                    "face": 50000,
                    "rate_pct": 4.25,
                    "maturity": "2031-05",
                },
                {
                    "kind": "fixed_income",
                    "id": "cd",
                    "instrument": "cd",
                    "face": 10000,
                    "rate_pct": 4.5,
                    "maturity": "2027-06",
                    "early_withdrawal_penalty_months": 6,
                    "reserve": False,
                },
                {
                    "kind": "fixed_income",
                    "id": "ibond",
                    "instrument": "i_bond",
                    "face": 10500,
                    "rate_pct": 1.2,
                    "purchased": "2023-05",
                    "accrued_interest": 500,
                },
                {
                    "kind": "401k",
                    "id": "k401",
                    "job": "job",
                    "pretax_balance": 250000,
                    "roth_balance": 20000,
                    "roth_basis": 15000,
                    "pretax_contrib_pct": 10,
                    "after_tax_contrib_pct": 5,
                    "in_plan_roth_conversion": True,
                    "match_tiers": [{"match_pct": 100, "up_to_pay_pct": 3}, {"match_pct": 50, "up_to_pay_pct": 2}],
                },
                {
                    "kind": "401k",
                    "id": "old401k",
                    "pretax_balance": 60000,
                    "allocation_pct": {"equity": 60, "bond": 40},
                },
                {
                    "kind": "brokerage",
                    "id": "taxable",
                    "company": "Example Brokerage",
                    "lots": [
                        {"value": 300000, "cost_basis": 120000, "acquired_year": 2015},
                        {"value": 20000, "cost_basis": 18000, "acquired_year": 2025, "acquired_month": 9},
                    ],
                    "allocation_pct": {"equity": 70, "bond": 30},
                    "expense_ratio_pct": 0.05,
                },
                {"kind": "traditional_ira", "id": "ira", "balance": 40000, "nondeductible_basis": 14000},
                {"kind": "roth_ira", "id": "roth", "balance": 80000, "contribution_basis": 50000},
                {"kind": "hsa", "id": "hsa", "balance": 12000, "basis": 9000},
            ],
            "contribution_plans": [{"account": "roth", "max_out": True}],
            "savings_policy": {"cash_floor": 40000, "sweep_to": "taxable"},
            "roth_conversion": {"fill_bracket_pct": 12, "until_age": 73},
        }
    ],
}


def household() -> HouseholdSpec:
    return HouseholdSpec.model_validate(copy.deepcopy(HOUSEHOLD))


class TestStatementFaithfulHousehold(unittest.TestCase):
    def test_validates_clean(self):
        self.assertEqual([str(f) for f in validate_spec(household())], [])

    def test_runs_under_the_strict_invariant_checker(self):
        model = build_model(household())
        model.checks = "strict"
        result = model.run()
        frame = result.model_frame if hasattr(result, "model_frame") else model.datacollector.get_model_vars_dataframe()
        self.assertEqual(len(frame), 15)
        self.assertEqual(model.invariant_violations, [])
        self.assertEqual(model.validate(), [])

    def test_build_extract_round_trip(self):
        spec = household()
        model = build_model(spec)
        self.assertEqual(dumps(spec_from_model(model)), dumps(canonical(spec)))

    def test_a_bonds_bank_account_still_warns(self):
        data = copy.deepcopy(HOUSEHOLD)
        data["people"][0]["accounts"].append({"kind": "bank", "company": "Bank", "type": "Bonds", "balance": 1})
        codes = [f.code for f in validate_spec(data)]
        self.assertIn("bonds_as_bank", codes)
