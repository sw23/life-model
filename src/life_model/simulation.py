# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from datetime import date

import pandas as pd

from .basemodel import BaseModel, EventLog


class Simulation(BaseModel):
    def __init__(self, end_year=None, start_year=None):
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
        self._year = start_year
        self._event_log = EventLog(self)
        self.simulated_years = []
        self.simulated_data = None

    def get_year(self):
        return self._year

    def get_event_log(self):
        return self._event_log

    def advance_year(self, objects=None):
        self.simulated_years.append(self._year)
        super().advance_year(objects)
        self._year += 1

    def get_year_range(self):
        return range(self.start_year, self.end_year + 1)

    def run(self, yearly_callback=None):
        self.simulated_data = []
        for year in self.get_year_range():
            self.advance_year()
            year_end_data = self.get_stats()
            year_end_data['Year'] = year
            if yearly_callback is not None:
                yearly_callback(year_end_data)
            self.simulated_data.append(year_end_data)
        return self.simulated_data

    def get_yearly_stat_df(self, columns=None, extra_columns=None, aggregate=None):
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
            df = df.aggregate(aggregators).reset_index(name='Total').transpose()
            df.columns = df.iloc[0]
            df = df.drop(df.index[0])
        formats = {x.title: x.fmt for x in stats if x.fmt is not None}
        return df.style.format(precision=0, na_rep='MISSING', formatter=formats).hide_index()
