# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Plan 32: the natively monthly engine.

``LifeModel.step()`` simulates one calendar month; a year is a reporting cadence (``step_year()``,
data collected at each year end). These tests pin the period plumbing (task 1), the monthly flows and
their December settlement (task 3), exact ages (task 2) and the money-conservation guard that runs
every month.
"""

import unittest
from itertools import pairwise

from ..account.bank import BankAccount
from ..checks import assert_conservation, check_conservation, conservation_records
from ..config.financial_config import FinancialConfig
from ..economy import annual_to_monthly, compound_months
from ..model import LifeModel, LifeModelAgent, ModelSetupException, parse_year_month
from ..people.family import Family
from ..people.person import Person, Spending
from .scenarios import married_homeowners, mortality_and_estate, renter_buys_home, stochastic_retiree


class TestPeriodPlumbing(unittest.TestCase):
    def test_step_advances_one_month(self):
        model = LifeModel(start_year=2026, end_year=2027)
        self.assertEqual((model.year, model.month, model.period), (2026, 1, 0))
        model.step()
        self.assertEqual((model.year, model.month, model.period), (2026, 2, 1))
        for _ in range(11):
            model.step()
        self.assertEqual((model.year, model.month, model.period), (2027, 1, 12))
        self.assertEqual(model.simulated_years, [2026])
        self.assertEqual(len(model.balance_sheets), 1)
        self.assertEqual(len(model.month_balance_sheets), 12)

    def test_start_month_gives_a_part_year(self):
        model = LifeModel(start="2026-10", end_year=2027)
        self.assertEqual((model.start_year, model.start_month, model.year, model.month), (2026, 10, 2026, 10))
        self.assertEqual(model.months_in_year(2026), 3)
        self.assertEqual(model.months_in_year(2027), 12)
        self.assertTrue(model.is_year_start)
        model.step_year()
        self.assertEqual((model.year, model.month, model.period), (2027, 1, 3))
        model.run()
        self.assertEqual(model.simulated_years, [2026, 2027])
        self.assertEqual(model.period, 15)
        self.assertFalse(model.running)

    def test_start_arguments(self):
        self.assertEqual(LifeModel(start_year=2030, start_month=4).month, 4)
        self.assertEqual(LifeModel(start="2030-04", start_year=2030).start_year, 2030)
        with self.assertRaises(ValueError):
            LifeModel(start="2030-04", start_year=2031)
        with self.assertRaises(ValueError):
            LifeModel(start="2030-04", start_month=5)
        with self.assertRaises(ValueError):
            LifeModel(start_year=2030, start_month=13)
        with self.assertRaises(ValueError):
            LifeModel(start="2030-4x")
        self.assertEqual(parse_year_month("1966-07"), (1966, 7))
        self.assertEqual(parse_year_month("1966-07-15"), (1966, 7))

    def test_year_end_flag_and_running(self):
        model = LifeModel(start_year=2026, end_year=2026)
        months = []
        while model.running:
            months.append((model.month, model.is_year_end))
            model.step()
        self.assertEqual(months[-1], (12, True))
        self.assertEqual(len(months), 12)
        model.step()  # past the end: a no-op
        self.assertEqual(model.period, 12)
        model.step_year()
        self.assertEqual(model.period, 12)

    def test_year_hooks_run_once_a_year_in_order(self):
        calls = []

        class Probe(LifeModelAgent):
            MONTHLY = True

            def on_year_start(self):
                calls.append(("start", self.model.year, self.model.month))

            def pre_step(self):
                calls.append(("pre", self.model.year, self.model.month))

            def on_year_end(self):
                calls.append(("end", self.model.year, self.model.month))

        model = LifeModel(start="2026-11", end_year=2027)
        Probe(model)
        model.run()
        self.assertEqual(calls[:4], [("start", 2026, 11), ("pre", 2026, 11), ("pre", 2026, 12), ("end", 2026, 12)])
        self.assertEqual(calls[4], ("start", 2027, 1))
        self.assertEqual(sum(1 for c in calls if c[0] == "pre"), 14)
        self.assertEqual(sum(1 for c in calls if c[0] == "end"), 2)

    def test_agents_record_their_creation_period(self):
        model = LifeModel(start_year=2026, end_year=2027)
        before = Spending(model, 0)
        model.step()
        model.step()
        after = Spending(model, 0)
        self.assertEqual((before.created_period, after.created_period), (0, 2))

    def test_collect_month_keeps_the_yearly_frame(self):
        model = LifeModel(start_year=2026, end_year=2027, collect="month")
        person = Person(Family(model), "Pat", 40, 65, Spending(model, base=12000))
        BankAccount(person, "Bank", balance=50000)
        model.run()
        yearly = model.get_yearly_stat_df(styled=False)
        self.assertEqual(yearly["Year"].tolist(), [2026, 2027])
        monthly = model.monthly_frame()
        self.assertEqual(len(monthly), 24)
        self.assertEqual(monthly[["Year", "Month"]].iloc[0].tolist(), [2026, 1])
        december = monthly[monthly.Month == 12].reset_index(drop=True)
        self.assertEqual(december["Bank Balance"].tolist(), yearly["Bank Balance"].tolist())
        with self.assertRaises(ModelSetupException):
            LifeModel(start_year=2026).monthly_frame()
        with self.assertRaises(ValueError):
            LifeModel(start_year=2026, collect="week")


def _economy_config(**economy) -> FinancialConfig:
    config = FinancialConfig()
    config.apply_scenario("test", {"economy": economy})
    return config


class TestMonthlyEconomy(unittest.TestCase):
    def test_fixed_annual_rates_become_monthly_rates_that_compound_back(self):
        model = LifeModel(start_year=2026, end_year=2030, config=_economy_config(equity_return=7.0, inflation=3.0))
        economy = model.economy
        monthly = economy.monthly_rate("equity_return")
        self.assertAlmostEqual(monthly, (1.07 ** (1 / 12) - 1) * 100)
        self.assertAlmostEqual(compound_months(economy.monthly_rates("equity_return", 2028)), 7.0)
        self.assertEqual(economy.equity_return(2028), 7.0)  # the annual view is exact
        self.assertAlmostEqual(annual_to_monthly(-100), -100)

    def test_path_months_override_the_year(self):
        drop = (0.8 ** (1 / 3) - 1) * 100  # -20% over three months
        config = _economy_config(
            mode="path",
            equity_return=7.0,
            paths={"equity_return": {2027: 10.0, "2026-01": drop, "2026-2": drop, "2026-03": drop}},
        )
        economy = LifeModel(start_year=2026, end_year=2028, config=config).economy
        months = economy.monthly_rates("equity_return", 2026)
        self.assertEqual(months[:3], [drop] * 3)
        self.assertAlmostEqual(months[3], annual_to_monthly(7.0))
        expected = (0.8 * 1.07 ** (9 / 12) - 1) * 100
        self.assertAlmostEqual(economy.equity_return(2026), expected)
        self.assertEqual(economy.equity_return(2027), 10.0)
        self.assertEqual(economy.monthly_rate("equity_return", 2027, 6), annual_to_monthly(10.0))

    def test_path_keys_are_validated(self):
        with self.assertRaises(ValueError):
            _economy_config(mode="path", paths={"equity_return": {"2026-13": 1.0}})
        with self.assertRaises(ValueError):
            _economy_config(mode="stochastic", stochastic={"autocorrelation": {"equity_return": 1.0}})
        config = _economy_config(mode="stochastic", stochastic={"autocorrelation": {"not_a_rate": 0.5}})
        with self.assertRaises(ValueError):
            LifeModel(start_year=2026, config=config)

    def test_stochastic_months_compound_to_the_year_and_reproduce(self):
        def draw(seed, start="2026-01"):
            model = LifeModel(start=start, end_year=2030, seed=seed, config=_economy_config(mode="stochastic"))
            return [model.economy.monthly_rates("equity_return", y) for y in range(2026, 2031)], model

        months, model = draw(42)
        self.assertEqual(months, draw(42)[0])
        self.assertNotEqual(months, draw(7)[0])
        # A model started in October draws the same first year (the economy resolves whole years).
        self.assertEqual(months[0], draw(42, start="2026-10")[0][0])
        for year, year_months in zip(range(2026, 2031), months, strict=True):
            self.assertAlmostEqual(model.economy.equity_return(year), compound_months(year_months))
        # Monthly volatility is the annual volatility over sqrt(12).
        many = LifeModel(start_year=2000, end_year=2400, seed=3, config=_economy_config(mode="stochastic"))
        draws = [r for y in range(2000, 2400) for r in many.economy.monthly_rates("equity_return", y)]
        mean = sum(draws) / len(draws)
        std = (sum((d - mean) ** 2 for d in draws) / len(draws)) ** 0.5
        self.assertAlmostEqual(std, 15.0 / 12**0.5, delta=0.15)
        self.assertAlmostEqual(mean, annual_to_monthly(7.0), delta=0.1)

    def test_autocorrelation_clusters_months(self):
        def lag1(phi):
            stochastic = {"autocorrelation": {"equity_return": phi}} if phi else {}
            model = LifeModel(
                start_year=2000, seed=11, config=_economy_config(mode="stochastic", stochastic=stochastic)
            )
            draws = [r for y in range(2000, 2300) for r in model.economy.monthly_rates("equity_return", y)]
            mean = sum(draws) / len(draws)
            num = sum((a - mean) * (b - mean) for a, b in pairwise(draws))
            return num / sum((d - mean) ** 2 for d in draws)

        self.assertLess(abs(lag1(0.0)), 0.05)
        self.assertAlmostEqual(lag1(0.5), 0.5, delta=0.05)

    def test_cumulative_inflation_has_monthly_resolution(self):
        model = LifeModel(start_year=2026, end_year=2030, config=_economy_config(inflation=3.0))
        economy = model.economy
        self.assertEqual(economy.cumulative_inflation(2028, 1), economy.cumulative_inflation(2028))
        self.assertAlmostEqual(economy.cumulative_inflation(2028, 7), 1.03**2.5)


class TestExactAges(unittest.TestCase):
    def test_born_july_1966_is_fifty_nine_and_a_half_in_january_2026(self):
        model = LifeModel(start="2025-12", end_year=2026)
        person = Person(Family(model), "Jo", None, 65, Spending(model, 0), birth="1966-07")
        self.assertEqual(person.age, 59)
        self.assertLess(person.age_years_fractional, 59.5)  # December 2025
        model.step()
        self.assertEqual((model.year, model.month), (2026, 1))
        self.assertEqual(person.age_years_fractional, 59.5)
        self.assertEqual(person.get_period_at_age(59.5), (2026, 1))
        self.assertEqual(person.age, 59)
        for _ in range(6):
            model.step()
        self.assertEqual((model.month, person.age), (7, 60))  # the 60th birthday month
        self.assertEqual((person.get_year_at_age(60), person.age_in(2026)), (2026, 60))

    def test_age_without_birth_assumes_january(self):
        model = LifeModel(start="2026-10", end_year=2027)
        person = Person(Family(model), "Al", 40, 65, Spending(model, 0))
        self.assertEqual((person.birth_year, person.birth_month, person.birth_month_assumed), (1986, 1, True))
        self.assertEqual((person.age, person.age_years_fractional), (40, 40.75))
        model.step_year()
        self.assertEqual((model.year, person.age), (2027, 41))
        self.assertEqual(person.get_year_at_age(65), 2051)

    def test_birth_and_age_must_agree(self):
        model = LifeModel(start_year=2026)
        with self.assertRaises(ValueError):
            Person(Family(model), "Al", 40, 65, Spending(model, 0), birth="1990-03")
        with self.assertRaises(ValueError):
            Person(Family(model), "Al", None, 65, Spending(model, 0))
        person = Person(Family(model), "Al", 35, 65, Spending(model, 0), birth="1990-03")
        self.assertFalse(person.birth_month_assumed)
        person.age = 50  # re-dates the birth year, keeping the month
        self.assertEqual((person.age, person.birth_year, person.birth_month), (50, 1975, 3))


class TestMonthlyConservation(unittest.TestCase):
    """Every month's change in household net worth equals that month's ledger flows."""

    def test_scenario_households(self):
        for name, build in {
            "married_homeowners": lambda: married_homeowners(years=30),
            "stochastic_retiree": lambda: stochastic_retiree(seed=5, years=30),
            "mortality_and_estate": lambda: mortality_and_estate(years=30),
            "renter_buys_home": lambda: renter_buys_home(years=30),
        }.items():
            with self.subTest(household=name):
                model = build()
                model.run()
                assert_conservation(model, monthly=True)
                assert_conservation(model)
                self.assertFalse(check_conservation(model, monthly=True))
                months = conservation_records(model, monthly=True)
                self.assertEqual(len(months), 30 * 12)
                # The months of a year add up to the year.
                years = {r.year: r for r in conservation_records(model)}
                for year, record in years.items():
                    flow = sum(m.net_flow for m in months if m.year == year)
                    self.assertAlmostEqual(flow, record.net_flow, places=4)


if __name__ == "__main__":
    unittest.main()
