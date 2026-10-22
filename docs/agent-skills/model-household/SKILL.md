---
name: model-household
description: Model a real or hypothetical household's finances with life-model from statements to a validated household spec, then run, explain, compare changes and Monte Carlo it with the life-model CLI. Use when asked to model, project, simulate or stress-test a household, family budget, retirement plan or "what if" (retire early, buy a house, change jobs), or to turn financial statements into a spec. Keeps real data in my-models/ and never invents balances.
---

# Modeling a household with life-model

You turn a household's facts into a **household spec** (YAML), validate it, run it, and explain
the results with explicit assumptions. You do not need to read `src/`. References:
`docs/modeling-a-household.md` (worked walkthrough), `docs/household-spec.md` (every field),
`docs/units-and-conventions.md`, `docs/constructor-cheatsheet.md` (silent defaults),
`docs/outputs.md` (output columns), `docs/cli.md` (every command and flag).

## Privacy rules (apply throughout)

- Real household files live in `my-models/` (git-ignored). Create the spec and every output there.
- Never write a real person's name, employer, account number or balance into a tracked file, a test,
  a fixture, a commit message, a PR, an issue or a doc. Refer to household files by path.
- Don't paste statement contents or balances into prompts for other agents or tools beyond what the
  task needs. Examples and tests use only synthetic data.
- `life-model run --out` refuses to write inside `src/`; don't work around it.

## Checklist

1. **Gather facts from statements, not memory.** Collect, per person: age (or birth year), state,
   retirement age; pay (pay stub or offer: salary, bonus %, raise expectations); spending (budget or
   bank statements); each account's balance and type (bank, 401k pre-tax/Roth split, contribution
   %, employer match tiers, brokerage value and cost basis, IRAs, HSA, 529); debts (current balance,
   original amount, APR, term); home (value, purchase price, mortgage statement: original amount,
   balance, rate, term, start year; property tax, insurance, HOA); rent; insurance policies; the SSA
   statement's earnings record and planned claiming age; children's birth years and months; planned
   events (a move, a purchase, a job change, college). Record `meta.as_of` (the statement date).
2. **Never invent a balance, rate or date.** If a value is missing, ask for it. If you must proceed,
   use a clearly labeled assumption (and list it in step 9), never a made-up "realistic" number.
   *Behavioral* inputs statements never show (raises, spending growth, retiree health costs) are
   different: don't leave them at a 0% core default because nothing was stated. Use the
   economy-linked documented choice (`raise_pct: economy`, `growth_pct: economy`) and list it as an
   assumption; "use the documented default" means the documented, economy-linked choice, not the
   silent 0% core default the validator warns about.
3. **Start from an example.** `life-model examples` lists them; `life-model examples --copy
   married_homeowners my-models/<name>.yaml` (or `single_renter`, `retiree_couple`) gives the shape.
   `life-model schema` prints the JSON Schema.
4. **Fill the spec.** Rates are percents (`4.5`, not `0.045`); flows say `_annual` or `_monthly`;
   debts are positive balances; `growth_pct: economy` follows the economy. Set what the engine would
   otherwise default silently: `mortality` (default immortal), spending `growth_pct` (default 0%),
   `raise_pct` (default 0%), rent growth (default 5%), `state` (must be a supported code), filing
   status via `relationships.marriages`. Things that already happened go in the starting state, not
   in events. Watch these, each of which silently changes a long-run answer:
   - **Spending is per person and adds up** across the household: put the whole budget on one
     spouse (leave the other's `spending` out) or split it, never the full budget on each.
   - **Children cost the configured bands on top of spending** (childcare, school age and college:
     the table in docs/household-spec.md). If the budget already includes the child, set
     `cost_override_annual: 0`; set `college_cost_annual` to the plan (0 for none); give `birth_month`.
   - **Health coverage before 65 and Medicare after**: payroll premiums stop with the job. For an
     early retiree add a `kind: health` policy (`coverage_start_age` to 64) and
     `healthcare: {medicare: true}`, or state the gap as an assumption.
   - **Surplus cash** stays in the bank at its yield unless a `savings_policy` sweeps it.
   - **Joint accounts**: list a joint checking or brokerage account once with `joint: true` (the
     other spouse then needs no bank account of their own).
   - **SSA estimates assume work until full retirement age**: give `pia_override_monthly` together
     with the statement's `earnings_history`, so an earlier retirement lowers the benefit.
   - **A loan behind its own schedule** (balance above what its terms leave) needs
     `schedule: statement`; contribution plans end with `end` / `until_age` (a 529 stops at college
     by default).
5. **Validate until clean.** `life-model validate my-models/<name>.yaml`. Fix every error; for each
   warning either fix it or keep it deliberately: list its code in `meta.accepted_warnings` and
   report it as an assumption. Exit code 2 means errors remain.
6. **Run.** `life-model run my-models/<name>.yaml --out my-models/out` (add `--seed N` for
   reproducibility, `--real-dollars` to compare years in today's money). Check the summary:
   `shortfall_years` (bills the household could not pay) and `conservation_failures` (always
   checked in nominal dollars, so the same with `--real-dollars`; it must be empty, and if not,
   report it as a model bug rather than explaining it away). The summary also gives the net-worth
   peak and the lowest cash (overall and after everyone retires), in nominal and start-year dollars.
7. **Explain and compare.** `life-model explain <spec> --year Y` for the years that matter
   (retirement, a purchase, the first RMD year). For a decision, `life-model compare <spec> --set
   'people[<id>].retirement_age=62'` or `--change my-models/change.yaml` (a merge patch; `events+:`
   appends events; `compare --json` has both runs' yearly rows, peaks and lowest cash). For risk,
   `life-model montecarlo <spec> --scenario stochastic --n 1000 --seed 1 [--real-dollars]` or
   `compare ... --montecarlo 500 --scenario stochastic`.
8. **Reconcile against actuals when you have them.** Put the filed return's lines (by that year's
   Form 1040 line numbers), W-2/1099 boxes and December 31 balances under `actuals: {<year>: ...}`
   in the spec (or a separate file in `my-models/`), start the spec on January 1 of that year, and
   run `life-model reconcile my-models/<name>.yaml --year <year> [--actuals FILE]`. Fix red
   `input_difference` / `missing_income_source` lines in the spec; report `unmodeled_credit`,
   `unmodeled_deduction`, `timing` and `missing_input` lines as model limitations, not spec errors
   (docs/reconciliation.md).
9. **Present results with assumptions.** Lead with the answer, then list every assumption and
   default you relied on (economy rates, growth, mortality, claiming age, scenario, seed, nominal
   vs real dollars), what you could not model (fields marked not yet supported), and the
   validator warnings you kept. It is a simulation, not financial advice.

## Useful flags

`--json` on every command for machine-readable output; exit codes 0 ok, 2 invalid input, 1 runtime
error. `--years N` / `--end-year Y` shorten a run; `--scenario NAME` (`life-model examples` lists
them; `stochastic` for random draws); `--checks strict` to fail on validator warnings and on any
invariant violation (money conservation, negative balances, contribution limits, RMDs, FICA...).
