# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the age-related medical cost curve agent."""

import unittest

from ..account.bank import BankAccount
from ..healthcare import MedicalCosts
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending


def _make_person(model, age, base_spending=0, balance=1_000_000):
    family = Family(model)
    person = Person(family=family, name="P", age=age, retirement_age=65, spending=Spending(model, base=base_spending))
    BankAccount(owner=person, company="Bank", balance=balance)
    return person


class TestMedicalCosts(unittest.TestCase):
    def test_band_lookup(self):
        """The cost curve maps ages to the configured bands (inclusive upper bounds)."""
        model = LifeModel(start_year=2026, end_year=2027)
        person = _make_person(model, age=30)
        mc = MedicalCosts(person)
        bands = model.config.healthcare.medical_cost_bands
        self.assertEqual(mc._band_cost(30), bands[0].annual_cost)
        self.assertEqual(mc._band_cost(39), bands[0].annual_cost)
        self.assertEqual(mc._band_cost(40), bands[1].annual_cost)
        self.assertEqual(mc._band_cost(70), bands[2].annual_cost)
        self.assertEqual(mc._band_cost(80), bands[3].annual_cost)
        self.assertEqual(mc._band_cost(90), bands[4].annual_cost)
        self.assertEqual(mc._band_cost(500), bands[-1].annual_cost)

    def test_registry_and_property(self):
        """The agent registers itself and is reachable via person.medical_costs."""
        model = LifeModel(start_year=2026, end_year=2027)
        person = _make_person(model, age=30)
        mc = MedicalCosts(person)
        self.assertEqual(person.medical_costs, [mc])

    def test_cost_charged_through_spending(self):
        """pre_step adds the year's medical cost to spending; settlement pays it."""
        model = LifeModel(start_year=2026, end_year=2026)
        person = _make_person(model, age=70, base_spending=10000)
        MedicalCosts(person)
        model.step()
        # Age 70 -> 71 during pre_step, still in the 65-74 band (6000 real, start-year factor 1.0).
        self.assertEqual(person.stat_money_spent, 16000)

    def test_medical_inflation_premium_applies(self):
        """Nominal medical cost grows at CPI + premium (2pp above the fixed 3% CPI)."""
        model = LifeModel(start_year=2026, end_year=2036)
        person = _make_person(model, age=65)
        mc = MedicalCosts(person)
        # After N years the factor is (1 + (3+2)/100)^N.
        factor_2030 = mc._medical_inflation_factor(2030)
        self.assertAlmostEqual(factor_2030, 1.05**4, places=10)

    def test_age_increasing_real_medical_spend(self):
        """A seeded retiree run shows medical spend rising faster than CPI."""
        model = LifeModel(start_year=2026, end_year=2056, seed=42)
        person = _make_person(model, age=60, base_spending=0)
        MedicalCosts(person)
        model.run()
        df = model.datacollector.get_model_vars_dataframe()
        med = df["Medical Costs"].tolist()
        years = df["Year"].tolist()
        # Nominal medical spend is non-decreasing (band jumps + medical inflation).
        for a, b in zip(med, med[1:]):
            self.assertGreaterEqual(b, a)
        # Real (CPI-deflated) medical spend increases with age across the run: deflate by CPI
        # only; the band jumps (65/75/85) plus the 2pp medical premium dominate.
        real = [m / model.economy.cumulative_inflation(int(y)) for m, y in zip(med, years)]
        self.assertGreater(real[-1], real[0] * 2)

    def test_conservation_with_retiree(self):
        """Liquid-asset conservation holds: delta bank == income - spending - taxes each year."""
        model = LifeModel(start_year=2026, end_year=2046, seed=7)
        person = _make_person(model, age=64, base_spending=20000, balance=2_000_000)
        MedicalCosts(person)
        model.run()
        df = model.datacollector.get_model_vars_dataframe()
        bank = df["Bank Balance"].tolist()
        income = df["Income"].tolist()
        spending = df["Spending"].tolist()
        taxes = df["Taxes"].tolist()
        prev = 2_000_000
        for i in range(len(bank)):
            expected = prev + income[i] - spending[i] - taxes[i]
            self.assertAlmostEqual(bank[i], expected, places=2, msg=f"conservation broke in row {i}")
            prev = bank[i]

    def test_no_agent_no_effect(self):
        """Without a MedicalCosts agent, frames are unchanged (opt-in guarantee)."""

        def run(with_medical: bool):
            model = LifeModel(start_year=2026, end_year=2036, seed=3)
            person = _make_person(model, age=50, base_spending=30000)
            if with_medical:
                MedicalCosts(person)
            model.run()
            return model.datacollector.get_model_vars_dataframe()

        base = run(False)
        again = run(False)
        self.assertTrue(base.equals(again))
        with_med = run(True)
        self.assertFalse(base["Spending"].equals(with_med["Spending"]))
        self.assertTrue((base["Medical Costs"] == 0).all())

    def test_deceased_person_stops_incurring_costs(self):
        """A deceased person's MedicalCosts agent charges nothing."""
        model = LifeModel(start_year=2026, end_year=2027)
        person = _make_person(model, age=70)
        mc = MedicalCosts(person)
        person.is_deceased = True
        mc.stat_medical_costs = 0.0
        mc.pre_step()
        self.assertEqual(mc.stat_medical_costs, 0.0)
        self.assertEqual(person.spending.one_time_expenses, 0)


if __name__ == "__main__":
    unittest.main()
