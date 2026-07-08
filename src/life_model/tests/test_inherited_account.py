# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the SECURE Act 10-year inherited-account rule (Plan 16 D3)."""

import unittest

from ..account.bank import BankAccount
from ..account.inherited import InheritedPretaxAccount
from ..account.traditional_IRA import TraditionalIRA
from ..config.financial_config import FinancialConfig
from ..model import LifeModel
from ..people.family import Family
from ..people.person import MortalityMode, Person, Spending


def _parent_child_model(*, start_year=2026, end_year=2037, ira_balance=500000, equity_return=None, mode=None):
    # Build the config before constructing the model: the economy eagerly caches the start-year
    # rates at construction, so equity_return has to be set on the config up front to apply to the
    # death year's growth as well.
    cfg = FinancialConfig()
    if equity_return is not None:
        cfg.model.economy.equity_return = equity_return
    if mode is not None:
        cfg.model.estate.inherited_pretax_mode = mode
    model = LifeModel(start_year=start_year, end_year=end_year, config=cfg)
    family = Family(model)
    parent = Person(
        family,
        "Parent",
        age=79,
        retirement_age=50,
        spending=Spending(model, 0),
        mortality_mode=MortalityMode.FIXED_AGE,
        death_age=80,
    )
    child = Person(family, "Kid", age=40, retirement_age=100, spending=Spending(model, 0))
    BankAccount(child, "C", balance=0, interest_rate=0)
    TraditionalIRA(person=parent, balance=ira_balance, growth_rate=0)
    return model, parent, child


class TestTenYearInheritance(unittest.TestCase):
    def test_ten_year_even_spread_taxes_beneficiary_annually(self):
        # Zero growth so distributions are an exact even spread ($50k/yr on $500k over 10 yrs).
        model, parent, child = _parent_child_model(equity_return=0)
        model.run()

        self.assertTrue(parent.is_deceased)
        df = model.datacollector.get_model_vars_dataframe()
        taxes = dict(zip(df["Year"], df["Taxes"]))
        # No lump sum in the death year (2026); distributions run over the following ten years.
        self.assertEqual(taxes[2026], 0)
        taxed_years = [y for y, t in taxes.items() if t > 0]
        self.assertEqual(taxed_years, list(range(2027, 2037)))  # exactly ten annual distributions

    def test_account_empties_by_year_ten_and_removes_itself(self):
        model, parent, child = _parent_child_model(equity_return=0)
        model.run()

        # The inherited account has removed itself from the simulation by the end.
        self.assertFalse(any(isinstance(a, InheritedPretaxAccount) for a in model.agents))
        # With zero growth, exactly the $500k was distributed: child holds it net of taxes paid.
        df = model.datacollector.get_model_vars_dataframe()
        total_taxes = sum(df["Taxes"])
        self.assertAlmostEqual(child.bank_account_balance + total_taxes, 500000, delta=1.0)

    def test_growth_continues_so_total_exceeds_starting_balance(self):
        # Default 7% equity return: the account keeps growing, so the ten distributions sum to
        # more than the starting $500k.
        model, parent, child = _parent_child_model()  # default economy
        model.run()

        self.assertFalse(any(isinstance(a, InheritedPretaxAccount) for a in model.agents))
        df = model.datacollector.get_model_vars_dataframe()
        total_taxes = sum(df["Taxes"])
        total_distributed = child.bank_account_balance + total_taxes
        self.assertGreater(total_distributed, 500000)

    def test_ten_year_has_lower_peak_tax_than_lump_sum(self):
        # ten_year (default)
        model_ty, _, _ = _parent_child_model()
        model_ty.run()
        ty_taxes = list(model_ty.datacollector.get_model_vars_dataframe()["Taxes"])

        # lump_sum
        model_ls, _, _ = _parent_child_model(mode="lump_sum")
        model_ls.run()
        ls_taxes = list(model_ls.datacollector.get_model_vars_dataframe()["Taxes"])

        # Spreading the distribution keeps every year in lower brackets, so the peak-year tax is
        # far lower than the single lump-sum year.
        self.assertLess(max(ty_taxes), max(ls_taxes))

    def test_inherited_corpus_visible_in_useable_balance_stat(self):
        # Reporting: the undistributed inherited corpus is surfaced in "Useable Balance" during
        # the 10-year window (inherited-account withdrawals carry no early-withdrawal penalty),
        # not invisible to balance stats for a decade.
        model, parent, child = _parent_child_model(equity_return=0)
        model.run()
        df = model.datacollector.get_model_vars_dataframe()
        useable = dict(zip(df["Year"], df["Useable Balance"]))
        bank = dict(zip(df["Year"], df["Bank Balance"]))
        # "Useable Balance" also counts bank balances; the inherited corpus is the difference.
        # Death year: full $500k corpus visible. Mid-window: the remaining corpus.
        self.assertEqual(useable[2026] - bank[2026], 500000)
        self.assertEqual(useable[2031] - bank[2031], 250000)  # five $50k slices distributed by then
        self.assertEqual(useable[2037] - bank[2037], 0)  # fully distributed and removed

    def test_401k_pretax_balance_follows_ten_year_rule(self):
        from ..account.job401k import Job401kAccount
        from ..work.job import Job, Salary

        cfg = FinancialConfig()
        cfg.model.economy.equity_return = 0
        model = LifeModel(start_year=2026, end_year=2038, config=cfg)
        family = Family(model)
        parent = Person(
            family,
            "Parent",
            age=79,
            retirement_age=50,
            spending=Spending(model, 0),
            mortality_mode=MortalityMode.FIXED_AGE,
            death_age=80,
        )
        child = Person(family, "Kid", age=40, retirement_age=100, spending=Spending(model, 0))
        BankAccount(child, "C", balance=0, interest_rate=0)
        job = Job(owner=parent, company="Co", role="Eng", salary=Salary(model=model, base=0))
        Job401kAccount(job=job, pretax_balance=500000, average_growth=0)
        model.run()

        self.assertTrue(parent.is_deceased)
        # The 401k's remaining pre-tax balance spreads over the ten years after death — no
        # death-year lump sum — and the inherited account removes itself when done.
        df = model.datacollector.get_model_vars_dataframe()
        taxes = dict(zip(df["Year"], df["Taxes"]))
        taxed_years = [y for y, t in taxes.items() if t > 0]
        self.assertEqual(taxed_years, list(range(2027, 2037)))
        self.assertFalse(any(isinstance(a, InheritedPretaxAccount) for a in model.agents))

    def test_lump_sum_distributes_entirely_in_death_year(self):
        model, parent, child = _parent_child_model(end_year=2027, mode="lump_sum")
        model.run()
        df = model.datacollector.get_model_vars_dataframe()
        taxes = dict(zip(df["Year"], df["Taxes"]))
        # The whole balance is taxed in the death year (2026), nothing after.
        self.assertGreater(taxes[2026], 0)
        self.assertEqual(taxes[2027], 0)


if __name__ == "__main__":
    unittest.main()
