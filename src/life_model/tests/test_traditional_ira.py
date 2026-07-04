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


def _person(age: int = 40, year: int = 2020) -> Person:
    model = LifeModel(end_year=year, start_year=year)
    return Person(Family(model), "P", age, 65, Spending(model))


class TestTraditionalIRA(unittest.TestCase):
    def test_distinct_tax_treatment_from_roth(self):
        """Item 1: traditional IRA is no longer byte-identical to Roth."""
        person = _person()
        trad = TraditionalIRA(person, growth_rate=0)
        roth = RothIRA(person, growth_rate=0)
        self.assertEqual(trad.tax_treatment, TaxTreatment.PRETAX)
        self.assertTrue(trad.is_rmd_eligible)
        self.assertEqual(roth.tax_treatment, TaxTreatment.ROTH)
        self.assertFalse(roth.is_rmd_eligible)

    def test_pretax_contribution_records_deduction(self):
        person = _person(age=40)
        trad = TraditionalIRA(person, growth_rate=0)
        contributed = trad.contribute(5000)
        self.assertEqual(contributed, 5000)
        # Above-the-line deduction reduces ordinary taxable income.
        self.assertEqual(person.income.ordinary_taxable, -5000)

    def test_roth_contribution_records_no_deduction(self):
        person = _person(age=40)
        roth = RothIRA(person, growth_rate=0)
        roth.contribute(5000)
        self.assertEqual(person.income.ordinary_taxable, 0)

    def test_required_minimum_distribution_taken_and_taxed(self):
        person = _person(age=75, year=2020)
        trad = TraditionalIRA(person, balance=100000, growth_rate=0)
        trad.step()
        self.assertGreater(trad.stat_required_min_distrib, 0)
        # RMD is ordinary income (not FICA wages).
        self.assertAlmostEqual(person.income.ordinary_taxable, trad.stat_required_min_distrib)
        self.assertEqual(person.income.fica_wages, 0)

    def test_no_rmd_before_start_age(self):
        person = _person(age=60, year=2020)
        trad = TraditionalIRA(person, balance=100000, growth_rate=0)
        trad.step()
        self.assertEqual(trad.stat_required_min_distrib, 0)


if __name__ == "__main__":
    unittest.main()
