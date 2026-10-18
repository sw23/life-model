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

from ..account.bank import BankAccount
from ..checks import assert_conservation, check_conservation, conservation_records
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
