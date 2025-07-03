# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

# The Social Security Administration uses a complex formula to calculate your
# Social Security benefits. Here's a simplified version of how it works:

# Calculate Your Average Indexed Monthly Earnings (AIME): The Social Security
# Administration takes your 35 highest-earning years (adjusted for inflation),
# adds them up, and then divides by the total number of months in those years
# to get your AIME.

# Apply the Bend Point Formula: The Social Security Administration then applies
# a formula to your AIME to calculate your Primary Insurance Amount (PIA). As
# of 2021, the formula is:

# 90% of the first $996 of your AIME, plus
# 32% of your AIME over $996 and up to $6,002, plus
# 15% of your AIME over $6,002
# The dollar amounts in the formula (known as "bend points") are adjusted each
# year for inflation.

# Adjust for Early or Late Retirement: If you start taking benefits before your
# full retirement age (which depends on your birth year), your monthly benefit
# will be reduced. If you delay taking benefits past your full retirement age,
# your monthly benefit will be increased.

# Cost-of-Living Adjustments (COLAs): Once you start receiving benefits, they
# will be adjusted each year for inflation based on the Consumer Price Index for
# Urban Wage Earners and Clerical Workers (CPI-W).

# The Social Security Administration has a more detailed explanation of how
# benefits are calculated.

# https://www.ssa.gov/oact/cola/piaformula.html
# https://www.ssa.gov/oact/cola/Benefits.html
# https://www.ssa.gov/oact/cola/latestCOLA.html
# https://www.ssa.gov/OACT/COLA/awiseries.html

from typing import List, Optional, Tuple, Union
from ..people.person import Person
from ..model import LifeModelAgent
from ..tax.fica import social_security_max_income


# Average Wage Index Series
# These values are used to adjust prior year salaries to current year dollars
avg_wage_index = {
    # https://www.ssa.gov/OACT/COLA/awiseries.html
    1951: 2799.16,  # 0.00%
    1952: 2973.32,  # 6.22%
    1953: 3139.44,  # 5.59%
    1954: 3155.64,  # 0.52%
    1955: 3301.44,  # 4.62%
    1956: 3532.36,  # 6.99%
    1957: 3641.72,  # 3.10%
    1958: 3673.80,  # 0.88%
    1959: 3855.80,  # 4.95%
    1960: 4007.12,  # 3.92%
    1961: 4086.76,  # 1.99%
    1962: 4291.40,  # 5.01%
    1963: 4396.64,  # 2.45%
    1964: 4576.32,  # 4.09%
    1965: 4658.72,  # 1.80%
    1966: 4938.36,  # 6.00%
    1967: 5213.44,  # 5.57%
    1968: 5571.76,  # 6.87%
    1969: 5893.76,  # 5.78%
    1970: 6186.24,  # 4.96%
    1971: 6497.08,  # 5.02%
    1972: 7133.80,  # 9.80%
    1973: 7580.16,  # 6.26%
    1974: 8030.76,  # 5.94%
    1975: 8630.92,  # 7.47%
    1976: 9226.48,  # 6.90%
    1977: 9779.44,  # 5.99%
    1978: 10556.03,  # 7.94%
    1979: 11479.46,  # 8.75%
    1980: 12513.46,  # 9.01%
    1981: 13773.10,  # 10.07%
    1982: 14531.34,  # 5.51%
    1983: 15239.24,  # 4.87%
    1984: 16135.07,  # 5.88%
    1985: 16822.51,  # 4.26%
    1986: 17321.82,  # 2.97%
    1987: 18426.51,  # 6.38%
    1988: 19334.04,  # 4.93%
    1989: 20099.55,  # 3.96%
    1990: 21027.98,  # 4.62%
    1991: 21811.60,  # 3.73%
    1992: 22935.42,  # 5.15%
    1993: 23132.67,  # 0.86%
    1994: 23753.53,  # 2.68%
    1995: 24705.66,  # 4.01%
    1996: 25913.90,  # 4.89%
    1997: 27426.00,  # 5.84%
    1998: 28861.44,  # 5.23%
    1999: 30469.84,  # 5.57%
    2000: 32154.82,  # 5.53%
    2001: 32921.92,  # 2.39%
    2002: 33252.09,  # 1.00%
    2003: 34064.95,  # 2.44%
    2004: 35648.55,  # 4.65%
    2005: 36952.94,  # 3.66%
    2006: 38651.41,  # 4.60%
    2007: 40405.48,  # 4.54%
    2008: 41334.97,  # 2.30%
    2009: 40711.61,  # -1.51%
    2010: 41673.83,  # 2.36%
    2011: 42979.61,  # 3.13%
    2012: 44321.67,  # 3.12%
    2013: 44888.16,  # 1.28%
    2014: 46481.52,  # 3.55%
    2015: 48098.63,  # 3.48%
    2016: 48642.15,  # 1.13%
    2017: 50321.89,  # 3.45%
    2018: 52145.80,  # 3.62%
    2019: 54099.99,  # 3.75%
    2020: 55628.60,  # 2.83%
    2021: 60575.07,  # 8.89%
    # Past this point, projections are from:
    # https://www.ssa.gov/OACT/COLA/awifactors.html
    2022: 63467.98,
    2023: 66147.17,
    2024: 68627.58,
    2025: 71411.99,
    2026: 74348.48,
    2027: 77393.67,
    2028: 80510.73,
    2029: 83757.03,
    2030: 87106.49,
    2031: 90574.48,
    2032: 93995.33,
    2033: 97455.02,
    2034: 101026.57,
    2035: 104726.27,
    2036: 108561.15,
    2037: 112537.34,
    2038: 116649.42,
    2039: 120914.15,
    2040: 125312.66,
    2041: 129842.92,
    2042: 134513.63,
    2043: 139333.70,
    2044: 144301.58,
    2045: 149423.47,
    2046: 154703.93,
    2047: 160173.47,
    2048: 165831.58,
    2049: 171691.12,
    2050: 177750.26,
    2051: 184025.21,
    2052: 190524.84,
    2053: 197257.17,
    2054: 204222.55,
    2055: 211432.09,
    2056: 218892.33,
    2057: 226625.90,
    2058: 234650.32,
    2059: 242974.68,
    2060: 251610.19,
    2061: 260565.06,
    2062: 269849.97,
    2063: 279468.10,
    2064: 289433.10,
    2065: 299758.27,
    2066: 310451.64,
    2067: 321530.33,
    2068: 332997.00,
    2069: 344877.40,
    2070: 357187.25,
    2071: 369926.81,
    2072: 383104.80,
    2073: 396743.41,
    2074: 410879.42,
    2075: 425523.94,
    2076: 440700.87,
    2077: 456424.42,
}

# Last year/pct in the dictionary above
last_avg_wage_index_year = 2077
last_avg_wage_index_increase = 3.567

# Cost of Living Adjustments
# Cost of living adjustments (COLA) for each year, as a percentage
cost_of_living_adj = {
    # https://www.ssa.gov/oact/COLA/colaseries.html
    1975: 8,
    1976: 6.4,
    1977: 5.9,
    1978: 6.5,
    1979: 9.9,
    1980: 14.3,
    1981: 11.2,
    1982: 7.4,
    1983: 3.5,
    1984: 3.5,
    1985: 3.1,
    1986: 1.3,
    1987: 4.2,
    1988: 4,
    1989: 4.7,
    1990: 5.4,
    1991: 3.7,
    1992: 3,
    1993: 2.6,
    1994: 2.8,
    1995: 2.6,
    1996: 2.9,
    1997: 2.1,
    1998: 1.3,
    1999: 2.5,
    2000: 3.5,
    2001: 2.6,
    2002: 1.4,
    2003: 2.1,
    2004: 2.7,
    2005: 4.1,
    2006: 3.3,
    2007: 2.3,
    2008: 5.8,
    2009: 0,
    2010: 0,
    2011: 3.6,
    2012: 1.7,
    2013: 1.5,
    2014: 1.7,
    2015: 0,
    2016: 0.3,
    2017: 2,
    2018: 2.8,
    2019: 1.6,
    2020: 1.3,
    2021: 5.9,
    2022: 8.7,
    # Past this point, projections are from the 2023 Trustees Report
    # https://www.ssa.gov/oact/TR/TRassum.html
    2023: 3.3,
    2024: 2.4,
    2025: 2.4,
    2026: 2.4,
    2027: 2.4,
    2028: 2.4,
    2029: 2.4,
    2030: 2.4,
    2031: 2.4,
    2032: 2.4
    # Past this point, the last value in this list will be used (line above)
}

# Last year in the dictionary above
last_cost_of_living_adj_year = 2032

# Bend Points
# Used to calculate the Primary Insurance Amount (PIA)
# https://www.ssa.gov/oact/COLA/bendpoints.html
bend_points = {
    1979: (180, 1085),
    1980: (194, 1171),
    1981: (211, 1274),
    1982: (230, 1388),
    1983: (254, 1528),
    1984: (267, 1612),
    1985: (280, 1691),
    1986: (297, 1790),
    1987: (310, 1866),
    1988: (319, 1922),
    1989: (339, 2044),
    1990: (356, 2145),
    1991: (370, 2230),
    1992: (387, 2333),
    1993: (401, 2420),
    1994: (422, 2545),
    1995: (426, 2567),
    1996: (437, 2635),
    1997: (455, 2741),
    1998: (477, 2875),
    1999: (505, 3043),
    2000: (531, 3202),
    2001: (561, 3381),
    2002: (592, 3567),
    2003: (606, 3653),
    2004: (612, 3689),
    2005: (627, 3779),
    2006: (656, 3955),
    2007: (680, 4100),
    2008: (711, 4288),
    2009: (744, 4483),
    2010: (761, 4586),
    2011: (749, 4517),
    2012: (767, 4624),
    2013: (791, 4768),
    2014: (816, 4917),
    2015: (826, 4980),
    2016: (856, 5157),
    2017: (885, 5336),
    2018: (895, 5397),
    2019: (926, 5583),
    2020: (960, 5785),
    2021: (996, 6002),
    2022: (1024, 6172),
    2023: (1115, 6721),
    # TODO - Add some way of estimating bend points after 2023
}

# Last year in the dictionary above
last_bend_points_year = 2023

# Credits earned in 1978 and later are based on earnings, not quarters.
# https://www.ssa.gov/oact/cola/QC.html
# https://www.ssa.gov/oact/cola/QC.html#qcseries
min_eligible_credits = 40
max_credits_per_year = 4

# Maximum number of years of earnings used to compute the PIA
max_years_of_income = 35

# https://www.ssa.gov/oact/ProgData/nra.html
# Note: Using a single value for minimum retirement age as a simplification.
min_ss_early_retirement_age = 62

# https://www.ssa.gov/oact/ProgData/ar_drc.html
# See table above for delayed retirement credit percentages
# No delayed retirement credit is given after age 69.
# Note: Using a single value for normal retirement age as a simplification.
normal_retirement_age = 67

# Note: Using a single value for delayed retirement credit as a simplification.
delayed_retirement_credit = 8.0  # Percent
max_delayed_retirement_credit_age = 70


def get_avg_wage_index(year: int) -> float:
    """ Compute the average wage index for a given year

    Args:
        year: The year to compute the average wage index for

    Returns:
        The average wage index for the given year

    Raises:
        ValueError: If the year is before 1951
    """
    if year < 1951:
        raise ValueError("Average wage index is not available before 1951")
    elif year <= last_avg_wage_index_year:
        # Years in this range are in the table above
        return avg_wage_index[year]
    else:
        # Years after this range are projected
        last_avg_wage_index = avg_wage_index[last_avg_wage_index_year]
        for _ in range(last_avg_wage_index_year, year):
            last_avg_wage_index *= (1 + last_avg_wage_index_increase / 100.0)
        return last_avg_wage_index


def get_cost_of_living_adj(year: int) -> float:
    """ Get the cost of living adjustment for a given year

    Args:
        year: The year to get the cost of living adjustment for

    Returns:
        The cost of living adjustment for the given year

    Raises:
        ValueError: If the year is before 1975
    """
    if year < 1975:
        raise ValueError("Cost of living adjustment is not available before 1975")
    elif year <= last_cost_of_living_adj_year:
        # Years in this range are in the table above
        return cost_of_living_adj[year]
    else:
        # Years after this range are projected
        last_cost_of_living_adj = cost_of_living_adj[last_cost_of_living_adj_year]
        cost_of_living_adj_result = 1
        for _ in range(last_avg_wage_index_year, year):
            cost_of_living_adj_result *= (1 + last_cost_of_living_adj / 100.0)
        return cost_of_living_adj_result


def get_bend_points(year: int) -> Tuple[float, float]:
    """ Get the bend points for a given year

    Args:
        year: The year to get the bend points for

    Returns:
        A tuple containing the bend points for the given year

    Raises:
        ValueError: If the year is before 1979
    """
    if year < 1979:
        raise ValueError("Bend points are not available before 1979")
    elif year <= last_bend_points_year:
        # Years in this range are in the table above
        return bend_points[year]
    else:
        # Years after this range are projected
        # TODO - Add some way of estimating bend points after 2023
        return bend_points[last_bend_points_year]


def get_qc_earnings_for_year(year: int) -> int:
    """ Compute the number of credits earned for a given year

    Args:
        year: The year to compute the number of credits earned for

    Returns:
        The number of credits earned for the given year

    Raises:
        ValueError: If the year is before 1978
    """
    credit_amt_1978 = 250.0
    avg_wage_idx_1976 = get_avg_wage_index(1976)

    # TODO - Handle years before 1978
    if year < 1978:
        raise ValueError("QC earnings are not available before 1978")

    # Calculate previous year's QC amount (rounded to nearest 10 dollars)
    prev_year_amount = credit_amt_1978 * get_avg_wage_index(year-3) / avg_wage_idx_1976
    prev_year_amount = int(round(prev_year_amount / 10.0) * 10.0)

    # Calculate current year's QC amount (rounded to nearest 10 dollars)
    curr_year_amount = credit_amt_1978 * get_avg_wage_index(year-2) / avg_wage_idx_1976
    curr_year_amount = int(round(curr_year_amount / 10.0) * 10.0)

    # Pick the larger of the two
    return max(prev_year_amount, curr_year_amount)


def get_credits_for_year(year: int, earnings: float) -> int:
    """ Compute the number of credits earned for a given year """
    qc_earnings = get_qc_earnings_for_year(year)
    return min(max_credits_per_year, int(earnings / qc_earnings))


class Income:
    def __init__(self, year: int, amount: float):
        """ Create an income record for a given year

        Args:
            year: The year of the income record
            amount: The amount of income for the given year
        """
        self.year = year
        self.amount = amount

    def _repr_html_(self):
        return f'<p>{self.year}: ${self.amount}</p>'

    def get_credits(self) -> int:
        """ Compute the number of credits earned for a given year """
        return get_credits_for_year(self.year, self.amount)

    def get_indexed_amount(self, person_age_60_year: int) -> float:
        """ Compute the indexed amount for a given year

        Args:
            person_age_60_year: The year in which the person attains age 60

        Returns:
            The indexed amount for the given year
        """
        if self.year >= person_age_60_year:
            return self.amount
        else:
            return self.amount * get_avg_wage_index(person_age_60_year) / get_avg_wage_index(self.year)


class SocialSecurity(LifeModelAgent):
    def __init__(self, person: Person, withdrawal_start_age: Optional[float] = None,
                 income_history: Optional[Union[List[Income], List[Tuple[int, float]]]] = None):
        """ Models Social Security benefits for a person

        Args:
            person: The person for whom to model Social Security benefits
            withdrawal_start_age: The age at which the person starts withdrawing Social Security benefits
            income_history: The person's income history

        Raises:
            ValueError: If the withdrawal start age is before the earliest age for early withdrawal
        """
        super().__init__(person.model)
        self.person = person
        self.withdrawal_start_age = withdrawal_start_age or person.retirement_age

        self.income_history = []
        if income_history is not None and len(income_history):
            for income in income_history:
                if isinstance(income, Income):
                    self.income_history.append(income)
                else:
                    self.income_history.append(Income(income[0], income[1]))

        if self.withdrawal_start_age < min_ss_early_retirement_age:
            raise ValueError("Withdrawal start age cannot be before early retirement age")

        # Register social security
        self.person.social_security = self

    def _repr_html_(self):
        desc = '<ul>'
        desc += f'<li>Withdrawal Start Age: {self.withdrawal_start_age}</li>'
        desc += f'<li>Years of Work: {len(self.income_history)}</li>'
        desc += '</ul>'
        return desc

    def add_income_for_year(self, amount: float, year: Optional[int] = None):
        """ Add income to the person's income history

        Args:
            amount: The amount of income to add
            year: The year to add the income for. If not specified, the current year is used
        """
        year = year or self.model.year
        matching_years = [x for x in self.income_history if x.year == year]
        if matching_years:
            income_obj = matching_years[0]
            income_obj.amount += amount
        else:
            income_obj = Income(year, amount)
            self.income_history.append(income_obj)

        # Cap income at the maximum amount
        if income_obj.amount > social_security_max_income:
            income_obj.amount = social_security_max_income

    @property
    def withdrawal_start_year(self) -> int:
        """ Returns the year in which the person starts withdrawing Social Security benefits """
        return self.person.get_year_at_age(int(self.withdrawal_start_age))

    def get_indexed_income_history(self) -> List[float]:
        """ Computes indexed earnings for a person """
        return [x.get_indexed_amount(self.person.get_year_at_age(60)) for x in self.income_history]

    def get_aime(self) -> float:
        """ Computes Average Indexed Monthly Earnings (AIME) for a person """

        # Make sure the person has enough credits to be eligible
        credits_earned = sum(x.get_credits() for x in self.income_history)
        if credits_earned < min_eligible_credits:
            return 0

        # Pick the highest 35 values from the list
        indexed_earnings = self.get_indexed_income_history()
        highest_earnings = sorted(indexed_earnings, reverse=True)[:max_years_of_income]

        return round(sum(highest_earnings) / (max_years_of_income * 12))

    def get_early_delayed_pia(self, pia: float) -> float:
        """ Computes the early or delayed PIA for a person

        Args:
            pia: The person's primary insurance amount

        Returns:
            PIA adjusted for early or delayed retirement
        """
        # Apply early/delayed retirement credits
        # https://www.ssa.gov/oact/quickcalc/early_late.html
        if self.withdrawal_start_age < normal_retirement_age:
            # Reduce for early withdrawal
            months_early = (normal_retirement_age - self.withdrawal_start_age) * 12
            reduction_pct = min(months_early, 36) * 0.01 * (5/9)
            reduction_pct += max(0, months_early - 36) * 0.01 * (5/12)
            pia *= (1 - reduction_pct)
        elif self.withdrawal_start_age > normal_retirement_age:
            # Increase for delayed withdrawal
            max_months_delayed = (max_delayed_retirement_credit_age - normal_retirement_age) * 12
            months_delayed = (self.withdrawal_start_age - normal_retirement_age) * 12
            months_delayed = min(months_delayed, max_months_delayed)
            increase_pct = months_delayed * (delayed_retirement_credit / (100 * 12))
            pia *= (1 + increase_pct)
        return pia

    def get_pia(self, current_year: Optional[int] = None) -> float:
        """ Computes Primary Insurance Amount (PIA) for a person
            Note: PIA is a monthly amount, so should be multiplied by 12 to get annual amount

        Args:
            current_year: The current year

        Returns:
            The person's PIA
        """
        current_year = current_year or self.model.year

        # Get AIME
        aime = self.get_aime()
        pia = 0.0

        # Apply bend points
        year_of_age_62 = self.person.get_year_at_age(62)
        bend_points = get_bend_points(year_of_age_62)
        pia += min(aime, bend_points[0]) * 0.9
        pia += min(max(0, aime - bend_points[0]), bend_points[1] - bend_points[0]) * 0.32
        pia += max(0, aime - bend_points[1]) * 0.15

        # Round to the nearest lowest dime
        pia = int(pia * 10) / 10.0

        # Apply cost of living adjustment
        for cola_year in range(year_of_age_62, current_year):
            # This rounding seems to match the SSA's rounding (truncating to nearest lower dime)
            pia = int(pia * (1 + get_cost_of_living_adj(cola_year) / 100.0) * 10) / 10.0

        # Apply early/delayed retirement credits
        pia = self.get_early_delayed_pia(pia)

        # Round to the nearest cent
        return round(pia, 2)

    def pre_step(self):

        # Add social security income to the person's income
        # TODO - The model does not tax this income, which isn't correct in some cases
        if self.model.year >= self.withdrawal_start_year:
            yearly_pia = self.get_pia() * 12
            self.person.deposit_into_bank_account(yearly_pia)
            self.person.stat_ss_income = yearly_pia

    @property
    def html_report(self) -> str:
        """ Returns a detailed report of the person's social security benefits """
        desc = '<ul>'
        desc += f'<li>Withdrawal Start Age: {self.withdrawal_start_age}</li>'
        desc += f'<li>Years of Work: {len(self.income_history)}</li>'
        desc += '<li><ul>'
        desc += ''.join(f'<li>{x._repr_html_()}</li>' for x in self.income_history)
        desc += '</ul></li>'
        desc += f'<li>AIME: {self.get_aime()}</li>'
        desc += f'<li>PIA: {self.get_pia()}</li>'
        desc += '</ul>'
        return desc
