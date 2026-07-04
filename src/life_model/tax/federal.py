# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from enum import Enum
from typing import TYPE_CHECKING, Optional

from ..config.config_manager import config as _global_config

if TYPE_CHECKING:
    from ..config.financial_config import FinancialConfig


class FilingStatus(Enum):
    SINGLE = 1
    MARRIED_FILING_JOINTLY = 2


def _fin(config: "Optional[FinancialConfig]") -> "FinancialConfig":
    """Resolve the financial config to use (per-model if given, else global)."""
    return config if config is not None else _global_config.financial


def get_federal_standard_deduction(filing_status: FilingStatus, config: "Optional[FinancialConfig]" = None) -> float:
    """Get federal standard deduction for filing status"""
    return _fin(config).get_federal_standard_deduction(filing_status)


def get_federal_tax_brackets(filing_status: FilingStatus, config: "Optional[FinancialConfig]" = None) -> list:
    """Get federal tax brackets for filing status"""
    return _fin(config).get_federal_tax_brackets(filing_status)


def federal_income_tax(income: float, filing_status: FilingStatus, config: "Optional[FinancialConfig]" = None) -> float:
    """Calculates federal income tax due.

    Brackets are treated as half-open marginal segments ``[prev_upper, upper)`` where ``upper``
    is each row's second column (the last row uses ``inf``). Using the upper bound as the segment
    boundary — rather than the row's own ``start`` (which is ``prev_upper + 1``) — closes the $1
    gaps the old ``[start, end]`` rows left between brackets. The result is not rounded (Plan 04
    D3); callers round the final total tax bill once.

    Args:
        income (float): Taxable income.
        filing_status (FilingStatus): Filing status for tax purposes.
        config (FinancialConfig, optional): Per-model config. Defaults to the global config.

    Returns:
        total_tax: Amount of tax due based on the taxable income.
    """
    brackets = get_federal_tax_brackets(filing_status, config)
    total_tax = 0.0
    prev_upper = 0.0
    for _start, upper, percent in brackets:
        if income <= prev_upper:
            break
        amount_in_bracket = min(income, upper) - prev_upper
        total_tax += amount_in_bracket * (percent / 100)
        prev_upper = upper
    return total_tax


def max_tax_rate(filing_status: FilingStatus, config: "Optional[FinancialConfig]" = None) -> float:
    """Get maximum tax rate for filing status"""
    return _fin(config).get_max_tax_rate(filing_status)
