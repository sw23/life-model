# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from enum import Enum
from typing import TYPE_CHECKING, Optional

from ..config.config_manager import config as _global_config
from .brackets import apply_brackets

if TYPE_CHECKING:
    from ..config.financial_config import FinancialConfig


class FilingStatus(Enum):
    SINGLE = 1
    MARRIED_FILING_JOINTLY = 2
    # Derived by TaxUnit.build_units for an unmarried member with a dependent child. Falls back
    # to SINGLE deduction/brackets when the config carries no head_of_household data.
    HEAD_OF_HOUSEHOLD = 3


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
    gaps the old ``[start, end]`` rows left between brackets. The result is not rounded; callers
    round the final total tax bill once.

    Args:
        income (float): Taxable income.
        filing_status (FilingStatus): Filing status for tax purposes.
        config (FinancialConfig, optional): Per-model config. Defaults to the global config.

    Returns:
        total_tax: Amount of tax due based on the taxable income.
    """
    brackets = get_federal_tax_brackets(filing_status, config)
    return apply_brackets(income, brackets)


def get_capital_gains_brackets(filing_status: FilingStatus, config: "Optional[FinancialConfig]" = None) -> list:
    """Get the preferential long-term capital gains / qualified dividend brackets."""
    return _fin(config).get_capital_gains_brackets(filing_status)


def capital_gains_tax(
    ordinary_income: float,
    preferential_income: float,
    filing_status: FilingStatus,
    config: "Optional[FinancialConfig]" = None,
) -> float:
    """Tax on preferential income, stacked on top of ordinary income.

    Reproduces the Qualified Dividends and Capital Gain Tax Worksheet as a difference of two
    bracket applications: ordinary income fills the 0%/15% bands first, and the gain is taxed only
    in whatever band space remains above it. Computing it this way means the shared bracket engine
    needs no special case.

    Both arguments are post-deduction figures. Preferential income is clamped at zero — a net
    capital loss is handled by the ordinary offset and carryforward at settlement, and letting a
    negative through here would corrupt the subtraction.

    Args:
        ordinary_income: Taxable income taxed at ordinary rates.
        preferential_income: Taxable long-term gains and qualified dividends.
        filing_status: Filing status of the unit.
        config: Per-model config. Defaults to the global config.
    """
    gains = max(0.0, preferential_income)
    if gains <= 0:
        return 0.0
    ordinary = max(0.0, ordinary_income)
    brackets = get_capital_gains_brackets(filing_status, config)
    return apply_brackets(ordinary + gains, brackets) - apply_brackets(ordinary, brackets)


def net_investment_income_tax(
    net_investment_income: float,
    magi: float,
    filing_status: FilingStatus,
    config: "Optional[FinancialConfig]" = None,
) -> float:
    """Net investment income surtax (IRC §1411).

    Levied at a flat rate on the lesser of net investment income and the amount by which modified
    AGI exceeds the filing-status threshold. The thresholds have never been inflation-indexed, so
    they are held fixed even when the rest of the tax parameters are projected forward — the real
    fiscal drag that creates is a genuine feature of the statute, not a modeling shortcut.

    Args:
        net_investment_income: Interest, dividends, and capital gains for the year.
        magi: Modified adjusted gross income (a pre-deduction figure).
        filing_status: Filing status of the unit.
        config: Per-model config. Defaults to the global config.
    """
    if net_investment_income <= 0:
        return 0.0
    niit = _fin(config).tax.federal.niit
    threshold = niit.threshold_for(filing_status)
    excess = max(0.0, magi - threshold)
    return min(net_investment_income, excess) * (niit.rate / 100)


def max_tax_rate(filing_status: FilingStatus, config: "Optional[FinancialConfig]" = None) -> float:
    """Get maximum tax rate for filing status"""
    return _fin(config).get_max_tax_rate(filing_status)
