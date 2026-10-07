# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Married filing separately (Plan 05 item 8).

2026 values from IRS Rev. Proc. 2025-32: the separate-return standard deduction is $16,100 and the
37% rate starts at $384,350 (half the joint $768,700). Statutory separate-filer thresholds: $125,000
for the additional Medicare tax and NIIT, a zero base amount for Social Security benefit taxation.
"""

import unittest

from ..account.bank import BankAccount
from ..config.financial_config import FinancialConfig
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..people.tax_unit import TaxUnit
from ..tax.federal import (
    FilingStatus,
    federal_income_tax,
    get_federal_standard_deduction,
    get_federal_tax_brackets,
)
from ..tax.fica import get_medicare_additional_rate_threshold
from ..work.job import Job, Salary


class TestSeparateReturnParameters(unittest.TestCase):
    def setUp(self):
        self.config = LifeModel(start_year=2026, end_year=2026).config_for_year(2026)

    def test_standard_deduction_is_half_the_joint_amount(self):
        self.assertEqual(get_federal_standard_deduction(FilingStatus.MARRIED_FILING_SEPARATELY, self.config), 16100)

    def test_brackets_are_the_joint_brackets_halved(self):
        brackets = get_federal_tax_brackets(FilingStatus.MARRIED_FILING_SEPARATELY, self.config)
        self.assertEqual(brackets[-2][1], 384350)  # 35% bracket tops out where 37% begins
        self.assertEqual(brackets[0][1], 12400)

    def test_tax_on_100k_wages_hand_computed(self):
        # Taxable $83,900: 10% x 12,400 + 12% x 38,000 + 22% x 33,500 = 1,240 + 4,560 + 7,370.
        tax = federal_income_tax(100000 - 16100, FilingStatus.MARRIED_FILING_SEPARATELY, self.config)
        self.assertAlmostEqual(tax, 13170.00, places=2)

    def test_statutory_thresholds(self):
        status = FilingStatus.MARRIED_FILING_SEPARATELY
        self.assertEqual(get_medicare_additional_rate_threshold(status, self.config), 125000)
        self.assertEqual(self.config.tax.federal.niit.threshold_for(status), 125000)


class TestSeparateReturnsInSimulation(unittest.TestCase):
    def _couple(self, *, separately: bool, start_year: int = 2026):
        model = LifeModel(start_year=start_year, end_year=start_year)
        family = Family(model)
        a = Person(family, "A", age=40, retirement_age=70, spending=Spending(model, 0))
        b = Person(family, "B", age=40, retirement_age=70, spending=Spending(model, 0))
        a.get_married(b)
        if separately:
            a.filing_status = b.filing_status = FilingStatus.MARRIED_FILING_SEPARATELY
        for person in (a, b):
            BankAccount(person, "Bank", balance=100000, interest_rate=0)
        return model, a, b

    def test_each_spouse_is_its_own_unit(self):
        _model, a, _b = self._couple(separately=True)
        units = TaxUnit.build_units(a.family)
        self.assertEqual(len(units), 2)
        self.assertTrue(all(u.filing_status == FilingStatus.MARRIED_FILING_SEPARATELY for u in units))

    def test_equal_earners_owe_the_same_federal_tax_either_way(self):
        """With identical incomes and only standard deductions, separate returns are exactly half of
        a joint return, because every separate amount is half the joint one."""
        totals = {}
        for separately in (False, True):
            model, a, b = self._couple(separately=separately)
            for person in (a, b):
                Job(person, "Co", "Dev", Salary(model=model, base=90000, yearly_increase=0, yearly_bonus=0))
            model.step()
            totals[separately] = sum(p.stat_taxes_paid_federal for p in (a, b))
        self.assertAlmostEqual(totals[True], totals[False], places=2)

    def test_spouse_itemizing_forces_zero_standard_deduction(self):
        model, a, b = self._couple(separately=True)
        # Give B itemized deductions above the separate standard deduction ($16,100).
        from ..charity.donation import Donation

        Donation(b, "Charity", annual_amount=30000, start_year=2026, end_year=2026)
        for agent in model.agents:  # the donation lands in pre_step
            agent.pre_step()
        # A has nothing to itemize, but because B itemizes, A's standard deduction is zero.
        self.assertEqual(a.standard_deduction, 0.0)

    def test_student_loan_interest_not_deductible_separately(self):
        from ..debt.student_loan import StudentLoan, StudentLoanType

        def federal_tax(separately: bool, with_loan: bool) -> float:
            model, a, b = self._couple(separately=separately)
            Job(a, "Co", "Dev", Salary(model=model, base=60000, yearly_increase=0, yearly_bonus=0))
            if with_loan:
                StudentLoan(a, StudentLoanType.FEDERAL_UNSUBSIDIZED, 40000, 6.0, 10, "U")
            model.step()
            return a.stat_taxes_paid_federal + b.stat_taxes_paid_federal

        # Jointly, the interest deduction lowers tax; separately (IRC §221(e)(2)) it does not.
        self.assertLess(federal_tax(False, True), federal_tax(False, False))
        self.assertAlmostEqual(federal_tax(True, True), federal_tax(True, False), places=2)


class TestSeparateReturnBenefitsAndMedicare(unittest.TestCase):
    def test_social_security_taxable_from_first_dollar(self):
        from ..insurance.social_security import SocialSecurity

        model = LifeModel(start_year=2026, end_year=2026)
        family = Family(model)
        a = Person(family, "A", age=70, retirement_age=60, spending=Spending(model, 0))
        b = Person(family, "B", age=70, retirement_age=60, spending=Spending(model, 0))
        a.get_married(b)
        a.filing_status = b.filing_status = FilingStatus.MARRIED_FILING_SEPARATELY
        BankAccount(a, "Bank", balance=0)
        ss = SocialSecurity(person=a, withdrawal_start_age=67)
        # Zero base amount: provisional 0.5 x 20,000 = 10,000 -> 85% inclusion caps at 0.85 x 10,000.
        self.assertAlmostEqual(ss._taxable_benefit_portion(20000), 8500.0, places=2)

    def test_irmaa_skips_middle_tiers(self):
        from ..healthcare.medicare import Medicare

        config = FinancialConfig()
        config.apply_scenario("flat", {"economy": {"inflation": 0.0}})
        model = LifeModel(start_year=2026, end_year=2026, config=config)
        person = Person(Family(model), "P", age=70, retirement_age=60, spending=Spending(model, 0))
        person.filing_status = FilingStatus.MARRIED_FILING_SEPARATELY
        medicare = Medicare(person)
        tiers = medicare.config.irmaa_tiers
        self.assertIs(medicare._tier(100000), tiers[0])
        self.assertIs(medicare._tier(110000), tiers[-2])
        self.assertIs(medicare._tier(400000), tiers[-1])


if __name__ == "__main__":
    unittest.main()
