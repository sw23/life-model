# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest

from ..account.hsa import HealthSavingsAccount, HSAType
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending


def _person(age: int = 40) -> Person:
    model = LifeModel(1)
    return Person(Family(model), "P", age, 65, Spending(model))


class TestHSA(unittest.TestCase):
    def test_individual_vs_family_limit(self):
        person = _person()
        individual = HealthSavingsAccount(person, HSAType.INDIVIDUAL, employer_contribution=0)
        family = HealthSavingsAccount(person, HSAType.FAMILY, employer_contribution=0)
        # Fixture-free: uses live defaults (self-only 4400, family 8750).
        self.assertGreater(family.annual_contribution_limit(), individual.annual_contribution_limit())

    def test_age_55_catch_up(self):
        young = _person(age=40)
        old = _person(age=56)
        young_hsa = HealthSavingsAccount(young, HSAType.INDIVIDUAL, employer_contribution=0)
        old_hsa = HealthSavingsAccount(old, HSAType.INDIVIDUAL, employer_contribution=0)
        self.assertEqual(
            old_hsa.annual_contribution_limit(),
            young_hsa.annual_contribution_limit() + 1000,
        )

    def test_contribution_capped_at_limit(self):
        person = _person()
        hsa = HealthSavingsAccount(person, HSAType.INDIVIDUAL, employer_contribution=0)
        limit = hsa.annual_contribution_limit()
        contributed = hsa.contribute(limit + 5000)
        self.assertEqual(contributed, limit)
        self.assertEqual(hsa.remaining_contribution_room(), 0)
        # Second contribution in the same year adds nothing.
        self.assertEqual(hsa.contribute(1000), 0)

    def test_employer_contribution_once_per_year_and_counts_toward_limit(self):
        person = _person()
        hsa = HealthSavingsAccount(person, HSAType.INDIVIDUAL, balance=0, growth_rate=0, employer_contribution=1200)
        hsa.step()
        # Once per year (not 1/12): full 1200 lands.
        self.assertEqual(hsa.balance, 1200)
        # And it consumed 1200 of the annual limit.
        self.assertEqual(hsa.contributions_ytd, 1200)

    def test_annual_contribution_resets_in_post_step(self):
        person = _person()
        hsa = HealthSavingsAccount(person, HSAType.INDIVIDUAL, employer_contribution=0)
        hsa.contribute(1000)
        self.assertEqual(hsa.contributions_ytd, 1000)
        hsa.post_step()
        self.assertEqual(hsa.contributions_ytd, 0)

    def test_non_medical_withdrawal_is_taxed_and_penalized_under_65(self):
        person = _person(age=40)
        hsa = HealthSavingsAccount(person, HSAType.INDIVIDUAL, balance=1000, employer_contribution=0)
        withdrawn = hsa.withdraw_non_medical(500)
        self.assertEqual(withdrawn, 500)
        self.assertEqual(person.income.ordinary_taxable, 500)
        self.assertAlmostEqual(person.income.penalties, 100)  # 20% of 500

    def test_non_medical_withdrawal_no_penalty_at_65(self):
        person = _person(age=66)
        hsa = HealthSavingsAccount(person, HSAType.INDIVIDUAL, balance=1000, employer_contribution=0)
        hsa.withdraw_non_medical(500)
        self.assertEqual(person.income.penalties, 0)
        self.assertEqual(person.income.ordinary_taxable, 500)

    def test_medical_withdrawal_is_tax_free(self):
        person = _person(age=40)
        hsa = HealthSavingsAccount(person, HSAType.INDIVIDUAL, balance=1000, employer_contribution=0)
        hsa.withdraw_medical(500)
        self.assertEqual(person.income.ordinary_taxable, 0)
        self.assertEqual(person.income.penalties, 0)


if __name__ == "__main__":
    unittest.main()
