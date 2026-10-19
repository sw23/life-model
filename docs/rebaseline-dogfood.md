# Re-baseline: dogfood fixes

Plan 30's acceptance test had a fresh agent model a synthetic household (the dogfood household) from
the agent-facing docs alone. This log records every output the follow-up fixes changed, with the
reason. Household goldens (`tests/goldens/households/*/expected.json`) are unchanged, and so are the
shipped examples' money outputs (their specs now state the child costs they used by default and
accept the warnings they keep on purpose; the values are the same).

## Changed outputs

| Output | Old | New | Reason |
|---|---|---|---|
| `conservation_failures` of a `--real-dollars` run (dogfood household, 2026-2079) | 53 years (every year after the first) | none | Conservation is a nominal identity; the real conversion divided the opening balance by the prior year's deflator and the flows by the year's, so inflation looked like money destroyed. `RunResult.conservation()` now re-inflates a real result before checking. Same for every example (married_homeowners 46 years, single_renter 41, retiree_couple 22, self_employed 54 → none). |
| `married` events of a household married before the start year (married_homeowners, retiree_couple, the dogfood household) | one "got married" event in the first year | none | A marriage dated before the start (or undated) is starting state. One dated in the start year is still logged. Event counts drop by one (married_homeowners 109 → 108). |
| Dogfood household (the agent's own `household.yaml`), final net worth 2079, nominal / start-year dollars | $30,258,203 / $6,316,409 | $29,866,837 / $6,234,711 | The $200/month 529 plan now stops the month before Kai's college months (it ran to 2079 and left a $534,591 529 counted in net worth); the cash it no longer moves stays in checking. Total taxes $2,817,569 → $2,829,730 (that cash earns taxable interest instead of untaxed 529 growth). |
| Dogfood household, re-modeled with the new fields (`tests/fixtures/dogfood_household.yaml`) | n/a | final net worth $6,212,643 (start-year dollars); Sam retiring at 55 instead of 60: -$295,744 | Uses `joint: true` for the checking and brokerage accounts (no made-up account for Sam), Kai's `birth_month` (after-school care through May 2030, not December 2029), `schedule: statement` for the car loan, the term policy's `issue_month`, the CD's pre-start interest and Sam's SSA earnings record. With the record Sam's PIA responds to retirement: $4,514.10 retiring at 60 and $4,274.00 at 55 (2054 dollars), where the bare override gave the same benefit for both. |
| `RunResult.explain()` "How they were paid" | 529 college withdrawals absent; everything "from cash on hand" | `- from <owner>'s Plan529 (qualified education expenses (tax-free)): $X`, and cash on hand reduced by it (HSA medical reimbursements likewise) | The 529 paid the bill; the ledger knew, the explanation did not. |
| `RunResult.explain()` "Savings moves" | `- contribution: <cause>: $X` (blank cause for a contribution plan: `contribution: : $2,400`) | `- contribution: <cause> → <target account>: $X` | Contribution plans now post the cause `contribution plan`, and every line names its target. |
| Ledger `cause` of a 529 qualified withdrawal and of contribution-plan contributions to IRAs, HSAs and 529s | empty | `qualified education expenses (tax-free)` / `contribution plan` | Same as above. |
| `life-model run` text summary | shortfall and conservation lines only when non-empty | always printed (`none` / `passed in every year`), plus the net-worth peak and lowest-cash lines | The summary should answer the questions it is asked without `--json`. |
| `life-model compare` text and `--json` | shortfall delta only when non-zero; no yearly rows | shortfall line always; peaks and lowest cash per run; `base.yearly` / `changed.yearly` in `--json` | Same. `Comparison.to_dict()` keeps `yearly=False` by default (the MCP tool's payload is unchanged). |
| `life-model montecarlo` text and JSON | nominal only | `dollars` key; `--real-dollars` deflates each trial by its own inflation | Friction 16. |
| Spec schema: a Social Security block with both `pia_override_monthly` and `earnings_history` | rejected | accepted (the history scales the override) | `test_spec_statement_insurance` now pins that the override excludes only a synthesized `assumed_career_start_age` record. |
| Validator findings on specs that lean on silent defaults | none | `default_child_costs`, `child_birth_month_assumed`, `no_health_coverage`, `cash_not_invested` (runs of 10+ years), `ss_estimate_assumes_work`, `hsa_employer_twice` (error), `rap_needs_federal_loan` (error), `joint_without_spouse` (error), `missing_spending` (error), `contribution_plan_never_runs` | Each names the amounts and the fix; `meta.accepted_warnings` keeps a warning on purpose. The five assumption warnings (`default_child_costs`, `child_birth_month_assumed`, `no_health_coverage`, `cash_not_invested`, `ss_estimate_assumes_work`) are reported by the command line, `life_model.validate` / `run` / `build`, `reconcile` and the MCP tools; `life_model.spec.validate_spec` returns them only with `include_assumptions=True`, so specs generated by the RL environment and the dashboard validate as before. |

## Unchanged by design

- Child costs without `birth_month` keep the January assumption, so households without it get the same
  numbers; tax rules keep using the age at the end of the year.
- `bonus_is_plan_pay` (formerly `match_on_bonus`, still accepted with a warning) keeps its default
  `false`; it is documented that it governs the deferral on the bonus as well as the match.
- A student loan's new default `loan_type: unknown` repays like the other types on the standard plan.
- Loans default to `schedule: contract`, the previous behavior.
