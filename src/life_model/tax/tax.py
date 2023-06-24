# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from .federal import FilingStatus, federal_income_tax
from .state import state_income_tax
from .fica import social_security_tax, medicare_tax


class TaxesDue:
    def __init__(self, federal: float = 0, state: float = 0, ss: float = 0, medicare: float = 0):
        """Taxes due for the year, split up by type of tax."""
        self.federal = federal
        self.state = state
        self.ss = ss
        self.medicare = medicare

    @property
    def total(self) -> float:
        """Total taxes due for the year."""
        return self.federal + self.state + self.ss + self.medicare


def get_income_taxes_due(gross_income: float, deductions: float, filing_status: FilingStatus) -> TaxesDue:
    """Gets income taxes due for the year for a person or family.

    Args:
        gross_income (float): Income subject to income taxes.
        deductions (float): Deductions from income.
        filing_status (FilingStatus): Filing status.

    Returns:
        float: Income taxes due.
    """

    adjusted_gross_income = max(gross_income - deductions, 0)
    tax_federal = federal_income_tax(adjusted_gross_income, filing_status)

    # TODO - Currently using the same deductions for state and federal taxes.
    tax_state = state_income_tax(adjusted_gross_income)

    # FICA taxes are based on gross income, not adjusted gross income.
    tax_ss = social_security_tax(gross_income)
    tax_medicare = medicare_tax(gross_income, filing_status)

    return TaxesDue(tax_federal, tax_state, tax_ss, tax_medicare)
