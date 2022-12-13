# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from math import e as const_e
from typing import Optional, Callable, Dict, List


def compound_interest(principal: float, rate: float, num_times_applied: int = 1, elapsed_time_periods: int = 1):
    return principal * pow(1 + ((rate / 100) / num_times_applied), num_times_applied * elapsed_time_periods) - principal


def continous_interest(principal: float, rate: float, elapsed_time_periods: int = 1):
    return principal * pow(const_e, (rate / 100) * elapsed_time_periods) - principal


FMT_MONEY = '${:,.0f}'


class Stat:
    def __init__(self, name: str, title: Optional[str] = None, fmt: Optional[str] = None,
                 aggregator: Optional[Callable] = None):
        """Stat

        Args:
            name (str): Name of stat.
            title (str, optional): Title of stat.
            fmt (str, optional): Format string for printing.
            aggregator (Callable, optional): Function to aggregate stat values. Default is sum().
        """
        self.name = name
        self.title = title or name
        self.fmt = fmt
        self.aggregator = aggregator or sum


class MoneyStat(Stat):
    def __init__(self, name: str, title: Optional[str] = None):
        super().__init__(name, title, FMT_MONEY)


class BaseModel:
    COMMON_STATS = [
        MoneyStat('stat_gross_income',         'Income'),           # Gross income made in a year
        MoneyStat('stat_bank_balance',         'Bank Balance'),     # Bank account balance at the end of each year
        MoneyStat('stat_401k_balance',         '401k Balance'),     # Total 401k balance at the end of each year
        MoneyStat('stat_useable_balance',      'Useable Balance'),  # Balance available for use in a year
        MoneyStat('stat_debt',                 'Debt'),             # Total debt balance in each year
        MoneyStat('stat_taxes_paid',           'Taxes'),            # Taxes paid in a year
        MoneyStat('stat_money_spent',          'Spending'),         # Money spent in a year
        MoneyStat('stat_retirement_contrib',   '401k Contrib'),     # Money contributed to retirement in a given year
        MoneyStat('stat_retirement_match',     '401k Match'),       # Money matched by company in 401k in a given year
        MoneyStat('stat_required_min_distrib', 'RMDs'),             # Money taken out from required minimum distrib.
        MoneyStat('stat_home_expenses_paid',   'Home Expenses'),    # Money paid towards mortgage
        MoneyStat('stat_interest_paid',        'Interest Paid'),    # Money paid in interest for loans
        MoneyStat('stat_rent_paid',            'Rent Paid')         # Money paid in rent
    ]

    def __init__(self):
        self.simulation = None

    @classmethod
    def get_stat_by_name(cls, stat_name: str) -> Optional[Stat]:
        """Returns a stat by name.

        Args:
            stat_name (str): Name of stat.

        Returns:
            Optional[Stat]: Stat.
        """
        for stat in cls.COMMON_STATS:
            if stat.name == stat_name:
                return stat
        return None

    def advance_year(self, objects=None):
        if objects is None:
            objects = [self]
        for base_obj in (getattr(self, x) for x in vars(self)):
            obj_list = base_obj if isinstance(base_obj, list) else [base_obj]
            for obj in obj_list:
                if callable(getattr(obj, "advance_year", None)) and obj not in objects:
                    # Each object is only advanced once for a given year
                    objects.append(obj)
                    obj.advance_year(objects)

    def get_stats(self, stats: Optional[Dict[str, float]] = None, objects: Optional[List['BaseModel']] = None):
        if objects is None or stats is None:
            stats = {x.name: 0 for x in self.COMMON_STATS}
            objects = [self]

        for stat_name in stats:
            stat_value = getattr(self, stat_name, None)
            if stat_value is not None:
                stats[stat_name] += stat_value

        for base_obj in (getattr(self, x) for x in vars(self)):
            obj_list = base_obj if isinstance(base_obj, list) else [base_obj]
            for obj in obj_list:
                if callable(getattr(obj, "get_stats", None)) and obj not in objects:
                    # Each object is only advanced once for a given year
                    objects.append(obj)
                    obj.get_stats(stats, objects)

        return stats
