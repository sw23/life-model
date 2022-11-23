# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from enum import Enum


class FilingStatus(Enum):
    SINGLE = 1
    MARRIED_FILING_JOINTLY = 2


federal_tax_brackets = {}

# The tables below capture the federal tax brackets, for purposes of determining how
# much taxes will be paid. This currently takes the current tax brackets and applies
# them to all future years, given that it is not possible to predict taxes in the future.

federal_tax_brackets[FilingStatus.SINGLE] = [
    [0,       10275,        10],
    [10276,   41775,        12],
    [41776,   89075,        22],
    [89076,   170050,       24],
    [170051,  215950,       32],
    [215951,  539900,       35],
    [539901,  float('inf'), 37],
]

federal_tax_brackets[FilingStatus.MARRIED_FILING_JOINTLY] = [
    [0,       20550,        10],
    [20551,   83550,        12],
    [83551,   178150,       22],
    [178151,  340100,       24],
    [340101,  431900,       32],
    [431901,  647850,       35],
    [647851,  float('inf'), 37],
]


def federal_income_tax(amount, filing_status):
    """Calculates federal income tax due

    Args:
        amount (float): Taxable income.
        filing_status (FilingStatus): Filing status for tax purposes.

    Returns:
        total_tax: Amount of tax due based on the taxable income.
    """
    bracket = federal_tax_brackets[filing_status]
    total_tax = 0
    for (start, end, percent) in bracket:
        total_tax += min(max(amount - start, 0), end) * (percent / 100)
    return total_tax


def max_tax_rate(filing_status):
    return federal_tax_brackets[filing_status][-1][2]
