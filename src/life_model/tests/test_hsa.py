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
        self.assertTrue(hsa.contribute(3000))
        self.assertEqual(hsa.balance, 3000)
        self.assertEqual(hsa.annual_contributions, 3000)

    def test_contribute_clamped_at_limit(self):
        hsa = self._hsa(contribution_limit=4000)
        self.assertTrue(hsa.contribute(3000))
        # Only $1000 of headroom remains; the surplus is clamped away.
        self.assertTrue(hsa.contribute(5000))
        self.assertEqual(hsa.balance, 4000)
        self.assertFalse(hsa.contribute(1))

    def test_deposit_is_a_contribution(self):
        hsa = self._hsa(contribution_limit=4000)
        self.assertTrue(hsa.deposit(1000))
        self.assertEqual(hsa.annual_contributions, 1000)

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
        self.assertEqual(hsa.annual_contributions, 0)
        # Fresh headroom after reset.
        self.assertTrue(hsa.contribute(1000))

    def test_employer_contribution_added_in_step(self):
        hsa = self._hsa(contribution_limit=8000, employer_contribution=1200)
        hsa.step()
        self.assertAlmostEqual(hsa.balance, 1200 / 12, places=6)

    def test_family_limit_higher_than_individual(self):
        individual = HealthSavingsAccount(self.person, HSAType.INDIVIDUAL)
        family = HealthSavingsAccount(self.person, HSAType.FAMILY)
        self.assertGreater(family.contribution_limit, individual.contribution_limit)


if __name__ == "__main__":
    unittest.main()
