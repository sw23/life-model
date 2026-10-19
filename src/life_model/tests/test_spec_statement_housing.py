# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Statement-entered housing and debt in the household spec: statement loan fields, home inputs, home equity lines, card
charges, and the refinance / heloc_draw events (validate, build, extract)."""

import copy
import unittest

from ..spec import build_model, dumps, spec_from_model, validate_spec
from ..spec.builder import canonical
from ..spec.validate import ERROR
from .spec_helpers import fixture_config, minimal, spec_of


def _codes(findings, level=None):
    return [(f.code, f.path) for f in findings if level is None or f.level == level]


def _homeowner(**mortgage) -> dict:
    data = minimal()
    data["meta"]["end_year"] = 2028
    data["people"][0]["accounts"][0]["balance"] = 100000
    data["people"][0]["housing"] = [
        {
            "kind": "home",
            "id": "house",
            "purchase_price": 600000,
            "value_growth_pct": 3,
            "mortgage": {"original_amount": 480000, "rate_pct": 6.5, "term_years": 30, **mortgage},
            "expenses": {"property_tax_annual": 7200, "insurance_annual": 2100, "maintenance_growth_pct": "economy"},
        }
    ]
    return data


class TestStatementLoansInTheSpec(unittest.TestCase):
    def test_origination_builds_the_scheduled_balance(self):
        built = build_model(spec_of(_homeowner(origination="2024-03")), config=fixture_config())
        mortgage = built.household.items["house"].mortgage
        self.assertAlmostEqual(mortgage.monthly_payment, 3033.93, places=2)
        self.assertAlmostEqual(mortgage.principal, 470376.52, delta=0.5)

    def test_validator_names_the_inconsistent_field(self):
        data = _homeowner(origination="2024-03", balance=495000)
        findings = validate_spec(data, config=fixture_config())
        self.assertIn(("loan_terms", "people[0].housing[0].mortgage.balance"), _codes(findings, ERROR))
        data = _homeowner(origination="2024-03", remaining_months=300)
        findings = validate_spec(data, config=fixture_config())
        self.assertIn(("loan_terms", "people[0].housing[0].mortgage.remaining_months"), _codes(findings, ERROR))

    def test_statement_fields_validate_cleanly(self):
        data = _homeowner()
        data["people"][0]["housing"][0]["mortgage"] = {
            "rate_pct": 6.5,
            "balance": 470376.6,
            "remaining_months": 339,
            "payment_monthly": 3600,
            "escrow_monthly": 566.07,
        }
        self.assertEqual(_codes(validate_spec(data, config=fixture_config()), ERROR), [])
        built = build_model(spec_of(data), config=fixture_config())
        self.assertAlmostEqual(built.household.items["house"].mortgage.monthly_payment, 3033.93, places=2)

    def test_car_loan_in_months_and_round_trip(self):
        data = minimal()
        data["people"][0]["debts"] = [
            {
                "kind": "car",
                "id": "car",
                "original_amount": 30000,
                "rate_pct": 7,
                "term_months": 66,
                "payments_made": 6,
                "extra_principal_monthly": 50,
            }
        ]
        self.assertEqual(_codes(validate_spec(data, config=fixture_config()), ERROR), [])
        spec = spec_of(data)
        model = build_model(spec, config=fixture_config())
        loan = model.household.items["car"]
        self.assertEqual(loan.remaining_months, 60)
        self.assertEqual(dumps(spec_from_model(model)), dumps(canonical(spec)))

    def test_home_inputs_heloc_and_card_round_trip(self):
        data = _homeowner(origination="2024-03")
        home = data["people"][0]["housing"][0]
        home.update({"current_value": 650000, "cost_basis": 610000, "purchase_year": 2024, "pmi": False})
        home["expenses"].update({"assessed_value": 500000, "assessment_growth_cap_pct": 2, "property_tax_pct": 1.2})
        del home["expenses"]["property_tax_annual"]
        data["people"][0]["debts"] = [
            {
                "kind": "heloc",
                "id": "line",
                "home": "house",
                "credit_limit": 80000,
                "balance": 20000,
                "rate_pct": 8.5,
                "improvement_balance": 15000,
            },
            {
                "kind": "credit_card",
                "credit_limit": 10000,
                "payment_strategy": "full_balance",
                "spending_charged_pct": 40,
            },
        ]
        self.assertEqual(_codes(validate_spec(data, config=fixture_config()), ERROR), [])
        spec = spec_of(data)
        model = build_model(spec, config=fixture_config())
        built_home = model.household.items["house"]
        self.assertEqual(built_home.home_value, 650000)
        self.assertAlmostEqual(built_home.property_tax_for_year, 6000, places=6)
        self.assertEqual(dumps(spec_from_model(model)), dumps(canonical(spec)))
        model.checks = "strict"
        model.run()

    def test_heloc_needs_a_home_id(self):
        data = _homeowner()
        data["people"][0]["debts"] = [{"kind": "heloc", "home": "nope", "credit_limit": 1, "rate_pct": 8}]
        self.assertIn(("unknown_reference", "people[0].debts[0].home"), _codes(validate_spec(data), ERROR))


class TestRefinanceAndDrawEvents(unittest.TestCase):
    def _data(self) -> dict:
        data = _homeowner(origination="2024-03")
        data["people"][0]["debts"] = [
            {"kind": "heloc", "id": "line", "home": "house", "credit_limit": 80000, "rate_pct": 8.5}
        ]
        data["events"] = [
            {
                "at": {"year": 2027, "month": 6},
                "person": "alex",
                "action": "refinance",
                "debt": "house",
                "rate_pct": 5.0,
                "term_years": 15,
                "costs": 3000,
            },
            {
                "at": {"year": 2027},
                "person": "alex",
                "action": "heloc_draw",
                "heloc": "line",
                "amount": 25000,
                "for_improvements": True,
            },
        ]
        return data

    def test_events_fire_and_conserve(self):
        data = self._data()
        self.assertEqual(_codes(validate_spec(data, config=fixture_config()), ERROR), [])
        model = build_model(spec_of(data), config=fixture_config())
        model.checks = "strict"
        result = model.run()
        mortgage = model.household.items["house"].mortgage
        self.assertEqual(mortgage.yearly_interest_rate, 5.0)
        self.assertEqual(mortgage.term_months, 180)
        self.assertEqual(model.household.items["line"].improvement_balance, 25000)
        self.assertIn("refinanced", set(result.events["kind"]))

    def test_refinance_target_must_be_a_mortgaged_home_or_loan(self):
        data = self._data()
        data["events"][0]["debt"] = "line"
        self.assertIn(("unknown_reference", "events[0].debt"), _codes(validate_spec(data), ERROR))
        data = copy.deepcopy(self._data())
        del data["events"][0]["term_years"]
        with self.assertRaises(ValueError):
            spec_of(data)


if __name__ == "__main__":
    unittest.main()
