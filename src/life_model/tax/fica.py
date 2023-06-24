# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from .federal import FilingStatus

# The variables below capture the social security tax rate and the maximum income
# that is subject to social security taxes.
social_security_rate = 6.2
social_security_max_income = 160200

# The variables below capture the medicare tax rate and the additional medicare tax
# rate that is applied to income above a certain threshold.
medicare_rate = 1.45
medicare_additional_rate = 0.9

medicare_additional_rate_threshold = {}
medicare_additional_rate_threshold[FilingStatus.SINGLE] = 200000
medicare_additional_rate_threshold[FilingStatus.MARRIED_FILING_JOINTLY] = 250000


# https://www.ssa.gov/oact/cola/cbb.html
# https://www.irs.gov/taxtopics/tc751
# https://smartasset.com/taxes/all-about-the-fica-tax
def social_security_tax(income: float) -> float:
    """ Calculates FICA taxes due
        This includes Social Security and Medicare taxes. """

    # TODO: This code does not account for self-employed individuals, who pay both the
    # employee and employer portions of FICA taxes. See the following for more information:
    # https://www.irs.gov/businesses/small-businesses-self-employed/self-employment-tax-social-security-and-medicare-taxes

    # Calculate social security tax
    if income > social_security_max_income:
        tax_amount = social_security_max_income * social_security_rate / 100
    else:
        tax_amount = income * social_security_rate / 100

    return tax_amount


def medicare_tax(income: float, filing_status: FilingStatus) -> float:
    """ Calculates FICA taxes due
        This includes Social Security and Medicare taxes. """

    # TODO: This code does not account for self-employed individuals, who pay both the
    # employee and employer portions of FICA taxes. See the following for more information:
    # https://www.irs.gov/businesses/small-businesses-self-employed/self-employment-tax-social-security-and-medicare-taxes

    # Calculate medicare tax
    tax_amount = income * medicare_rate / 100
    medicare_additional_rate_max = medicare_additional_rate_threshold[filing_status]
    if income > medicare_additional_rate_max:
        tax_amount += (income - medicare_additional_rate_max) * medicare_additional_rate / 100

    return tax_amount
