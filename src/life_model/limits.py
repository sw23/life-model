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


def job_401k_contrib_limit(age: int, config: "Optional[FinancialConfig]" = None) -> int:
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


def required_min_distrib(
    age: int,
    balance: float,
    config: "Optional[FinancialConfig]" = None,
    start_age: "Optional[int]" = None,
) -> float:
    """Calculate the required minimum distribution (RMD) for the year.

    Args:
        age: The account owner's age this year.
        balance: The pre-tax retirement balance subject to RMDs.
        config: Per-model config. Defaults to the global config.
        start_age: The age at which RMDs begin. When ``None``, RMDs begin at the first age in the
            distribution-period table. Callers should pass the SECURE 2.0 start
            age via :func:`rmd_start_age`.

    Returns:
        The RMD amount, or 0 before the start age.
    """
    periods = get_rmd_distribution_periods(config)
    # Map integer ages to their distribution period (the table is contiguous by year).
    period_by_age = {int(row[0]): row[1] for row in periods}
    table_start = min(period_by_age)
    table_end = max(period_by_age)

    if start_age is None:
        start_age = table_start
    if age < start_age:
        return 0

    # Clamp the (possibly fractional) age into the table's range to avoid IndexErrors.
    lookup_age = int(age)
    if lookup_age < table_start:
        lookup_age = table_start
    elif lookup_age > table_end:
        lookup_age = table_end
    return balance / period_by_age[lookup_age]


def rmd_start_age(birth_year: int, config: "Optional[FinancialConfig]" = None, year: "Optional[int]" = None) -> int:
    """Age at which required minimum distributions begin (SECURE 2.0).

    The base start age is the year-indexed ``rmd_start_age`` parameter (73 under SECURE 2.0);
    people born in 1960 or later start at 75.

    Args:
        birth_year: The account owner's birth year.
        config: Per-model config. Defaults to the global config.
        year: The simulated year, used to look up the year-indexed base start age.
    """
    if birth_year >= 1960:
        return 75
    fin = _fin(config)
    if year is not None:
        return fin.tax_year(year).rmd_start_age
    return 73
