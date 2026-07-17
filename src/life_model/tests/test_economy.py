# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the economy model, its consumers, real-dollar reporting, and tax indexation."""

import unittest

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount
from ..config.financial_config import FinancialConfig
from ..housing.apartment import Apartment
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..work.job import Job, Salary


def _config(**economy):
    """A FinancialConfig with the ``economy`` section overridden by ``economy`` kwargs."""
    cfg = FinancialConfig()
    cfg.apply_scenario("test", {"economy": economy})
    return cfg


class TestEconomyModes(unittest.TestCase):
    def test_fixed_mode_returns_constants_every_year(self):
        model = LifeModel(start_year=2026, end_year=2030, config=_config(mode="fixed", equity_return=8.0))
        for year in (2026, 2028, 2030, 2100):
            self.assertEqual(model.economy.equity_return(year), 8.0)

    def test_path_mode_overrides_listed_years_only(self):
        cfg = _config(mode="path", equity_return=7.0, paths={"equity_return": {2027: -20.0, 2028: -5.0}})
        model = LifeModel(start_year=2026, end_year=2030, config=cfg)
        self.assertEqual(model.economy.equity_return(2026), 7.0)  # not listed -> fixed constant
        self.assertEqual(model.economy.equity_return(2027), -20.0)
        self.assertEqual(model.economy.equity_return(2028), -5.0)
        self.assertEqual(model.economy.equity_return(2029), 7.0)

    def test_path_mode_rejects_unknown_rate(self):
        cfg = _config(mode="path", paths={"not_a_rate": {2027: 1.0}})
        # An unknown path rate is caught eagerly when the economy first resolves a year.
        with self.assertRaises(ValueError):
            LifeModel(start_year=2026, end_year=2027, config=cfg)

    def test_stochastic_is_reproducible_under_seed(self):
        def realized(seed):
            cfg = _config(mode="stochastic")
            model = LifeModel(start_year=2026, end_year=2035, config=cfg, seed=seed)
            return [round(model.economy.equity_return(y), 6) for y in range(2026, 2036)]

        self.assertEqual(realized(42), realized(42))
        self.assertNotEqual(realized(42), realized(7))

    def test_cumulative_inflation(self):
        model = LifeModel(start_year=2026, end_year=2030, config=_config(mode="fixed", inflation=3.0))
        self.assertEqual(model.economy.cumulative_inflation(2026), 1.0)  # base year
        self.assertAlmostEqual(model.economy.cumulative_inflation(2028), 1.03**2)
        self.assertAlmostEqual(model.economy.cumulative_inflation(2031), 1.03**5)


class TestEconomyConsumers(unittest.TestCase):
    def test_bank_interest_defers_to_cash_yield(self):
        model = LifeModel(start_year=2026, end_year=2027, config=_config(cash_yield=4.0))
        family = Family(model)
        person = Person(family, "A", 30, 65, Spending(model, base=0))
        bank = BankAccount(person, "Bank")  # no explicit rate -> economy
        self.assertEqual(bank.interest_rate, 4.0)
        explicit = BankAccount(person, "Bank2", interest_rate=1.5)
        self.assertEqual(explicit.interest_rate, 1.5)  # override wins

    def test_brokerage_growth_defers_to_equity_return(self):
        model = LifeModel(start_year=2026, end_year=2027, config=_config(equity_return=9.0))
        family = Family(model)
        person = Person(family, "A", 30, 65, Spending(model, base=0))
        broker = BrokerageAccount(person, "B", balance=1000)
        self.assertEqual(broker.growth_rate, 9.0)
        self.assertEqual(broker.calculate_growth(), 90.0)

    def test_brokerage_growth_tracks_path_year_over_year(self):
        cfg = _config(mode="path", equity_return=10.0, paths={"equity_return": {2027: -50.0}})
        model = LifeModel(start_year=2026, end_year=2028, config=cfg)
        family = Family(model)
        person = Person(family, "A", 30, 65, Spending(model, base=0))
        broker = BrokerageAccount(person, "B", balance=1000)
        model.step()  # 2026: +10% -> 1100
        self.assertAlmostEqual(broker.balance, 1100.0)
        model.step()  # 2027: -50% -> 550
        self.assertAlmostEqual(broker.balance, 550.0)

    def test_salary_none_opts_into_wage_growth(self):
        model = LifeModel(start_year=2026, end_year=2027, config=_config(wage_growth=5.0))
        salary = Salary(model=model, base=100000, yearly_increase=None)
        self.assertEqual(salary.yearly_increase, 5.0)
        # An explicit 0 is honored (not replaced by the economy default).
        self.assertEqual(Salary(model=model, base=1, yearly_increase=0).yearly_increase, 0)

    def test_spending_none_opts_into_inflation(self):
        model = LifeModel(start_year=2026, end_year=2027, config=_config(inflation=2.5))
        self.assertEqual(Spending(model, base=1000, yearly_increase=None).yearly_increase, 2.5)
        self.assertEqual(Spending(model, base=1000).yearly_increase, 0)  # default unchanged

    def test_apartment_none_opts_into_inflation(self):
        model = LifeModel(start_year=2026, end_year=2027, config=_config(inflation=2.0))
        family = Family(model)
        person = Person(family, "A", 30, 65, Spending(model, base=0))
        self.assertEqual(Apartment(person, "Apt", 1000, yearly_increase=None).yearly_increase, 2.0)
        self.assertEqual(Apartment(person, "Apt2", 1000).yearly_increase, 5)  # default unchanged


class TestGoldenFramePreservation(unittest.TestCase):
    """A fixed economy set to explicit constants reproduces the pre-economy explicit-rate frames."""

    @staticmethod
    def _frame(defer_to_economy):
        cfg = _config(mode="fixed", cash_yield=0.0, equity_return=7.0, wage_growth=2.0, inflation=2.0)
        model = LifeModel(start_year=2026, end_year=2035, config=cfg)
        family = Family(model)
        if defer_to_economy:
            spending = Spending(model, base=20000, yearly_increase=None)
        else:
            spending = Spending(model, base=20000, yearly_increase=2.0)
        person = Person(family, "A", 30, 65, spending)
        if defer_to_economy:
            BankAccount(person, "Bank")
            BrokerageAccount(person, "B", balance=50000)
            Job(person, "Co", "Dev", Salary(model=model, base=80000, yearly_increase=None))
        else:
            BankAccount(person, "Bank", interest_rate=0.0)
            BrokerageAccount(person, "B", balance=50000, growth_rate=7.0)
            Job(person, "Co", "Dev", Salary(model=model, base=80000, yearly_increase=2.0))
        model.run()
        return model.datacollector.get_model_vars_dataframe()

    def test_deferred_matches_explicit(self):
        explicit = self._frame(defer_to_economy=False)
        deferred = self._frame(defer_to_economy=True)
        # Every collected value must match exactly.
        self.assertTrue(explicit.equals(deferred), "fixed economy did not reproduce explicit-rate frames")


class TestRealDollarReporting(unittest.TestCase):
    def test_real_bank_balance_is_nominal_deflated(self):
        cfg = _config(mode="fixed", inflation=3.0, cash_yield=0.0)
        model = LifeModel(start_year=2026, end_year=2030, config=cfg)
        family = Family(model)
        person = Person(family, "A", 30, 65, Spending(model, base=0))
        BankAccount(person, "Bank", balance=10000, interest_rate=0.0)
        model.run()

        nominal = model.datacollector.get_model_vars_dataframe()
        real = model._to_real_dollars(nominal)
        for i, year in enumerate(nominal["Year"].tolist()):
            deflator = model.economy.cumulative_inflation(int(year))
            self.assertAlmostEqual(real.iloc[i]["Bank Balance"], nominal.iloc[i]["Bank Balance"] / deflator)
        # Year column is untouched.
        self.assertEqual(real["Year"].tolist(), nominal["Year"].tolist())

    def test_get_yearly_stat_df_real_dollars_runs(self):
        cfg = _config(mode="fixed", inflation=3.0)
        model = LifeModel(start_year=2026, end_year=2028, config=cfg)
        family = Family(model)
        person = Person(family, "A", 30, 65, Spending(model, base=0))
        BankAccount(person, "Bank", balance=1000, interest_rate=0.0)
        model.run()
        styler = model.get_yearly_stat_df(columns=["Year", "Bank Balance"], real_dollars=True)
        self.assertIsNotNone(styler)


class TestTaxIndexation(unittest.TestCase):
    def test_projection_default_is_frozen(self):
        cfg = FinancialConfig()
        frozen = cfg.tax_year(2050)
        latest = cfg.tax_year(2026)
        self.assertEqual(frozen.standard_deduction.single, latest.standard_deduction.single)

    def test_projection_scales_and_rounds(self):
        cfg = FinancialConfig()
        base = cfg.tax_year(2026).standard_deduction.single
        projected = cfg.tax_year(2050, inflation_factor=2.0)
        self.assertEqual(projected.standard_deduction.single, int(round(base * 2 / 50) * 50))
        # Top bracket's infinite ceiling stays infinite; rates are unchanged.
        top = projected.tax_brackets.single[-1]
        self.assertEqual(top[1], float("inf"))
        self.assertEqual(top[2], cfg.tax_year(2026).tax_brackets.single[-1][2])

    def test_model_projects_with_realized_inflation(self):
        cfg = _config(mode="fixed", inflation=3.0)
        model = LifeModel(start_year=2026, end_year=2027, config=cfg)
        frozen = model.config.tax_year(2050).standard_deduction.single
        projected = model.tax_params_for_year(2050).standard_deduction.single
        self.assertGreater(projected, frozen)  # inflation-projected, not frozen


if __name__ == "__main__":
    unittest.main()
