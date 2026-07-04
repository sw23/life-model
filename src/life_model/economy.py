# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Economy-wide rate provider for a simulation.

A single :class:`EconomyModel` agent exists per :class:`~life_model.model.LifeModel`. It answers
per-year queries for the rates that drive the rest of the model — inflation, wage growth, and the
returns on cash, bonds, equities, and homes. Accounts, salaries, spending, and housing consult the
economy each year instead of owning their own frozen rate constants, so a whole simulation can be
run under a single coherent economic assumption (fixed, an explicit path, or stochastic draws).

The economy runs first every year (``STEP_PRIORITY`` puts its ``pre_step`` ahead of everyone
else's) so that whatever it draws or looks up for the year is already cached before any consumer
reads it. Rates are cached per year, which makes stochastic runs reproducible under a fixed seed
(every consumer in a given year sees the same draw) and lets the deflator be reconstructed for
real-dollar reporting.
"""

from typing import TYPE_CHECKING, Dict, List

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


class EconomyModel(LifeModelAgent):
    """Provides per-year economic rates (percentages) to the rest of the model.

    Query the current year's rate via the named accessors (:meth:`inflation`, :meth:`equity_return`,
    ...), or any year via ``rate(name, year)``. Behavior is governed by ``config.economy.mode``:

    * ``fixed`` — every year returns the configured constant (default; reproduces the pre-economy
      per-account constants exactly).
    * ``path`` — the ``economy.paths`` table overrides individual years per rate; unlisted years
      fall back to the fixed constant.
    * ``stochastic`` — equity/bond/inflation are drawn as correlated normals and the remaining
      series independently, using the model's seeded RNG so runs are reproducible.
    """

    # Run before every other agent's pre_step so the year's rates are cached before anyone reads
    # them (Person ages at -20, accounts grow at -10; the economy must precede both).
    STEP_PRIORITY = {"pre_step": -100}

    def __init__(self, model: "LifeModel"):
        super().__init__(model)
        self.config = model.config.economy
        # year -> {rate_name: percent}
        self._rates_by_year: Dict[int, Dict[str, float]] = {}
        # Cache the starting year immediately so consumers constructed before the first step
        # (the usual case) already see coherent rates.
        self._ensure_year(model.year)

    # ------------------------------------------------------------------
    # Per-year resolution
    # ------------------------------------------------------------------
    def _ensure_year(self, year: int) -> Dict[str, float]:
        rates = self._rates_by_year.get(year)
        if rates is None:
            rates = self._compute_year(year)
            self._rates_by_year[year] = rates
        return rates

    def _compute_year(self, year: int) -> Dict[str, float]:
        mode = self.config.mode
        if mode == "fixed":
            return self._fixed_rates()
        if mode == "path":
            return self._path_rates(year)
        if mode == "stochastic":
            return self._stochastic_rates()
        raise ValueError(f"Unknown economy mode {mode!r}")

    def _fixed_rates(self) -> Dict[str, float]:
        c = self.config
        return {
            "inflation": c.inflation,
            "wage_growth": c.wage_growth,
            "equity_return": c.equity_return,
            "bond_return": c.bond_return,
            "cash_yield": c.cash_yield,
            "home_appreciation": c.home_appreciation,
        }

    def _path_rates(self, year: int) -> Dict[str, float]:
        rates = self._fixed_rates()
        for name, series in self.config.paths.items():
            if name not in rates:
                raise ValueError(f"Unknown economy path rate {name!r}; expected one of {RATE_NAMES}")
            if year in series:
                rates[name] = series[year]
        return rates

    def _stochastic_rates(self) -> Dict[str, float]:
        s = self.config.stochastic
        # Correlated equity/bond/inflation draw via a Cholesky factor of the correlation matrix.
        equity_z, bond_z, inflation_z = self._correlated_normals(
            s.equity_bond_correlation, s.equity_inflation_correlation, s.bond_inflation_correlation
        )
        cash = s.cash_yield_mean + s.cash_yield_vol * self.model.random.gauss(0, 1)
        return {
            "inflation": s.inflation_mean + s.inflation_vol * inflation_z,
            "wage_growth": s.wage_growth_mean + s.wage_growth_vol * self.model.random.gauss(0, 1),
            "equity_return": s.equity_mean + s.equity_vol * equity_z,
            "bond_return": s.bond_mean + s.bond_vol * bond_z,
            # A yield can't go negative; floor it at zero.
            "cash_yield": max(0.0, cash),
            "home_appreciation": s.home_appreciation_mean
            + s.home_appreciation_vol * self.model.random.gauss(0, 1),
        }

    def _correlated_normals(self, eq_bond: float, eq_inf: float, bond_inf: float) -> List[float]:
        """Return three correlated standard normals drawn from the model's seeded RNG.

        Independent normals are combined through the Cholesky factor of the correlation matrix so
        the draw is reproducible under the model seed without a second RNG.
        """
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
        z = np.array([self.model.random.gauss(0, 1) for _ in range(3)])
        return list(factor @ z)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def rate(self, name: str, year: int | None = None) -> float:
        """Return the ``name`` rate (percent) for ``year`` (defaults to the current model year)."""
        if name not in RATE_NAMES:
            raise ValueError(f"Unknown economy rate {name!r}; expected one of {RATE_NAMES}")
        year = self.model.year if year is None else year
        return self._ensure_year(year)[name]

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

    def cumulative_inflation(self, year: int) -> float:
        """Cumulative price level (deflator) from the start year through ``year``.

        The start year has a deflator of 1.0; each subsequent year multiplies by
        ``1 + inflation(previous year)/100``. Dividing a nominal amount in ``year`` by this factor
        expresses it in start-year dollars.
        """
        factor = 1.0
        for y in range(self.model.start_year, year):
            factor *= 1 + self.inflation(y) / 100
        return factor

    def pre_step(self):
        # Draw / look up this year's rates before any consumer reads them.
        self._ensure_year(self.model.year)
