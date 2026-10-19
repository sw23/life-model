# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Year-indexed tax parameters in the ``tax_years`` table, pinned to the primary
sources they were verified against (Rev. Procs. 2021-45, 2022-38, 2023-34, 2024-40, 2025-32; OBBBA,
P.L. 119-21), and the per-return SALT cap with its OBBBA phase-down."""

import unittest
from unittest import mock

from ..config.financial_config import FinancialConfig
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..people.tax_unit import TaxUnit
from ..tax.credits import child_tax_credit_parts
from ..tax.deductions import salt_cap
from ..tax.federal import FilingStatus

CONFIG = FinancialConfig()


def view(year: int, factor: float = 1.0) -> FinancialConfig:
    return CONFIG.year_view(CONFIG.tax_year(year, factor), factor)


class TestPublishedValues(unittest.TestCase):
    def test_capital_gains_thresholds(self):
        # (0% top, 15% top) per status: single, joint, head of household, separate.
        expected = {
            2022: ((41675, 459750), (83350, 517200), (55800, 488500), (41675, 258600)),  # RP 2021-45 §3.03
            2023: ((44625, 492300), (89250, 553850), (59750, 523050), (44625, 276900)),  # RP 2022-38 §3.03
            2024: ((47025, 518900), (94050, 583750), (63000, 551350), (47025, 291850)),  # RP 2023-34 §3.03
            2025: ((48350, 533400), (96700, 600050), (64750, 566700), (48350, 300000)),  # RP 2024-40 §2.03
            2026: ((49450, 545500), (98900, 613700), (66200, 579600), (49450, 306850)),  # RP 2025-32 §4.03
        }
        statuses = (
            FilingStatus.SINGLE,
            FilingStatus.MARRIED_FILING_JOINTLY,
            FilingStatus.HEAD_OF_HOUSEHOLD,
            FilingStatus.MARRIED_FILING_SEPARATELY,
        )
        for year, rows in expected.items():
            config = view(year)
            for status, (zero_top, fifteen_top) in zip(statuses, rows, strict=True):
                with self.subTest(year=year, status=status.name):
                    brackets = config.get_capital_gains_brackets(status)
                    self.assertEqual((brackets[0][1], brackets[1][1]), (zero_top, fifteen_top))

    def test_child_tax_credit(self):
        expected = {2022: (2000, 1500), 2023: (2000, 1600), 2024: (2000, 1700), 2025: (2200, 1700), 2026: (2200, 1700)}
        for year, amounts in expected.items():
            dependents = view(year).dependents
            self.assertEqual((dependents.ctc_per_child, dependents.ctc_refundable_max), amounts, year)
        # 2024 vs 2025 on the same return: $2,000 vs $2,200 per child.
        self.assertEqual(
            sum(child_tax_credit_parts(2, 100000, 10000, FilingStatus.MARRIED_FILING_JOINTLY, view(2024))), 4000
        )
        self.assertEqual(
            sum(child_tax_credit_parts(2, 100000, 10000, FilingStatus.MARRIED_FILING_JOINTLY, view(2025))), 4400
        )

    def test_2026_head_of_household_bracket(self):
        # Rev. Proc. 2025-32 §4.01 Table 2: 24% over $105,700 but not over $201,750.
        brackets = view(2026).get_federal_tax_brackets(FilingStatus.HEAD_OF_HOUSEHOLD)
        self.assertEqual(brackets[3][1], 201750)
        self.assertEqual(brackets[4][0], 201751)

    def test_senior_deduction_and_niit_by_year(self):
        self.assertEqual(view(2024).tax.federal.senior_deduction.amount, 0)
        self.assertEqual(view(2025).tax.federal.senior_deduction.amount, 6000)
        for year in (2022, 2026):
            niit = view(year).tax.federal.niit
            self.assertEqual(
                (niit.single, niit.married_filing_jointly, niit.married_filing_separately), (200000, 250000, 125000)
            )

    def test_additional_standard_deduction_recorded(self):
        # §63(f) amounts (married, unmarried), applied as the additional standard deduction for 65+.
        expected = {2022: (1400, 1750), 2023: (1500, 1850), 2024: (1550, 1950), 2025: (1600, 2000), 2026: (1650, 2050)}
        for year, (married, unmarried) in expected.items():
            extra = CONFIG.tax_year(year).additional_standard_deduction
            self.assertEqual((extra.married, extra.unmarried), (married, unmarried), year)


class TestSaltCap(unittest.TestCase):
    def test_caps_by_year(self):
        single = FilingStatus.SINGLE
        self.assertEqual(salt_cap(single, 100000, view(2024)), 10000)
        self.assertEqual(salt_cap(single, 100000, view(2025)), 40000)
        self.assertEqual(salt_cap(single, 100000, view(2026)), 40400)
        self.assertEqual(salt_cap(FilingStatus.MARRIED_FILING_SEPARATELY, 100000, view(2024)), 5000)
        self.assertEqual(salt_cap(FilingStatus.MARRIED_FILING_SEPARATELY, 100000, view(2025)), 20000)

    def test_obbba_phase_down(self):
        joint = FilingStatus.MARRIED_FILING_JOINTLY
        # 2025: 40,000 - 30% x (550,000 - 500,000) = 25,000; floor 10,000.
        self.assertAlmostEqual(salt_cap(joint, 550000, view(2025)), 25000)
        self.assertEqual(salt_cap(joint, 700000, view(2025)), 10000)
        # Separate: 20,000 - 30% x (260,000 - 250,000) = 17,000; floor 5,000.
        self.assertAlmostEqual(salt_cap(FilingStatus.MARRIED_FILING_SEPARATELY, 260000, view(2025)), 17000)

    def test_statutory_schedule_after_the_table(self):
        # §164(b)(7): +1% a year through 2029 (not inflation), $10,000 without phase-down from 2030.
        for year, factor in ((2027, 1.03), (2029, 1.09)):
            config = view(year, factor)
            self.assertAlmostEqual(config.tax.federal.salt_deduction_cap, round(40400 * 1.01 ** (year - 2026), 2))
        config = view(2030, 1.13)
        self.assertEqual(config.tax.federal.salt_deduction_cap, 10000)
        self.assertIsNone(config.tax.federal.salt_phaseout_threshold)

    def test_cap_is_per_return_not_per_spouse(self):
        model = LifeModel(start_year=2025, end_year=2025)
        family = Family(model)
        head = Person(family=family, name="A", age=50, retirement_age=65, spending=Spending(model, base_annual=0))
        spouse = Person(family=family, name="B", age=50, retirement_age=65, spending=Spending(model, base_annual=0))
        head.get_married(spouse)
        unit = TaxUnit.build_units(family)[0]
        with mock.patch.object(Person, "salt_paid", lambda self, state=0.0: 30000.0 + state):
            # Each spouse pays $30,000 of property tax: the joint return deducts $40,000, not $60,000.
            self.assertEqual(unit.salt_deduction(), 40000)
            self.assertEqual(unit.itemized_components()["salt"], 40000)


if __name__ == "__main__":
    unittest.main()
