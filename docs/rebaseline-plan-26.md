# Plan 26 re-baseline log

Every existing test whose expected value, or whose inputs, changed while implementing Plan 26
(engine timing, events and settlement correctness) is listed here with the reason. Tests that did
not change are not listed. New tests live in `src/life_model/tests/test_engine_timing.py`.

## Task 1 / D1 — constructor `age` is the age during the first simulated year

Before: `Person.pre_step` incremented `age` before the first year ran, so a person built with
`age=40` was 41 in the first simulated year (and every age-dated rule fired one calendar year
early relative to the constructor value). After: the person is 40 in the first year, 41 in the
second, and `get_year_at_age(a) == start_year + (a - age)`.

Tests whose scenario depends on a person reaching an age inside a short window (mostly
`death_age` deaths that must happen in the first simulated year) were re-baselined by **adding 1
to every constructor `age` in the test**, which reproduces exactly the simulated ages of the old
run. The expected values are unchanged; only the inputs moved.

| Test | Old input | New input | Reason |
| --- | --- | --- | --- |
| `test_annuity.py::TestJointAndSurvivor::_couple` (all J&S tests) | husband 70, wife 68 | 71, 69 | D1: same simulated ages as before |
| `test_annuity.py::TestAnnuityDeathTerms::_owner_with_heir` | owner `death_age - 2`, heir 40 | `death_age - 1`, 41 | D1: owner still dies in the second year |
| `test_child.py::TestChildSurvivesParentDeath::test_death_reassigns_child_to_inheritor` | parent 40, guardian 38 | 41, 39 | D1: parent still dies (death_age 41) in year 1 |
| `test_end_of_life_costs.py::TestEndOfLifeCosts::_run_death` (all four tests) | decedent 79, child 50 | 80, 51 | D1: death at 80 in year 1 |
| `test_engine_correctness.py::TestRetirementCrossing::test_non_integer_retirement_age_triggers` | 64 | 65 | D1: the test's comments ("age 65 -> still working") hold again |
| `test_inherited_account.py::_parent_child_model` and `test_401k_pretax_balance_follows_ten_year_rule` | parent 79, child 40 | 80, 41 | D1: death at 80 in year 1 |
| `test_mortality_death.py::TestMortalityModes::test_fixed_age_death` | 60 | 61 | D1 |
| `test_mortality_death.py::TestEstateTransferToSpouse::test_spouse_inherits_bank_and_death_benefit` | 74, 74 | 75, 75 | D1 |
| `test_mortality_death.py::TestEstateTransferNonSpouse::test_nonspouse_pretax_inheritance_is_taxed` | 79, 40 | 80, 41 | D1 |
| `test_mortality_death.py::TestPerAccountBeneficiary::_family_with_designated_ira`, `test_nonspouse_designation_stays_in_estate_tax_base`, `test_spousal_residual_alone_still_untaxed` | 69/68/40 and 75/74/40 | 70/69/41 and 76/75/41 | D1 |
| `test_mortality_death.py::TestPensionSurvivorAtDeath::_couple` and `test_nonretired_survivor_receives_benefit_immediately` | 74/74 and 70/49 | 75/75 and 71/50 | D1 |
| `test_pension.py::TestPension::test_no_cola_before_eligibility` | 63 | 64 | D1: still eligible only in the final year |
| `test_trust.py::TestTrustEstateIntegration` (`_dying_grantor_with_trust`, `test_revocable_pays_out_to_beneficiaries_outside_the_will`, `test_revocable_trust_with_predeceased_beneficiaries_escheats_to_residual`) | grantor 75 (death 76), others 40/74/45/50 | 76, 41/75/46/51 | D1 |

## Task 2 / D2–D3 — events stage, `created_year`, past events

No existing test's expected value changed. `LifeEvents` was never exercised by the suite; its new
behaviour is pinned in `test_engine_timing.py` (`TestEventsStage`, `TestCreatedYear`,
`TestPastEvents`).

## Task 3 / D4 — household payment waterfall

No existing test's expected value changed. New behaviour pinned in `TestHouseholdWaterfall`,
`TestRothBasisBeforePretax` and `TestMidYearPurchaseUsesHouseholdWaterfall`. Probe 4 (married
homeowners, 401k, brokerage) now sells $0 of brokerage in every year (before: $3.7k–$34k a year
with $140k–$382k sitting in the bank).

## Task 4 / D5 — bank interest is income

No existing test's expected value changed (the default economy's cash yield is 0%, so only
accounts with an explicit `interest_rate` earn interest). Bank interest now accrues in the `step`
stage at priority -10 (before settlement, like investment growth) instead of at priority 0 after
the usual-construction-order settlement, so an account with a non-zero rate earns interest on its
balance before the year's bills are paid rather than after; the interest is posted to the ledger
as `IncomeType.INTEREST` and taxed. Probe 5: $1M at 5% now pays $16.4k–$18.0k more tax a year
than at 0% (before: identical taxes).

## Task 5 / D6 — Social Security taxed at settlement (and Task 10: one tax path)

No existing test's expected value changed. `SocialSecurity.pre_step` now records the gross
benefit (`IncomeLedger.add_social_security`, an `SS_BENEFIT` entry whose `amount` starts at 0)
and `TaxUnit` sets the taxable share from the unit's provisional income at the top of every tax
computation. `SocialSecurity._taxable_benefit_portion` keeps its signature (a single-person view
now also counting preferential income and tax-exempt interest); the tests that call it
(`test_social_security.py`, `test_married_filing_separately.py`) pass unchanged.
`Person.get_income_taxes_due` is now `TaxUnit([person]).get_income_taxes_due` (the
`TaxCalculationService` and `test_state_tax.py` callers pass unchanged).

## Task 6 / D7 — 401k match tiers, vesting, year-indexed 415(c)

No existing test's expected value changed: `company_match_percent` keeps its legacy formula (a
percent of the deferral, capped at that percent of pay) and now emits a `DeprecationWarning`
naming the `match_tiers` equivalents. The 415(c) annual-additions limit is read from
`model.year_config`; `tax_years` gained `limit_415c` (2022 $61,000 … 2026 $72,000, IRS) and
projects it in $1,000 steps. The dashboard's "Company Match" slider now means a dollar-for-dollar
match up to that percent of pay (`match_tiers=[(100, pct)]`), changing dashboard outputs for any
non-zero match (the default 3% with a 6% deferral: $180 → $3,000 of match on $100k).
`Job.retire()` is now idempotent (a second call no longer logs a second "retired" event).

## Task 7 / D8–D9 — level term premiums, annuity defaults

These tests pinned the default age-banded term pricing that D8 removes. Their *intent* is the
age-band mechanics, so they now ask for it explicitly; one expected value changed:

| Test | Old | New | Reason |
| --- | --- | --- | --- |
| `test_life_insurance.py::TestLifeInsurance::test_age_based_premium_increases` | default premium (age-banded) | input `premium_increase_rate=PremiumIncreaseType.AGE_BANDED` | D8: age bands are opt-in |
| `test_life_insurance.py::TestLifeInsurance::test_default_age_multipliers` | default policy carries the config multipliers | input `AGE_BANDED` (same expected multipliers) | D8 |
| `test_life_insurance.py::TestLifeInsurance::test_update_term_life_premiums_method` | default policy | input `AGE_BANDED` | D8 |
| `test_life_insurance.py::TestLifeInsurance::test_premium_increase_rate_types` (None branch) | `premium_increase_type == AGE_BASED`, non-empty multipliers | `== LEVEL`, `age_multipliers == {}` | D8: None means level (pinned the bug) |
| `test_annuity.py::TestTermLifeMultipliersFromConfig::test_age_multipliers_come_from_config` | default policy | input `AGE_BANDED` | D8 |

`PremiumIncreaseType.AGE_BASED` remains as an alias of the new `AGE_BANDED`. No annuity test
changed: every FIXED/VARIABLE test already passed an explicit `payout_start_age`. Probe 6: a $50/mo
level term policy now costs $600 every year (was $600, $1,344, $1,428, $1,512); a $100k FIXED
annuity at age 40 stays in accumulation (was fully annuitized in year 1).
