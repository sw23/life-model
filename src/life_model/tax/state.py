# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

# TODO: This code does not account for differences in state income tax
# TODO: This can be expanded later for greater accuracy

from typing import TYPE_CHECKING, Optional

from ..config.config_manager import config as _global_config

if TYPE_CHECKING:
    from ..config.financial_config import FinancialConfig


def get_state_tax_rate(config: "Optional[FinancialConfig]" = None) -> float:
    """Get the configured state tax rate"""
    fin = config if config is not None else _global_config.financial
    return fin.tax.state.tax_rate


def state_income_tax(income: float, config: "Optional[FinancialConfig]" = None) -> float:
    """Calculates state income taxes due

    Args:
        income (float): Income subject to state income taxes.
        config (FinancialConfig, optional): Per-model config. Defaults to the global config.

    Returns:
        total_tax: Amount of tax due based on the taxable income.
    """
    return income * get_state_tax_rate(config) / 100
