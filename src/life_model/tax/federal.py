# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from enum import Enum
from ..config.config_manager import config


class FilingStatus(Enum):
    SINGLE = 1
    MARRIED_FILING_JOINTLY = 2


def get_federal_standard_deduction(filing_status: FilingStatus) -> float:
    """Get federal standard deduction for filing status"""
    return config.financial.get_federal_standard_deduction(filing_status)


def get_federal_tax_brackets(filing_status: FilingStatus) -> list:
    """Get federal tax brackets for filing status"""
    return config.financial.get_federal_tax_brackets(filing_status)


# Legacy compatibility - maintain old variable names for backward compatibility
def _get_federal_standard_deduction_dict():
    """Legacy compatibility function"""
    return {
        FilingStatus.SINGLE: get_federal_standard_deduction(FilingStatus.SINGLE),
        FilingStatus.MARRIED_FILING_JOINTLY: get_federal_standard_deduction(FilingStatus.MARRIED_FILING_JOINTLY)
    }


def _get_federal_tax_brackets_dict():
    """Legacy compatibility function"""
    return {
        FilingStatus.SINGLE: get_federal_tax_brackets(FilingStatus.SINGLE),
        FilingStatus.MARRIED_FILING_JOINTLY: get_federal_tax_brackets(FilingStatus.MARRIED_FILING_JOINTLY)
    }


# For backward compatibility, expose these as module attributes
federal_standard_deduction = _get_federal_standard_deduction_dict()
federal_tax_brackets = _get_federal_tax_brackets_dict()


def federal_income_tax(income: float, filing_status: FilingStatus) -> float:
    """Calculates federal income tax due

    Args:
        income (float): Taxable income.
        filing_status (FilingStatus): Filing status for tax purposes.

    Returns:
        total_tax: Amount of tax due based on the taxable income.
    """
    bracket = get_federal_tax_brackets(filing_status)
    total_tax = 0
    for (start, end, percent) in bracket:
        amount_in_bracket = min(max(income - start, 0), end - start)
        if amount_in_bracket == 0:
            break
        total_tax += amount_in_bracket * (percent / 100)
    return round(total_tax)


def max_tax_rate(filing_status: FilingStatus) -> float:
    """Get maximum tax rate for filing status"""
    return config.financial.get_max_tax_rate(filing_status)
