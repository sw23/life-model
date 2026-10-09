# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Property-based tests (Hypothesis).

These assert invariants that must hold across a wide space of inputs rather than a handful of
examples: loan amortization always terminates at a zero balance, account withdraw/deposit never
produces a negative balance or over-withdraws, and the federal bracket calculation is monotone,
continuous, and bounded by the top declared rate.

Skipped cleanly when Hypothesis is not installed; CI installs it via requirements-dev.txt.
"""

import unittest
from pathlib import Path

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings
from hypothesis import strategies as st

from ..account.brokerage import BrokerageAccount
from ..config.financial_config import FinancialConfig
from ..housing.home import Mortgage
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..tax.federal import FilingStatus, federal_income_tax, max_tax_rate

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    return FinancialConfig(config_file=TEST_CONFIG)


def _fresh_person() -> Person:
    model = LifeModel(start_year=2020, end_year=2020)
    return Person(Family(model), "P", age=40, retirement_age=70, spending=Spending(model, 0))


class TestLoanAmortizationProperties(unittest.TestCase):
    @settings(max_examples=200, deadline=None)
    @given(
        rate=st.one_of(st.just(0.0), st.floats(min_value=0.1, max_value=20.0)),
        term=st.integers(min_value=1, max_value=30),
        principal=st.floats(min_value=1000.0, max_value=1_000_000.0),
    )
    def test_loan_amortizes_to_zero_and_total_covers_principal(self, rate, term, principal):
        mortgage = Mortgage(loan_amount=principal, start_date=2020, length_years=term, yearly_interest_rate=rate)
        payment = mortgage.monthly_payment
        total_paid = 0.0
        for _ in range(term):
            total_paid += mortgage.make_yearly_payment(payment)
            # Principal never goes negative at any point in the schedule.
            self.assertGreaterEqual(mortgage.principal, -1e-6)
        # Fully amortized after `term` years.
        self.assertAlmostEqual(mortgage.principal, 0.0, delta=1e-2)
        # Total cash paid is at least the borrowed principal.
        self.assertGreaterEqual(total_paid, principal - 1e-2)


class TestAccountWithdrawDepositProperties(unittest.TestCase):
    @settings(max_examples=200, deadline=None)
    @given(
        balance=st.floats(min_value=0.0, max_value=1_000_000.0),
        amount=st.floats(min_value=0.0, max_value=2_000_000.0),
    )
    def test_withdraw_never_over_withdraws_or_goes_negative(self, balance, amount):
        account = BrokerageAccount(_fresh_person(), "Broker", balance=balance, growth_rate=0)
        withdrawn = account.withdraw(amount)
        self.assertLessEqual(withdrawn, balance + 1e-9)
        self.assertLessEqual(withdrawn, amount + 1e-9)
        self.assertGreaterEqual(account.balance, -1e-9)

    @settings(max_examples=200, deadline=None)
    @given(amount=st.floats(min_value=0.0, max_value=1_000_000.0))
    def test_deposit_then_withdraw_round_trips(self, amount):
        account = BrokerageAccount(_fresh_person(), "Broker", balance=0, growth_rate=0)
        account.deposit(amount)
        self.assertAlmostEqual(account.withdraw(amount), amount, delta=1e-6)
        self.assertAlmostEqual(account.balance, 0.0, delta=1e-6)


class TestBracketMathProperties(unittest.TestCase):
    def setUp(self):
        self.config = _fixture_config()

    @settings(max_examples=200, deadline=None)
    @given(
        low=st.floats(min_value=0.0, max_value=600_000.0),
        extra=st.floats(min_value=0.0, max_value=600_000.0),
    )
    def test_tax_is_monotone_non_decreasing(self, low, extra):
        tax_low = federal_income_tax(low, FilingStatus.SINGLE, self.config)
        tax_high = federal_income_tax(low + extra, FilingStatus.SINGLE, self.config)
        self.assertGreaterEqual(tax_high + 1e-9, tax_low)

    @settings(max_examples=200, deadline=None)
    @given(income=st.floats(min_value=0.0, max_value=500_000.0))
    def test_marginal_rate_within_declared_bounds(self, income):
        top_rate = max_tax_rate(FilingStatus.SINGLE, self.config) / 100
        delta = 1.0
        marginal = (
            federal_income_tax(income + delta, FilingStatus.SINGLE, self.config)
            - federal_income_tax(income, FilingStatus.SINGLE, self.config)
        ) / delta
        self.assertGreaterEqual(marginal, -1e-9)
        self.assertLessEqual(marginal, top_rate + 1e-9)


if __name__ == "__main__":
    unittest.main()


def _bracket_rows(thresholds: list[int], rates: list[float]) -> list[list[float]]:
    """``[lower, upper, rate]`` rows in the published convention: lower = previous upper + 1."""
    rows, lower = [], 0
    for upper, rate in zip(thresholds, rates, strict=False):
        rows.append([lower, upper, rate])
        lower = upper + 1
    rows.append([lower, float("inf"), rates[-1]])
    return rows


class TestFederalAndStateBracketEnginesAgree(unittest.TestCase):
    """Plan 17: the federal and state-pack bracket paths must produce the same tax for the same table."""

    @settings(max_examples=150, deadline=None)
    @given(
        thresholds=st.lists(st.integers(1_000, 1_000_000), min_size=1, max_size=6, unique=True),
        rates=st.lists(st.floats(0, 50, allow_nan=False), min_size=7, max_size=7),
        income=st.floats(0, 3_000_000, allow_nan=False),
    )
    def test_same_table_same_tax(self, thresholds, rates, income):
        from itertools import pairwise

        from hypothesis import assume

        from ..tax.income import IncomeType
        from ..tax.state import state_income_tax_for_unit

        thresholds = sorted(thresholds)
        assume(all(b > a + 1 for a, b in pairwise(thresholds)))
        rows = _bracket_rows(thresholds, rates[: len(thresholds) + 1])

        config = FinancialConfig()
        config.apply_scenario(
            "same_table",
            {
                "tax": {
                    "federal": {"tax_brackets": {"single": rows}},
                    "state": {"packs": {"CA": {"brackets": {"single": rows}, "standard_deduction": {"single": 0}}}},
                }
            },
        )
        federal = federal_income_tax(income, FilingStatus.SINGLE, config)
        state = state_income_tax_for_unit({IncomeType.WAGES: income}, FilingStatus.SINGLE, "CA", income, config)
        self.assertAlmostEqual(federal, state, delta=1e-6 * max(1.0, federal))
