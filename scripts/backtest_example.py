# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The synthetic 2020-2025 backtest example (Plan 29 D5).

``python scripts/backtest_example.py statements`` writes the example household
(``src/life_model/tests/goldens/backtest/synthetic_2020_2025.yaml``) with December 31 statement
balances for 2020-2025 computed here, by plain arithmetic on the realized series in
``src/life_model/config/data/realized_economy.yaml`` (no life_model import):

* salary: $90,000 in 2020, then each year's raise is the national average wage index change;
* 401(k): a 10% pre-tax deferral plus a 50% match on up to 6% of pay (3% of pay), credited at the
  start of the year (the annual engine's convention), then the year's S&P 500 total return;
* Roth IRA and brokerage: no flows, the year's S&P 500 total return.

``python scripts/backtest_example.py`` (no argument) runs ``life_model.backtest.backtest`` on it and
writes the report to ``docs/backtest-2020-2025.md``.
"""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "src" / "life_model" / "tests" / "goldens" / "backtest" / "synthetic_2020_2025.yaml"
REALIZED = ROOT / "src" / "life_model" / "config" / "data" / "realized_economy.yaml"
REPORT = ROOT / "docs" / "backtest-2020-2025.md"
YEARS = range(2020, 2026)


def statements() -> dict[int, dict[str, float]]:
    data = yaml.safe_load(REALIZED.read_text(encoding="utf-8"))
    awi, equity = data["avg_wage_index"], data["sp500_total_return_pct"]
    salary = 90000.0
    k401, roth, brokerage = 150000.0, 30000.0, 50000.0
    out = {}
    for year in YEARS:
        growth = 1 + equity[year] / 100
        k401 = (k401 + salary * 0.10 + salary * 0.03) * growth
        roth *= growth
        brokerage *= growth
        out[year] = {
            "morgan_401k": round(k401, 2),
            "morgan_roth": round(roth, 2),
            "morgan_brokerage": round(brokerage, 2),
        }
        if year + 1 in awi:
            salary *= awi[year + 1] / awi[year]
    return out


def monthly_401k_2025() -> float:
    """The 2025 401(k) statement if each year's contributions arrived in twelve equal monthly deposits
    (each earning the rest of the year's return, compounded monthly): the size of the engine's
    contribution-timing convention."""
    data = yaml.safe_load(REALIZED.read_text(encoding="utf-8"))
    awi, equity = data["avg_wage_index"], data["sp500_total_return_pct"]
    salary, balance = 90000.0, 150000.0
    for year in YEARS:
        monthly = (1 + equity[year] / 100) ** (1 / 12)
        deposit = salary * 0.13 / 12
        balance = balance * (1 + equity[year] / 100) + sum(deposit * monthly ** (12 - m) for m in range(1, 13))
        if year + 1 in awi:
            salary *= awi[year + 1] / awi[year]
    return balance


def write_spec() -> None:
    spec = {
        "spec_version": 1,
        "meta": {
            "name": "Synthetic backtest household",
            "description": "Synthetic example (not real data) for the 2020-2025 backtest: a single saver whose 401(k), "
            "Roth IRA and brokerage follow the stock market index. Statement balances are computed by scripts/backtest_example.py.",
            "as_of": "2020-01",
            "start_year": 2020,
            "end_year": 2025,
            "seed": 1,
            "default_state": "TX",
        },
        "people": [
            {
                "id": "morgan",
                "name": "Morgan",
                "age": 40,
                "retirement_age": 65,
                "spending": {"amount_annual": 35000, "growth_pct": "economy"},
                "jobs": [
                    {"id": "morgan_job", "company": "Example Analytics", "salary_annual": 90000, "raise_pct": "economy"}
                ],
                "accounts": [
                    {
                        "kind": "bank",
                        "id": "morgan_checking",
                        "company": "Community Bank",
                        "balance": 20000,
                        "interest_pct": 0,
                    },
                    {
                        "kind": "401k",
                        "id": "morgan_401k",
                        "job": "morgan_job",
                        "pretax_balance": 150000,
                        "pretax_contrib_pct": 10,
                        "growth_pct": "economy",
                        "match_tiers": [{"match_pct": 50, "up_to_pay_pct": 6}],
                    },
                    {"kind": "roth_ira", "id": "morgan_roth", "balance": 30000, "growth_pct": "economy"},
                    {
                        "kind": "brokerage",
                        "id": "morgan_brokerage",
                        "company": "Example Brokerage",
                        "balance": 50000,
                        "growth_pct": "economy",
                        "dividend_yield_pct": 0,
                    },
                ],
                "housing": [
                    {"kind": "rental", "id": "morgan_rental", "rent_monthly": 1200, "rent_growth_pct": "economy"}
                ],
            }
        ],
        "actuals": {year: {"balances": balances} for year, balances in statements().items()},
    }
    SPEC.parent.mkdir(parents=True, exist_ok=True)
    SPEC.write_text(
        "# Synthetic backtest example (not real data). Generated by scripts/backtest_example.py statements.\n"
        + yaml.safe_dump(spec, sort_keys=False, width=110),
        encoding="utf-8",
    )
    print(f"wrote {SPEC}")


def write_report() -> None:
    from life_model.backtest import backtest
    from life_model.spec import load

    report = backtest(load(SPEC))
    text = report.to_markdown()
    intro = (
        "<!-- Generated by scripts/backtest_example.py; do not edit by hand. -->\n\n"
        "The synthetic 2020-2025 household in `src/life_model/tests/goldens/backtest/` run with the realized "
        "economy (S&P 500 total return, CPI-U, the SSA average wage index) and scored against statement "
        "balances computed independently from the same series (see [reconciliation.md](reconciliation.md)).\n\n"
    )
    simulated = next(s.simulated for s in report.final() if s.account == "morgan_401k")
    monthly = monthly_401k_2025()
    timing = (
        "\nContribution timing: the annual engine credits a year's 401(k) contributions before that year's "
        f"growth. Had the same contributions arrived monthly, the 2025 401(k) statement would read ${monthly:,.2f}, "
        f"{(simulated - monthly) / monthly:+.2%} against the simulated balance: the size of the timing convention a "
        "backtest against real statements should expect (a monthly engine, Plan 32, is meant to remove it).\n"
    )
    REPORT.write_text(text.replace("\n\n", "\n\n" + intro, 1) + timing, encoding="utf-8")
    print(f"wrote {REPORT}")


if __name__ == "__main__":
    if sys.argv[1:] == ["statements"]:
        write_spec()
    else:
        write_report()
