# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import TYPE_CHECKING, Optional

from ..config.config_manager import config as _global_config
from .federal import FilingStatus

if TYPE_CHECKING:
    from ..config.financial_config import FinancialConfig


def _fin(config: "Optional[FinancialConfig]") -> "FinancialConfig":
    """Resolve the financial config to use (per-model if given, else global)."""
    return config if config is not None else _global_config.financial


def get_social_security_rate(config: "Optional[FinancialConfig]" = None) -> float:
    """Get the configured social security tax rate"""
    return _fin(config).tax.fica.social_security_rate


def get_social_security_max_income(config: "Optional[FinancialConfig]" = None) -> float:
    """Get the configured social security maximum income"""
    return _fin(config).tax.fica.social_security_max_income


def get_medicare_rate(config: "Optional[FinancialConfig]" = None) -> float:
    """Get the configured medicare tax rate"""
    return _fin(config).tax.fica.medicare_rate


def get_medicare_additional_rate(config: "Optional[FinancialConfig]" = None) -> float:
    """Get the configured additional medicare tax rate"""
    return _fin(config).tax.fica.medicare_additional_rate


def get_medicare_additional_rate_threshold(
    filing_status: FilingStatus, config: "Optional[FinancialConfig]" = None
) -> float:
    """Get the configured medicare additional rate threshold for filing status.

    HEAD_OF_HOUSEHOLD statutorily shares the single threshold (IRC §3101(b)(2)).
    """
    threshold = _fin(config).tax.fica.medicare_additional_rate_threshold
    if filing_status == FilingStatus.MARRIED_FILING_JOINTLY:
        return threshold.married_filing_jointly
    return threshold.single


# https://www.ssa.gov/oact/cola/cbb.html
# https://www.irs.gov/taxtopics/tc751
# https://smartasset.com/taxes/all-about-the-fica-tax
def social_security_tax(income: float, config: "Optional[FinancialConfig]" = None) -> float:
    """Calculates FICA taxes due
    This includes Social Security and Medicare taxes."""

    # TODO: This code does not account for self-employed individuals, who pay both the
    # employee and employer portions of FICA taxes. See the following for more information:
    # https://www.irs.gov/businesses/small-businesses-self-employed/self-employment-tax-social-security-and-medicare-taxes

    max_income = get_social_security_max_income(config)
    rate = get_social_security_rate(config)

    # Calculate social security tax
    if income > max_income:
        tax_amount = max_income * rate / 100
    else:
        tax_amount = income * rate / 100

    return tax_amount


def medicare_tax(income: float, filing_status: FilingStatus, config: "Optional[FinancialConfig]" = None) -> float:
    """Calculates FICA taxes due
    This includes Social Security and Medicare taxes."""

    # TODO: This code does not account for self-employed individuals, who pay both the
    # employee and employer portions of FICA taxes. See the following for more information:
    # https://www.irs.gov/businesses/small-businesses-self-employed/self-employment-tax-social-security-and-medicare-taxes

    # Calculate medicare tax
    tax_amount = income * get_medicare_rate(config) / 100
    medicare_additional_rate_max = get_medicare_additional_rate_threshold(filing_status, config)
    if income > medicare_additional_rate_max:
        tax_amount += (income - medicare_additional_rate_max) * get_medicare_additional_rate(config) / 100

    return tax_amount
