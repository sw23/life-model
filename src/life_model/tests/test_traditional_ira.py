# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest

from ..account.roth_IRA import RothIRA
from ..account.traditional_IRA import TraditionalIRA
from ..base_classes import TaxTreatment
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending


class TestTraditionalIRA(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(start_year=2020, end_year=2020)
        self.person = Person(
            family=Family(self.model), name="Sam", age=40, retirement_age=65, spending=Spending(self.model, 0)
        )

    def _ira(self, **kwargs):
        kwargs.setdefault("growth_rate", 5.0)
        return TraditionalIRA(self.person, **kwargs)

    def test_contribute_up_to_limit(self):
        ira = self._ira(contribution_limit=6000)
        self.assertEqual(ira.contribute(4000), 4000)
        self.assertEqual(ira.balance, 4000)

    def test_contribute_clamped_at_limit(self):
        ira = self._ira(contribution_limit=6000)
        ira.contribute(5000)
        self.assertEqual(ira.contribute(5000), 1000)
        self.assertEqual(ira.balance, 6000)

    def test_deposit_is_a_plain_credit(self):
        """deposit() credits without using contribution room (rollovers); validation is uniform."""
        ira = self._ira(contribution_limit=6000)
        self.assertTrue(ira.deposit(1000))
        self.assertEqual(ira.balance, 1000)
        self.assertEqual(ira.remaining_contribution_room(), 6000)
        self.assertTrue(ira.deposit(0))
        with self.assertRaises(ValueError):
            ira.deposit(-100)

    def test_withdraw_capped_at_balance(self):
        ira = self._ira(contribution_limit=6000, balance=3000)
        self.assertEqual(ira.withdraw(5000), 3000)
        self.assertEqual(ira.balance, 0)
        self.assertEqual(ira.withdraw(100), 0)

    def test_deposit_withdraw_round_trip(self):
        ira = self._ira(contribution_limit=6000)
        ira.deposit(2000)
        self.assertEqual(ira.withdraw(2000), 2000)
        self.assertEqual(ira.balance, 0)

    def test_growth_positive_on_positive_balance(self):
        ira = self._ira(contribution_limit=6000, balance=1000)
        growth = ira.calculate_growth()
        self.assertAlmostEqual(growth, 50.0, places=6)

    def test_reset_annual_contributions(self):
        ira = self._ira(contribution_limit=6000)
        ira.contribute(6000)
        ira.reset_annual_contributions()
        self.assertEqual(ira.contributions_ytd, 0)
        self.assertEqual(ira.contribute(1000), 1000)


def _plan06_person(age: int = 40, year: int = 2020) -> Person:
    model = LifeModel(end_year=year, start_year=year)
    return Person(Family(model), "P", age, 65, Spending(model))


class TestTraditionalIRATaxSemantics(unittest.TestCase):
    def test_distinct_tax_treatment_from_roth(self):
        """Plan 06 item 1: traditional IRA is no longer identical to Roth."""
        person = _plan06_person()
        trad = TraditionalIRA(person, growth_rate=0)
        roth = RothIRA(person, growth_rate=0)
        self.assertEqual(trad.tax_treatment, TaxTreatment.PRETAX)
        self.assertTrue(trad.is_rmd_eligible)
        self.assertEqual(roth.tax_treatment, TaxTreatment.ROTH)
        self.assertFalse(roth.is_rmd_eligible)

    def test_pretax_contribution_records_deduction(self):
        person = _plan06_person(age=40)
        trad = TraditionalIRA(person, growth_rate=0)
        self.assertEqual(trad.contribute(5000), 5000)
        self.assertEqual(person.income.ordinary_taxable, -5000)

    def test_roth_contribution_records_no_deduction(self):
        person = _plan06_person(age=40)
        RothIRA(person, growth_rate=0).contribute(5000)
        self.assertEqual(person.income.ordinary_taxable, 0)

    def test_early_withdrawal_is_taxed_and_penalized(self):
        person = _plan06_person(age=40)
        TraditionalIRA(person, balance=10000, growth_rate=0)
        person.withdraw_from_traditional_iras(2000)
        self.assertEqual(person.income.ordinary_taxable, 2000)
        self.assertAlmostEqual(person.income.penalties, 200)

    def test_required_minimum_distribution_taken_and_taxed(self):
        person = _plan06_person(age=75, year=2020)
        trad = TraditionalIRA(person, balance=100000, growth_rate=0)
        trad.pre_step()
        self.assertGreater(trad.stat_required_min_distrib, 0)
        self.assertAlmostEqual(person.income.ordinary_taxable, trad.stat_required_min_distrib)
        self.assertEqual(person.income.fica_wages, 0)
        self.assertEqual(person.income.penalties, 0)

    def test_no_rmd_before_start_age(self):
        person = _plan06_person(age=60, year=2020)
        trad = TraditionalIRA(person, balance=100000, growth_rate=0)
        trad.pre_step()
        self.assertEqual(trad.stat_required_min_distrib, 0)


if __name__ == "__main__":
    unittest.main()
