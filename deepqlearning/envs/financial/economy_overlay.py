# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Named economy scenarios as overlays on the stochastic economy.

``FinancialConfig.apply_scenario`` *replaces* the economy: ``high_inflation`` sets ``mode: fixed``
(8% inflation and 5% equity every year, forever), and ``recession`` sets ``mode: path`` (three
scripted years, then constant long-run rates). Under that semantics every Monte Carlo trial of a
scenario household sees the same market, varying only in mortality, and a level scenario is a
permanent 60-year regime.

An overlay keeps the stochastic economy and layers the scenario on top:

* a **level** override (``inflation: 8.0``) shifts that rate's stochastic draw by
  ``level - baseline_mean`` for the first ``regime_years`` simulated years, then the economy reverts
  to its baseline distribution (a decade-long regime, not a permanent one);
* a **path** override (``paths: {equity_return: {2027: -12.0}}``) replaces the draw in exactly the
  listed years (a scripted shock inside an otherwise random history).

Non-economy overrides in a scenario (credit-card rates, state tax) are applied through the normal
config path. The overlay adjusts ``EconomyModel``'s per-year resolution through its
``set_year_adjuster`` hook (the monthly rates are rescaled to the adjusted year).
"""

from dataclasses import dataclass, field
from typing import Any

# Scenario level key -> the stochastic-config mean it shifts.
_MEAN_OF_RATE = {
    "inflation": "inflation_mean",
    "wage_growth": "wage_growth_mean",
    "equity_return": "equity_mean",
    "bond_return": "bond_mean",
    "cash_yield": "cash_yield_mean",
    "home_appreciation": "home_appreciation_mean",
}

#: Years a level scenario holds before the economy reverts to its baseline distribution.
DEFAULT_REGIME_YEARS = 10


@dataclass(frozen=True)
class ScenarioOverlay:
    """Per-year adjustments a named scenario makes to stochastic draws."""

    start_year: int
    regime_years: int
    #: rate name -> additive shift (percentage points) applied during the regime.
    shifts: dict[str, float] = field(default_factory=dict)
    #: rate name -> {year: replacement value (percent)}.
    paths: dict[str, dict[int, float]] = field(default_factory=dict)

    @classmethod
    def from_scenario(
        cls, economy_overrides: dict[str, Any], stochastic_config: Any, start_year: int, regime_years: int
    ) -> "ScenarioOverlay":
        """Build the overlay from a scenario's ``economy`` block and the baseline stochastic config."""
        shifts = {
            rate: float(value) - float(getattr(stochastic_config, _MEAN_OF_RATE[rate]))
            for rate, value in economy_overrides.items()
            if rate in _MEAN_OF_RATE
        }
        paths = {
            rate: {int(year): float(value) for year, value in series.items()}
            for rate, series in (economy_overrides.get("paths") or {}).items()
        }
        unknown = set(paths) - set(_MEAN_OF_RATE)
        if unknown:
            raise ValueError(f"Unknown path rate(s) {sorted(unknown)}; expected {sorted(_MEAN_OF_RATE)}")
        return cls(start_year=start_year, regime_years=regime_years, shifts=shifts, paths=paths)

    def adjust(self, year: int, rates: dict[str, float]) -> dict[str, float]:
        """The scenario's version of one year's drawn ``rates`` (a new dict)."""
        adjusted = dict(rates)
        if self.start_year <= year < self.start_year + self.regime_years:
            for rate, shift in self.shifts.items():
                adjusted[rate] = adjusted[rate] + shift
        for rate, series in self.paths.items():
            if year in series:
                adjusted[rate] = series[year]
        adjusted["cash_yield"] = max(0.0, adjusted["cash_yield"])
        return adjusted

    def install(self, economy: Any) -> None:
        """Adjust ``economy``'s per-year rates (and any already-resolved year); each year's monthly
        rates are rescaled to compound to the adjusted annual rate (``EconomyModel.set_year_adjuster``)."""
        economy.set_year_adjuster(self.adjust)
