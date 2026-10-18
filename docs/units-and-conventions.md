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

The engine steps one **year** at a time. Monthly quantities (rent, premiums, loan payments) are
billed as twelve months within the year; loans amortize monthly.

## Interest: APR vs APY

- **Loans** (`rate_pct` on mortgages, car and student loans, credit cards): an APR. The monthly rate
  is `APR / 12` and the payment is the standard fully amortizing payment over `term_years * 12`
  months; credit-card interest accrues on the carried balance.
- **Bank accounts** (`interest_pct`): an APR compounded per `compounding` (default monthly, from
  `accounts.bank.compound_rate`). If the statement shows an APY, enter it with
  `compounding: annual`.
- **Investment growth** (`growth_pct` on brokerage, IRAs, 401k, HSA, 529, trusts; the economy's
  returns): an effective annual rate applied once a year (`balance * rate / 100`).

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

- `age` is the person's age **during the first simulated year**; they are `age + 1` the year after.
  An event `at: {age: A}` fires in `start_year + (A - age)`.
- `retirement_age` may be fractional (`59.5`); every job stops then. Social Security claiming
  (`claim_age`, 62-70) defaults to the retirement age.
- Years are inclusive: a run covers `start_year` through `end_year`, `end_year - start_year + 1`
  steps. Output rows describe the year's flows and its year-end balances.
- Money is never negative in a spec: a debt is a positive `balance`. In outputs, `Debt` and
  `Mortgage Principal` are positive amounts owed and `Net Worth` is assets minus liabilities.

## Filing and residence

Everyone files single until married; a marriage in `relationships.marriages` (or a `marry` event)
creates a married-filing-jointly unit (or separately, with `filing_status: separate`) headed by the
first spouse listed, and the unit files in the head's state. A state needs a state tax pack (`CA`,
`NY`, `TX`, ...): an unknown code is a spec error, because the core would silently tax it at the
flat default rate.
