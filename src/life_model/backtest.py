# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Backtest a household against its statements over past years.

:func:`backtest` runs a household spec from its ``meta.start_year`` through the last year that has
statement balances in ``actuals``, feeding the economy the *realized* path (``economy.mode: path``):

* ``equity_return_pct`` for year Y: the S&P 500 total return of calendar year Y (account growth in Y);
* ``inflation_pct`` for year Y: the CPI-U annual-average change from Y to Y+1 (the escalator that
  turns year Y's spending and rent into year Y+1's);
* ``wage_growth_pct`` for year Y: the national average wage index change from Y to Y+1 (year Y+1's
  raise).

The realized series live in ``config/data/realized_economy.yaml`` (each stamped with its source).
Then it scores every year-end balance in ``actuals[year].balances`` against the simulated balance of
that account. Accounts the household spec gives other growth rates keep them; use ``"economy"`` for
the ones that should follow the realized market.

Feeding real statements: describe the household as of January 1 of the first year (balances from
the December 31 statements before it), put each later December 31 statement balance under
``actuals.<year>.balances.<account id>``, set ``growth_pct: economy`` on accounts invested like the
S&P 500 (or a fixed rate for those that are not), and run :func:`backtest`. Differences then come
from what the spec does not capture: contribution timing (the engine credits a year's contributions
before that year's growth; monthly deposits earn about half a year less), fees, the actual fund mix.
"""

import json
from dataclasses import asdict, dataclass, field
from importlib.resources import files
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from .spec import HouseholdSpec


def realized_series() -> dict[str, dict[int, float]]:
    """The packaged realized series (``cpi_u_annual_average``, ``sp500_total_return_pct``,
    ``avg_wage_index``)."""
    text = (files("life_model.config") / "data" / "realized_economy.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return {name: {int(year): float(value) for year, value in series.items()} for name, series in data.items()}


def realized_paths(first_year: int, last_year: int) -> dict[str, dict[int, float]]:
    """Spec ``economy.paths`` (percent) for ``[first_year, last_year]`` from the realized series. A rate
    whose data is missing for a year is left out for that year (the economy's constant applies)."""
    series = realized_series()
    cpi, awi, equity = series["cpi_u_annual_average"], series["avg_wage_index"], series["sp500_total_return_pct"]
    paths: dict[str, dict[int, float]] = {"equity_return_pct": {}, "inflation_pct": {}, "wage_growth_pct": {}}
    for year in range(first_year, last_year + 1):
        if year in equity:
            paths["equity_return_pct"][year] = equity[year]
        if year in cpi and year + 1 in cpi:
            paths["inflation_pct"][year] = round((cpi[year + 1] / cpi[year] - 1) * 100, 6)
        if year in awi and year + 1 in awi:
            paths["wage_growth_pct"][year] = round((awi[year + 1] / awi[year] - 1) * 100, 6)
    return {name: values for name, values in paths.items() if values}


@dataclass
class BalanceScore:
    """One account's simulated vs statement balance at a year end."""

    year: int
    account: str
    simulated: float
    statement: float

    @property
    def difference(self) -> float:
        return self.simulated - self.statement

    @property
    def relative(self) -> float:
        return self.difference / self.statement if self.statement else 0.0


@dataclass
class BacktestReport:
    household: str
    years: list[int]
    paths: dict[str, dict[int, float]]
    scores: list[BalanceScore] = field(default_factory=list)

    def final(self) -> list[BalanceScore]:
        last = max(s.year for s in self.scores)
        return [s for s in self.scores if s.year == last]

    def max_relative_error(self, *, final_only: bool = False) -> float:
        scores = self.final() if final_only else self.scores
        return max((abs(s.relative) for s in scores), default=0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "household": self.household,
            "years": self.years,
            "paths": {k: {str(y): v for y, v in s.items()} for k, s in self.paths.items()},
            "scores": [asdict(s) | {"difference": s.difference, "relative": s.relative} for s in self.scores],
            "max_relative_error": self.max_relative_error(),
            "final_max_relative_error": self.max_relative_error(final_only=True),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def to_markdown(self) -> str:
        out = [f"# Backtest: {self.household}, {self.years[0]}-{self.years[-1]}", ""]
        out.append("Realized economy fed to the model (percent; `--` keeps the configured constant, unused here):")
        out.append("")
        out.append("| Year | " + " | ".join(self.paths) + " |")
        out.append("|---|" + "---:|" * len(self.paths))
        for year in self.years:
            cells = [f"{self.paths[name][year]:.2f}" if year in self.paths[name] else "--" for name in self.paths]
            out.append(f"| {year} | " + " | ".join(cells) + " |")
        out += [
            "",
            "| Year | Account | Simulated | Statement | Difference | Relative |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for s in self.scores:
            difference = 0.0 if abs(s.difference) < 0.005 else s.difference
            relative = 0.0 if difference == 0 else s.relative
            out.append(
                f"| {s.year} | {s.account} | ${s.simulated:,.2f} | ${s.statement:,.2f} | {difference:+,.2f} | "
                f"{relative:+.4%} |"
            )
        out += [
            "",
            (
                f"Largest relative difference: {self.max_relative_error():.4%} (final year: "
                f"{self.max_relative_error(final_only=True):.4%})."
            ),
        ]
        return "\n".join(out) + "\n"


def backtest(
    spec: "HouseholdSpec",
    *,
    actuals: "dict[int, Any] | None" = None,
    years: "list[int] | None" = None,
    realized: bool = True,
    seed: int | None = None,
    checks: str = "strict",
) -> BacktestReport:
    """Run ``spec`` over its statement years with the realized economy and score the balances.

    Args:
        spec: The household as of January 1 of ``meta.start_year``.
        actuals: ``{year: ActualRecords}`` (default: ``spec.actuals``); each year's ``balances`` are
            December 31 statement balances by spec account id.
        years: Years to score (default: every year with balances, from ``meta.start_year``).
        realized: Feed the realized path (:func:`realized_paths`); False keeps the spec's economy.
        seed: Random seed (overrides ``meta.seed``).
        checks: Invariant-checker mode for the run (default ``strict``).
    """
    import warnings

    from .spec import build_household
    from .spec.schema import Economy

    actuals = actuals if actuals is not None else (spec.actuals or {})
    start = spec.meta.start_year
    scored = sorted(y for y, records in actuals.items() if records.balances and y >= start)
    if years is not None:
        scored = sorted(y for y in years if y in scored)
    if not scored:
        raise ValueError("No statement balances to score: add actuals.<year>.balances (years >= meta.start_year)")
    end = scored[-1]
    paths = realized_paths(start, end) if realized else {}
    economy = spec.economy.model_dump(exclude_none=True) if spec.economy is not None else {}
    if paths:
        economy = {**economy, "mode": "path", "paths": {**economy.get("paths", {}), **paths}}
    run_spec = spec.model_copy(
        update={
            "meta": spec.meta.model_copy(update={"end_year": end}),
            "economy": Economy.model_validate(economy) if economy else spec.economy,
        }
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        built = build_household(run_spec, seed=seed, check=checks != "off")
        built.model.checks = checks
        built.model.run()
    from .ledger import account_label

    report = BacktestReport(household=spec.meta.name, years=list(range(start, end + 1)), paths=paths)
    for year in scored:
        lines = built.model.balance_sheets[year].closing.lines
        for account, statement in actuals[year].balances.items():
            agent = built.items.get(account)
            if agent is None:
                raise ValueError(f"actuals.{year}.balances: no account with id {account!r}")
            simulated = abs(lines.get(account_label(agent), 0.0))
            report.scores.append(BalanceScore(year, account, simulated, statement))
    return report
