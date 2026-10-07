# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Table-driven, cent-exact checks against the 2026 published federal tables (Plan 05 / Plan 13).

Every expected value is hand-computed from IRS Rev. Proc. 2025-32 (2026 brackets, standard deduction,
capital-gains breakpoints), SSA's 2026 wage base ($184,500), and the statutory FICA/NIIT rates and
thresholds. The parameters come from the 2026 entry of the year table, which is historical and does
not move when later years are added.

Cumulative ordinary tax at each 2026 bracket top, used below:
  single: 12,400 -> 1,240.00 | 50,400 -> 5,800.00 | 105,700 -> 17,966.00 | 201,775 -> 41,024.00 |
          256,225 -> 58,448.00 | 640,600 -> 192,979.25
  joint:  24,800 -> 2,480.00 | 100,800 -> 11,600.00 | 211,400 -> 35,932.00 | 403,550 -> 82,048.00 |
          512,450 -> 116,896.00 | 768,700 -> 206,583.50
  head of household: 17,700 -> 1,770.00 | 67,450 -> 7,740.00
"""

import unittest

from ..model import LifeModel
from ..tax.federal import FilingStatus, federal_income_tax, net_investment_income_tax
from ..tax.tax import compute_taxes

S = FilingStatus.SINGLE
J = FilingStatus.MARRIED_FILING_JOINTLY
H = FilingStatus.HEAD_OF_HOUSEHOLD
M = FilingStatus.MARRIED_FILING_SEPARATELY

# (description, filing status, taxable ordinary income, expected federal income tax)
ORDINARY_CASES = [
    ("single $1 below the 10% bracket top", S, 12399, 1239.90),
    ("single at the 10% bracket top", S, 12400, 1240.00),
    ("single $1 above the 10% bracket top", S, 12401, 1240.12),
    ("single mid 12% bracket", S, 50000, 5752.00),  # 1,240 + 12% x 37,600
    ("single at the 22% bracket top", S, 105700, 17966.00),
    ("single in the 37% bracket", S, 700000, 214957.25),  # 192,979.25 + 37% x 59,400
    ("joint mid 12% bracket", J, 100000, 11504.00),  # 2,480 + 12% x 75,200
    ("joint $1 above the 22% bracket top", J, 211401, 35932.24),
    ("joint in the 24% bracket", J, 400000, 81196.00),  # 35,932 + 24% x 188,600
    ("joint in the 37% bracket", J, 1000000, 292164.50),  # 206,583.50 + 37% x 231,300
    ("head of household mid 12% bracket", H, 60000, 6846.00),  # 1,770 + 12% x 42,300
    ("separate at the 35% bracket top", M, 384350, 103291.75),  # half the joint 768,700 tax
]

# (description, filing status, wages per worker, expected Social Security, expected Medicare)
PAYROLL_CASES = [
    ("single at the wage base", S, [184500], 11439.00, 2675.25),
    ("single above the cap and the additional-Medicare threshold", S, [300000], 11439.00, 5250.00),
    # Per-worker cap: 6.2% x 184,500 + 6.2% x 100,000. Additional Medicare on combined wages over
    # $250k: 1.45% x 300,000 + 0.9% x 50,000.
    ("joint two earners, one over the wage base", J, [200000, 100000], 17639.00, 4800.00),
]

# (description, filing status, taxable ordinary, taxable long-term gain, expected federal tax)
GAINS_CASES = [
    # Ordinary 40,000 -> 1,240 + 12% x 27,600 = 4,552; the gain stacks on top: 9,450 in the 0% band,
    # 10,550 at 15% -> 1,582.50.
    ("single gain straddling the 0%/15% breakpoint", S, 40000, 20000, 6134.50),
    # All gain: 98,900 at 0%, 1,100 at 15%.
    ("joint gain-only return", J, 0, 100000, 165.00),
]


class TestIrsGolden2026(unittest.TestCase):
    def setUp(self):
        self.config = LifeModel(start_year=2026, end_year=2026).config_for_year(2026)

    def test_ordinary_income_tax(self):
        for description, status, taxable, expected in ORDINARY_CASES:
            with self.subTest(description):
                self.assertAlmostEqual(federal_income_tax(taxable, status, self.config), expected, places=2)

    def test_payroll_taxes(self):
        for description, status, wages, social_security, medicare in PAYROLL_CASES:
            with self.subTest(description):
                taxes = compute_taxes(sum(wages), 0, status, wages, self.config, state_tax=0)
                self.assertAlmostEqual(taxes.ss, social_security, places=2)
                self.assertAlmostEqual(taxes.medicare, medicare, places=2)

    def test_preferential_gains_stack_on_ordinary_income(self):
        for description, status, ordinary, gain, expected in GAINS_CASES:
            with self.subTest(description):
                taxes = compute_taxes(ordinary, 0, status, [], self.config, state_tax=0, preferential_income=gain)
                self.assertAlmostEqual(taxes.federal, expected, places=2)

    def test_net_investment_income_tax(self):
        # Single, MAGI $250,000 with $100,000 of investment income: 3.8% x min(100,000, 50,000).
        self.assertAlmostEqual(net_investment_income_tax(100000, 250000, S, self.config), 1900.00, places=2)

    def test_case_count_meets_the_plan_bar(self):
        self.assertGreaterEqual(len(ORDINARY_CASES) + len(PAYROLL_CASES) + len(GAINS_CASES) + 1, 12)


if __name__ == "__main__":
    unittest.main()
