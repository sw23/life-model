# Modeling a household

This walkthrough takes a household from statements to a validated spec, a run, an explanation of
any year and a comparison of a decision. It uses only the `life-model` command line (see
[cli.md](cli.md)); the same steps work from Python with `life_model.run/validate/explain/compare`.
The example is the synthetic `married_homeowners` household that ships with the package.

## Where files go

Real household data never goes into the repository. Work in `my-models/`, which git ignores:

```bash
mkdir -p my-models
life-model examples --copy married_homeowners my-models/household.yaml
```

Refer to household files by path in notes, issues, commit messages and prompts; don't paste names,
employers or balances. The command line refuses to write outputs inside `src/`, and the repository's
example specs and test fixtures use only synthetic names (a test enforces an allowlist).

## 1. From statements to a spec

A spec is YAML (or JSON) with `meta`, optional `economy`, `people` (each with spending, jobs,
accounts, debts, housing, insurance, Social Security, healthcare, giving and children),
`relationships` and dated `events`. Every field is in [household-spec.md](household-spec.md); the
units are in [units-and-conventions.md](units-and-conventions.md).

| Statement | Spec |
|---|---|
| Statement date | `meta.as_of: 2026-01`; `meta.start_year` is the first simulated year |
| Ages, state, retirement plans | `people[].age` (age during `start_year`), `state` (a packed state, or `DEFAULT` deliberately), a planned move as `residency: [[YYYY-MM, state]]`, `retirement_age`, `gender`, `mortality`; `widowed_year` for a spouse who died recently |
| Pay stub / offer letter | `jobs[]`: `company`, `salary_annual`, `bonus_pct`, `raise_pct`; `payroll.withholding` (`w4_default`, or the W-4's entries) when taxes are withheld |
| Estimated tax vouchers (1040-ES) | `estimated_payments` (`quarterly` amounts, or `policy: safe_harbor` with last year's tax) |
| Form 1095-A (marketplace coverage) | `insurance[]` `kind: health` with `marketplace: {slcsp_monthly, advance_monthly}` |
| A supported parent or other relative | `dependents[]` (`relationship`, `gross_income_annual`, `lives_with`) |
| Budget or bank history | `spending.amount_annual` (living costs, excluding housing, debt payments, taxes and the costs the model adds itself, such as children's cost bands), `growth_pct`; optional `categories` (`amount_annual` or `amount_monthly`, `essential`, `start_year`/`end_year`) and an age `schedule` (a retirement spending smile). **Spending is per person and adds up across the household**: give the whole budget on one spouse (leave the other's `spending` out) or split it |
| Bank statements | `accounts[]` `kind: bank`: `balance`, `interest_pct` (APR; `compounding: annual` for an APY), one `primary: true`; a joint account once, under either spouse, with `joint: true` (the other spouse then needs no bank account); an emergency fund as its own `reserve: true` account |
| 401k statement | `kind: 401k`, `job:` (the job's `id`), `pretax_balance`, `roth_balance`, `pretax_contrib_pct`, `roth_contrib_pct`, `match_tiers` |
| Brokerage statement | `kind: brokerage` with `lots` (`value`, `cost_basis`, `acquired_year`) or a single `balance`; `joint: true` for a joint account |
| Recurring contributions (a 529 from checking, an IRA) | `contribution_plans[]`: `account`, `amount_annual` / `pay_pct` / `max_out`, `start`, `end` or `until_age` (a 529 for a child stops the month before college unless `end` says otherwise); `stop_contribution` / `change_contribution` events |
| IRA / HSA / 529 statements | `kind: traditional_ira`, `roth_ira`, `hsa`, `529` |
| Mortgage statement | `housing[]` `kind: home`: `purchase_price`, `current_value`, `cost_basis`, `purchase_year`, `mortgage` (`original_amount`, `rate_pct`, `term_years`, and `origination: YYYY-MM`, or the current `balance` with `remaining_months`; `payment_monthly` with `escrow_monthly` when the statement payment includes escrow, and `rate_compounding: semiannual` if the quoted annual rate compounds twice a year), `pmi`/`pmi_monthly`, `expenses` (property tax as `property_tax_annual` or % of an `assessed_value`, `insurance_annual`, maintenance, HOA) |
| Lease | `kind: rental`: `rent_monthly`, `rent_growth_pct` |
| Loan statements | `debts[]` `kind: car`, `student`, `credit_card`, `heloc`: `rate_pct` (APR), then the statement's terms (`original_amount` with `term_months`/`term_years` and `origination`, or the current `balance` with `remaining_months`), `extra_principal_monthly`; `schedule: statement` when the balance is above what the original terms leave (late payments, a deferral); a student loan's `loan_type` (leave it unset when the statement does not say); a student loan's `deferment_until` and `qualifying_payments`; a card's `spending_charged_pct`; a HELOC's `home`, `improvement_balance` |
| Insurance declarations | `insurance[]` `kind: life` (term/whole; an existing policy's `issue_year`, `cash_value`, `loan_balance`) or a general policy (`health` with `deductible`, `coinsurance_pct`, `oop_max_annual`; `disability` with `benefit_pct`; `auto`, `home`, `renters`, ...) |
| Pension / annuity statements | `kind: pension` (`benefit_annual` or the formula with `salary_history_annual`, `normal_retirement_age`, `early_retirement_reduction_pct`, `survivor_reduction_pct`, `employee_basis`, `lump_sum_option`); `kind: annuity` (`basis`, `purchase_year`, `qualified`, `in_payout` with `payout_monthly`) |
| SSA statement | `social_security.pia_override_monthly` (the full-retirement-age benefit) **with** `earnings_history` (year: covered earnings, from the same statement): the estimate assumes work until full retirement age, and the history lets an earlier retirement lower it; `claim_age`, `fra_from_birth_year`, `spousal_benefit` |
| Children | `children[]`: `name`, `birth_year`, `birth_month`, `cost_override_annual` / `college_cost_annual` (the configured bands are added on top of spending unless overridden: 0 when the budget already includes the child), `care_expenses_annual` (until the 13th birthday), and `kind: 529` accounts that name them as `beneficiary` |
| Health insurance after a job ends | `insurance[]` `kind: health` with `premium_annual`, `coverage_start_age` (the retirement age) and `coverage_end_age: 64` (for marketplace coverage add `marketplace: {slcsp_monthly, advance_monthly}`, which earns the ACA premium tax credit); `healthcare: {medicare: true}` from 65. Payroll premiums stop with the job |
| Term life policy | `kind: life`, `policy: term`, `issue_year` and `issue_month` (premiums on the anniversary; coverage ends at the last anniversary) |
| Marriage | `relationships.marriages[]`: `spouses` (the first is the tax-unit head), `filing_status` |
| Plans | `events[]`: `at: {year}` / `{age}` / `{relative: {after, years}}`, `person`, `action` (`retire`, `change_job`, `move`, `buy_home`, `one_time_expense`, `recurring_expense`, `change_spending`, `contribute`, `convert_to_roth`, `claim_social_security`, `refinance`, `renew_mortgage`, `heloc_draw`, `disability`, ...) |

Schedule `renew_mortgage` with the borrower's `person`, the `home` id, and an effective month such as
`at: 2030-07`. The new `rate_pct` applies to that month's regular payment using the current balance and
remaining amortization. Set `amortization_months` to change the payment count or
`rate_compounding: semiannual` to use a semiannual quote. Renewal adds no fees or cash-out.

A `savings_policy` can name one spendable opening bank account with `source_bank`. The
`cash_floor` then applies to that account alone. If you omit `source_bank`, the floor applies
across spendable bank accounts. The destination must also be an opening account. Optional
`start_year` and `end_year` bound the actual transfer year, inclusively. Taxable destinations
receive the sweep at year end. Tax-advantaged accounts and 529s receive it at the start of the
transfer year, up to that year's contribution room.

Schedule `pay_mortgage_at_maturity` with the borrower's `person`, `home` id and an explicit
`at: {year, month, day}`. It pays the live principal and the lender's quoted `interest_due` before the
month's regular bills. Use the date on the mortgage contract. The engine accepts that date and
bypasses prepayment caps and fees. The payoff follows the home's current owner and draws spendable
bank cash above `cash_floor`, with emergency reserves excluded. Any unpaid amount is logged as
`shortfall_debt` and comes due with the next month's bills. When relying on a same-day receipt,
give both events IDs that sort with the receipt first (for example, `01-sale` and `02-payoff`).
Set the payoff's optional `bridge` to a borrower-owned `bridge_line` id to draw automatically.
The draw rounds the amount needed to fund the payoff and preserve `cash_floor` up to whole cents,
then caps it at approved headroom. The payoff records the bridge draw and carries any remaining gap
as `shortfall_debt`, due with the next month's bills. Bridge interest is never deductible in the
model, including interest on an automatic draw. Under U.S. rules, debt that refinances a mortgage
can stay acquisition debt up to the balance it replaced
([IRS Publication 936](https://www.irs.gov/publications/p936)), but the model doesn't apply that
rule to a bridge that pays off a mortgage, so the mortgage-interest deduction can be understated in
that case.

Schedule `prepay_mortgage` on the last calendar day of a month to apply spendable cash
to principal after scheduled bills. Each month it uses the same tax holdback as bank-funded
contributions, reserving cash for this year's accrued unpaid tax and any balance owed from last
year. Set `cash_floor` to keep additional cash and `cash_fraction` to pay a share of the remaining
surplus (for example, `0.5` for half). Scheduled payments continue at the contracted amount.

In December, prepayment runs first, then annual taxes settle, then the taxable `savings_policy`
sweep runs. The sweep applies its own `cash_floor`, and can leave less cash than the prepayment's
floor. Tax-advantaged sweeps run at the start of the following year.

For a contractual annual cap, set the mortgage's `prepayment_privilege` with the first eligible
`anniversary` and `annual_limit_pct`. The cap resets on that anniversary each year. Set
`basis_amount` if the contract uses a different amount from the original mortgage, and `used` for
lump sums already paid in the opening contract year. A saved projection carries forward the cap's
basis and usage. Use the lump-sum cap with `prepay_mortgage` events and enter regular principal in
the mortgage's scheduled payment.

A `renew_mortgage` event keeps the same cap and usage by default. New `prepayment_privilege` terms
start at zero usage and use the balance immediately before renewal as their default basis. Pass
`prepayment_privilege: uncapped` to end the cap at renewal. A refinance starts a new loan and
clears the previous cap.

Use a `bridge_line` under `debts` for approved, short-term credit secured by an existing
home. Set the `home` id, `credit_limit`, and annual `rate_pct`. A `draw_bridge` event deposits
its `amount` in spendable bank cash. A `repay_bridge` event draws spendable cash above `cash_floor`
and carries any gap as `shortfall_debt` due with the next month's bills. Both events require an
explicit calendar date and follow the current owner of the line. Interest accrues on drawn principal
using actual days divided by 365. Outstanding interest counts toward liabilities, and the approved
limit applies to principal. A sale of
the collateral clears the bridge through the sale date before depositing the net proceeds.
For same-day events that rely on one another, give them IDs that sort in the intended order.

Two rules matter most. **Never invent a value**: a missing balance or rate is a question for the
person, or a labeled assumption, never a plausible-looking number. Behavioral inputs that
statements never show (raises, spending growth) are not "missing values": use the economy-linked
choice (`raise_pct: economy`, `growth_pct: economy`) and list it among the assumptions, rather than
the silent 0% core default. **Say what the engine would
otherwise assume**: people are immortal unless `mortality: stochastic` (or `fixed_age`), spending
and salaries don't grow unless given a rate or `economy`, rent rises 5% a year by default, and
investments grow at the economy's 7% equity return. [constructor-cheatsheet.md](constructor-cheatsheet.md)
lists every silent default.

Something that already happened belongs in the starting state, not in an event: a past marriage is
a `relationships.marriages` entry, a past purchase is an owned home with its current mortgage
balance. Events dated before `start_year` are errors. (A marriage dated before the start year is
part of the starting state: it does not appear in the run's event list.)

The defaults that most often change a long-run answer, and that the validator warns about: a
child's configured cost bands added on top of spending, no health coverage between an early
retirement and Medicare (and no Medicare premiums), surplus cash left in a low-yield bank without a
`savings_policy`, and an SSA estimate without its earnings record. Fix each one, or keep it on purpose
by listing its code in `meta.accepted_warnings` (it then stops failing `--checks strict`) and report it
as an assumption.

## 2. Validate

```bash
life-model validate my-models/household.yaml
```

The validator prints every finding as `[error|warning] path: message Fix: ...` and exits 2 while
errors remain. Errors are things the builder refuses (a schema mismatch, an unknown state, an event
before the start year, a field the engine cannot simulate yet); warnings are likely mistakes (0%
spending growth, a percent typed as a fraction, an event after the end year). Fix errors; fix each
warning or keep it on purpose and say so.

## 3. Run

```bash
life-model run my-models/household.yaml --seed 1 --out my-models/out
```

The run prints the key columns per year (income, taxes, spending, housing, bank balance, debt, net
worth) and a summary: final net worth, run totals, `shortfall_years` (years the household could not
pay its bills and carried the gap as debt) and `conservation_failures` (years where net worth moved
without a matching ledger flow, always checked in nominal dollars; this must be empty, and a
non-empty list is a model bug to report). It also reports the net-worth peak and the lowest cash
(overall and after everyone retires), in nominal and start-year dollars.
`my-models/out/result.json` holds everything: model and agent frames, every tax return, the
cash-flow ledger and the events ([outputs.md](outputs.md) documents every column). Add
`--real-dollars` to compare years in start-year dollars, `--years N` to shorten the run.

## 4. Explain a year

```bash
life-model explain my-models/household.yaml --seed 1 --year 2035
```

The account of one year: income by source and person, investment growth, every bill by category,
how the bills were paid (cash on hand, then the household waterfall's brokerage sales and pre-tax
withdrawals, each with its cause), savings moves, each tax return line by line (income,
adjustments, AGI, deduction, taxable income, federal, state, payroll, marginal and effective rate),
the change in net worth and the year's events. Explain the years where something happens:
retirement, a home purchase, college, the first required minimum distribution.

## 5. Compare a decision

```bash
life-model compare my-models/household.yaml --seed 1 --set 'people[john].retirement_age=58'
life-model compare my-models/household.yaml --seed 1 --change my-models/kitchen.yaml
```

Both runs use the same seed; the output is changed minus base for final net worth, total taxes,
each final balance, the number of shortfall years and each run's net-worth peak and lowest cash
(`--json` adds both runs' yearly rows). A change file is a JSON merge patch in YAML,
with `key+:` to append to a list and `people: {<id>: {...}}` to patch a list item by id:

```yaml
# my-models/kitchen.yaml
events+:
  - id: kitchen
    at: {year: 2030}
    person: jane
    action: one_time_expense
    amount: 40000
```

## 6. Measure risk

```bash
life-model montecarlo my-models/household.yaml --scenario stochastic --n 1000 --seed 1
life-model compare my-models/household.yaml --set 'people[john].retirement_age=58' \
    --scenario stochastic --montecarlo 500 --seed 1
```

The `stochastic` scenario draws correlated equity, bond and inflation rates every year; with
`mortality: stochastic` lifespans vary too. The success rate is the share of trials in which the
household never carried unpaid bills as new debt.

## 7. Reconcile against actuals

When the household has actual results for a simulated year (a filed tax return, W-2s, 1099s, a
paystub, year-end statements), write them into the spec's `actuals` block under that year, by the
form's own line and box numbers (or keep them in a separate file in `my-models/`), and run:

```bash
life-model reconcile my-models/h.yaml --year 2025                      # spec's actuals
life-model reconcile my-models/h.yaml --year 2025 --actuals my-models/2025-actuals.yaml
```

Describe the household as of January 1 of that year (`meta.start_year: 2025`; a `meta.start` later in
the year reconciles only the simulated months). Every line comes
back green, yellow or red with the likely cause of a difference: fix `input_difference` and
`missing_income_source` lines in the spec; `unmodeled_credit`/`unmodeled_deduction` lines are tax
features the engine lacks; `timing` lines (withholding, refund) mean the spec settles taxes as a December
lump: set `payroll.withholding` and `estimated_payments` (the validator suggests it); `missing_input` lines
need an input the spec does not take yet; `propagated` totals follow the line they name. See
[reconciliation.md](reconciliation.md) for the format and the tolerances.

## 8. Present the results

Lead with the answer, then state every assumption: the economy (fixed 3% inflation, 7% equity
unless a scenario says otherwise), growth rates, mortality, Social Security claiming ages, the
seed, nominal or real dollars, the validator warnings kept, and anything the engine cannot model
yet (fields marked *not yet supported* in the spec reference). It is a simulation, not financial
advice.

## Checklist for agents

The same workflow is packaged as an agent skill in
[agent-skills/model-household/SKILL.md](agent-skills/model-household/SKILL.md). A clone of this
repository already has it installed (`.github/skills/model-household` links to it, and
`.claude/skills` links to `.github/skills`); to use it in another project, copy it to that
project's `.claude/skills/model-household/SKILL.md`:

1. Gather facts from statements, not memory; record `meta.as_of`.
2. Never invent a balance, rate or date: ask, or label an assumption.
3. Start from a shipped example (`life-model examples --copy ...`) in `my-models/`.
4. Fill the spec in percents and stated periods; set mortality, growth (economy-linked when the
   statements are silent, listed as an assumption), state and filing status explicitly instead of
   relying on silent defaults. Spending is per person and adds up; children cost the configured
   bands on top of it; early retirees need health coverage before 65 and Medicare after.
5. `life-model validate` until there are no errors; decide on every warning (fix it, or list its code
   in `meta.accepted_warnings` and report it).
6. `life-model run --out my-models/out`; check `shortfall_years` and `conservation_failures`.
7. `life-model explain` the years that matter; `life-model compare` the decision; `montecarlo` with
   `--scenario stochastic` for risk.
8. Reconcile against actual documents when you have them (`life-model reconcile --year Y`); fix
   every red `input_difference` / `missing_income_source` line in the spec.
9. Present the answer with every assumption, default and limitation stated.
10. Keep real names, employers and balances out of tracked files, commit messages and prompts.
