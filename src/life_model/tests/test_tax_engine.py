# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Regression tests for Plan 05 — tax engine correctness.

Each test targets a specific tax bug catalogued in plans/05-tax-engine.md. Dollar
assertions read the frozen fixture config (fixtures/test_config.yaml), never live-year
defaults, so they stay stable across annual data refreshes.
"""

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..account.job401k import Job401kAccount
from ..config.financial_config import FinancialConfig
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..tax.federal import FilingStatus, federal_income_tax
from ..work.job import Job, Salary

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    """Fresh FinancialConfig loaded from the frozen test fixture."""
    return FinancialConfig(config_file=TEST_CONFIG)


class TestBracketMath(unittest.TestCase):
    """Item 4: brackets are half-open and computed marginally with no boundary gaps."""

    def setUp(self):
        self.config = _fixture_config()

    def test_no_boundary_gap(self):
        # Fixture: 10% to $40,000 then 25%. Income sitting in the boundary "gap" the old
        # [start, end] rows left ($40,000 -> $40,001) must be taxed marginally, not skipped.
        # $40,000 @ 10% = $4,000; the extra $0.50 @ 25% = $0.125.
        tax = federal_income_tax(40000.50, FilingStatus.SINGLE, self.config)
        self.assertAlmostEqual(tax, 4000.125, places=4)

    def test_marginal_is_not_rounded(self):
        # Item 4 / Plan 04 D3: no premature round() to the dollar.
        tax = federal_income_tax(40010.40, FilingStatus.SINGLE, self.config)
        # $40,000 @ 10% + $10.40 @ 25% = 4000 + 2.60 = 4002.60
        self.assertAlmostEqual(tax, 4002.60, places=4)

    def test_exact_boundary(self):
        # Income exactly at the threshold stays fully in the lower bracket.
        self.assertAlmostEqual(federal_income_tax(40000, FilingStatus.SINGLE, self.config), 4000.0, places=6)

    def test_zero_and_negative(self):
        self.assertEqual(federal_income_tax(0, FilingStatus.SINGLE, self.config), 0)
        self.assertEqual(federal_income_tax(-100, FilingStatus.SINGLE, self.config), 0)

    def test_mfj_brackets(self):
        # MFJ fixture: 10% to $80,000 then 25%. $100,000 -> 8000 + 5000 = 13000.
        tax = federal_income_tax(100000, FilingStatus.MARRIED_FILING_JOINTLY, self.config)
        self.assertAlmostEqual(tax, 13000.0, places=6)


class TestFicaPerPerson(unittest.TestCase):
    """Bugs 1-3: FICA is a per-person payroll tax on wages only."""

    def test_retiree_401k_distribution_pays_no_fica(self):
        # Bug 1: a retiree living on 401k distributions has no wages, so owes zero FICA.
        model = LifeModel(start_year=2020, end_year=2020, config=_fixture_config())
        family = Family(model)
        person = Person(family, "Retired R", age=65, retirement_age=60, spending=Spending(model, base=30000))
        BankAccount(person, "Bank", balance=0, interest_rate=0)
        job = Job(person, "Old Co", "Retiree", Salary(model=model, base=0))
        Job401kAccount(job=job, pretax_balance=500000, average_growth=0)

        model.step()

        # The distribution funded the year's spending as ordinary income, but no payroll tax.
        self.assertGreater(person.stat_taxes_paid_federal, 0)
        self.assertEqual(person.stat_taxes_paid_ss, 0)
        self.assertEqual(person.stat_taxes_paid_medicare, 0)

    def test_worker_pretax_deferral_still_pays_fica_on_full_gross(self):
        # Bug 2: pre-tax 401k deferrals reduce income tax but are still FICA wages.
        model = LifeModel(start_year=2020, end_year=2020, config=_fixture_config())
        family = Family(model)
        person = Person(family, "Saver S", age=40, retirement_age=70, spending=Spending(model, base=0))
        BankAccount(person, "Bank", balance=0, interest_rate=0)
        job = Job(person, "Co", "Dev", Salary(model=model, base=100000))
        # Defer 20% ($20k) pre-tax.
        Job401kAccount(job=job, pretax_contrib_percent=20, average_growth=0)

        model.step()

        # FICA base is the full $100k gross (SS at 6.2%), not the $80k after deferral.
        self.assertAlmostEqual(person.stat_taxes_paid_ss, 100000 * 0.062, places=2)
        self.assertAlmostEqual(person.stat_taxes_paid_medicare, 100000 * 0.0145, places=2)

    def test_two_earner_mfj_each_under_cap_pays_ss_on_both_salaries(self):
        # Bug 3: the Social Security wage cap is per person, not on combined MFJ wages.
        # Fixture wage base is $110k; two earners at $70k and $80k are both under it.
        model = LifeModel(start_year=2020, end_year=2020, config=_fixture_config())
        family = Family(model)
        b = Person(family, "Spouse B", age=40, retirement_age=70, spending=Spending(model, base=0))
        c = Person(family, "Spouse C", age=40, retirement_age=70, spending=Spending(model, base=0))
        b.get_married(c)
        for p in (b, c):
            BankAccount(p, "Bank", balance=100000, interest_rate=0)
        Job(b, "Co", "Dev", Salary(model=model, base=70000))
        Job(c, "Co", "Dev", Salary(model=model, base=80000))

        model.step()

        # Combined SS = 6.2% of both full salaries (neither capped): 150000 * 0.062.
        total_ss = sum(p.stat_taxes_paid_ss for p in (b, c))
        self.assertAlmostEqual(total_ss, 150000 * 0.062, places=2)


class TestWithdrawalSizing(unittest.TestCase):
    """Item 9 / D3: pre-tax withdrawals are sized by a fixed-point solve, not a max-rate buffer."""

    def test_fifty_k_net_need_no_over_withdrawal(self):
        # A retiree needs $50k of spending funded entirely from a pre-tax 401k, with an empty
        # bank account. The solver must withdraw just enough to cover the $50k plus the tax the
        # withdrawal triggers — leaving no meaningful buffer behind.
        model = LifeModel(start_year=2020, end_year=2020, config=_fixture_config())
        family = Family(model)
        person = Person(family, "Retiree", age=65, retirement_age=60, spending=Spending(model, base=50000))
        BankAccount(person, "Bank", balance=0, interest_rate=0)
        job = Job(person, "Old Co", "Retiree", Salary(model=model, base=0))
        Job401kAccount(job=job, pretax_balance=1000000, average_growth=0)

        model.step()

        # The $50k spending was fully covered from the 401k and created no debt.
        self.assertEqual(person.stat_money_spent, 50000)
        self.assertEqual(person.debt, 0)
        # No max-rate over-buffer: at most ~$1 of excess is left in the bank after settlement.
        self.assertLessEqual(person.bank_account_balance, 1.0)
        # The bank actually received at least the $50k net need (before it was spent).
        withdrawn = 1000000 - job.retirement_account.pretax_balance
        self.assertGreaterEqual(withdrawn, 50000 - 1.0)


if __name__ == "__main__":
    unittest.main()
