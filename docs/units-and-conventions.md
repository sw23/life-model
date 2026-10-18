# Units and conventions

How numbers mean what they mean, in the [household spec](household-spec.md), the core constructors
and the outputs. When a statement gives a number in another form, convert it before it goes into
a spec, and say so when you present the assumptions.

## Rates: percent, not fraction

| Where | Convention | Example |
|---|---|---|
| Spec fields ending `_pct` | Percent | `rate_pct: 6.5` is 6.5% |
| Core constructor rates (`interest_rate`, `growth_rate`, `yearly_increase`, `yearly_interest_rate`, `*_percent`) | Percent | `BankAccount(..., interest_rate=0.5)` is 0.5% |
| Config YAML rates (`economy.equity_return`, `tax.state.tax_rate`, ...) | Percent | `equity_return: 7.0` |
| Output rate columns (`Marginal Rate`) and `TaxReturn.marginal_rate` / `effective_rate` | Percent | `22.0` |
| Stock vesting schedules in the spec (`vesting_schedule_pct`) | Percent per year (the builder divides by 100 for the core `VestingSchedule`, which takes fractions) | `[25, 25, 25, 25]` |
| The `slm` adviser's `HouseholdProfile` (`employer_match_rate`, `retirement_spending_ratio`) | **Fractions** | `0.5` is 50% |

The spec validator warns ("did you mean 4.5?") when a field whose real-world values are normally
above 1 (growth, contribution and interest rates) gets a value between 0 and 1. A genuinely small
rate (a 0.5% savings account) is fine: those fields are not flagged.

## Periods: annual vs monthly

Every spec flow names its period: `*_annual` (per year) or `*_monthly` (per month), for example
`salary_annual`, `amount_annual`, `rent_monthly`, `premium_monthly`, `hoa_monthly`,
`premium_annual`. Balances, prices, face values and one-time amounts (`balance`, `purchase_price`,
`death_benefit`, `amount` on a one-time expense) are plain dollars.

The core constructors mix periods, which is one reason to prefer the spec:
`Apartment(monthly_rent=)`, `LifeInsurance(monthly_premium=)` and `Mortgage` payments are monthly;
`Salary(base=)`, `Spending(base=)`, `Insurance(annual_premium=)` and `HomeExpenses(hoa_amount=,
maintenance_amount=)` are annual (the builder multiplies `hoa_monthly` by 12).

The engine steps one **month** at a time (see [Time](#time) below): annual amounts are paid a
twelfth a month, monthly ones (rent, loan payments) once a month, and loans amortize one period per
month.

## Interest: APR vs APY

- **Loans** (`rate_pct` on mortgages, car and student loans, credit cards): an APR. The monthly rate
  is `APR / 12` and the payment is the standard fully amortizing payment over `term_years * 12`
  months; credit-card interest accrues on the carried balance.
- **Bank accounts** (`interest_pct`): an APR compounded per `compounding` (default monthly, from
  `accounts.bank.compound_rate`). If the statement shows an APY, enter it with
  `compounding: annual`.
- **Investment growth** (`growth_pct` on brokerage, IRAs, 401k, HSA, 529, trusts; the economy's
  returns): an effective annual rate (APY), applied monthly as `(1 + rate)^(1/12) - 1`, so twelve
  months compound to the annual rate and money grows from the month it arrives.

## Dollars: nominal vs real

Inputs are **nominal dollars at the as-of date** (`meta.as_of`): what the statements say. Growth
rates are nominal (a 3% raise in a 3% inflation economy is a 0% real raise). Every output is in
**nominal dollars of the year it describes**. To compare years, convert with
`RunResult.real_dollars()` (or `life-model run --real-dollars`): every money amount divided by the
economy's cumulative inflation since the start year (`RunResult.deflators`, 1.0 in the start year).
Rates, years and identifiers are unchanged. A few config tables are stated in real start-year
dollars and inflated by the engine (the medical cost curve, long-term-care costs, child costs).

## Growth: a number, `"economy"` or `None`

| Value | Spec | Core |
|---|---|---|
| A number | That percent every year | Same (the explicit argument overrides the economy) |
| `"economy"` | Follow the simulation economy: inflation for spending, rent and costs; wage growth for salaries; the asset class return for accounts (equity 7%, bonds 3%, cash 0% in the fixed economy); home appreciation (4%) for homes | (spec only) |
| `None` | (spec: field not given; see each field's default) | Follow the economy, re-read every year, so path and stochastic economies flow through |
| `0` | No growth | No growth; this is the **core default** for `Spending` and `Salary` |

Defaults differ between the spec and the core: the spec's spending `growth_pct` defaults to `0`
(and the validator warns), its account growth to `"economy"`, its rent growth to `5`. See
[constructor-cheatsheet.md](constructor-cheatsheet.md) for every silent default.

## What `None` means elsewhere

- **Optional spec fields** (`end_year`, `seed`, `scenario`, `state`, `social_security`,
  `healthcare`, ...): not given. The field's description says what happens (for example
  `end_year` defaults to `start_year + 50`; `state` falls back to `meta.default_state`; no
  `social_security` block means no Social Security benefit).
- **Core rate arguments**: follow the economy (above) or a config default (a credit card's
  `yearly_interest_rate=None` is `debt.credit_card.default_interest_rate`, 18%).
- **Loans in progress**: `principal=None` means a brand-new loan (balance = original amount);
  `monthly_payment=None` means the computed amortizing payment. The spec's `balance` is the
  current principal.
- **`seed=None`**: draw a fresh seed (reported as `RunResult.seed`); deterministic households give
  the same numbers either way.

## Ages, years and signs

- `age` is the person's age (completed years) **in the first simulated month**; with `birth` the
  ages are exact, without it the birth month is taken to be January (the person is `age` for the
  rest of the first year, `age + 1` the year after). An event `at: {age: A}` fires in the month the
  person turns `A` (see [Ages](#ages) below).
- `retirement_age` may be fractional (`59.5`); every job stops after the paycheck of the month it is
  reached. Social Security claiming (`claim_age`, 62-70) defaults to the retirement age.
- Years are inclusive: a run covers `start_year` (from `meta.start`'s month, default January)
  through `end_year`'s December, `end_year - start_year + 1` reporting years. Output rows describe
  the year's flows and its year-end balances.
- Money is never negative in a spec: a debt is a positive `balance`. In outputs, `Debt` and
  `Mortgage Principal` are positive amounts owed and `Net Worth` is assets minus liabilities.

## Filing and residence

Everyone files single until married; a marriage in `relationships.marriages` (or a `marry` event)
creates a married-filing-jointly unit (or separately, with `filing_status: separate`) headed by the
first spouse listed, and the unit files in the head's state. A state needs a state tax pack (`CA`,
`NY`, `TX`, ...): an unknown code is a spec error, because the core would silently tax it at the
flat default rate.

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
| Invariant checks (`checks=`) | Read: monthly conservation, between-month continuity, month-end balances, the cash floor at the month of each waterfall draw | Run at each year end, after December's taxes (`life_model.invariants`) |
