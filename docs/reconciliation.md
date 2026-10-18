# Checking the model: invariants, reconciliation and backtests

## The invariant checker

`life_model.invariants` holds the rules every simulated year must satisfy. They read the year's
results (balance sheets, the cash-flow ledger, typed events, tax returns), not engine internals:

| Invariant | Rule |
|---|---|
| `conservation` | Net worth changed by exactly the ledger's net external flow (within $1). |
| `continuity` | Between two years (outside `step()`), net worth moved only by posted ledger entries. |
| `no_negative_balances` | No asset below zero, no liability below zero. |
| `no_draw_above_cash_floor` | No waterfall brokerage sale or pre-tax withdrawal while the tax unit ends the year with cash above its floor (the floor is $0 until Plan 27 adds one). |
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
