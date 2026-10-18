# Checking the model: reconciliation, goldens, invariants and backtests

Four tools tie the simulation to reality (Plan 29):

* **Reconciliation**: compare a simulated year with the household's real documents
  (`life-model reconcile`).
* **Household goldens**: synthetic households whose returns were worked by hand from the IRS forms,
  which the engine must match line by line.
* **The invariant checker**: rules every simulated year must satisfy (`--checks`,
  `LifeModel(checks=)`).
* **Backtests**: run past years with the realized economy and score statement balances.

## Actual records (`actuals`)

A household spec may carry what its documents say, by tax year. Line and box numbers are the
official ones for that year (the 2025 Form 1040 renumbered several lines: `7` became `7a`, `11` became
`11a`/`11b`, `12` became `12e`, `13` became `13a`/`13b`; the 2026 draft adds `12f`, swaps `13a`/`13b`
and splits `24`):

```yaml
actuals:
  2025:
    form_1040: {"1a": 85400, "2b": 412, "9": 85812, "11a": 85812, "11b": 85812, "12e": 15750,
                "14": 15750, "15": 70062, "16": 10308, "24": 10308, "25a": 11200, "34": 892}
    schedules:
      "1": {"21": 1850, "26": 1850}
      A: {"5e": 12000, "17": 31000}
    w2:
      - {person: alex, employer: Example Analytics, boxes: {"1": 85400, "2": 11200, "3": 92000,
                                                             "5": 92000}, box12: {D: 6600}}
    form_1099:
      - {form: 1099-INT, person: alex, account: alex_savings, boxes: {"1": 412}}
    paystub:
      - {person: alex, gross_monthly: 7666.67, pretax_deductions_monthly: {401k: 550, health: 180}}
    balances: {alex_savings: 10412, alex_401k: 61250}     # December 31 statements, by account id
    spending: {living_annual: 31000}
```

A household that files several returns (married filing separately, several single adults) lists
them under `returns: [{filer: <person id>, form_1040: ..., schedules: ...}]`. The builder ignores
`actuals`; the validator checks every line name against that year's forms and every person and
account id. Real documents belong in `my-models/` (git-ignored): a separate actuals file works too
(`--actuals FILE`, holding `{2025: {...}}` or one year's records).

## `life-model reconcile`

```bash
life-model reconcile my-models/h.yaml --year 2025 [--actuals my-models/2025.yaml] [--json]
```

```python
report = life_model.reconcile("my-models/h.yaml", 2025)     # ReconciliationReport
print(report.to_markdown()); report.to_dict(); report.red
```

The household is run from `meta.start_year` through the year (describe it as of January 1 of that
year for the cleanest comparison), each `TaxReturn` is mapped onto that year's lines
(`life_model.reconciliation.form_1040_lines` / `schedule_lines`), W-2 boxes are rebuilt from the
ledger per employer, 1099 boxes from the account's flows, balances from the December 31 balance
sheet. Every line the records carry gets a status:

| Status | Meaning (default tolerance) |
|---|---|
| `green` | within $2 or 0.05% (whole-dollar rounding on a filed return); line 16 and the totals after it within $10 (the Tax Table taxes the midpoint of a $50 row; the engine computes the exact schedule); balances within $5 or 0.5% |
| `yellow` | within $100 or 2% |
| `red` | further off |
| `not_modeled` | the engine has no equivalent yet (withholding, the refund, payroll deductions, IRA basis) |

and anything not green gets a likely cause:

| Cause | Means | Fix |
|---|---|---|
| `missing_income_source` | the document shows income the spec lacks | add the account, job or income |
| `input_difference` | both have it, amounts differ | correct the spec input (salary, balance, rate) |
| `unmodeled_credit` / `unmodeled_deduction` | a credit or deduction the engine does not compute (EITC, dependent care, education, the 65+ standard deduction amount, ...) | none yet (Plan 31) |
| `unit_mismatch` | off by 12x or 100x | a monthly amount entered as annual, or a fraction as a percent |
| `timing` | withholding, estimated payments, the refund or balance due | none yet (taxes settle as a year-end lump; Plan 31 D3) |
| `missing_input` | needs a spec field the engine does not take yet | none yet (Plan 27: payroll deductions, basis) |
| `unmodeled_line` | a line with no engine equivalent | none |
| `propagated` | a total off only because a line it adds up is off | fix the line it names (`follows 1040 line 2b`) |
| `unexplained` | none of the above | investigate |

The tolerance table is `life_model.reconciliation.TOLERANCES` (override per call with
`tolerances=`). Calibration lines (`spending`) show the model's assumed amount next to the actual one
and name the setting that drives it (medical cost bands, child cost bands, Medicare).

## Household goldens

`src/life_model/tests/goldens/households/` holds six synthetic households for 2024, 2025 and 2026
(single renter with a student loan; married homeowners who itemize, with two children; head of
household; a retiree couple with RMDs, Social Security and Medicare; an early retiree harvesting
gains; married filing separately). Each return was worked line by line from the year's Form 1040 and
instructions by `scripts/household_goldens.py`, which does not use the library; each golden's
`worksheet.md` shows every line's arithmetic and its `expected.json` is an `actuals` record, so
`test_household_goldens.py` simply reconciles it. Lines the engine cannot produce yet are expected
failures naming the plan that adds them. See the
[goldens README](https://github.com/sw23/life-model/blob/main/src/life_model/tests/goldens/households/README.md)
for the format and how to add one.

## The invariant checker

`life_model.invariants` holds the rules every simulated year must satisfy. They read the year's
results (the balance sheets around the year and around each month, the cash-flow ledger, typed
events, tax returns), not engine internals, and run at each year end, after December's taxes:

| Invariant | Rule |
|---|---|
| `conservation` | Net worth changed by exactly the ledger's net external flow over the year (within $1). |
| `monthly_conservation` | The same for each month of the year (catches money that appears in one month and leaves in another). |
| `continuity` | Between two years and between two months (outside `step()`), net worth moved only by posted ledger entries. |
| `no_negative_balances` | At no month end an asset below zero or a liability below zero. |
| `no_draw_above_cash_floor` | No waterfall brokerage sale or pre-tax withdrawal in a month the tax unit ends with cash above its floor, not counting money that arrived after the month's last draw (the floor is $0 until Plan 27 adds one). The waterfall pays each month's bills, so a sale in a lean month is fine when later pay refills the bank. |
| `contribution_limits` | 402(g) deferrals (+ catch-up), 415(c) additions per plan, IRA and HSA contributions within the year's limits. |
| `no_income_after_job_end` | No wages, bonus or vests from an employer after the job ended. |
| `fica_wage_base` | Social Security tax = 6.2% of wages up to the wage base, per worker; no payroll tax without wages. |
| `rmd_minimum` | From the start age, each pre-tax IRA/401(k) pays out at least the prior year-end pre-tax balance over the Uniform Lifetime Table period. |
| `taxes_non_negative` | No tax line negative; federal tax negative only by refundable credits. |
| `deduction_choice` | Itemizers itemize at least the standard deduction; every return deducts the larger one (plus the senior deduction). |
| `return_identities` | The Form 1040 identities of each `TaxReturn`. |

Run them every year with `LifeModel(checks="strict" | "warn" | "off")` (library default `off`;
`strict` raises `InvariantError` at the end of the first bad year, `warn` emits `InvariantWarning`),
on a finished run with `life_model.invariants.check_model(model)`, or from the command line with
`--checks` (default `warn`). Violations are kept on `model.invariant_violations`.

The checker found one engine imprecision when it was introduced: the brokerage sale that funds a
year was sized against tax on gains a prior-year capital-loss carryforward was about to cancel, so
it over-sold (see [rebaseline-plan-29.md](rebaseline-plan-29.md)). The test suite runs every example
spec, the broad test scenarios, every RL scenario household (with random actions) and sampled adviser
households for 50 years under `strict`.

## Backtests

`life_model.backtest.backtest(spec)` runs a household from `meta.start_year` through the last year
with statement balances in `actuals`, feeding the realized economy as a `path`: the S&P 500 total
return as the equity return of each year, the CPI-U annual-average change as the escalator from each
year to the next, and the SSA average wage index change as the next year's raise
(`config/data/realized_economy.yaml`, each series stamped with its source). It scores every December
31 statement balance against the simulated one:

```python
from life_model.backtest import backtest
from life_model.spec import load

report = backtest(load("my-models/h.yaml"))
print(report.to_markdown(), report.max_relative_error(final_only=True))
```

To feed real statements: describe the household as of January 1 of the first year (the December 31
balances before it), give each account an `id`, put the later December 31 balances under
`actuals.<year>.balances`, and use `growth_pct: economy` for accounts invested like the index (a
fixed rate for the rest). The synthetic 2020-2025 example
([backtest-2020-2025.md](backtest-2020-2025.md), `scripts/backtest_example.py`) reproduces its
statements to the cent; with real statements expect differences from contribution timing (the annual
engine credits a year's contributions before its growth: about 2% on a growing 401(k) over six years),
fees and the actual fund mix.
