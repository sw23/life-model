# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import TYPE_CHECKING, Optional

from .federal import FilingStatus, federal_income_tax
from .fica import medicare_tax, social_security_tax
from .state import state_income_tax

if TYPE_CHECKING:
    from ..config.financial_config import FinancialConfig


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


def get_income_taxes_due(
    gross_income: float,
    deductions: float,
    filing_status: FilingStatus,
    config: "Optional[FinancialConfig]" = None,
) -> TaxesDue:
    """Gets income taxes due for the year for a person or family.

    Args:
        gross_income (float): Income subject to income taxes.
        deductions (float): Deductions from income.
        filing_status (FilingStatus): Filing status.
        config (FinancialConfig, optional): Per-model config. Defaults to the global config.

    Returns:
        float: Income taxes due.
    """

    adjusted_gross_income = max(gross_income - deductions, 0)
    tax_federal = federal_income_tax(adjusted_gross_income, filing_status, config)

    # TODO - Currently using the same deductions for state and federal taxes.
    tax_state = state_income_tax(adjusted_gross_income, config)

    # FICA taxes are based on gross income, not adjusted gross income.
    tax_ss = social_security_tax(gross_income, config)
    tax_medicare = medicare_tax(gross_income, filing_status, config)

    return TaxesDue(tax_federal, tax_state, tax_ss, tax_medicare)
