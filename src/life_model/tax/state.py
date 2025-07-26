# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

# TODO: This code does not account for differences in state income tax
# TODO: This can be expanded later for greater accuracy

from ..config.config_manager import config


def get_state_tax_rate() -> float:
    """Get the configured state tax rate"""
    return config.financial.get('tax.state.tax_rate', 6.0)


def state_income_tax(income: float) -> float:
    """ Calculates state income taxes due

    Args:
        income (float): Income subject to state income taxes.

    Returns:
        total_tax: Amount of tax due based on the taxable income.
    """
    return income * get_state_tax_rate() / 100


# Legacy compatibility
state_tax_rate = get_state_tax_rate()
