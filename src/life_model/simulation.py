# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from datetime import date
from typing import Optional, List, Callable, Dict
from pandas.io.formats.style import Styler

import pandas as pd

from .basemodel import BaseModel


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
    def __init__(self, simulation: 'Simulation'):
        """Event Log

        Args:
            simulation (Simulation): Simulation.
        """
        self.simulation = simulation
        self.list = []

    def _repr_html_(self):
        table = "<table>"
        table += "<tr><th>Year:</th><th>Event:</th></tr>\n"
        table += "".join(x._repr_html_() for x in self.list)
        table += "</table>"
        return table

    def add(self, event: Event):
        event.year = self.simulation.year
        self.list.append(event)


class Simulation(BaseModel):
    def __init__(self, end_year: Optional[int] = None, start_year: Optional[int] = None):
        """Simulation Helper Class

        Args:
            end_year (int, optional): End date of the simulation. Defaults to None.
            start_year (int, optional): Start date of the simulation. Defaults to None.
        """
        if start_year is None:
            start_year = date.today().year
        if end_year is None:
            end_year = start_year + 50
        self.simulation = self
        self.top_level_models = []
        self.start_year = start_year
        self.end_year = end_year
        self.year = start_year
        self.event_log = EventLog(self)
        self.simulated_years = []
        self.simulated_data = []

    def advance_year(self, objects=None):
        self.simulated_years.append(self.year)
        super().advance_year(objects)
        self.year += 1

    def get_year_range(self) -> range:
        return range(self.start_year, self.end_year + 1)

    def run(self, yearly_callback: Optional[Callable] = None) -> List[dict]:
        """Run the simulation

        Args:
            yearly_callback (Optional[Callable], optional): Optional callback to call every year. Defaults to None.

        Returns:
            List[dict]: List of simulated data for each year.
        """
        self.simulated_data = []
        for year in self.get_year_range():
            self.advance_year()
            year_end_data = self.get_stats()
            year_end_data['Year'] = year
            if yearly_callback is not None:
                yearly_callback(year_end_data)
            self.simulated_data.append(year_end_data)
        return self.simulated_data

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
        if columns is None:
            columns = ['Year'] + [x.name for x in self.COMMON_STATS]
        if extra_columns is not None:
            for i, column in enumerate(extra_columns):
                columns.insert(i+1, column)
        data = {}
        stats = []
        for column_name in columns:
            stat = self.get_stat_by_name(column_name)
            if stat is not None:
                stats.append(stat)
                title = stat.title
            else:
                title = column_name
            data[title] = [x[column_name] for x in self.simulated_data]
        df = pd.DataFrame(data)
        if aggregate is not None:
            aggregators = {**{'Year': max}, **aggregate, **{x.title: x.aggregator for x in stats}}
            df = df.aggregate(aggregators).reset_index().transpose()
            df.columns = df.iloc[0]
            df = df.drop(df.index[0])
        formats = {x.title: x.fmt for x in stats if x.fmt is not None}
        if column_formats is not None:
            formats.update(column_formats)
        return df.style.format(precision=0, na_rep='MISSING', formatter=formats).hide()
