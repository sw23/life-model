# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

# TODO: This code does not account for differences in state income tax
# TODO: This can be expanded later for greater accuracy

state_tax_rate = 6


def state_income_tax(income: float) -> float:
    """ Calculates state income taxes due

    Args:
        income (float): Income subject to state income taxes.

    Returns:
        total_tax: Amount of tax due based on the taxable income.
    """

    return income * state_tax_rate / 100
