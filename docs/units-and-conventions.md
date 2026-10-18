# Units and conventions

How the engine measures time, money, rates and ages, and which flows happen every month versus once
a year (Plan 32).

## Time

The engine is **monthly**. `LifeModel.step()` simulates one calendar month; a year is a reporting
cadence:

| API | Meaning |
| --- | --- |
| `LifeModel(start_year=2026)` | Starts in January 2026 (`start_month=1`). |
| `LifeModel(start="2026-10")` / `start_month=10` | Starts in October: the first year has three months. |
| `end_year` | The last simulated year (its December is the last month). |
| `model.year`, `model.month` | The month being simulated during a step; between steps, the next month to simulate. |
| `model.period` | Months simulated so far (0-based index of the current month). |
| `model.is_year_start` / `model.is_year_end` | First simulated month of the year / December. |
| `model.months_in_year(year)` | 12, or fewer for a part-year first year. |
| `model.step()` | One month. |
| `model.step_year()` | The rest of the current year, through its year end. |
| `model.run()` | Every remaining month; returns a `RunResult`. |

Each month runs the stages `pre_step` → `events` → `step` → `post_step` over every agent (by
`STEP_PRIORITY`, then construction order). The first month of each year starts with
`on_year_start`; December ends with `on_year_end` (the year's tax settlement, escalators and
resets), then every agent's `collect_stats` and the year's data collection. With
`LifeModel(collect="month")` a model-level row is also kept at every month end
(`model.monthly_frame()`).

Life events fire in their month: `LifeEvent(year, name, fn, month=7)`; without `month`, in the first
simulated month of the year (January). In a household spec, `at: {year: 2030, month: 7}` or
`at: "2030-07"`; an `at: {age: 65}` event fires in the month the person turns 65.

## Money and rates

* Money is nominal dollars unless a result is converted with `real_dollars()` (start-year dollars).
* Rates are **percent**. Annual rates (`growth_rate=7`, `interest_rate=5`, `economy.equity_return`)
  are annual; the engine applies them monthly. An annual return `R` becomes the monthly rate
  `(1 + R)^(1/12) - 1`, so twelve months compound back to `R`; a bank APR compounded monthly
  accrues `APR / 12` a month (`compounding="annual"`: the monthly equivalent of the APY).
* `EconomyModel.rate(name, year)` is a year's rate (the compound of its months);
  `EconomyModel.monthly_rate(name, year, month)` a month's (percent for the month). Path tables
  take `"YYYY-MM"` keys for single months; stochastic mode draws each month (`vol / sqrt(12)`, an
  optional AR(1) term per series in `economy.stochastic.autocorrelation`).
* Annual amounts (a salary's `base`, `Spending(base=)`, a pension's `benefit_amount`) are paid a
  twelfth a month.

## Ages

A person has a birth month: `Person(birth="1966-07")`, or `Person(age=40)` with the birth month
taken to be January of the year that makes them 40 now (the validator warns about the assumption
in a spec).

| API | Meaning |
| --- | --- |
| `person.age` | Completed years in the model's current month (frozen at death). |
| `person.age_years_fractional` | Exact age (`59.5` six months after the 59th birthday): thresholds compare it. |
| `person.age_in(year)` | The age reached during `year` (the IRS's "by the end of the year" age). |
| `person.get_year_at_age(age)` | The year the person turns `age`. |
| `person.get_period_at_age(age)` | `(year, month)` the exact age is first reached. |

Exact-age thresholds: the 59.5 early-withdrawal age (pre-tax accounts, Roth earnings), the HSA's 65,
`retirement_age` (a job stops after the paycheck of the month it is reached), Social Security's claim
month, Medicare at 65, annuity payout start, pension start. By the end-of-year age: RMD start, the
401(k) and HSA catch-ups, the senior deduction.

## Monthly versus annual

| Subsystem | Every month | Once a year |
| --- | --- | --- |
| Jobs | A twelfth of base salary (the bonus in `Salary(bonus_month=)`, default March); 401k deferral per paycheck against the year's 402(g) room; the match per paycheck, capped by 415(c) | December match true-up (`Job401kAccount(match_true_up=True)`); the raise at year end |
| Spending | A twelfth of base; one-time expenses in the month they are added | The base escalates at year end |
| Housing | A twelfth of property tax, insurance, upkeep, HOA and PMI; one mortgage payment; rent | Home appreciation and the expense and rent escalators at year end |
| Loans and cards | One payment each (amortization one period per month) | Deferment interest capitalizes at year end; a RAP payment is set from the last return's AGI |
| Investments | Growth at the month's rate (401k, IRAs, HSA, brokerage, 529, trusts, annuities) | A DAF's growth, fee and grant at year end; the HSA employer contribution at year start |
| Brokerage dividends | Quarterly (March, June, September, December), or monthly (`accounts.brokerage.dividend_frequency`) | |
| Bank interest | Monthly | |
| Social Security, pensions, annuities | One payment a month (from the claim or eligibility month) | Pension COLA and service credit at year end; Social Security's PIA (with COLAs) is set once a year |
| RMDs | A twelfth of the year's RMD | The amount is set at year start from the prior year-end balance |
| Inherited IRAs (10-year rule) | Growth | The year's even-spread distribution at year start |
| Healthcare | Medical costs, Medicare premiums (from 65), long-term-care costs while in care | LTC: the episode hazard is drawn at year start, the insurance claim filed at year end |
| Children | A twelfth of the age band's yearly cost (529 draws for college) | |
| Insurance premiums, donations, stock vests | | In the first month of the year; policy updates (term expiry, re-pricing, cash value) at year end |
| Bills | Paid through the household waterfall each month; unpaid bills carried as debt with a month of interest | |
| Taxes | | Settled in December from the year's income ledger (the sized waterfall) |
| Mortality | Monthly hazard `1 - (1 - q)^(1/12)` (fixed-age deaths in the birth month); a death in month m stops pay from m+1 | |
| Data | Ledger entries carry their month; month-end balance sheets (the monthly conservation check); monthly rows with `collect="month"` | Model and agent frames at each year end; tax returns |
