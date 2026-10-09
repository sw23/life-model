# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""AGI-dependent deductions (Plan 05 items 11 and 15).

- OBBBA senior deduction (IRC §151(d)(5)(C)): $6,000 per person 65+ in 2025-2028, reduced by 6% of
  MAGI over $75,000 ($150,000 joint); not available on separate returns.
- Charitable cash gifts capped at 60% of AGI (IRC §170(b)(1)(G)); the excess carries forward five
  years (§170(d)(1)), used after current-year gifts, oldest first.
"""

import unittest

from ..account.bank import BankAccount
from ..charity.donation import Donation
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..people.tax_unit import TaxUnit
from ..tax.deductions import senior_deduction, settle_charitable_carryforwards
from ..tax.federal import FilingStatus
from ..tax.income import IncomeType


def _person(model, age, family=None):
    person = Person(family or Family(model), "P", age=age, retirement_age=60, spending=Spending(model, 0))
    BankAccount(person, "Bank", balance=1_000_000, interest_rate=0)
    return person


class TestSeniorDeduction(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(start_year=2026, end_year=2026)
        self.config = self.model.config_for_year(2026)

    def test_full_amount_below_phaseout(self):
        person = _person(self.model, 70)
        self.assertEqual(senior_deduction([person], FilingStatus.SINGLE, 60000, 2026, self.config), 6000)

    def test_phaseout_six_percent_of_excess(self):
        person = _person(self.model, 70)
        # 6% x (100,000 - 75,000) = 1,500 off the 6,000.
        self.assertAlmostEqual(senior_deduction([person], FilingStatus.SINGLE, 100000, 2026, self.config), 4500)

    def test_joint_each_spouse_reduced_by_the_joint_excess(self):
        family = Family(self.model)
        a, b = _person(self.model, 70, family), _person(self.model, 66, family)
        # Joint MAGI 220,000: each reduced by 6% x 70,000 = 4,200 -> 1,800 each.
        status = FilingStatus.MARRIED_FILING_JOINTLY
        self.assertAlmostEqual(senior_deduction([a, b], status, 220000, 2026, self.config), 3600)

    def test_under_65_separate_return_and_after_2028_get_nothing(self):
        young, old = _person(self.model, 64), _person(self.model, 70)
        self.assertEqual(senior_deduction([young], FilingStatus.SINGLE, 50000, 2026, self.config), 0)
        status = FilingStatus.MARRIED_FILING_SEPARATELY
        self.assertEqual(senior_deduction([old], status, 50000, 2026, self.config), 0)
        self.assertEqual(senior_deduction([old], FilingStatus.SINGLE, 50000, 2029, self.config), 0)

    def test_reduces_settled_federal_tax(self):
        """Single 70-year-old, $60,000 of ordinary income in 2026: taxable 60,000 - 16,100 - 6,000 =
        37,900 -> 10% x 12,400 + 12% x 25,500 = $4,300."""
        person = _person(self.model, 70)
        person.income.add(IncomeType.ORDINARY, 60000)
        taxes = TaxUnit([person]).get_income_taxes_due()
        self.assertAlmostEqual(taxes.federal, 4300.0, places=2)


class TestCharitableLimit(unittest.TestCase):
    def test_gifts_capped_at_sixty_percent_of_agi_with_carryforward(self):
        model = LifeModel(start_year=2026, end_year=2027)
        person = _person(model, 40)
        person.income.add(IncomeType.ORDINARY, 50000)
        Donation(person, "Charity", annual_amount=40000, start_year=2026, end_year=2026)

        model.step()

        # 60% of $50k AGI = $30k deductible; the other $10k carries forward from 2026.
        self.assertEqual(person.charitable_carryforwards, [(2026, 10000)])
        self.assertAlmostEqual(person.stat_itemized_deductions, 30000 + person.stat_taxes_paid_state, places=2)

    def test_expired_carryforward_is_not_deductible(self):
        from ..tax.deductions import deductible_charity

        model = LifeModel(start_year=2026, end_year=2026)
        person = _person(model, 40)
        person.charitable_carryforwards = [(2020, 5000), (2022, 3000)]
        self.assertEqual(deductible_charity([person], 100000, model.config_for_year(2026)), 3000)

    def test_carryforward_used_after_current_gifts_and_expires(self):
        model = LifeModel(start_year=2026, end_year=2026)
        person = _person(model, 40)
        person.charitable_carryforwards = [(2021, 5000), (2024, 8000)]
        config = model.config_for_year(2026)

        # Cap 60% x 20,000 = 12,000: the 2021 gift (oldest) is used first, then 7,000 of 2024's.
        # 2021's excess was usable through 2026, so nothing of it would survive anyway.
        settle_charitable_carryforwards([person], 20000, 2026, config)
        self.assertEqual(person.charitable_carryforwards, [(2024, 1000)])

        # An excess is usable for five years after the gift (2021 -> 2022-2026): it is dropped after
        # its last year even when unused, and never used once past it.
        person.charitable_carryforwards = [(2021, 5000)]
        settle_charitable_carryforwards([person], 0, 2026, config)
        self.assertEqual(person.charitable_carryforwards, [])
        person.charitable_carryforwards = [(2020, 5000)]
        settle_charitable_carryforwards([person], 100000, 2026, config)
        self.assertEqual(person.charitable_carryforwards, [])

    def test_standard_deduction_year_records_zero_itemized(self):
        model = LifeModel(start_year=2026, end_year=2026)
        person = _person(model, 40)
        person.income.add(IncomeType.ORDINARY, 50000)
        model.step()
        self.assertEqual(person.stat_itemized_deductions, 0.0)


if __name__ == "__main__":
    unittest.main()
