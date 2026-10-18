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

The household is run from its first simulated month through the year's December (describe it as of
January 1 of that year for the cleanest comparison; a spec whose `meta.start` falls inside the year
reconciles a part year: its return and flows cover only the simulated months, and the report's notes
say so), each `TaxReturn` is mapped onto that year's lines
(`life_model.reconciliation.form_1040_lines` / `schedule_lines`), W-2 boxes are rebuilt from the
ledger per employer, 1099 boxes from the account's flows, balances from the December 31 balance
sheet. Every line the records carry gets a status:

| Status | Meaning (default tolerance) |
|---|---|
| `green` | within $2 or 0.05% (whole-dollar rounding on a filed return); line 16 and the totals after it within $10 (the Tax Table taxes the midpoint of a $50 row; the engine computes the exact schedule); balances within $5 or 0.5% |
| `yellow` | within $100 or 2% |
| `red` | further off |
| `not_modeled` | the engine has no equivalent yet (or, without `payroll.withholding`, withholding and the refund) |

and anything not green gets a likely cause:

| Cause | Means | Fix |
|---|---|---|
| `missing_income_source` | the document shows income the spec lacks | add the account, job or income |
| `input_difference` | both have it, amounts differ | correct the spec input (salary, balance, rate) |
| `unmodeled_credit` / `unmodeled_deduction` | a credit or deduction the engine does not compute (foreign tax credit, energy credits, ...) or computes from an input the spec lacks (care or college costs, a child's income, marketplace coverage) | add the input (`children[].care_expenses_annual`, `payroll.dependent_care_fsa_annual`, `insurance[].marketplace`, ...); otherwise none yet |
| `unit_mismatch` | off by 12x or 100x | a monthly amount entered as annual, or a fraction as a percent |
| `timing` | withholding, estimated payments, the refund or balance due of a household that settles as a December lump | set `payroll.withholding` (`w4_default`, or the W-4's entries) and `estimated_payments` (the validator suggests it when the W-2s show box 2) |
| `missing_input` | needs a spec field the engine does not take yet | none yet (a 1099-B's per-sale basis, the 1098 lines) |
| `unmodeled_line` | a line with no engine equivalent | none |
| `propagated` | a total off only because a line it adds up is off | fix the line it names (`follows 1040 line 2b`) |
| `unexplained` | none of the above | investigate |

The tolerance table is `life_model.reconciliation.TOLERANCES` (override per call with
`tolerances=`). Calibration lines (`spending`) show the model's assumed amount next to the actual one
and name the setting that drives it (medical cost bands, child cost bands, Medicare).

### What the engine computes (line coverage)

Every `TaxReturn` field maps onto the year's lines; since Plan 31 each credit has its own line:

| Item | Lines |
|---|---|
| Wages, interest, dividends, IRA / pension / Social Security, capital gains | 1040 lines 1a-7a; Schedules B and D |
| Taxable dependent care benefits (FSA over the exclusion) | 1040 line 1e; Form 2441 line 26; W-2 box 10 |
| Schedule C profit, self-employment tax and its deductible half | Schedule 1 lines 3, 15; Schedule C line 31; Schedule SE lines 2-13; Schedule 2 line 4 (and the Additional Medicare Tax on SE income, Form 8959 Part II) |
| SEP / solo 401(k) deduction | Schedule 1 line 16 |
| Form 8814 (child's interest and dividends) | 1040 line 3a share, Schedule 1 line 8z, the 10% tax in line 16 (Form 8814 line 15) |
| Adjustments (HSA, IRA after the phase-out, student loan interest after the phase-out) | Schedule 1 lines 13, 20, 21, 26 |
| Standard deduction with the §63(f) amount for 65+, or itemized after the 2026 floor and §68 | 1040 line 12 / 12e; Schedule A lines 4-17 (cash line 11, appreciated property line 12) |
| Non-itemizer charitable deduction (2026) | 1040 line 12f |
| Senior deduction | Schedule 1-A lines 37-38 (2025) / 43-44 (2026); 1040 line 13b / 13a |
| Qualified business income deduction | Form 8995 lines 1, 15; 1040 line 13 / 13a / 13b |
| AMT (ISO bargain element, SALT or standard deduction add-back, Part III gains) | Form 6251 lines 4, 9, 11; Schedule 2 lines 2-3; 1040 line 17 |
| Child tax credit and credit for other dependents; additional child tax credit | 1040 lines 19, 28; Schedule 8812 lines 14, 27 |
| Dependent care, education (nonrefundable part), saver's, prior-year minimum tax credits | Schedule 3 lines 2, 3, 4, 6b (7, 8); 1040 line 20; Forms 2441 line 11, 8863 line 19, 8880 line 12 |
| Earned income credit; refundable American opportunity credit | 1040 line 27 (27a); line 29, Form 8863 line 8 |
| NIIT, Additional Medicare Tax, early-distribution and HSA additional taxes | Schedule 2; 1040 line 23 |
| Withholding (with `payroll.withholding`) | W-2 boxes 2, 4, 6, 17 (per employer); 1040 lines 25a, 25c, 25d; Schedule 3 line 11 (excess Social Security from several employers); the paystub's federal withholding |
| Estimated payments, the refund or balance due, the penalty | 1040 lines 26, 33, 34, 35a, 37, 38; Form 2210 lines 4, 6, 9, 19 |
| ACA premium tax credit | Form 8962 lines 3, 5, 7, 8a, 11a-11f, 24-29; Schedule 3 lines 9, 15; 1040 lines 31, 32; Schedule 2 lines 1a, 1z, 3 (excess advance credit repaid) |
| State return | state AGI, taxable income, tax, withheld (a part-year return compares the share of the record's state) |

Not modeled yet: the foreign tax credit, Form 1099 withholding (box 4). Form 8606 basis is recovered pro rata on distributions and
Roth conversions (Plan 27: 8606 lines 2 and 14, 1099-R box 2a); Treasury coupons are 1099-INT box 3.

## Household goldens

`src/life_model/tests/goldens/households/` holds synthetic households for 2024, 2025 and 2026: the six
of Plan 29 (single renter with a student loan; married homeowners who itemize, with two children; head
of household; a retiree couple with RMDs, Social Security, the §63(f) amount and Medicare; an early
retiree harvesting gains; married filing separately), five of Plan 31's tasks 6-7 for 2024-2026
(withholding with the April refund or balance due; estimated payments with a Form 2210 penalty; the
ACA premium tax credit with advance payments and the repayment limit; a qualifying surviving spouse; head
of household with a dependent parent), twelve for 2025-2026 (a California-to-Texas part-year mover's
Form 540NR; one W-2 state return per new state pack) and twelve of Plan 31's tasks 1-5 (the earned income and
additional child tax credits; dependent care with an FSA; the American opportunity credit with a 529;
the saver's credit and the 2026 non-itemizer deduction; an ISO exercise with AMT, and the next year's
minimum tax credit; a self-employed filer with SE tax, a SEP and the QBI deduction; the kiddie tax
on Form 8814; a gift of appreciated shares with the 30% limit, the 2026 floor and §68; a qualified
charitable distribution; the IRA deduction and student loan interest phase-outs). Each return was
worked line by line from the year's Form 1040 and
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
| `no_draw_above_cash_floor` | No waterfall brokerage sale or pre-tax withdrawal in a month the tax unit ends with cash above its floor, not counting money that arrived after the month's last draw (a year-end insurance payout, a refund) (the floor is $0: the waterfall spends all bank cash, and `SavingsPolicy.cash_floor` only limits the yearly sweep). The waterfall pays each month's bills, so a sale in a lean month is fine when later pay refills the bank. |
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
statements to the cent (they are computed with the engine's conventions: monthly paycheck deposits at
the start of the month, monthly compounding of the year's return); with real statements expect
differences from intra-month contribution timing (about 0.3% on a growing 401(k) over six years
between start- and end-of-month deposits), fees and the actual fund mix.
