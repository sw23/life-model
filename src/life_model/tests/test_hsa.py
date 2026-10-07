# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest

from ..account.hsa import HealthSavingsAccount, HSAType
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending


class TestHSA(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(start_year=2020, end_year=2020)
        self.person = Person(
            family=Family(self.model), name="Sam", age=40, retirement_age=65, spending=Spending(self.model, 0)
        )

    def _hsa(self, **kwargs):
        kwargs.setdefault("hsa_type", HSAType.INDIVIDUAL)
        return HealthSavingsAccount(self.person, **kwargs)

    def test_contribute_up_to_limit(self):
        hsa = self._hsa(contribution_limit=4000)
        self.assertEqual(hsa.contribute(3000), 3000)
        self.assertEqual(hsa.balance, 3000)
        self.assertEqual(hsa.contributions_ytd, 3000)

    def test_contribute_clamped_at_limit(self):
        hsa = self._hsa(contribution_limit=4000)
        self.assertTrue(hsa.contribute(3000))
        # Only $1000 of headroom remains; the surplus is clamped away.
        self.assertTrue(hsa.contribute(5000))
        self.assertEqual(hsa.balance, 4000)
        self.assertFalse(hsa.contribute(1))

    def test_deposit_is_not_a_contribution(self):
        """deposit() is a plain credit (rollovers, transfers); only contribute() uses the annual limit."""
        hsa = self._hsa(contribution_limit=4000)
        self.assertTrue(hsa.deposit(1000))
        self.assertEqual(hsa.balance, 1000)
        self.assertEqual(hsa.contributions_ytd, 0)
        self.assertEqual(hsa.remaining_contribution_room(), 4000)

    def test_withdraw_capped_at_balance(self):
        hsa = self._hsa(contribution_limit=4000, balance=2000)
        self.assertEqual(hsa.withdraw(5000), 2000)
        self.assertEqual(hsa.balance, 0)

    def test_medical_and_non_medical_withdraw_reduce_balance(self):
        hsa = self._hsa(contribution_limit=4000, balance=1000)
        self.assertEqual(hsa.withdraw_medical(400), 400)
        self.assertEqual(hsa.withdraw_non_medical(200), 200)
        self.assertEqual(hsa.balance, 400)

    def test_reset_annual_contributions(self):
        hsa = self._hsa(contribution_limit=4000)
        hsa.contribute(4000)
        hsa.reset_annual_contributions()
        self.assertEqual(hsa.contributions_ytd, 0)
        # Fresh headroom after reset.
        self.assertTrue(hsa.contribute(1000))

    def test_employer_contribution_added_in_step(self):
        """The full annual employer contribution lands once per yearly step (was 1/12, Plan 06 item 5)."""
        hsa = self._hsa(contribution_limit=8000, employer_contribution=1200, growth_rate=0)
        hsa.step()
        self.assertAlmostEqual(hsa.balance, 1200, places=6)
        # Employer money counts against the same annual limit.
        self.assertEqual(hsa.contributions_ytd, 1200)

    def test_family_limit_higher_than_individual(self):
        individual = HealthSavingsAccount(self.person, HSAType.INDIVIDUAL)
        family = HealthSavingsAccount(self.person, HSAType.FAMILY)
        self.assertGreater(family.annual_contribution_limit(), individual.annual_contribution_limit())


def _plan06_person(age: int = 40, year: int = 2020) -> Person:
    model = LifeModel(end_year=year, start_year=year)
    return Person(Family(model), "P", age, 65, Spending(model))


class TestHSALimitsAndTaxes(unittest.TestCase):
    def test_age_55_catch_up(self):
        young = HealthSavingsAccount(_plan06_person(age=40), HSAType.INDIVIDUAL, employer_contribution=0)
        old = HealthSavingsAccount(_plan06_person(age=56), HSAType.INDIVIDUAL, employer_contribution=0)
        self.assertEqual(old.annual_contribution_limit(), young.annual_contribution_limit() + 1000)

    def test_family_limit_includes_employer_contribution(self):
        person = _plan06_person()
        hsa = HealthSavingsAccount(person, HSAType.FAMILY, growth_rate=0, employer_contribution=3000)
        hsa.step()
        self.assertEqual(hsa.remaining_contribution_room(), hsa.annual_contribution_limit() - 3000)

    def test_personal_contribution_is_deductible(self):
        person = _plan06_person()
        hsa = HealthSavingsAccount(person, HSAType.INDIVIDUAL, employer_contribution=0)
        hsa.contribute(2000)
        self.assertEqual(person.income.ordinary_taxable, -2000)

    def test_non_medical_withdrawal_is_taxed_and_penalized_under_65(self):
        person = _plan06_person(age=40)
        hsa = HealthSavingsAccount(person, HSAType.INDIVIDUAL, balance=1000, employer_contribution=0)
        self.assertEqual(hsa.withdraw_non_medical(500), 500)
        self.assertEqual(person.income.ordinary_taxable, 500)
        self.assertAlmostEqual(person.income.penalties, 100)  # 20% of 500

    def test_non_medical_withdrawal_no_penalty_at_65(self):
        person = _plan06_person(age=66)
        hsa = HealthSavingsAccount(person, HSAType.INDIVIDUAL, balance=1000, employer_contribution=0)
        hsa.withdraw_non_medical(500)
        self.assertEqual(person.income.penalties, 0)
        self.assertEqual(person.income.ordinary_taxable, 500)

    def test_medical_withdrawal_is_tax_free(self):
        person = _plan06_person(age=40)
        hsa = HealthSavingsAccount(person, HSAType.INDIVIDUAL, balance=1000, employer_contribution=0)
        hsa.withdraw_medical(500)
        self.assertEqual(person.income.ordinary_taxable, 0)
        self.assertEqual(person.income.penalties, 0)


if __name__ == "__main__":
    unittest.main()
