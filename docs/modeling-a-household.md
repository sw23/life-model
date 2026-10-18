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
| Budget or bank history | `spending.amount_annual` (living costs, excluding housing, debt payments and taxes), `growth_pct`; optional `categories` (`amount_annual` or `amount_monthly`, `essential`, `start_year`/`end_year`) and an age `schedule` (a retirement spending smile) |
| Bank statements | `accounts[]` `kind: bank`: `balance`, `interest_pct` (APR; `compounding: annual` for an APY), one `primary: true` |
| 401k statement | `kind: 401k`, `job:` (the job's `id`), `pretax_balance`, `roth_balance`, `pretax_contrib_pct`, `roth_contrib_pct`, `match_tiers` |
| Brokerage statement | `kind: brokerage` with `lots` (`value`, `cost_basis`, `acquired_year`) or a single `balance` |
| IRA / HSA / 529 statements | `kind: traditional_ira`, `roth_ira`, `hsa`, `529` |
| Mortgage statement | `housing[]` `kind: home`: `purchase_price`, `current_value`, `cost_basis`, `purchase_year`, `mortgage` (`original_amount`, `rate_pct`, `term_years`, and `origination: YYYY-MM`, or the current `balance` with `remaining_months`; `payment_monthly` with `escrow_monthly` when the statement payment includes escrow), `pmi`/`pmi_monthly`, `expenses` (property tax as `property_tax_annual` or % of an `assessed_value`, `insurance_annual`, maintenance, HOA) |
| Lease | `kind: rental`: `rent_monthly`, `rent_growth_pct` |
| Loan statements | `debts[]` `kind: car`, `student`, `credit_card`, `heloc`: `rate_pct` (APR), then the statement's terms (`original_amount` with `term_months`/`term_years` and `origination`, or the current `balance` with `remaining_months`), `extra_principal_monthly`; a student loan's `deferment_until` and `qualifying_payments`; a card's `spending_charged_pct`; a HELOC's `home`, `improvement_balance` |
| Insurance declarations | `insurance[]` `kind: life` (term/whole; an existing policy's `issue_year`, `cash_value`, `loan_balance`) or a general policy (`health` with `deductible`, `coinsurance_pct`, `oop_max_annual`; `disability` with `benefit_pct`; `auto`, `home`, `renters`, ...) |
| Pension / annuity statements | `kind: pension` (`benefit_annual` or the formula with `salary_history_annual`, `normal_retirement_age`, `early_retirement_reduction_pct`, `survivor_reduction_pct`, `employee_basis`, `lump_sum_option`); `kind: annuity` (`basis`, `purchase_year`, `qualified`, `in_payout` with `payout_monthly`) |
| SSA statement | `social_security.pia_override_monthly` (the full-retirement-age benefit) or `earnings_history` (year: covered earnings), `claim_age`, `fra_from_birth_year`, `spousal_benefit` |
| Children | `children[]`: `name`, `birth_year`, optional `cost_override_annual` / `college_cost_annual` (and `kind: 529` accounts that name them as `beneficiary`) |
| Marriage | `relationships.marriages[]`: `spouses` (the first is the tax-unit head), `filing_status` |
| Plans | `events[]`: `at: {year}` / `{age}` / `{relative: {after, years}}`, `person`, `action` (`retire`, `change_job`, `move`, `buy_home`, `one_time_expense`, `recurring_expense`, `change_spending`, `contribute`, `convert_to_roth`, `claim_social_security`, `refinance`, `heloc_draw`, `disability`, ...) |

Two rules matter most. **Never invent a value**: a missing balance or rate is a question for the
person, or a labeled assumption, never a plausible-looking number. **Say what the engine would
otherwise assume**: people are immortal unless `mortality: stochastic` (or `fixed_age`), spending
and salaries don't grow unless given a rate or `economy`, rent rises 5% a year by default, and
investments grow at the economy's 7% equity return. [constructor-cheatsheet.md](constructor-cheatsheet.md)
lists every silent default.

Something that already happened belongs in the starting state, not in an event: a past marriage is
a `relationships.marriages` entry, a past purchase is an owned home with its current mortgage
balance. Events dated before `start_year` are errors.

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
without a matching ledger flow; this must be empty, and a non-empty list is a model bug to report).
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
each final balance and the number of shortfall years. A change file is a JSON merge patch in YAML,
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

The same workflow is packaged as a Claude Code skill in
[agent-skills/model-household/SKILL.md](agent-skills/model-household/SKILL.md) (copy it to
`.claude/skills/model-household/SKILL.md` to install it):

1. Gather facts from statements, not memory; record `meta.as_of`.
2. Never invent a balance, rate or date: ask, or label an assumption.
3. Start from a shipped example (`life-model examples --copy ...`) in `my-models/`.
4. Fill the spec in percents and stated periods; set mortality, growth, state and filing status
   explicitly instead of relying on silent defaults.
5. `life-model validate` until there are no errors; decide on every warning.
6. `life-model run --out my-models/out`; check `shortfall_years` and `conservation_failures`.
7. `life-model explain` the years that matter; `life-model compare` the decision; `montecarlo` with
   `--scenario stochastic` for risk.
8. Reconcile against actual documents when you have them (`life-model reconcile --year Y`); fix
   every red `input_difference` / `missing_income_source` line in the spec.
9. Present the answer with every assumption, default and limitation stated.
10. Keep real names, employers and balances out of tracked files, commit messages and prompts.
