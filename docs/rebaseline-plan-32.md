# Plan 32 re-baseline log

Plan 32 makes the engine natively monthly: `LifeModel.step()` simulates one calendar month, income,
bills, growth and benefits flow month by month, taxes settle in December, and ages are exact. The
numbers move on purpose. This log lists every existing test that changed (its old and new value
and why, grouped by cause), the outputs no test pins, the tolerance against the annual engine, and
the timing. New tests live in `test_monthly_engine.py` (the mechanics) and
`test_monthly_acceptance.py` (the plan's acceptance criteria). See
[units-and-conventions.md](units-and-conventions.md) for what now happens monthly versus yearly.

Tests that pin exact tax arithmetic on given inputs (`test_irs_golden.py`, the `test_tax_*.py`
function tests) did not change. Loan payoff months did not change (a 60-month car loan still makes
exactly 60 payments: `TestMonthlyBills.test_loan_payoff_month_follows_the_amortization_schedule`).
No RL, SLM or dashboard fixture changed, and the Plan 25 parity tests (old vs spec construction on
the same engine) pass unchanged.

## Mechanics only: no expected value changed

* **`model.step()` is a month.** Every test that called `model.step()` (or `self.model.step()`,
  `built.model.step()`, `model2.step()`) to simulate a year now calls `model.step_year()` (132 call
  sites across the core, dashboard and RL test suites, and `deepqlearning/evaluation/benchmark_env.py`).
* **A year of an agent is twelve monthly calls.** Unit tests that called one stage method for a
  year now run it once per month with `tests/helpers.run_months(model, method)`:
  `test_job.py` (6 tests, `job.pre_step`), `test_pension.py::test_benefit_lands_in_cash_and_ordinary_income_not_fica`
  (the ledger now has 12 pension entries summing to the same 30,000),
  `test_social_security.py::test_benefits_route_through_income_ledger` (`assertEqual` →
  `assertAlmostEqual(places=6)` on the sum of 12 benefits), `test_annuity.py::test_annuity_interest_growth`,
  `test_bank.py::test_bank_account` (`assertEqual` → `assertAlmostEqual(places=8)`: twelve multiplications by
  `1 + APR/12` vs one `pow`), `test_investment.py` (3), `test_roth_ira.py` (2),
  `test_capital_gains.py` (`TestTaxLots` 2, `test_default_yield_leaves_growth_untouched`; growth history
  1 → 12 entries), `test_engine_timing.py::TestBankInterestIsIncome` (2), `test_job401k.py` (2),
  `test_traditional_ira.py` (2), `test_plan529.py::test_full_year_cycle`.
* **Annual work moved to the year hooks.** `post_step` resets and escalators → `on_year_end`:
  `test_job.py::TestSalary` (`salary.on_year_end()`), `test_accounts_integration.py::test_hsa_contribution_resets_across_years`,
  `test_plan529.py` (`test_step`, `test_post_step`), `test_general_insurance.py` (2 tests: the
  yearly premium increase), `test_life_insurance.py` (7 call sites: term expiry, re-pricing, cash
  value growth, loan interest and lapse). The HSA employer contribution runs in `on_year_start`
  (`test_hsa.py`, 2 tests); a year's RMD is set in `on_year_start` and paid in twelve `pre_step`s
  (`test_job401k.py`, `test_traditional_ira.py`).
* **Monthly bills.** `test_capital_gains.py::TestBrokerageFundsSpending` (4 tests) settled spending
  with `TaxUnit.settle_year()`, which now settles only taxes; they run twelve `settle_month()`s then
  `settle_year()` (`_settle_a_year`). Expected values unchanged.
* **Brokerage mock.** `test_brokerage.py`'s mock model gains `month = 1`, an `economy.monthly_rate`
  and `dividend_frequency`; `test_apply_growth_integration` compares `apply_growth()` with
  `calculate_monthly_growth()`; `test_step_integration` calls `on_year_end()` (balance history is
  recorded at year end).
* **Ages read between steps.** `person.age` is computed for the model's current month, which between
  steps is the next month to simulate (January of the next year after `step_year()`).
  `test_engine_timing.py::test_person_created_mid_run_keeps_constructor_age_that_year` reads
  `late.age_in(2027)` / `age_in(2028)` (same 30 / 31) and adds `(model.year, late.age) == (2029, 32)`.
* **Cause strings.** "fund 2026 bills and taxes" → "fund 2026 taxes"
  (`test_run_result.py::test_explain_names_every_forced_sale_and_pretax_withdrawal_with_its_cause`);
  "repay unpaid bills carried from last year" → "repay unpaid bills"
  (`test_ledger.py::test_unpaid_bills_debt_passes_to_the_heir`).
* **Ledger month.** `test_ledger.py::test_paycheck_tax_and_spending_are_posted`: `frame.month.isna().all()`
  → `frame.month.between(1, 12).all()` (entries carry the month they were posted in).
* **Exports.** `test_run_result.py::test_json_and_csv`: the CSV export adds `monthly_balance_sheets.csv`.
* **Strengthened checks.** `test_ledger.py`'s whole-household conservation tests and
  `test_spec_outputs.py` also assert monthly conservation.

## Changed expected values, by cause

### Monthly payroll (per-paycheck 402(g) room)

| Test | Old | New | Reason |
| --- | --- | --- | --- |
| `test_job401k.py::test_two_jobs_share_one_402g_limit` | job 1 15,000, job 2 5,000 | 10,000 and 10,000 (total 20,000) | Both jobs pay monthly and defer $1,250 a month each until the shared $20k limit is reached in August; the annual engine booked job 1's year first. |

### Exact ages

| Test | Old | New | Reason |
| --- | --- | --- | --- |
| `test_engine_correctness.py::test_non_integer_retirement_age_triggers` | input age 65; retired from the second year | input age 64 (born January 1956); retires in July 2021 after July's paycheck; income 2021 = 7/12 × 50,000 | A 65.5 retirement age is reached six months after the 65th birthday. The input moved so the test still covers "working one year, retiring the next". |

### Monthly mortality: the death month's income is received (D6)

A death in month *m* happens after month *m*'s wages, benefits and RMD share (stopping them from
*m*+1). The annual engine killed a person at the start of the year, before any income.

| Test | Old | New |
| --- | --- | --- |
| `test_mortality_death.py::test_fixed_age_death` | income 2030 = 0 | 50,000 / 12 (January's paycheck) |
| `test_mortality_death.py::TestPensionSurvivorAtDeath` (2 tests) | pension income 2027 = 20,000 | 40,000/12 + 20,000 × 11/12 = 21,666.67 (January's full payment, then the survivor's) |
| `test_mortality_death.py` single-life pension | pension income 2027 = 0 | 40,000/12 (January's payment; a pension removed at a death keeps its year-to-date flows in the year's totals) |
| `test_ledger.py::test_social_security_stops_at_death` | benefit years [2026, 2027] | [2026, 2027, 2028], the last paid (2028, 1) |
| `test_ledger.py::test_agents_removed_at_a_death_do_not_run_the_rest_of_that_stage` | no benefit in 2029 | the last benefit is (2029, 1) |
| `test_inherited_account.py::test_inherited_corpus_visible_in_useable_balance_stat` | corpus 500,000 (and 250,000 mid-window) | 500,000 − January's twelfth of the parent's age-80 RMD = 497,937.29 (and half of it), derived in the test |
| `test_mortality_death.py::TestPerAccountBeneficiary::test_nonspouse_designation_stays_in_estate_tax_base` | input death age 76 | input death age 72 (before RMDs); expected $400,000 tax and $600,000 unchanged — at 76 a January RMD would move $7,032 from the designated IRA into the residual estate |

### Year-dated events fire in January

`LifeEvent(year, ...)` without a month fires in the first simulated month of its year. The annual
engine fired it after the whole year's income had been booked, and a `post_step` event after the
year's settlement.

| Test | Old input | New input | Reason |
| --- | --- | --- | --- |
| `test_engine_timing.py::test_post_step_event_takes_effect_next_year` | `LifeEvent(2026, ..., stage="post_step")` | adds `month=12` | December's `post_step` is the old year end. Expected values unchanged. |
| `test_engine_timing.py::test_unvested_match_forfeited_on_leaving_early` | quit `LifeEvent(2027, ...)` | adds `month=12` (quit after December's paycheck) | Same two years of deferrals and forfeited match. |

### Monthly growth, quarterly dividends, holding period in months

| Test | Old | New | Reason |
| --- | --- | --- | --- |
| `test_capital_gains.py::test_dividend_splits_total_return_without_changing_it` | dividends 200 | 207.50 (`_quarterly_dividends`: 0.5% of the balance at the start of March, June, September and December on $10k growing 7%); balance 10,700 unchanged | Dividends are paid quarterly on the growing balance. |
| `test_capital_gains.py::test_reinvested_dividend_gets_full_basis` | basis 10,200, gain 500, 2 lots | basis 10,207.50, gain 492.50, 5 lots | Same. |
| `test_capital_gains.py::test_divergence` (Roth vs brokerage, 30 years) | preferential income == unrealized gain | preferential + short-term == gain, short-term < 1% of it | Dividend lots reinvested in the last 12 months sell at a short-term gain (holding period in months). |

### Monthly bills and the waterfall

| Test | Old | New | Reason |
| --- | --- | --- | --- |
| `test_ledger.py::test_settlement_draws_carry_their_cause` | one brokerage sale, "fund 2026 bills and taxes" | one sale each month, "pay 2026-MM bills" (and December's tax funding) | Bills are paid monthly. |
| `test_typed_events.py::test_settlement_logs_forced_sales_and_pretax_withdrawals_with_cause` | one forced sale and one sized pre-tax withdrawal | monthly sales and withdrawals ("pay 2026-MM bills"), then one sized withdrawal for the taxes ("fund 2026 taxes", amount == solver target); penalty = 10% of all pre-tax withdrawals | Same. |
| `test_donation.py::test_donation_with_insufficient_funds` | unpaid-bills debt 50,000 | 54,338.38: twelve monthly $4,166.67 shortfalls, each month's carried debt accruing 18%/12 (derived in the test) | Carried debt is retried with each month's bills after a month of interest. |
| `test_engine_correctness.py::test_carried_debt_accrues_a_year_of_interest` | repaid 10,000 × 1.18; interest 1,800 | repaid in January: 10,000 × (1 + 0.18/12); interest 150 | Same. |
| `test_engine_timing.py::test_interest_accrues_before_settlement_and_is_reported_at_year_end` | interest 5,000 (on the opening balance) | monthly interest on the balance after each month's bills (derived in the test) | Monthly bank interest and bills. |

### Spec (task 6)

| Test | Change | Reason |
| --- | --- | --- |
| `tests/spec_helpers.minimal()` | adds `birth: "<2026 - age>-01"` (same exact ages as an age-only person); `birth=None` leaves it out | The validator now warns `birth_assumed` for a person without a birth month; minimal specs stay clean. |
| `test_spec_validate.py::test_not_yet_supported_fields_and_kinds` | 4 `not_yet_supported` findings → 2 | `meta.start` and `birth` are supported. |
| `test_spec_validate.py::test_claim_age_relative_to_another_person`, `test_spec_builder.py` (2 tests) | set `birth` with the changed `age` | The birth must agree with the age. |
| Example specs | every person has a `birth` | They validate cleanly (no `birth_assumed` warning) and exercise exact ages. The fixed-economy tolerance test strips them (its annual-engine values are for the age-only examples). |

## Outputs no test pins

* **Retirement takes effect in the retirement month.** A job stops after the paycheck of the month
  the exact age reaches `retirement_age`; for an age-only person (January birth) and a whole-year
  retirement age that is January of the year they turn that age. The annual engine paid the whole
  year in which the age was reached (`Person.step` retired the job after the year's payroll), so the
  retirement year now has one month of salary, deferrals and match instead of twelve, and every later
  balance is lower by that year's savings. This is the largest single difference in the long-run
  frames below (e.g. the Plan 28 married homeowners: John retires at 58 in 2042).
* **Contributions grow from their month** (on average about 5.5 months less growth on a year's
  contributions than the annual engine's January deposit): a saver's 401k ends 0.3-3% lower.
* **Spending is withdrawn monthly** (the annual engine grew the whole balance before withdrawing a
  year of spending): a retiree drawing about 4-5% a year ends 0.2% of wealth a year lower; the
  notebook's Monte Carlo retiree ($1.2M, $60k/yr, stochastic): success rate 49.7% → 42.8% (n=1000,
  seed 7; 47% → 35% at the notebook's n=100), median final brokerage unchanged at $0, p90 $7.18M →
  $6.03M.
* **Bank interest** accrues monthly on the balance actually held (the annual engine credited a year
  of interest on the opening balance plus the year's take-home pay before any bill was paid).
* **Taxes are paid in December**, so the money for them earns interest/growth until then.
* **Year-dated events fire in January** (above): `renter_buys_home`'s "Lose job" (2038) and "New
  job" (2039) now leave 11 months without salary in 2038 (the annual engine paid 2038 in full).
* **Stochastic economy**: draws are monthly (the annual mean converted to its monthly equivalent,
  `vol / sqrt(12)`, the same correlation matrix), so every stochastic run's numbers change; the
  expected annual return is unchanged.
* **Death-year income on the return**: a spouse who dies mid-year stays on the survivor's joint
  return for that year (their income so far is taxed jointly); a single decedent's year-to-date income
  is reported by the heir (an approximation of the final return, which is not modeled) or, with no
  heir, goes untaxed.
* **Events**: one RMD event per account and recipient a year (with the year's total); forced-sale and
  pre-tax-withdrawal detail events are per month; the agent frame's `Age` column is the age at the
  year end (with a birth month after January, the age reached that year).
* **Flow stats** accumulate monthly and restart each January; an agent removed mid-year (a
  decedent, a terminated pension) keeps its year-to-date flows in that year's model totals (the
  annual engine zeroed a decedent's stats).

## Fixed-economy tolerance against the annual engine

Measured with `economy.mode: fixed` and immortal people on the example households (age-only, as
before this plan added birth months to them; up to 50 years) and the four Plan 28 scenario households (the stochastic retiree under a fixed economy),
against the pre-plan engine (`fourth-wave` at f66307f, run in a scratch worktree). "Aligned" runs
the monthly engine with every retirement age raised by 11/12 of a year, so a person retires in
December of the year they reach their retirement age — the annual engine's last paid year — which
isolates the monthly flows from the exact-age retirement month. Maximum absolute difference in
year-end net worth, as a percent of the annual engine's:

| Household | Year 1 | Years 1-5 | Years 1-10 | Years 1-20 | All years | All years, not aligned |
| --- | --- | --- | --- | --- | --- | --- |
| Example single renter (61 y) | 0.68 | 1.76 | 2.20 | 2.25 | 3.28 | 9.48 |
| Example married homeowners (47 y) | 0.10 | 0.47 | 0.76 | 1.22 | 1.73 | 8.38 |
| Example retiree couple (31 y) | 0.08 | 0.59 | 0.94 | 1.30 | 1.91 | 1.91 |
| Plan 28 married homeowners (45 y) | 0.38 | 1.29 | 1.84 | 2.42 | 4.38 | 12.14 |
| Plan 28 stochastic retiree, fixed economy (40 y) | 0.00 | 0.35 | 0.70 | 0.70 | 6.23 | 6.23 |
| Plan 28 mortality and estate (50 y) | 0.00 | 0.03 | 0.17 | 0.30 | 0.33 | 0.57 |
| Plan 28 renter buys home (45 y) | 1.92 | 2.80 | 5.40 | 13.81 | 23.71 | 25.31 |

Re-measured after merging Plans 29 and 30, against `fourth-wave` at f66307f: Plan 29's verified
`tax_years` table (the SALT cap from 2025 on, among others) moved the annual engine's numbers, so the
pinned values in `TestFixedEconomyMatchesTheAnnualEngine` were re-measured there too (the Plan 28
married homeowners' 2035 and 2045 values failed against the 2cb84b0 pins). The first measurement,
against 2cb84b0 (the single renter over its first 50 years), differed from this one by at most 0.5
points in any cell.

The plan expected "< 1% for balances". That holds for the first year (except the renter, whose
first-year 401k starts from $0 so the half-year of growth its new contributions lose is 3% of it) and
not over decades: the differences are the corrections D3 asked for (contributions no longer get a
full year of growth, a retiree's spending no longer earns a year of growth before it is spent, bank
interest is no longer credited on income not yet received), they compound, and the renter's two
year-dated job events moved to January. The acceptance test
(`TestFixedEconomyMatchesTheAnnualEngine`) pins the annual engine's net worth in years 1, 5, 10 and
20 of six households (aligned; the renter's events are excluded) and allows 1% in year 1, 2.5% through
year 10 and 3% at year 20. Taxes on given inputs are exact (the IRS goldens are unchanged); loan
payoff months are exact.

## Sequence-of-returns risk (the motivating case)

A 70-year-old with $1M in a brokerage account (0% return otherwise) spends $60k a year ($5k a month)
under a path economy with a 20% fall over three months, `(0.8)^(1/3) - 1` a month:

| Crash | Monthly engine, year-1 net worth | Annual engine |
| --- | --- | --- |
| January-March | $741,049.54 | $740,000.00 |
| October-December | $750,049.54 | $740,000.00 |

Both paths compound to the same -20% year, so the annual engine (which sees only the year's rate)
gave both retirees the same result; on the monthly engine the late crash spares the $45k sold in the
nine months before it (20% of it: $9,000). `TestSequenceOfReturns` pins the ordering.

## Timing

| Measurement | Before (annual engine) | After (monthly engine) |
| --- | --- | --- |
| Monte Carlo, 50 years, n=1000, process pool (single_renter spec, stochastic economy, 18 cores) | 6.4-7.2 s | 12.3-13.0 s (15.4 s before the balance-sheet and ledger-record optimizations) |
| One 50-year run of the same spec | 0.10 s | 0.19 s |
| Core suite (`src/life_model/tests -m "not notebooks"`) | 1004 tests, 41 s | 1049 tests, 53 s |
| Dashboard + RL + SLM suites (`-m "not slow and not notebooks"`) | 350 tests (+1 skipped), about 5.5 min | 351 tests (+1 skipped), 7 min 38 s |

The Monte Carlo slowdown is 1.7-2.0x, well inside the 10x budget; per-month balance sheets (the
monthly conservation check) were the largest new cost and are built with cached imports now.

## Plan 26 D10 (`as_of` proration)

Nothing to delete: Plan 26 did not implement it. `meta.as_of` remains informational; a part-year
first year is `meta.start` / `LifeModel(start=...)`.

## Merging Plans 29 and 30

Plans 29 (reconciliation, invariants, household goldens, backtest) and 30 (CLI, API, MCP, agent docs)
were written against the annual engine and merged into this branch afterwards. Their expected tax lines
are external truth and did not change; what changed is listed here.

The merge conflicted in five files: `model.py` (the monthly `step()` now also runs the invariant
checker: a snapshot at year start, the yearly rules at year end, and records balance sheets whenever
checks are on), `spec/validate.py` (both the start/birth checks and the actuals checks),
`docs/index.rst` (every page), `docs/units-and-conventions.md` (Plan 30's units page plus this plan's
time, money, ages and monthly-versus-annual sections, adjusted to the monthly engine) and
`montecarlo.py` (both docstring notes).

`life-model run --collect month` / `life_model.run(collect="month")` collect month-end rows and export
them; a mid-year `meta.start` works with `--years` / `--end-year` (the part first year counts as one),
`explain`, `compare` and `montecarlo`, and the run summary carries it (`start`).

### Household goldens: `early_retiree` spec inputs (no expected value changed)

The 15 other household goldens reproduce every line on the monthly engine unchanged (wages and
withholding per paycheck sum to the W-2; 1098 interest is already a month-by-month figure; the bank
interest of a balance held all year at an APY is the same whether credited yearly or monthly).

`early_retiree_2024/2025/2026` did not: the engine reported 1040 line 2b $43.76 (golden $400),
3a/3b $17,525.13 ($18,000), 1099-B $69,979.63 ($69,716.67) and so line 7a, 9-16 for 2025. The
golden's 1099s state facts the annual engine produced by timing: the savings earned a full year's
interest *and* paid the year's bills, and the fund paid 2% of its opening value in dividends *and*
funded a sale of the year's spending, at a price that had not moved. On the monthly engine the $80,000
is paid a twelfth a month, so the savings is spent in January (one month's interest) and the fund is
sold down from February (smaller dividends; a different gain). The engine is right; the spec relied on
annual timing. Its inputs now state the same facts under monthly semantics:

* spending `amount_annual: 0` plus a `one_time_expense` of $80,000 in December of the year: the household
  pays the year in one December lump, so the savings and the fund are held all year and one sale (in
  December, after the last dividend) pays it, as the 1099-B states;
* the fund's `dividend_yield_pct` is the payout that keeps its price flat while it returns 2%: with growth
  compounded monthly (`a = 1.02^(1/12)`) and quarterly dividends on the start-of-month balance, the
  price is flat over the year when each payout is `a - a^-2`, so the yield is `4 (a - a^-2)` =
  1.97863149058084% (instead of 2). The year's dividends are then exactly `900,000 x (a^12 - 1)` =
  $18,000 and the lot is worth $900,000 at the sale, so the gain is 2/3 of the proceeds.

`expected.json` is byte-for-byte unchanged (regenerated by `scripts/household_goldens.py`, whose
narrative and worksheet text now say the spending is paid in December).

### Invariants on the monthly engine

The checker still runs once a year, at the year end (after December's taxes), and reads results
only; it now also reads the year's monthly balance sheets (`model.month_balance_sheets`, recorded
whenever checks are on):

* new `monthly_conservation`: each month's net-worth change equals the ledger's net flow posted in it
  (the yearly `conservation` nets a month that gains unposted money against one that loses it);
* `continuity` also checks the gap between consecutive months (a driver acting between monthly
  `step()` calls must post what it moves); `Violation` gained an optional `month`;
* `no_negative_balances` checks every month end (each account reported once a year); a debt line seen
  only mid-year (`Debt:` labels) counts as a liability;
* `no_draw_above_cash_floor` looks at the month of each waterfall draw rather than the year end: the
  unit's banks at that month's close, less money that reached them after the month's last waterfall
  draw. Two monthly-engine facts made the year-end form wrong: a lean month's sale is legitimate when
  later months' pay refills the bank, and money can arrive after December's bills were funded by a
  sale: the long-term-care policy pays the year's claim at the year end (every `stochastic_retiree`
  seed tripped the year-end form on this), and refundable credits are refunded at settlement (a
  sampled SLM household with children).

Test changes in `test_invariants.py` are mechanical: a "year" of driver steps is `step_year()`; mocks
that inject a once-a-year violation from a monthly stage (`pre_step`) act in January only; the
"brokerage first sold in 2027" assertion compares the set of sale years (the sales are monthly now);
and the pre-Plan-26 reconstruction also restricts the bank draw order to the head's banks (the
monthly waterfall pays from `_bank_accounts_in_draw_order`, not from a sized `bank_account_balance`).
New tests cover a between-months move and offsetting unposted months.

### Backtest statements under monthly semantics

`scripts/backtest_example.py statements` (still independent of `life_model`) now computes the
synthetic 2020-2025 statements with the monthly engine's conventions: each paycheck's 401(k)
deferral and match (13% of pay a year, a twelfth a month) deposited at the start of its month,
and every account compounding the year's S&P 500 return monthly (`(1 + R)^(1/12) - 1`). The
statements moved (the 2025 401(k) from the annual convention's year-start crediting to
$478,174.32) and `life_model.backtest` reproduces every one of the 18 statements to the cent (largest
relative difference 0.0000%; acceptance is 1%). The report's timing note now gives the size of
intra-month timing instead: end-of-month deposits would read $476,693.08 in 2025 (+0.31% against
the simulated balance).

### Reconcile with a part-year start

`reconcile` runs a spec from its first simulated month, so a `meta.start` inside the reconciled year
gives a return and flows for the simulated months only; the report now says so in its notes
(`test_part_year_start_reconciles_only_the_simulated_months`: May-December pays 8/12 of the year's
wages, a January bonus is not paid, the part-year records reconcile green and a full-year record is
red on wages with the note).
