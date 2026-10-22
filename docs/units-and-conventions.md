# Units and conventions

How numbers mean what they mean, in the [household spec](household-spec.md), the core constructors
and the outputs. When a statement gives a number in another form, convert it before it goes into
a spec, and say so when you present the assumptions.

## Rates: percent, not fraction

| Where | Convention | Example |
|---|---|---|
| Spec fields ending `_pct` | Percent | `rate_pct: 6.5` is 6.5% |
| Core constructor rates (`interest_pct`, `growth_pct`, `raise_pct`, `rate_pct`, `*_pct`; the deprecated `interest_rate`, `growth_rate`, `yearly_increase`, `*_percent`) | Percent | `BankAccount(owner, interest_pct=0.5)` is 0.5% |
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

The core constructors for housing, debts, insurance, Social Security and spending use the spec's
names too: `Apartment(rent_monthly=)`, `LifeInsurance(premium_monthly=)` and the loans'
`payment_monthly=` are monthly; `Spending(base_annual=)`, `Insurance(premium_annual=)` and
`HomeExpenses(hoa_annual=, maintenance_annual=)` are annual (the spec's `hoa_monthly` is multiplied by
12). The deprecated names (`monthly_rent`, `monthly_premium`, `base`, `annual_premium`, `hoa_amount`,
...) and positional arguments after the owner of a loan, annuity or pension are accepted for one release
with a `DeprecationWarning` naming the replacement. `Salary(base_annual=)` is annual.

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

The money-conservation check is a statement about nominal money (a year's change in net worth
equals its ledger flows), so it is always checked in nominal dollars, also for a real-dollar result:
in start-year dollars inflation erodes the opening balance without any ledger flow.
`RunResult.conservation()` returns nominal records either way, and `conservation_failures` is the
same list with and without `--real-dollars`.

## Spending is per person and adds up

`people[].spending.amount_annual` is that person's living spending; the household spends the sum
over everyone. Put the whole household budget on one spouse (and leave the other spouse's
`spending` out) or split it, never the full budget on each. Spending excludes what the model adds
itself: housing, debt payments, taxes, payroll deductions, insurance premiums, healthcare agents,
events and **children's cost bands** (see the Child cost bands table in
[household-spec.md](household-spec.md)): when the budget already includes a child, set the child's
`cost_override_annual: 0`.

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
  `rate_pct=None` is `debt.credit_card.default_interest_rate`, 18%).
- **Loans in progress**: enter what the statement shows. `origination="YYYY-MM"` (or
  `payments_made`) with the original amount and term gives today's balance and payment; or give
  `current_balance` (spec: `balance`) with `remaining_months` (or the payment). Any three of balance /
  months remaining / payment determine the fourth; inputs that contradict each other raise
  `LoanTermsError` (a spec validation error) naming the field. The first payment is in the month after
  origination (a loan originated 2024-03 has made 21 payments by January 2026). A balance below the
  original schedule is a prepaid loan: it keeps the contract payment and pays off early. Without any of
  these, `current_balance=None` means a brand-new loan and `payment_monthly=None` the computed
  amortizing payment. Terms are in months (`term_months`; `term_years` is sugar). A mortgage's
  `escrow_monthly` is subtracted from a statement payment that includes it (the home's expenses pay the
  tax and insurance). A balance **above** the original schedule (late payments, a deferral) is an error
  under the default `schedule: contract`; when the statement is right, `schedule: statement` trusts
  the balance and amortizes it at `payment_monthly`, else over `remaining_months`, else at the
  contract payment of the original amount and term (paying off after the original maturity). The
  error's Fix names the field combinations that validate.
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
first spouse listed, and the unit files in the head's state. An unmarried person files head of
household with a dependent child (under 19, or a student under 24) or a qualifying relative
(`dependents[]`: a parent wherever they live, another relative living with them), and as a qualifying
surviving spouse for the two years after a spouse's death (`widowed_year`, or a death in the run)
while a dependent child lives with them.

A state needs a state tax pack (`CA`, `NY`, `GA`, ...; `DEFAULT` is the flat rate, chosen
deliberately): an unknown code is an error in the spec and in the core (`UnknownStateError`). The
state follows a residency timeline (`residency: [[YYYY-MM, state], ...]`; a `move` event adds an
entry): a year with a move files part-year returns, wages allocated by the months worked in each
state and other income by residence when received.

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
* Annual amounts (a salary's `base`, `Spending(base_annual=)`, a pension's `benefit_annual`) are paid a
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
401(k) and HSA catch-ups, the senior deduction, the §63(f) additional standard deduction (65 by December
31), the earned income credit's 25-64 test, the saver's credit's 18, the long-term care premium age band and
children's ages for the credits. The qualified charitable distribution's 70½ is exact (at the distribution).

## Monthly versus annual

| Subsystem | Every month | Once a year |
| --- | --- | --- |
| Jobs | A twelfth of base salary (the bonus in `Salary(bonus_month=)`, default March); 401k deferral per paycheck against the year's 402(g) room; the match per paycheck, capped by 415(c) | December match true-up (`Job401kAccount(match_true_up=True)`); the raise at year end |
| Self-employment (`Job(kind="self_employed")`) | A twelfth of the net profit (receipts less expenses; the bonus month adds its bonus), no withholding | The owner's SEP / solo 401(k) contribution with December's payment, on the year's profit; self-employment tax and QBI with the year's return |
| Dependent-care FSA (`payroll.dependent_care_fsa_annual`) | A twelfth of the election out of each paycheck (wages and FICA wages) | The Form 2441 exclusion and any taxable excess at settlement |
| Other payroll deductions (`PayrollDeductions`) | Health / dental-vision premiums and commuter benefits (monthly amounts), a twelfth of the health FSA and of employee / employer HSA money: out of wages and FICA wages; premiums and HSA money out of take-home pay | |
| Jobs with `start_year` / `end_year` | Paid only from the start month through the end month; the job retires the month after | |
| ESPP (`StockPlan(espp=)`) | Pay set aside each month | The purchase (and its discount income) in each purchase month (June, December) |
| Contribution plans (`person.add_contribution_plan`) | Bank-sourced: after the month's bills, never more than the bank holds (December: less the year's estimated tax); payroll-sourced: with the paycheck | A 401(k) "max" / dollar plan's percent re-derived at the year start |
| Savings sweep (`person.savings_policy`) | | Cash above the floor invested after the year's taxes |
| Roth conversions (`person.roth_conversion_policy`, `convert_to_roth` events) | A dollar event in its month | A standing or `fill_bracket_pct` conversion in December, before the year's taxes |
| Fixed income (`FixedIncomeHolding`) | CD interest credited, Treasury coupons and bond-fund distributions paid, I bond interest accrued (tax deferred); maturity in its month | An I bond's rate resets every six months from its issue month |
| Spending | A twelfth of base and of each annual category (monthly categories in full); one-time expenses in the month they are added; a schedule step in the month the age is reached; part of it charged to a card with `spending_charge_pct` | The base and categories escalate at year end |
| Housing | A twelfth of property tax (a percent of the market or assessed value, or a dollar bill), insurance, upkeep, HOA and PMI (until 80% of the original value by balance, 78% by the original schedule, or the term's midpoint); one mortgage payment; rent | Home appreciation, the assessed value (capped), and the expense and rent escalators at year end |
| Loans and cards | One payment each (amortization one period per month) plus any `extra_principal_monthly`; a home equity line's interest-only payment | Deferment interest capitalizes at year end (and repayment starts after `deferment_until`); a RAP payment is set from the last return's AGI |
| Investments | Growth at the month's rate (401k, IRAs, HSA, brokerage, 529, trusts, annuities), an allocation's blend drifting with the classes' returns, net of the expense ratio | Allocations rebalance at year end; a DAF's growth, fee and grant; the legacy yearly HSA employer contribution at year start (while employed) |
| Brokerage dividends | Quarterly (March, June, September, December), or monthly (`accounts.brokerage.dividend_frequency`) | |
| Bank interest | Monthly | |
| Social Security, pensions, annuities | One payment a month (from the claim or eligibility month; a spousal benefit once both spouses claim; earnings-test withholding takes whole checks); a pension's lump sum in its start month | Pension COLA and service credit at year end; Social Security's PIA (with COLAs) is set once a year (and again at FRA after withheld months); the earnings test at year end |
| RMDs | A twelfth of the year's RMD | The amount is set at year start from the prior year-end balance, less any qualified charitable distribution made then (owner 70½ by exact age) |
| Inherited IRAs (10-year rule) | Growth | The year's even-spread distribution at year start |
| Healthcare | Medical costs (capped by a health policy's deductible, coinsurance and out-of-pocket maximum over the calendar year), Medicare premiums (from 65), long-term-care costs while in care; disability benefits after the elimination period | LTC: the episode hazard is drawn at year start, the insurance claim filed at year end |
| Children | A twelfth of the age band's yearly cost and of `care_expenses_annual` (529 draws for college, keeping the year's first $4,000 for the AOTC) | The child's `interest_annual` / `dividends_annual` on the parents' return (Form 8814) |
| Insurance premiums, donations (cash, appreciated shares in kind), stock vests and option exercises | | In the first month of the year; policy updates (term expiry, re-pricing, cash value) at year end |
| Bills | Paid through the household waterfall each month; unpaid bills carried as debt with a month of interest | |
| Taxes | With `payroll.withholding`: federal (Pub. 15-T), Social Security, Medicare and state tax withheld from each paycheck; estimated tax installments in April, June, September and January (`estimated_payments`); last year's balance due paid (or refund received) in April | Settled in December from the year's income ledger: by default the whole year as a lump through the sized waterfall; with withholding or estimates the return is figured and the balance due (or refund) accrued as a liability (or receivable), with the Form 2210 penalty |
| RSU vests (with withholding) | | Supplemental federal rate (22%, 37% past $1,000,000), FICA and state tax withheld by selling shares to cover them |
| Marketplace health coverage (`marketplace`) | A twelfth of the premium, net of any advance premium tax credit, while covered | The premium tax credit on the return (Form 8962) |
| Contribution plans (bank-sourced), tax hold-back | Each month holds back the balance due on last year's return and the month's share of the year's projected tax not yet withheld or paid | |
| Mortality | Monthly hazard `1 - (1 - q)^(1/12)` (fixed-age deaths in the birth month); a death in month m stops pay from m+1 | |
| Data | Ledger entries carry their month; month-end balance sheets (the monthly conservation check); monthly rows with `collect="month"` | Model and agent frames at each year end; tax returns |
| Invariant checks (`checks=`) | Read: monthly conservation, between-month continuity, month-end balances, the cash floor at the month of each waterfall draw | Run at each year end, after December's taxes (`life_model.invariants`) |
