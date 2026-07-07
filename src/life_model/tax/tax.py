# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import TYPE_CHECKING, Optional, Sequence

from .federal import FilingStatus, federal_income_tax
from .fica import (
    get_medicare_additional_rate,
    get_medicare_additional_rate_threshold,
    get_medicare_rate,
    social_security_tax,
)
from .state import state_income_tax

if TYPE_CHECKING:
    from ..config.financial_config import FinancialConfig


class TaxesDue:
    def __init__(
        self, federal: float = 0, state: float = 0, ss: float = 0, medicare: float = 0, credits: float = 0.0
    ):
        """Taxes due for the year, split up by type of tax.

        ``credits`` holds tax credits (e.g. the Child Tax Credit) that reduce the total. A
        refundable credit may exceed the federal liability, driving ``total`` negative (a refund).
        """
        self.federal = federal
        self.state = state
        self.ss = ss
        self.medicare = medicare
        self.credits = credits

    @property
    def total(self) -> float:
        """Total taxes due for the year, net of credits (negative means a refund)."""
        return self.federal + self.state + self.ss + self.medicare - self.credits


def compute_taxes(
    ordinary_income: float,
    deductions: float,
    filing_status: FilingStatus,
    wage_incomes: "Sequence[float]",
    config: "Optional[FinancialConfig]" = None,
    credits: float = 0.0,
) -> TaxesDue:
    """Compute income and payroll taxes for a tax unit.

    Income tax is levied on the unit's combined ordinary income; FICA is levied **per person**
    on each worker's own wages. Keeping the two bases separate fixes three payroll-tax bugs:

    * FICA is no longer charged on 401k/IRA distributions (they are ordinary income, not wages).
    * The Social Security wage cap is applied per worker, not to the couple's combined wages, so
      two earners each below the cap pay Social Security on both full salaries.
    * The FICA base already includes pre-tax 401k deferrals (recorded as wages by ``Job``).

    Args:
        ordinary_income: Combined ordinary taxable income for the unit (income tax base).
        deductions: Deductions applied against ordinary income.
        filing_status: Filing status of the unit.
        wage_incomes: Each member's FICA-subject wages (payroll tax base), one entry per person.
        config: Per-model config. Defaults to the global config.
        credits: Pre-computed tax credits (e.g. Child Tax Credit) recorded on the result and
            subtracted from ``total``. Defaults to 0 (full back-compat).
    """
    adjusted_gross_income = max(ordinary_income - deductions, 0)
    tax_federal = federal_income_tax(adjusted_gross_income, filing_status, config)
    # TODO - Currently using the same deductions for state and federal taxes.
    tax_state = state_income_tax(adjusted_gross_income, config)

    # Social Security and base Medicare are per worker; the Additional Medicare surtax applies to
    # the unit's combined wages over the filing-status threshold.
    tax_ss = sum(social_security_tax(wages, config) for wages in wage_incomes)
    medicare_rate = get_medicare_rate(config)
    tax_medicare = sum(wages * medicare_rate / 100 for wages in wage_incomes)
    combined_wages = sum(wage_incomes)
    additional_threshold = get_medicare_additional_rate_threshold(filing_status, config)
    if combined_wages > additional_threshold:
        tax_medicare += (combined_wages - additional_threshold) * get_medicare_additional_rate(config) / 100

    return TaxesDue(tax_federal, tax_state, tax_ss, tax_medicare, credits=credits)


def get_income_taxes_due(
    gross_income: float,
    deductions: float,
    filing_status: FilingStatus,
    config: "Optional[FinancialConfig]" = None,
) -> TaxesDue:
    """Gets income taxes due for a single earner whose entire income is wages.

    This is a convenience wrapper around :func:`compute_taxes` that treats ``gross_income`` as
    both the ordinary income tax base and a single worker's FICA wages. Multi-person units and
    units with non-wage income should use :func:`compute_taxes` (via ``TaxUnit``) so that FICA is
    computed per person on wages only.

    Args:
        gross_income (float): Income subject to income and payroll taxes.
        deductions (float): Deductions from income.
        filing_status (FilingStatus): Filing status.
        config (FinancialConfig, optional): Per-model config. Defaults to the global config.

    Returns:
        TaxesDue: Taxes due, split by type.
    """
    return compute_taxes(gross_income, deductions, filing_status, [gross_income], config)
