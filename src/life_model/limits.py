# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import TYPE_CHECKING, Optional

from .config.config_manager import config as _global_config

if TYPE_CHECKING:
    from .config.financial_config import FinancialConfig


def _fin(config: "Optional[FinancialConfig]") -> "FinancialConfig":
    """Resolve the financial config to use (per-model if given, else global)."""
    return config if config is not None else _global_config.financial


def job_401k_contrib_limit(age, config: "Optional[FinancialConfig]" = None) -> int:
    """Get 401k contribution limit based on age"""
    return _fin(config).get_job_401k_contrib_limit(age)


def federal_retirement_age(config: "Optional[FinancialConfig]" = None) -> float:
    """Get federal retirement age"""
    return _fin(config).retirement.federal_retirement_age


def get_rmd_distribution_periods(config: "Optional[FinancialConfig]" = None) -> list:
    """Get RMD distribution periods from configuration.

    The Uniform Lifetime Table (IRS Pub. 590-B Appendix B) lives in the config
    (``retirement.rmd_distribution_periods``); this returns the applicable table.
    """
    return _fin(config).retirement.rmd_distribution_periods


def required_min_distrib(age, balance, config: "Optional[FinancialConfig]" = None) -> float:
    """Calculate required minimum distribution"""
    periods = get_rmd_distribution_periods(config)
    if age < periods[0][0]:
        return 0
    elif age > periods[-1][0]:
        return balance / periods[-1][1]
    else:
        return balance / [x[1] for x in periods if x[0] == age][0]
