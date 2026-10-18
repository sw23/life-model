# Plan 27 re-baseline log (statement-faithful inputs)

Plan 27 lets a household be entered from its statements. Every new constructor argument and spec field
defaults to the previous behavior, so a household that does not use them simulates exactly as before.
Each half of the plan lists what moved and why.

## 27a: accounts, payroll and standing policies (PR A and PR B)

### What did not move

Model frames of the four shipped examples (two seeds each, as they were before this change) and of the
`married_homeowners`, `stochastic_retiree` and `mortality_and_estate` test scenarios are identical to the
base branch, column for column, except for the new `Fixed Income Balance` column (0 without fixed-income
holdings). No household-golden `expected.json` value and no IRS-golden test changed; the conservation and
invariant suites pass unchanged.

Behavior changes that are no-ops for those households, and why:

| Change | When it moves numbers |
|---|---|
| The IRA contribution limit adds the age-50 catch-up (§219(b)(5)(B); `tax_years.limit_ira_catch_up`, validated but unread before) and the §219(g) phase-out reduces that larger limit | Someone 50+ contributing over the base limit |
| The 401(k) deferral limit uses the §414(v)(2)(E) catch-up at ages 60-63 (2025+) | Someone 60-63 deferring past base + the regular catch-up |
| Projected (post-2026) IRA catch-up rounds down to $100 (§219(b)(5)(C)); it was rounded to $1,000, so it fell back to $1,000 after 2026 | Projected years, with the above |
| Traditional IRA distributions recover Form 8606 basis pro rata (`nondeductible_basis`, which Plan 31's deduction phase-out also records) | An IRA with basis (entered, or left by a phased-out deduction) that is later distributed |
| The legacy yearly `HealthSavingsAccount(employer_contribution=)` stops once the owner's W-2 jobs have all ended (Plan 27 D3); an owner modeled without any job keeps receiving it | An HSA with an employer contribution whose owner retires |
| The default waterfall gains `fixed_income` (after `bank`) and `reserve` (last) steps; an explicit five-source order is kept and the two new steps take their default places | Households with fixed-income holdings or reserve bank accounts |
| Roth IRA withdrawals order contributions, then conversions, then earnings (conversion basis is new) | Roth IRAs with `conversion_basis` or conversions |
| The December waterfall repeats an unsized step (fixed income, Roth basis/earnings, reserves) while the tax it raised leaves a gap | A taxable draw in an unsized step (a bond-fund sale, an I bond's deferred interest, non-qualified Roth 401(k) earnings) |

### Example specs

The examples now use the new inputs where a real statement would show them, without changing the
household's story:

| Example | Change | Effect (fixed economy, seed as shipped) |
|---|---|---|
| `married_homeowners` | John's pay stub's $250/month pre-tax health premium (`payroll.health_premium_monthly`) | 2026: wages -$3,000, taxes -$771 (12% federal + 7.65% FICA + NY), net worth -$2,237; 2050 net worth $2,746,412 -> $2,688,380 |
| `self_employed` | The brokerage entered as a $95,000 lot with $70,000 basis (2019) instead of a no-gain balance | None through 2080 (the account is never sold) |

`single_renter` and `retiree_couple` are unchanged: their numbers are pinned by the monthly-engine
acceptance test and the construction-order test, which mirror them in Python.

### Tests whose expectations changed

All are the not-yet-supported pins the plan designed to flip; no dollar value changed.

| Test | Old | New | Reason |
|---|---|---|---|
| `test_spec_validate.TestSpecErrors.test_not_yet_supported_fields_and_kinds` | `fixed_income` and `convert_to_roth` rejected | they validate; a `divorce` event (backlog) is the rejected example | Plan 27 D2 and the Roth conversion are supported |
| `test_spec_validate.TestSpecErrors.test_every_not_yet_supported_field_is_rejected` | `bank.reserve` as the flagged field | the spec of `spec_helpers.not_yet_supported()` | `reserve` is supported (D2/D4) |
| `test_spec_validate.TestSpecErrors.test_standalone_401k` | a job-less 401k rejected | accepted | D3 |
| `test_spec_validate.TestSpecErrors.test_event_added_accounts_are_checked` | codes `not_yet_supported` + 2 x `unknown_reference` | 2 x `unknown_reference` | the first event's job-less 401k is supported |
| `test_spec_builder.TestBuildChecks.test_not_yet_supported_is_rejected_even_without_checks` | `bank.reserve` | `spec_helpers.not_yet_supported()` | as above |
| `test_plan31_household.TestSpecFields.test_other_payroll_items_are_still_not_supported` | `payroll.fsa_annual` rejected | renamed `..._are_supported_since_plan_27`, accepted | D3 |
| `spec_helpers.not_yet_supported()` (used by the API, CLI, MCP and main tests) | a job `end_year` | employer group life (`insurance[].group`, Plan 27 item 13) | `end_year` is supported |
| `test_engine_timing.TestMatchTiers.test_deprecated_percent_warns_and_keeps_the_legacy_formula` | read the first warning | finds the match warning among them | the helper's positional `BankAccount` call now warns first (D8); the expected message is unchanged |

### New constants

| Constant | Values | Source |
|---|---|---|
| `tax_years.limit_401k_catch_up_60_63` | 2025: $11,250; 2026: $11,250 | IRS Notice 2024-80 (IR-2024-285); Notice 2025-67 (IR-2025-111); IRC §414(v)(2)(E) |
| `tax_years.limit_health_fsa` | 2024: $3,200; 2025: $3,300; 2026: $3,400 | Rev. Proc. 2023-34 §3.16; Rev. Proc. 2024-40 (IRS newsroom, tax year 2025); Rev. Proc. 2025-32 (IRB 2025-45) |
| `tax_years.limit_commuter_monthly` | 2024: $315; 2025: $325; 2026: $340 | Rev. Proc. 2023-34 §3.17; Rev. Proc. 2024-40; Rev. Proc. 2025-32 |
| ESPP limit and discount (`work/stock.py`) | $25,000 a calendar year; price >= 85% of FMV | IRC §423(b)(8), §423(b)(6) |
| I bond rules (`account/fixed_income.py`) | composite = fixed + 2 x semiannual inflation + fixed x semiannual inflation, floored at 0, reset every 6 months from issue; cashable after 12 months; last 3 months' interest forfeited before 5 years; 30-year life; federal tax deferrable, state-exempt | TreasuryDirect "I bonds" and "I bonds interest rates" (fetched 2026-10-18) |
| CD early-withdrawal penalty deduction | above the line (Schedule 1 line 18) | IRC §62(a)(9) |
| Projection rounding | IRA catch-up down to $100 (§219(b)(5)(C)); health FSA down to $50 (§125(i)(2)); commuter down to $5 (§132(f)(6)) | the statutes; `TODO(verify)`: the post-2025 rounding of the 60-63 catch-up (projected in $500 steps) |

All dollar values were fetched on 2026-10-18 from irs.gov (newsroom pages and IRB 2023-48 / 2025-45),
TreasuryDirect and the Cornell LII text of the Code. The IRS PDFs of Rev. Procs. 2024-40 and 2025-32
did not extract; their values come from the IRS newsroom release and the IRB HTML text.

### Removed (D8)

The dead config keys `accounts.brokerage.default_growth_rate`, `accounts.bank.default_interest_rate`,
`retirement.ira.default_growth_rate` and `accounts.plan_529.default_growth_rate` are gone from the
packaged defaults; the models accept and ignore them for one release.
