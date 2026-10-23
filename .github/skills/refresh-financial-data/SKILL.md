---
name: refresh-financial-data
description: Annual refresh of tax/retirement/Social Security constants (brackets, standard deduction, contribution limits, wage base, credits, AMT/QBI, withholding tables, ACA, Medicare, state packs, bend points, COLA, RMD rules). Use when asked to update tax data, add a new tax year, or when values in config/financial_defaults.yaml are stale.
---

# Refreshing financial data

All simulation constants live in `src/life_model/config/data/financial_defaults.yaml`, validated
by `config/models.py` (`extra='forbid'` everywhere, so a misspelled key fails at load). The point of
this skill is that refreshes are complete, sourced, and don't silently break.
`docs/configuration.md` describes every key, its source and its projection rule — read its
"Year-indexed tax parameters" and "Withholding, estimated tax and the premium tax credit" sections
first, and update its prose (year ranges, quoted amounts) along with the YAML.

## How the data is shaped

Simulated years read the **per-year table** `tax_years.<year>` through `model.year_config`
(`LifeModel.config_for_year(year)`; `FinancialConfig.year_view` copies the year onto `tax.federal`).
A new tax year is an appended `tax_years` entry. Past the last published year, indexed amounts are
inflation-projected with each statute's rounding rule (`config/financial_config.py`); statutory,
unindexed thresholds stay fixed. Some keys have a **static mirror** of the latest year
(`tax.federal.standard_deduction` / `tax_brackets` / `capital_gains`, `tax.fica`, `retirement.*`,
`accounts.hsa.*`), the fallback for module helpers; the credit and regime keys have none. The frozen
test fixture (`tests/fixtures/test_config.yaml`) lacks many of them, which leaves those features off
there — don't add live values to it.

## Values to refresh, and primary sources (never trust model memory for these)

### Indexed every year

| Config path | Values | Primary source (typical release) |
|---|---|---|
| `tax_years.<year>` core | standard deduction and brackets per status (separate = joint halved unless set), §63(f) `additional_standard_deduction`, `capital_gains` breakpoints, SS wage base, `gift_exclusion`, `ctc_per_child` / `ctc_refundable_max`, `salt` cap and phase-out threshold, `kiddie_tax`, `ltc_premium_limits`, `student_loan_phaseout`, `amt`, `qbi`, `eitc` | IRS Rev. Proc. inflation adjustments (Oct; e.g. Rev. Proc. 2025-32 for 2026); SSA COLA fact sheet (Oct) for the wage base |
| `tax_years.<year>` retirement | `limit_401k_base`, `limit_401k_catch_up`, `limit_401k_catch_up_60_63`, `limit_415c`, `limit_ira`, `limit_ira_catch_up`, `ira_phaseouts`, `savers_credit`, `qcd_limit`, `compensation_limit`, `rmd_start_age` | IRS retirement-limits notice (Nov; e.g. Notice 2025-67) |
| `tax_years.<year>` health & payroll | `limit_hsa_self` / `limit_hsa_family` (May Rev. Proc.), `limit_health_fsa`, `limit_commuter_monthly`, `dependent_care` | IRS Rev. Procs.; IRC §21/§129 as amended by OBBBA |
| `tax_years.<year>.withholding` | Pub. 15-T Worksheet 1A amounts and annual percentage-method tables; supplemental rates | IRS Pub. 15-T (Dec), Pub. 15 |
| `tax_years.<year>.premium_tax_credit`, `qualifying_relative_income_limit` | Form 8962 applicable-percentage bands, the poverty guideline the return uses, 400% cap, repayment limits; §152(d)(1)(B) amount | IRS Rev. Proc. (applicable percentage, ~Jul); HHS poverty guidelines; Form 8962 instructions |
| `tax.federal.estimated_tax.underpayment_rates` | IRS individual underpayment rate per quarter (append quarters) | IRS quarterly interest-rate news releases (IRC §6621(a)(2)) |
| static mirrors | `tax.federal.standard_deduction` / `tax_brackets` / `capital_gains`, `tax.fica.social_security_max_income`, `retirement.*`, `accounts.hsa.*` | same as the latest `tax_years` entry |
| `social_security` | AWI, COLA, bend points — **append** the new year, never overwrite history; the `last_*_year` markers | ssa.gov OACT (AWI series, COLA, bend points) |
| `healthcare.medicare` | `part_b_base_monthly_premium`, `part_d_base_monthly_premium`, every `irmaa_tiers` row (single + joint thresholds, Part B, Part D surcharge) | CMS Medicare Parts B premiums fact sheet (Nov); CMS Part D national base beneficiary premium (Jul); SSA POMS HI 01101.020 |
| `healthcare.long_term_care` | `annual_cost`, `mean_duration_years`, incidence hazard bands | Genworth/CareScout Cost of Care Survey; ASPE LTC risk studies |
| `healthcare.funeral_cost`, `final_year_medical_multiplier`, `medical_cost_bands`, `medical_inflation_premium` | end-of-life and age-banded medical costs | NFDA General Price List study (funeral); CMS NHE / MEPS (medical) |
| `tax.state.packs.<STATE>.years.<year>` | brackets or flat rate per status, state standard deduction, exemptions/credits, retirement-income and Social Security treatment, capital gains | each state's department of revenue (every pack is stamped with its sources); clear `TODO(verify)` items once the state publishes |
| `dependents` | child-cost bands | Child Care Aware, USDA/Brookings, College Board |
| `accounts.plan_529` | annual contribution limit (gift exclusion) | IRS Rev. Proc. |
| `people/mortality.py` | SSA period life table (male / female death probabilities, ages 0-119) | SSA OACT period life table, refreshed with each Trustees Report (`table4c6.html`) |

### Fixed by statute or rule — re-check only when the law changes

| Config path | Values | Source |
|---|---|---|
| `retirement.rmd_distribution_periods` | Uniform Lifetime Table (the only copy; `limits.py` reads it from config) | IRS Pub. 590-B |
| `tax.federal.senior_deduction` | first/last year of OBBBA's $6,000 deduction (2025-2028; the amount is `tax_years.<year>.senior_deduction_amount`) | OBBBA (IRC §151(d)(5)(C)) — drop or extend if Congress acts |
| `tax.federal.salt_cap_statute` | the cap's 1%/yr rise through 2029, the $10k floor, the 2030 reversion (applies past the table) | OBBBA §70120, IRC §164(b)(6) |
| `tax.federal.charitable`, `credits.education`, `credits.savers_credit_last_year` | 60% cash / 30% appreciated-property limits, carryover, non-itemizer deduction, 0.5% floor, §68 limit; §25A phase-outs; saver's credit sunset | IRC §170, §68, §25A; OBBBA; SECURE 2.0 §103 |
| `tax.federal.niit`, `capital_loss_ordinary_offset`, `mortgage_interest_*`, `tax.fica.medicare_additional_rate_threshold`, `social_security.benefit_taxation` | unindexed statutory thresholds (never projected) | IRC §1411, §1211(b), §163(h)(3), §3101(b)(2), §86 |
| `tax.federal.estimated_tax` (except the rates) | Form 2210 safe-harbor rules and the $1,000 threshold | IRC §6654 |
| `tax.self_employment` (defaults in `config/models.py`, `SelfEmploymentTaxConfig`; not in the YAML), `dependents.odc_per_dependent`, `actc_earned_income_threshold` | SE tax rules; ODC and the ACTC formula | IRC §1401-1402, §24 |
| `retirement.early_withdrawal_penalty_rate`, `accounts.hsa.non_medical_penalty_*` | 10% / 20% additional taxes and ages | IRC §72(t), §223(f)(4) |
| `debt.student_loan` | interest deduction cap; Repayment Assistance Plan tiers, credits, match, horizon, forgiveness taxability | IRC §221; OBBBA / studentaid.gov |

## Procedure

1. **Fetch each value from its primary source** (WebSearch/WebFetch the pages above). Record the
   document ID (e.g. "Rev. Proc. 2025-32 §3.01"). Avoid WebFetch for numeric tables (it summarizes
   through a small model); fetch the raw page or PDF and parse it. **ssa.gov returns 403 to
   automated clients**: use the Internet Archive raw capture
   (`http://web.archive.org/web/<timestamp>id_/https://www.ssa.gov/...`, timestamps from the CDX API),
   cross-check against the page's redundant columns, and say in the vintage stamp that the capture
   was the source.
2. **Append, don't overwrite, year-keyed tables** (`tax_years`, state pack `years`, SS AWI/COLA/bend
   points, underpayment-rate quarters). Scalar values: update in place.
3. **Stamp vintage comments** on every section touched:
   `# vintage: 2027, source: Rev. Proc. 2026-XX` — this convention is how staleness gets caught.
   Mark anything not yet published `TODO(verify)` rather than guessing.
4. **Keep the static mirror and the year table consistent.** When appending `tax_years.<year>` for a
   new latest year, update the static mirrors to match it, and grep an old value across `src/` to be
   sure nothing else carries it (`rg -n "<old number>" src/life_model`).
5. **Expect test breakage — handle it correctly.** Tests that assert dollars should use the frozen
   fixture config; one that breaks because it read live defaults should be moved to the fixture, not
   re-pinned. Tests that check the live table itself (year coverage, mirror consistency, projection
   rounding) get the new values from the source document.
6. **Household goldens.** `scripts/household_goldens.py` works each golden's return independently of
   the library from its own table of published amounts (2024-2026 today). For a new tax year, add the
   year's amounts there from the same primary sources, generate the year's goldens, and require
   `test_household_goldens.py` to pass: a mismatch means the YAML or the worksheet is wrong.
7. **Re-run the full suite and the example notebook** (see `dev-setup` and `verify-simulation`);
   commit the data change and any re-baseline separately.
8. **Sanity table in the PR/commit message**: old value → new value → source, one row per
   constant. Flag anything that moved >10% for reviewer attention.

## Known traps

- A key added to `tax_years` but missing from the Pydantic model fails at load; a key in the model
  but absent from a year leaves that feature off for the year without an error. Check the feature
  actually runs for the new year (a probe `explain` shows the credit or line).
- Projected years use each statute's rounding (`config/financial_config.py`); a new indexed key needs
  its rounding rule there, and a statutory unindexed one must be kept out of the projection.
- The 2025 Pub. 15-T tables predate OBBBA's 2025 standard deduction; projected years derive the
  withholding tables from the year's brackets instead. Re-check that this still reproduces the newly
  published tables.
