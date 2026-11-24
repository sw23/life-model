# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from decimal import Decimal

from ..checks import assert_conservation
from ..spec import build_household, spec_from_model, validate_spec
from .spec_helpers import fixture_config, minimal, spec_of


class TestMortgageRateCompounding(unittest.TestCase):
    def _inputs(self, **mortgage):
        return minimal(
            jobs=[],
            spending={"amount_annual": 0, "growth_pct": 2},
            accounts=[{"kind": "bank", "balance": 60000, "interest_pct": 0}],
            housing=[
                {
                    "kind": "home",
                    "id": "home",
                    "purchase_price": 450000,
                    "expenses": {"property_tax_pct": 0, "insurance_pct": 0},
                    "mortgage": {
                        "original_amount": 300000,
                        "term_years": 20,
                        "rate_pct": 5.6,
                        "rate_compounding": "semiannual",
                        **mortgage,
                    },
                }
            ],
        )

    def _expected(self):
        monthly_rate = (1 + Decimal("0.056") / 2) ** (Decimal(1) / 6) - 1
        payment = Decimal(300000) * monthly_rate / (1 - (1 + monthly_rate) ** -240)
        return monthly_rate, payment

    def test_monthly_payment_interest_and_snapshot_keep_the_quoted_rate(self):
        built = build_household(spec_of(self._inputs()), config=fixture_config(), collect="month")
        loan = built.items["home"].mortgage
        i, payment = self._expected()
        built.model.step()
        self.assertAlmostEqual(loan.monthly_payment, float(payment), places=8)
        self.assertAlmostEqual(loan.interest_paid_this_year, float(300000 * i), places=8)
        self.assertAlmostEqual(loan.principal, float(300000 * (1 + i) - payment), places=8)
        assert_conservation(built.model, monthly=True)

        snapshot = spec_from_model(built.model)
        statement = snapshot.people[0].housing[0].mortgage
        self.assertEqual((statement.rate_pct, statement.rate_compounding), (5.6, "semiannual"))
        rebuilt = build_household(snapshot, config=fixture_config())
        resumed = rebuilt.items["home"].mortgage
        self.assertAlmostEqual(resumed.principal, loan.principal, places=8)
        self.assertAlmostEqual(resumed.monthly_payment, loan.monthly_payment, places=8)

    def test_statement_validation_uses_the_quoted_compounding_convention(self):
        i, payment = self._expected()
        factor = (1 + i) ** 6
        balance = Decimal(300000) * factor - payment * (factor - 1) / i
        spec = spec_of(self._inputs(payments_made=6, balance=float(balance), payment_monthly=float(payment)))
        self.assertFalse([finding for finding in validate_spec(spec) if finding.level == "error"])
        built = build_household(spec, config=fixture_config())
        self.assertAlmostEqual(built.items["home"].mortgage.principal, float(balance), places=8)

    def test_refinance_replaces_previous_quote_with_the_existing_monthly_convention(self):
        built = build_household(spec_of(self._inputs()), config=fixture_config())
        loan = built.items["home"].mortgage
        built.model.step_year()
        loan.refinance(4.8, term_months=120)
        built.model.step_year()
        snapshot = spec_from_model(built.model).people[0].housing[0].mortgage
        self.assertEqual((snapshot.rate_pct, snapshot.rate_compounding), (4.8, "monthly"))

    def _semiannual_refinance(self, loan_inputs=None):
        data = loan_inputs or self._inputs()
        data["events"] = [
            {
                "action": "refinance",
                "person": "alex",
                "debt": "home",
                "at": {"year": 2027},
                "rate_pct": 4.8,
                "term_months": 120,
                "rate_compounding": "semiannual",
            }
        ]
        return data

    def test_refinance_accepts_a_semiannual_quote_and_snapshot_keeps_it(self):
        built = build_household(spec_of(self._semiannual_refinance()), config=fixture_config(), collect="month")
        built.model.checks = "strict"
        loan = built.items["home"].mortgage
        built.model.step_year()
        balance = loan.principal
        built.model.step()
        monthly_rate = (1 + Decimal("0.048") / 2) ** (Decimal(1) / 6) - 1
        payment = Decimal(balance) * monthly_rate / (1 - (1 + monthly_rate) ** -120)
        self.assertEqual((loan.quoted_rate_pct, loan.rate_compounding), (4.8, "semiannual"))
        self.assertAlmostEqual(loan.yearly_interest_rate, float(monthly_rate * 1200), places=10)
        self.assertAlmostEqual(loan.monthly_payment, float(payment), places=8)
        self.assertAlmostEqual(loan.interest_paid_this_year, float(Decimal(balance) * monthly_rate), places=8)
        (refinanced,) = built.model.event_log.of_kind("refinanced")
        self.assertIn("at 4.8%", refinanced.message)
        assert_conservation(built.model, monthly=True)

        snapshot = spec_from_model(built.model)
        statement = snapshot.people[0].housing[0].mortgage
        self.assertEqual((statement.rate_pct, statement.rate_compounding), (4.8, "semiannual"))
        resumed_run = build_household(snapshot, config=fixture_config(), collect="month")
        resumed = resumed_run.items["home"].mortgage
        self.assertEqual((resumed.quoted_rate_pct, resumed.rate_compounding), (4.8, "semiannual"))
        self.assertAlmostEqual(resumed.yearly_interest_rate, loan.yearly_interest_rate, places=12)
        self.assertAlmostEqual(resumed.monthly_payment, loan.monthly_payment, places=8)
        self.assertAlmostEqual(resumed.principal, loan.principal, places=6)
        for _ in range(6):
            built.model.step()
            resumed_run.model.step()
        self.assertAlmostEqual(resumed.principal, loan.principal, places=6)

    def test_core_refinance_converts_the_quote_before_amortizing(self):
        built = build_household(spec_of(self._inputs()), config=fixture_config())
        loan = built.items["home"].mortgage
        built.model.step_year()
        loan.refinance(4.8, term_months=120, rate_compounding="semiannual")
        self.assertAlmostEqual(loan.yearly_interest_rate, 1200 * ((1 + 0.048 / 2) ** (1 / 6) - 1), places=12)
        with self.assertRaises(ValueError):
            loan.refinance(4.8, term_months=120, rate_compounding="quarterly")  # type: ignore[arg-type]

    def test_only_a_mortgage_refinance_can_take_a_semiannual_quote(self):
        data = self._semiannual_refinance(
            minimal(
                jobs=[],
                debts=[{"kind": "car", "id": "car", "original_amount": 20000, "term_years": 5, "rate_pct": 6}],
            )
        )
        data["events"][0]["debt"] = "car"
        errors = [f for f in validate_spec(spec_of(data)) if f.level == "error"]
        self.assertEqual([f.path for f in errors], ["events[0].rate_compounding"])
