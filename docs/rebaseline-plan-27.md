# Plan 27 re-baseline log

Plan 27 lets a household be entered from its statements. It is implemented in two halves: 27a
(accounts, jobs and payroll) and 27b (housing and debt, insurance, Social Security, spending). Each
half lists here every simulated number that moved, why, and every existing test whose code or
expected values changed. No household golden's `expected.json` changed.

## 27b: housing, debt, insurance, Social Security, spending

### Sources

Every new constant was fetched on 2026-10-18 and is stamped `# vintage: <year>, source: <doc>` in
`config/data/financial_defaults.yaml` (and the matching defaults in `config/models.py`). ssa.gov blocks
automated fetches, so the SSA pages were read from web.archive.org `id_` captures (2025-2026).

| Parameter | Value | Source |
|---|---|---|
| Full retirement age by birth year | 65 through 1937; +2 months a year to 65 and 10 months (1942); 66 for 1943-54; +2 months a year to 66 and 10 months (1959); 67 from 1960 | SSA OACT Normal Retirement Age table (ssa.gov/oact/ProgData/nra.html, capture 2026-01); agrees with ssa.gov/oact/quickcalc/earlyretire.html and the Benefits Planner reduction table |
| Spousal benefit | 50% of the worker's PIA less the spouse's own PIA; reduced 25/36 of 1% a month for the first 36 months before FRA and 5/12 of 1% beyond; no delayed credits | 42 U.S.C. 402(b), 402(q); SSA earlyretire.html (a $500 spousal benefit is $350 at 62 with FRA 66, $325 with FRA 67) |
| Earnings test exempt amounts 2000-2026 | 2026: $24,480 / $65,160 ($1 withheld per $2 / per $3) | SSA OACT rtea.html (capture 2026-01-01) |
| Earnings test projection | $670 (1994 monthly) x AWI(year-2)/AWI(1992), $2,500 (2002 monthly) x AWI(year-2)/AWI(2000), to $10, not below the prior year, x 12 | SSA OACT rtdet.html (the 2026 determination reproduces $2,040 and $5,430 a month) |
| Mortgage interest | $750,000 acquisition-debt limit ($375,000 separate); $1,000,000 ($500,000) for debt incurred on or before 2017-12-15, which reduces the $750,000; home-equity interest not deductible after 2017 unless the debt bought, built or substantially improved the home; a refinance keeps acquisition (and grandfathered) status up to the refinanced balance | IRC §163(h)(3)(B), (C), (F)(i)(I), (IV), (F)(ii), as amended by P.L. 115-97 and P.L. 119-21 (law.cornell.edu/uscode/text/26/163) |
| PMI | cancellation at 80% of the original value (borrower request; by actual payments), automatic termination when the original schedule reaches 78%, final termination at the term's midpoint; "original value" is the lesser of the price and the appraisal | Homeowners Protection Act, 12 U.S.C. 4901(2), (12), (18), 4902(a)-(c) (law.cornell.edu) |
| Simplified Method | anticipated payments 360 / 310 / 260 / 210 / 160 by age at the annuity start (55 or under ... 71 or older); joint: 410 / 360 / 310 / 260 / 210 by combined age (110 or under ... 141 or older) | IRS Pub. 575 (2025), Simplified Method Worksheet Tables 1 and 2; IRC §72(d)(1)(B) |
| Basis recovery | once an annuity's basis is recovered every payment is taxable | IRC §72(b)(2) |
| Disability benefits | taxable when the employer paid the premiums (or they were pre-tax), else tax-free | IRC §104(a)(3), §105(a) |

Modeling assumptions (not published constants, so no vintage): the pension lump sum / actuarial survivor
rate (`insurance.pension.lump_sum_interest_rate`, 5%), and the delayed retirement credit stays the
configured 8% a year for every birth year (SSA's lower credits apply to births before 1943, who are past
70 in every supported start year). `TODO(verify)`: none.

### Behavior that changed for existing inputs

These change numbers only for households that use them; no shipped example or test other than the ones
listed below depends on them.

* **A mortgage's past `start_date` (spec `start_year`) is honored** when no current balance is given: the
  loan is taken to originate in January of that year and starts the run at the scheduled balance, with
  the schedule's payments made (plan item 11: a 2024 loan used to start 2026 at its full original
  amount). With a balance the old behavior is unchanged (the balance is authoritative); `origination`
  (`YYYY-MM`) is the precise input, and the validator says so.
* **Mortgage interest over the debt limit** is now limited with the year's average balance (Pub. 936's
  worksheet: interest x limit / average acquisition balance) instead of the original loan amount, so a
  jumbo loan's deductible share grows as it amortizes. A mortgage originated on or before 2017-12 gets
  the $1,000,000 limit (the engine compares months, so all of December 2017 counts). Loans under the
  limit (every example and golden) are unchanged.
* **Annuity payouts after the basis is recovered** are fully taxable (the exclusion ratio used to apply
  forever). Only annuitants who outlive the expected-payout horizon see a change.
* **Section 121**: a home bought during the run (`purchase: true`, or a `buy_home` event) or entered with
  a `purchase_year` gets no exclusion when sold within 24 months (the two-year ownership test; the use
  test is assumed met and §121(c)'s reduced exclusion is not modeled). A home owned before the run with
  no purchase year passes, as before.
* **PMI** also ends at 78% of the original schedule and at the term's midpoint (it already ended at 80%
  by balance, measured against the purchase price, which is the original value); `pmi: false` and
  `pmi_monthly` are new.
* **A loan's last payment** clears a balance below half a cent (floating-point residue) instead of
  leaving it for a ghost payment the next month.
* **Spec defaults**: `social_security.earnings_test` defaults to true (the law); `fra_from_birth_year`
  defaults to false (so the retiree-couple goldens keep the benefit they pin) and the validator warns
  (`ss_fra_by_birth_year`) for anyone born before 1960. `HomeExpenses.property_tax_pct` / `insurance_pct`
  and the loans' `original_amount` / `term_years` became optional (the statement alternatives).

### Example re-baseline

* **`retiree_couple`** sets `fra_from_birth_year: true` for both spouses (the validator would warn
  otherwise). Pat (born 1957-10, FRA 66 and 6 months) claims at 67: six months of delayed credits, PIA
  $2,919.40 -> $3,036.18 a month in 2026 (x 1.04). Lee (born 1959-04, FRA 66 and 10 months) claims at 70:
  38 months instead of 36, $3,166.09 -> $3,200.14 (x 1.25333 / 1.24). Year-end net worth 2026
  $1,774,556.01 -> $1,775,968.81; taxes 2028 $643.23 -> $728.11 (more provisional income); the split of
  Lee's 2036 end-of-life costs between Lee's bank and the estate moves by $46 (the total is unchanged).
* `married_homeowners`, `single_renter` and `self_employed`: identical yearly frames before and after
  (checked with a scratch worktree of the base: every model column, every year).

### Existing tests whose code or expected values changed

| Test | Change | Reason |
|---|---|---|
| `test_spec_io.TestSchema.test_json_schema_is_embeddable` | checks the not-yet-supported marker on `LifeInsurance` (group life) instead of `Mortgage` | every mortgage field is supported now |
| 60 core test modules, `dashboard/tests/test_dashboard.py`, `deepqlearning/tests/envs/test_financial_env.py`, `test_household_spec_parity.py`, `deepqlearning/evaluation/benchmark_env.py` | constructor calls use the canonical names (`owner=`, `rate_pct=`, `original_amount=`, `base_annual=`, ...) and keywords instead of positional arguments after the owner of a loan, annuity or pension (a mechanical AST rewrite; no expected value changed) | Plan 27 D8; the deprecated names would warn (and one, `test_engine_timing.TestMatchTiers.test_deprecated_percent_warns_and_keeps_the_legacy_formula`, captures the first `DeprecationWarning` its helper raises) |

### New tests

`test_statement_housing.py` (PR C acceptance: a 2024-03 $480,000 30-year 6.5% mortgage is $3,033.93 a
month and $470,376.52 after 21 payments; the same loan entered as balance + 339 remaining months matches
year after year; a 66-month car loan ends in month 66; consistency errors; refinance; HELOC; card
charges; home inputs; PMI; dollar property tax and insurance), `test_spec_statement_housing.py`,
`test_statement_insurance.py` (PR D acceptance: a whole-life policy with $20k cash value and a $5k loan;
a spousal benefit of $1,500 beats a $600 own benefit; a 100/80/70% age schedule reproduces the entered
totals; plus annuities in payout, pensions, health and disability policies, FRA, the earnings test),
`test_spec_statement_insurance.py` and `test_deprecated_names.py`.
