# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import mesa
import pandas as pd


from datetime import date
from typing import Optional, List, Callable, Dict
from pandas.io.formats.style import Styler
from math import e as const_e


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

    def model_reporter(self, model: 'LifeModel'):
        """ Return the value of the stat for the model. """
        return self.aggregator(getattr(agent, self.name) for agent in model.schedule.agents)


class MoneyStat(Stat):
    def __init__(self, name: str, title: Optional[str] = None):
        super().__init__(name, title, FMT_MONEY)


class Event:
    def __init__(self, message: str):
        """Event

        Args:
            message (str): Event description.
        """
        self.message = message
        self.year = 0

    def _repr_html_(self):
        return f"<tr><td>{self.year}</td><td>{self.message}</td></tr>\n"


class EventLog:
    def __init__(self, model: 'LifeModel'):
        """Event Log

        Args:
            model (LifeModel): LifeModel.
        """
        self.model = model
        self.list = []

    def _repr_html_(self):
        table = "<table>"
        table += "<tr><th>Year:</th><th>Event:</th></tr>\n"
        table += "".join(x._repr_html_() for x in self.list)
        table += "</table>"
        return table

    def add(self, event: Event):
        event.year = self.model.year
        self.list.append(event)


class LifeModel(mesa.Model):

    STATS = [
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

    def __init__(self, end_year: Optional[int] = None, start_year: Optional[int] = None):
        """LifeModel Helper Class

        Args:
            end_year (int, optional): End date of the model. Defaults to None.
            start_year (int, optional): Start date of the model. Defaults to None.
        """
        if start_year is None:
            start_year = date.today().year
        if end_year is None:
            end_year = start_year + 50
        self.start_year = start_year
        self.end_year = end_year
        self.year = start_year
        self.event_log = EventLog(self)
        self.simulated_years = []
        self.schedule = mesa.time.StagedActivation(self, stage_list=["pre_step", "step", "post_step"])
        self.datacollector = mesa.DataCollector(
            model_reporters={
                **{"Year": "year"},
                **{x.title: lambda model, x=x: x.model_reporter(model) for x in self.STATS}
            },
            agent_reporters={x.title: x.name for x in self.STATS}
        )

    @classmethod
    def get_stat_by_name(cls, stat_name: str) -> Optional[Stat]:
        """Returns a stat by name.

        Args:
            stat_name (str): Name of stat.

        Returns:
            Optional[Stat]: Stat.
        """
        for stat in cls.STATS:
            if stat.name == stat_name:
                return stat
        return None

    @classmethod
    def get_stat_by_title(cls, stat_title: str) -> Optional[Stat]:
        """Returns a stat by title.

        Args:
            stat_title (str): Title of stat.

        Returns:
            Optional[Stat]: Stat.
        """
        for stat in cls.STATS:
            if stat.title == stat_title:
                return stat
        return None

    def step(self):
        self.simulated_years.append(self.year)
        self.datacollector.collect(self)
        self.schedule.step()
        self.year += 1

    def get_year_range(self) -> range:
        """ Get the range of years in the model """
        return range(self.start_year, self.end_year + 1)

    def run(self):
        """ Run the simulation """
        for _ in self.get_year_range():
            self.step()

    def add_agent_stat(self, title: str, attr_name: str):
        """Add an agent stat to the model

        Args:
            title (str): Title of the stat
            attr_name (str): Name of the attribute
        """
        self.datacollector._new_agent_reporter(title, attr_name)

        # Set stat value to 0 for agents that don't have that attribute
        for agent in self.schedule.agents:
            if not hasattr(agent, attr_name):
                setattr(agent, attr_name, 0)

    def get_yearly_stat_df(self, columns: Optional[List[str]] = None, extra_columns: Optional[List[str]] = None,
                           aggregate: Optional[Dict[str, Callable]] = None,
                           column_formats: Optional[Dict[str, str]] = None) -> Styler:
        """Get a DataFrame of the yearly stats

        Args:
            columns (List[str], optional): Optional list of columns to include. Defaults to None.
            extra_columns (List[str], optional): Optional list of extra columns to include. Defaults to None.
            aggregate (Dict[str, Callable], optional): Dictionary of aggregators to use. Defaults to None.
            column_formats (Dict[str, str], optional): Dictionary of column formats to use. Defaults to None.

        Returns:
            pd.DataFrame: DataFrame of the yearly stats
        """
        # Get the list of columns to use
        if columns is None:
            columns = ['Year'] + [x.name for x in self.STATS]
        if extra_columns is not None:
            for i, column in enumerate(extra_columns):
                columns.insert(i+1, column)
        # Get the list of stats to use
        stats = []
        for column_name in columns:
            stat = self.get_stat_by_name(column_name)
            if stat is not None:
                stats.append(stat)
        # Create a dataframe from the data
        df = self.datacollector.get_model_vars_dataframe()
        # Only keep certain columns in the data frame
        df = df[columns]
        if aggregate is not None:
            # Aggregate the data if desired
            aggregators = {**{'Year': max}, **aggregate, **{x.title: x.aggregator for x in stats}}
            df = df.aggregate(aggregators).reset_index().transpose()
            df.columns = df.iloc[0]
            df = df.drop(df.index[0])
        formats = {x.title: x.fmt for x in stats if x.fmt is not None}
        if column_formats is not None:
            formats.update(column_formats)
        return df.style.format(precision=0, na_rep='MISSING', formatter=formats).hide()

    def format_dataframe(self, df: pd.DataFrame, extra_formats: Optional[Dict[str, str]] = None) -> Styler:
        """Format a dataframe

        Args:
            df (pd.DataFrame): DataFrame to format
            extra_formats (Dict[str, str], optional): Dictionary of formats to use. Defaults to None.

        Returns:
            Styler: Formatted DataFrame
        """
        stats = [self.get_stat_by_title(str(x)) for x in df.columns]
        stats = [x for x in stats if x is not None]
        formats = {x.title: x.fmt for x in stats if x.fmt is not None}
        formats = {**formats, **extra_formats} if extra_formats is not None else formats
        return df.style.format(precision=0, na_rep='MISSING', formatter=formats).hide()

    def aggregate_dataframe(self, df: pd.DataFrame, aggregate: Optional[Dict[str, Callable]] = None) -> pd.DataFrame:
        """Aggregate a dataframe

        Args:
            df (pd.DataFrame): DataFrame to aggregate
            aggregate (Dict[str, Callable], optional): Dictionary of aggregators to use. Defaults to None.

        Returns:
            pd.DataFrame: Aggregated DataFrame
        """
        # Aggregate the data
        stats = [self.get_stat_by_title(str(x)) for x in df.columns]
        stats = [x for x in stats if x is not None]
        aggregators = {**{'Year': max}, **{x.title: x.aggregator for x in stats}}
        df = df.aggregate(aggregators).reset_index().transpose()
        df.columns = df.iloc[0]
        return df.drop(df.index[0])


class LifeModelAgent(mesa.Agent):
    def __init__(self, model: LifeModel):
        """LifeModelAgent

        Args:
            model (LifeModel): LifeModel.
        """
        super().__init__(id(self), model)

        # Register the agent with the model
        self.model = model
        self.model.schedule.add(self)

        # Initialize the stats
        for stat in LifeModel.STATS:
            setattr(self, stat.name, 0)

    def pre_step(self):
        """ Pre-step phase. Called for all agents before step phase. """
        pass

    def step(self):
        """ Step phase. Called for all agents after pre-step phase. """
        pass

    def post_step(self):
        """ Post-step phase. Called for all agents after post-step phase. """
        pass


class ModelSetupException(Exception):
    """Exception raised when there is an error setting up the model."""
    pass
