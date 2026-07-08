# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from datetime import date
from math import e as const_e
from typing import Callable, Dict, List, Optional

import mesa
import pandas as pd
from pandas.io.formats.style import Styler

from .config.financial_config import FinancialConfig
from .registry import ModelRegistries


def compound_interest(principal: float, rate: float, num_times_applied: int = 1, elapsed_time_periods: int = 1):
    return principal * pow(1 + ((rate / 100) / num_times_applied), num_times_applied * elapsed_time_periods) - principal


def continous_interest(principal: float, rate: float, elapsed_time_periods: int = 1):
    return principal * pow(const_e, (rate / 100) * elapsed_time_periods) - principal


FMT_MONEY = "${:,.0f}"


def round_money(amount: float) -> float:
    """Round a monetary amount to whole cents to avoid float residue accumulating in balances."""
    return round(amount, 2)


class Stat:
    def __init__(
        self, name: str, title: Optional[str] = None, fmt: Optional[str] = None, aggregator: Optional[Callable] = None
    ):
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

    def model_reporter(self, model: "LifeModel"):
        """Return the value of the stat for the model."""
        return self.aggregator(getattr(agent, self.name) for agent in model.agents)


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
    def __init__(self, model: "LifeModel"):
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
        MoneyStat("stat_gross_income", "Income"),  # Gross income made in a year
        MoneyStat("stat_bank_balance", "Bank Balance"),  # Bank account balance at the end of each year
        MoneyStat("stat_401k_balance", "401k Balance"),  # Total 401k balance at the end of each year
        MoneyStat("stat_useable_balance", "Useable Balance"),  # Balance available for use in a year
        MoneyStat("stat_debt", "Debt"),  # Total debt balance in each year
        MoneyStat("stat_taxes_paid", "Taxes"),  # Taxes paid in a year
        MoneyStat("stat_money_spent", "Spending"),  # Money spent in a year
        MoneyStat("stat_retirement_contrib", "401k Contrib"),  # Money contributed to retirement in a given year
        MoneyStat("stat_retirement_match", "401k Match"),  # Money matched by company in 401k in a given year
        MoneyStat("stat_required_min_distrib", "RMDs"),  # Money taken out from required minimum distrib.
        MoneyStat("stat_housing_costs", "Housing"),  # Money paid towards mortgage or rent
        MoneyStat("stat_interest_paid", "Interest Paid"),  # Money paid in interest for loans
        MoneyStat("stat_ss_income", "SS Income"),  # Income from social security
        MoneyStat("stat_charitable_donations", "Charity"),  # Total charitable donations in a year
    ]

    EXTRA_STATS = [
        MoneyStat("stat_taxes_paid_federal", "Federal Taxes"),  # Federal income taxes paid in a year
        MoneyStat("stat_taxes_paid_state", "State Taxes"),  # State income taxes paid in a year
        MoneyStat("stat_taxes_paid_ss", "SS Taxes"),  # Social security taxes paid in a year
        MoneyStat("stat_taxes_paid_medicare", "Medicare Taxes"),  # Medicare taxes paid in a year
        MoneyStat("stat_premium_payments", "Life Ins Premiums"),  # Life insurance premiums paid in a year
        MoneyStat("stat_cash_value", "Life Ins Cash Value"),  # Life insurance cash value
        MoneyStat("stat_death_benefit_paid", "Death Benefits"),  # Death benefits paid out
        MoneyStat("stat_dependent_costs", "Dependent Costs"),  # Child/dependent costs charged in a year
        MoneyStat("stat_pension_income", "Pension Income"),  # Defined-benefit pension income received in a year
    ]

    def __init__(
        self,
        end_year: Optional[int] = None,
        start_year: Optional[int] = None,
        seed: Optional[int] = None,
        config: Optional[FinancialConfig] = None,
        scenario: Optional[str] = None,
    ):
        """LifeModel Helper Class

        Args:
            end_year (int, optional): End date of the model. Defaults to None.
            start_year (int, optional): Start date of the model. Defaults to None.
            seed (int, optional): Random seed. Defaults to None.
            config (FinancialConfig, optional): Per-model financial configuration.
                Defaults to a fresh copy of the packaged defaults so that separate
                models can run different scenarios in the same process.
            scenario (str, optional): Name of a packaged scenario to apply. Defaults to None.
        """
        super().__init__(seed=seed)  # Required in Mesa 3.0
        if start_year is None:
            start_year = date.today().year

        # Resolve per-model financial configuration.
        if config is None:
            config = FinancialConfig(scenario=scenario)
        elif scenario is not None:
            from .config.scenarios import get_scenario

            config.apply_scenario(scenario, get_scenario(scenario))
        self.config = config

        # Initialize registries
        self.registries = ModelRegistries()
        if end_year is None:
            end_year = start_year + 50
        self.start_year = start_year
        self.end_year = end_year
        self.year = start_year
        self.event_log = EventLog(self)
        self.simulated_years = []
        self._stages = ["pre_step", "step", "post_step"]

        # The economy provides the year's rates (inflation, returns, wage growth) to every other
        # agent. It is created first and steps first so its rates are cached before any consumer
        # reads them.
        from .economy import EconomyModel

        self.economy = EconomyModel(self)
        self.datacollector = mesa.DataCollector(
            model_reporters={
                **{"Year": "year"},
                **{x.title: lambda model, x=x: x.model_reporter(model) for x in self.STATS},
                **{x.title: lambda model, x=x: x.model_reporter(model) for x in self.EXTRA_STATS},
            },
            agent_reporters={
                **{x.title: x.name for x in self.STATS},
                **{x.title: x.name for x in self.EXTRA_STATS},
            },
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
        for stat in cls.EXTRA_STATS:
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
        for stat in cls.EXTRA_STATS:
            if stat.title == stat_title:
                return stat
        return None

    def step(self):
        """Execute one step of the model for a single simulated year.

        Canonical yearly sequence (see LifeModelAgent.STEP_PRIORITY for ordering within a stage):
          * pre_step:  age++, income deposited, account growth, RMDs
          * step:      tax units settle taxes/spending/withdrawals
          * post_step: stat resets, escalators (salary/spending/rent increases), taxable_income reset

        The DataCollector row for year Y is collected *after* the stages run (while ``self.year``
        still equals Y), so the row for year Y contains year-Y flows and end-of-year-Y balances.

        Once the final year has been simulated ``self.running`` is cleared and further calls are
        no-ops. This lets interactive drivers (SolaraViz's Play loop, which runs while
        ``self.running``) stop at ``end_year``; the notebook ``run()`` path calls step() exactly
        once per year in the range and never reaches the no-op branch.
        """
        # Don't step past the configured final year.
        if self.year > self.end_year:
            self.running = False
            return

        self.simulated_years.append(self.year)

        # Execute each stage in a deterministic, priority-ordered sequence per stage
        for stage in self._stages:
            for agent in sorted(self.agents, key=lambda a: a.STEP_PRIORITY.get(stage, 0)):
                getattr(agent, stage)()

        # Collect after the stages so row Year=Y holds year-Y flows and balances
        self.datacollector.collect(self)

        self.year += 1
        self.running = self.year <= self.end_year

    def get_year_range(self) -> range:
        """Get the inclusive range of simulated years ``[start_year, end_year]``."""
        return range(self.start_year, self.end_year + 1)

    def tax_params_for_year(self, year: int):
        """Tax parameters for ``year``, inflation-projected past the published table.

        For years beyond the last published tax year, the dollar-denominated parameters are
        indexed by the economy's realized cumulative inflation from the last published year to
        ``year`` (so a 50-year simulation doesn't apply frozen present-day brackets in 2050).
        Years within the published table are returned unchanged.
        """
        published_years = self.config.model.tax_years
        last_published = max(published_years) if published_years else year
        factor = 1.0
        if year > last_published:
            for y in range(last_published, year):
                factor *= 1 + self.economy.inflation(y) / 100
        return self.config.tax_year(year, inflation_factor=factor)

    def run(self):
        """Run the simulation over the inclusive year range ``[start_year, end_year]``.

        The number of simulated years is ``end_year - start_year + 1``.
        """
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
        for agent in self.agents:
            if not hasattr(agent, attr_name):
                setattr(agent, attr_name, 0)

    def get_yearly_stat_df(
        self,
        columns: Optional[List[str]] = None,
        extra_columns: Optional[List[str]] = None,
        aggregate: Optional[Dict[str, Callable]] = None,
        column_formats: Optional[Dict[str, str]] = None,
        real_dollars: bool = False,
    ) -> Styler:
        """Get a DataFrame of the yearly stats

        Args:
            columns (List[str], optional): Optional list of columns to include. Defaults to None.
            extra_columns (List[str], optional): Optional list of extra columns to include. Defaults to None.
            aggregate (Dict[str, Callable], optional): Dictionary of aggregators to use. Defaults to None.
            column_formats (Dict[str, str], optional): Dictionary of column formats to use. Defaults to None.
            real_dollars (bool, optional): When True, every money column is deflated by the economy's
                cumulative inflation so values are expressed in start-year dollars. Defaults to False
                (nominal dollars).

        Returns:
            pd.DataFrame: DataFrame of the yearly stats
        """
        # Get the list of columns to use
        if columns is None:
            columns = ["Year"] + [x.name for x in self.STATS]
        if extra_columns is not None:
            for i, column in enumerate(extra_columns):
                columns.insert(i + 1, column)
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
        if real_dollars:
            df = self._to_real_dollars(df)
        if aggregate is not None:
            # Aggregate the data if desired
            aggregators = {**{"Year": "max"}, **aggregate, **{x.title: x.aggregator.__name__ for x in stats}}
            df = df.aggregate(aggregators).reset_index().transpose()
            df.columns = df.iloc[0]
            df = df.drop(df.index[0])
        formats = {x.title: x.fmt for x in stats if x.fmt is not None}
        if column_formats is not None:
            formats.update(column_formats)
        return df.style.format(precision=0, na_rep="MISSING", formatter=formats).hide()

    def _to_real_dollars(self, df: pd.DataFrame) -> pd.DataFrame:
        """Deflate every money column of ``df`` into start-year dollars.

        Each row's money values are divided by the economy's cumulative inflation for that row's
        year (taken from the ``Year`` column when present, otherwise inferred from the simulated
        year range). Non-money columns (e.g. ``Year``) are left untouched.
        """
        df = df.copy()
        money_titles = {s.title for s in (self.STATS + self.EXTRA_STATS) if isinstance(s, MoneyStat)}
        if "Year" in df.columns:
            years = [int(y) for y in df["Year"].tolist()]
        else:
            years = list(self.get_year_range())[: len(df)]
        deflators = [self.economy.cumulative_inflation(y) for y in years]
        for col in df.columns:
            if col in money_titles:
                df[col] = [value / deflators[i] for i, value in enumerate(df[col].tolist())]
        return df

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
        return df.style.format(precision=0, na_rep="MISSING", formatter=formats).hide()

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
        aggregators = {**{"Year": "max"}, **{x.title: x.aggregator.__name__ for x in stats}}
        df = df.aggregate(aggregators).reset_index().transpose()
        df.columns = df.iloc[0]
        return df.drop(df.index[0])


class LifeModelAgent(mesa.Agent):
    # Per-stage execution priority. Within a stage, agents run in ascending priority order
    # (lower runs first); ties preserve construction order. This makes the yearly sequence
    # deterministic and independent of object construction order (see LifeModel.step docstring).
    #   pre_step:  Person ages first (-20), then account growth/RMDs (-10), then job income (0)
    #   step:      account growth (-10) before tax-unit settlement (0)
    #   post_step: stat resets/escalators run at the default priority (0)
    STEP_PRIORITY: Dict[str, int] = {}

    def __init__(self, model: LifeModel):
        """LifeModelAgent

        Args:
            model (LifeModel): LifeModel.
        """
        super().__init__(model)  # unique_id is now automatically assigned

        # Initialize the stats
        for stat in LifeModel.STATS:
            setattr(self, stat.name, 0)
        for stat in LifeModel.EXTRA_STATS:
            setattr(self, stat.name, 0)

    def pre_step(self):
        """Pre-step phase. Called for all agents before step phase."""
        pass

    def step(self):
        """Step phase. Called for all agents after pre-step phase."""
        pass

    def post_step(self):
        """Post-step phase. Called for all agents after the step phase."""
        pass


class ModelSetupException(Exception):
    """Exception raised when there is an error setting up the model."""

    pass
