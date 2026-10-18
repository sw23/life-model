# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Economy-wide rate provider for a simulation.

A single :class:`EconomyModel` agent exists per :class:`~life_model.model.LifeModel`. It answers
queries for the rates that drive the rest of the model — inflation, wage growth, and the returns on
cash, bonds, equities, and homes — per month (:meth:`EconomyModel.monthly_rate`, what monthly flows
such as account growth use) and per year (:meth:`EconomyModel.rate`, what annual decisions such as
raises, cost-of-living adjustments and tax indexation use). Accounts, salaries, spending, and housing
consult the economy instead of owning their own frozen rate constants, so a whole simulation can be
run under a single coherent economic assumption (fixed, an explicit path, or stochastic draws).

Rates are in **percent**. A year's rate is the compound of its twelve monthly rates, so the two
views always agree: in ``fixed`` and ``path`` modes an annual percentage ``R`` becomes the monthly
rate ``(1 + R)^(1/12) - 1``; in ``stochastic`` mode each month is drawn and the year compounds them.

The economy resolves a whole year at a time (its twelve months, all at once) the first time anything
reads the year, and caches it. That makes stochastic runs reproducible under a fixed seed (every
consumer in a given year sees the same draws, whatever month the model started in) and lets the
deflator be reconstructed for real-dollar reporting. Its ``pre_step`` (run first every month)
resolves the current year before any consumer reads it.
"""

import math
from typing import TYPE_CHECKING, ClassVar

from .model import LifeModelAgent

if TYPE_CHECKING:
    from .model import LifeModel

# The rates the economy provides, in the fixed order used to build correlated draws.
RATE_NAMES = (
    "inflation",
    "wage_growth",
    "equity_return",
    "bond_return",
    "cash_yield",
    "home_appreciation",
)


def annual_to_monthly(percent: float) -> float:
    """The monthly rate (percent) that compounds to ``percent`` over twelve months."""
    if percent <= -100:
        return -100.0
    return ((1 + percent / 100) ** (1 / 12) - 1) * 100


def compound_months(monthly_percents) -> float:
    """The annual rate (percent) of a sequence of monthly rates (percent)."""
    factor = 1.0
    for rate in monthly_percents:
        factor *= 1 + rate / 100
    return (factor - 1) * 100


def path_month_key(year: int, month: int) -> str:
    """The ``economy.paths`` key of one month (``"2027-03"``)."""
    return f"{year:04d}-{month:02d}"


class EconomyModel(LifeModelAgent):
    """Provides per-month and per-year economic rates (percentages) to the rest of the model.

    Query a month via :meth:`monthly_rate` (defaults to the current month), a year via
    ``rate(name, year)`` or the named accessors (:meth:`inflation`, :meth:`equity_return`, ...).
    Behavior is governed by ``config.economy.mode``:

    * ``fixed`` — every year returns the configured constant (each month its twelfth-root share).
    * ``path`` — the ``economy.paths`` table overrides individual years (``{2027: -20.0}``: the
      year's annual percent, spread evenly over its months) or individual months
      (``{"2027-03": -7.2}``: that month's own return); unlisted periods fall back to the year's
      entry, then the fixed constant.
    * ``stochastic`` — each month is drawn: equity/bond/inflation as correlated normals (the
      configured correlation matrix) and the remaining series independently, with the annual mean
      converted to its monthly equivalent and the annual volatility scaled by ``1/sqrt(12)``, plus an
      optional AR(1) term per series (``economy.stochastic.autocorrelation``), using the model's
      seeded RNG so runs are reproducible.
    """

    # Run before every other agent's pre_step so the year's rates are cached before anyone reads
    # them (Person ages at -20, accounts grow at -10; the economy must precede both).
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"pre_step": -100}

    def __init__(self, model: "LifeModel"):
        super().__init__(model)
        self.config = model.config.economy
        # year -> {rate_name: annual percent}
        self._rates_by_year: dict[int, dict[str, float]] = {}
        # year -> {rate_name: [12 monthly percents, January first]}
        self._monthly_by_year: dict[int, dict[str, list[float]]] = {}
        # The standardized AR(1) state of each series (stochastic mode).
        self._ar_state: dict[str, float] = {}
        self._cholesky = None
        # Cache the starting year immediately so consumers constructed before the first step
        # (the usual case) already see coherent rates.
        self._ensure_year(model.year)

    # ------------------------------------------------------------------
    # Per-year resolution
    # ------------------------------------------------------------------
    def _ensure_year(self, year: int) -> dict[str, float]:
        rates = self._rates_by_year.get(year)
        if rates is None:
            monthly, annual = self._compute_year(year)
            self._monthly_by_year[year] = monthly
            self._rates_by_year[year] = rates = annual
        return rates

    def _compute_year(self, year: int) -> "tuple[dict[str, list[float]], dict[str, float]]":
        mode = self.config.mode
        if mode == "fixed":
            annual = self._fixed_rates()
            return {name: [annual_to_monthly(rate)] * 12 for name, rate in annual.items()}, annual
        if mode == "path":
            return self._path_rates(year)
        if mode == "stochastic":
            monthly = self._stochastic_year()
            return monthly, {name: compound_months(months) for name, months in monthly.items()}
        raise ValueError(f"Unknown economy mode {mode!r}")

    def _fixed_rates(self) -> dict[str, float]:
        c = self.config
        return {
            "inflation": c.inflation,
            "wage_growth": c.wage_growth,
            "equity_return": c.equity_return,
            "bond_return": c.bond_return,
            "cash_yield": c.cash_yield,
            "home_appreciation": c.home_appreciation,
        }

    def _path_rates(self, year: int) -> "tuple[dict[str, list[float]], dict[str, float]]":
        annual = self._fixed_rates()
        monthly: dict[str, list[float]] = {}
        for name in self.config.paths:
            if name not in annual:
                raise ValueError(f"Unknown economy path rate {name!r}; expected one of {RATE_NAMES}")
        for name, base in annual.items():
            series = self.config.paths.get(name, {})
            year_rate = series.get(year, base)
            months = [annual_to_monthly(year_rate)] * 12
            listed = False
            for month in range(1, 13):
                key = path_month_key(year, month)
                if key in series:
                    months[month - 1] = series[key]
                    listed = True
            monthly[name] = months
            # A year with no month entries keeps its annual percent exactly.
            annual[name] = compound_months(months) if listed else year_rate
        return monthly, annual

    def _stochastic_year(self) -> dict[str, list[float]]:
        s = self.config.stochastic
        phi = dict(s.autocorrelation)
        for name in phi:
            if name not in RATE_NAMES:
                raise ValueError(f"Unknown autocorrelation rate {name!r}; expected one of {RATE_NAMES}")
        sqrt12 = math.sqrt(12)
        params = {
            "inflation": (s.inflation_mean, s.inflation_vol),
            "wage_growth": (s.wage_growth_mean, s.wage_growth_vol),
            "equity_return": (s.equity_mean, s.equity_vol),
            "bond_return": (s.bond_mean, s.bond_vol),
            "cash_yield": (s.cash_yield_mean, s.cash_yield_vol),
            "home_appreciation": (s.home_appreciation_mean, s.home_appreciation_vol),
        }
        monthly: dict[str, list[float]] = {name: [] for name in RATE_NAMES}
        for _month in range(12):
            # Correlated equity/bond/inflation shocks via a Cholesky factor of the correlation matrix,
            # then the independent series, in a fixed order (the seeded stream is reproducible).
            equity_z, bond_z, inflation_z = self._correlated_normals(
                s.equity_bond_correlation, s.equity_inflation_correlation, s.bond_inflation_correlation
            )
            shocks = {
                "equity_return": equity_z,
                "bond_return": bond_z,
                "inflation": inflation_z,
                "cash_yield": self.model.random.gauss(0, 1),
                "wage_growth": self.model.random.gauss(0, 1),
                "home_appreciation": self.model.random.gauss(0, 1),
            }
            for name in RATE_NAMES:
                mean, vol = params[name]
                z = shocks[name]
                rho = phi.get(name, 0.0)
                if rho:
                    # Stationary AR(1) on the standardized shock: the series keeps its volatility
                    # but bad months cluster.
                    z = rho * self._ar_state.get(name, 0.0) + math.sqrt(1 - rho * rho) * z
                    self._ar_state[name] = z
                value = annual_to_monthly(mean) + vol / sqrt12 * z
                if name == "cash_yield":
                    value = max(0.0, value)  # a yield can't go negative
                monthly[name].append(value)
        return monthly

    def _correlated_normals(self, eq_bond: float, eq_inf: float, bond_inf: float) -> list[float]:
        """Return three correlated standard normals drawn from the model's seeded RNG.

        Independent normals are combined through the Cholesky factor of the correlation matrix so
        the draw is reproducible under the model seed without a second RNG.
        """
        if self._cholesky is None:
            import numpy as np

            corr = np.array(
                [
                    [1.0, eq_bond, eq_inf],
                    [eq_bond, 1.0, bond_inf],
                    [eq_inf, bond_inf, 1.0],
                ]
            )
            try:
                factor = np.linalg.cholesky(corr)
            except np.linalg.LinAlgError:
                # Not positive-definite (inconsistent correlations); fall back to independent draws.
                factor = np.eye(3)
            self._cholesky = factor.tolist()
        z = [self.model.random.gauss(0, 1) for _ in range(3)]
        return [sum(row[j] * z[j] for j in range(3)) for row in self._cholesky]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def rate(self, name: str, year: int | None = None) -> float:
        """Return the ``name`` rate (percent) for ``year`` (defaults to the current model year): the
        compound of its twelve monthly rates."""
        if name not in RATE_NAMES:
            raise ValueError(f"Unknown economy rate {name!r}; expected one of {RATE_NAMES}")
        year = self.model.year if year is None else year
        return self._ensure_year(year)[name]

    def monthly_rate(self, name: str, year: int | None = None, month: int | None = None) -> float:
        """Return the ``name`` rate (percent) for one month (defaults to the model's current month):
        e.g. about 0.565 for a 7% year."""
        if name not in RATE_NAMES:
            raise ValueError(f"Unknown economy rate {name!r}; expected one of {RATE_NAMES}")
        year = self.model.year if year is None else year
        month = self.model.month if month is None else month
        self._ensure_year(year)
        return self._monthly_by_year[year][name][month - 1]

    def monthly_rates(self, name: str, year: int | None = None) -> list[float]:
        """The twelve monthly ``name`` rates (percent) of ``year``, January first."""
        year = self.model.year if year is None else year
        self._ensure_year(year)
        return list(self._monthly_by_year[year][name])

    def inflation(self, year: int | None = None) -> float:
        return self.rate("inflation", year)

    def wage_growth(self, year: int | None = None) -> float:
        return self.rate("wage_growth", year)

    def equity_return(self, year: int | None = None) -> float:
        return self.rate("equity_return", year)

    def bond_return(self, year: int | None = None) -> float:
        return self.rate("bond_return", year)

    def cash_yield(self, year: int | None = None) -> float:
        return self.rate("cash_yield", year)

    def home_appreciation(self, year: int | None = None) -> float:
        return self.rate("home_appreciation", year)

    def cumulative_inflation(self, year: int, month: int | None = None) -> float:
        """Cumulative price level (deflator) from the start year through ``year`` (and, when given,
        through the start of ``month`` within it).

        The start year has a deflator of 1.0; each subsequent year multiplies by
        ``1 + inflation(previous year)/100``, and within a year each month by its monthly
        inflation (so month 1 equals the annual value). Dividing a nominal amount in ``year`` by this
        factor expresses it in start-year dollars.
        """
        factor = 1.0
        for y in range(self.model.start_year, year):
            factor *= 1 + self.inflation(y) / 100
        if month is not None:
            for rate in self.monthly_rates("inflation", year)[: month - 1]:
                factor *= 1 + rate / 100
        return factor

    def pre_step(self):
        # Draw / look up this year's rates before any consumer reads them.
        self._ensure_year(self.model.year)
