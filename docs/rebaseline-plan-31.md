# Plan 31 re-baseline log (tasks 1-5; Part 2: tasks 6-7)

Plan 31 adds the credits, deductions and regimes real returns need (see
[reconciliation.md](reconciliation.md) for the line coverage and [configuration.md](configuration.md)
for the parameters). Wherever a missing deduction or credit now applies, simulated numbers move; every
change is listed here with its reason. Tests whose expected values changed are listed with the old and
new values; **no IRS-golden tax-function test (`test_irs_golden.py`) changed**.

## Sources

Every new constant was fetched on 2026-10-18 from irs.gov (Rev. Procs. 2023-34 §3, 2024-40 §2,
2025-32 §4; Notices 2023-75, 2024-80, 2025-67; Pub. 560, Pub. 526, Pub. 590-A/B, Pub. 596, Pub. 970;
Forms 2441, 6251, 8801, 8812, 8814, 8863, 8880, 8959, 8995 and Schedule SE with their instructions),
the OBBBA text (P.L. 119-21, congress.gov / govinfo) and the Internal Revenue Code; each YAML entry is
stamped `# vintage: <year>, source: <doc>`. The 2024 EIC Table method (the §32 formula at each $50
row's midpoint, the kink rows at the maximum) reproduces all 1,329 rows x 8 columns of the published
2024 table. The 2025-2026 Rev. Proc. numbering is `§2.xx` (Rev. Proc. 2024-40) and `§4.xx` (Rev. Proc.
2025-32).

| Parameter | 2024 | 2025 | 2026 | Source |
|---|---|---|---|---|
| EITC earned income amount (0/1/2/3+) | 8,260 / 12,390 / 17,400 / 17,400 | 8,490 / 12,730 / 17,880 / 17,880 | 8,680 / 13,020 / 18,290 / 18,290 | Rev. Proc. §32 table |
| EITC maximum credit | 632 / 4,213 / 6,960 / 7,830 | 649 / 4,328 / 7,152 / 8,046 | 664 / 4,427 / 7,316 / 8,231 | same |
| EITC phase-out start (other; joint) | 10,330 / 22,720; 17,250 / 29,640 | 10,620 / 23,350; 17,730 / 30,470 | 10,860 / 23,890; 18,140 / 31,160 | same |
| EITC investment income limit | 11,600 | 11,950 | 12,200 | same (§32(i)) |
| AMT exemption (single / joint / separate) | 85,700 / 133,300 / 66,650 | 88,100 / 137,000 / 68,500 | 90,100 / 140,200 / 70,100 | Rev. Proc. §55 |
| AMT phase-out start; rate | 609,350 / 1,218,700; 25% | 626,350 / 1,252,700; 25% | 500,000 / 1,000,000; 50% | Rev. Proc.; OBBBA §70107 |
| AMT 28% breakpoint (separate) | 232,600 (116,300) | 239,100 (119,550) | 244,500 (122,250) | Rev. Proc. |
| QBI threshold (single / joint / separate); range | 191,950 / 383,900 / 191,950; 50k/100k | 197,300 / 394,600 / 197,300; 50k/100k | 201,750 / 403,500 / 201,775; 75k/150k, $400 minimum | Rev. Proc.; OBBBA §70105 |
| Kiddie tax base (Form 8814) | 1,300 | 1,350 | 1,350 | Rev. Proc. §1(g) |
| Student loan interest phase-out (single; joint) | 80-95k; 165-195k | 85-100k; 170-200k | 85-100k; 175-205k | Rev. Proc. §221 |
| LTC premium limits (<=40/50/60/70/>70) | 470 / 880 / 1,760 / 4,710 / 5,880 | 480 / 900 / 1,800 / 4,810 / 6,020 | 500 / 930 / 1,860 / 4,960 / 6,200 | Rev. Proc. §213(d)(10) |
| IRA deduction phase-out (single covered; joint covered; spouse covered) | 77-87k; 123-143k; 230-240k | 79-89k; 126-146k; 236-246k | 81-91k; 129-149k; 242-252k | IRS notices |
| Roth phase-out (single; joint) | 146-161k; 230-240k | 150-165k; 236-246k | 153-168k; 242-252k | IRS notices |
| Saver's credit ceilings, joint (50/20/10%) | 46,000 / 50,000 / 76,500 | 47,500 / 51,000 / 79,000 | 48,500 / 52,500 / 80,500 | IRS notices (HoH 3/4, others 1/2) |
| QCD limit | 105,000 | 108,000 | 111,000 | IRS notices (§408(d)(8)) |
| §401(a)(17) compensation limit | 345,000 | 350,000 | 360,000 | IRS notices |
| §129 exclusion; §21 rate | 5,000; 35% to 20% | 5,000; 35% to 20% | 7,500; 50% to 35%, then to 20% from 150k (75k) | IRC §21, §129; OBBBA §§70404-70405 |

Statutory and unindexed: AOTC/LLC (§25A: 100% of $2,000 + 25% of $2,000, 40% refundable; LLC 20% of
$10,000; phase-out 80-90k / 160-180k), the credit for other dependents ($500, §24(h)(4)), the
additional child tax credit (15% of earned income over $2,500), the 30% limit on appreciated property
(§170(b)(1)(C)), the 2026 charitable rules (§170(p) $1,000 / $2,000; §170(b)(1)(I) 0.5% floor; §68
2/37), self-employment tax (92.35%, 12.4% / 2.9%, $400), SEP 25% (Pub. 560 rate table 20%), the
saver's credit sunset after 2026 (SECURE 2.0 §103). `TODO(verify)`: none; the 2027+ projection
roundings follow each statute's rounding rule but are projections (`financial_config._project_plan31_params`).

## Data fix

| Parameter | Old | New | Source |
|---|---|---|---|
| `dependents.ctc_qualifying_age_max` | 17 (a 17-year-old got the CTC) | 16 (inclusive: under 17 at year end) | IRC §24(c)(1) |
| `debt.student_loan` deduction | per person (a joint return with two borrowers deducted up to $5,000) | per return, $2,500, phased out by MAGI | IRC §221(b) |

## Bug found by a new golden: the `contribute` event did not conserve money

`spec/events.py`'s `contribute` debited the bank without posting it while the account posted the
contribution as new money from outside; the invariant checker's conservation rule flagged it on the
`ira_deduction_phaseout` golden. The debit is now posted bank by bank as a transfer into the account.
Balances are unchanged; only the ledger differs.

## Existing tests whose expected values changed

| Test | Old | New | Reason |
|---|---|---|---|
| `test_deductions.TestSeniorDeduction.test_reduces_settled_federal_tax` (single 70-year-old, $60,000, 2026) | federal $4,300 | $4,054 | the §63(f) $2,050 is now deducted: taxable 35,850 -> 1,240 + 12% x 23,450 |
| `test_deductions.TestCharitableLimit.test_gifts_capped_at_sixty_percent_of_agi_with_carryforward` (2026) | carryforward `[(2026, 10000)]`, itemized charity 30,000 | `[(2026, 10250)]`, 29,750 | OBBBA's 0.5%-of-AGI floor ($250 of $50,000) applies from 2026, and in a year with a carryover the floor amount joins it (§170(d)(1)(C)) |
| `test_tax_return.assert_return_reconciles` (identities, used by several whole-household tests) | `deduction = max(standard, itemized) + senior`; `federal = ordinary + preferential + NIIT + AMT - credits + penalties`; `total = federal + state + SS + Medicare`; Medicare = sum of FICA lines | the deduction adds the non-itemizer charitable deduction (with the standard) and QBI; federal adds the Form 8814 tax; total adds self-employment tax; the FICA lines exclude the Additional Medicare Tax on SE income; credits split into nonrefundable / refundable sums | the return has those lines now |
| `test_api`, `test_cli` (2), `test_main`, `test_mcp` (2), `test_spec_io` (3) | the `self_employed` example was the invalid (not-yet-supported) spec | a spec with a `birth` month (Plan 32 D4) plays that part (`spec_helpers.not_yet_supported`); `self_employed` is runnable and validates cleanly | Plan 31 makes self-employment buildable |
| `test_privacy` allowlist | — | adds tax-form words (Schedule, Part, SE, SEP, FSA, Pub, American, III) | the new goldens' descriptions |
| `slm/tests/test_evaluate_adviser.py::test_rationale_of_matches_build_rationale` | compared `rationale_of(scored)` with the rationale of `argmax_candidate(scored)` | with the rationale of `label_decision(scored)` (what `rationale_of` explains by definition) | the test assumed the label equals the argmax; with Plan 31's taxes the sampled household's best-scoring plan (`save0_split_claimret_conventional`) and its evidence-backed label (`save0_roth_claimret_conventional`, within noise) differ, which `label_decision` allows by design |

## Household goldens

* `retiree_couple_2024/2025/2026`: the §63(f) expected failures are removed (the engine now matches the
  hand-worked lines; e.g. 2024 line 15 $94,125.47 instead of the engine's former $97,225.47). The
  2026 IRMAA expected failure stays (Plan 27).
* `married_homeowners_2026`: the golden script applies OBBBA's 0.5% floor to the $6,000 of cash gifts:
  Schedule A line 11 $6,000 -> $4,714.25, line 17 / 1040 line 12e $49,950 -> $48,664.25, line 15
  $207,200 -> $208,485.75, line 16 $35,008 -> $35,290.87, line 24a $30,893.20 -> $31,176.07.
* Every golden with a child tax credit gains Schedule 8812 line 14; worksheets reword a few lines
  (Form vs Schedule labels, the 60% note). No other golden line changed.
* New: twelve Plan 31 households (see the goldens README).

## Simulation outputs (probe: the packaged examples and the test scenarios, before and after)

Run on `fourth-wave` (f66307f) and on this branch in a scratch worktree; every difference traces to a
Plan 31 item:

| Run | What moved | Why |
|---|---|---|
| `retiree_couple` example | deduction +$5,300 a year (2026), taxes lower from 2028 | §63(f) for two people 65+ ($1,650 each in 2026) and the senior deduction already there |
| `married_homeowners` example | from 2032: CTC $2,600 -> $500; 2033-2036: education credits $2,500 a year, credit for other dependents $500; final net worth +$62,455 (2072) | the child turns 17 in 2032 (CTC age fix, now the $500 credit for other dependents), then is a college student: the AOTC with $4,000 a year kept out of the 529 draw |
| `single_renter` example | AGI +$31 in 2027, 2029, ... | the student loan interest deduction now phases out (MAGI near $85,000) |
| `married_homeowners` scenario | 2026 dependent care credit $600; later years a few dollars | a child under 6 with two earners (childcare band = care expenses) |
| `stochastic_retiree` scenario | deduction +$3,050 in 2026 (§63(f) $2,050 + the $1,000 non-itemizer charitable deduction); final net worth +$198k | lower taxes compound over 40 years |
| `mortality_and_estate` scenario | deduction +$3,300 (two 65+), taxes lower | §63(f) |
| `renter_buys_home` scenario | AGI +$2,500 (2026), federal +$600; final net worth -$65k | the student loan interest deduction phases out above $100,000 of MAGI (single) |
| `everything_stochastic` scenario | itemized charity reduced by the 0.5% floor (2026+), AGI +$2,330 (student loan phase-out), the retiree member +$2,050 (§63(f)) | as above |

The example notebook stores no outputs, so it needs no re-baseline (it executes cleanly). All four
packaged examples, including the now-buildable `self_employed` one, run 50 years under
`LifeModel(checks="strict")` with no invariant violation.

## Merging Plan 32 (the monthly engine)

`fourth-wave` (Plan 32's monthly engine) was merged into this branch after tasks 1-5 were written. No
golden's expected values changed, and no Plan 31 golden needed a spec-input restatement.

Conflicts (resolved in the merge commit): `work/job.py`, `people/tax_unit.py`,
`account/traditional_IRA.py`, `charity/donation.py`, `dependents/child.py`, `spec/validate.py`,
`tax/deductions.py`, `docs/index.rst`, `docs/constructor-cheatsheet.md` (regenerated). How each Plan 31
feature runs on the monthly engine:

* **Self-employment** (`Job(kind="self_employed")`): the month's net profit (a twelfth of receipts less
  a twelfth of expenses, plus the bonus month's bonus) is paid to the bank every month like a paycheck,
  with no withholding (task 6). The owner's **SEP / solo 401(k) contributions are made with the December
  payment**, figured on the year's profit and the year's W-2 Social Security wages (Pub. 560's worksheet
  works on the year's net earnings; SEP and profit-sharing deposits may be made until the filing
  deadline and a sole proprietor's deferral is figured on the year's earned income), and limited to the
  cash on hand. A self-employed job that ends before December makes no contribution that year.
* **Dependent-care FSA**: a twelfth of the election comes out of each paycheck (wages, FICA wages and
  the Social Security record), and the year-to-date paycheck sums carry it.
* **QCD**: the RMD is set at the year start and paid in twelfths (Plan 32); the IRA makes the year's QCDs
  in the year-start stage, with the year's donations, when the owner is 70½ by exact age that month,
  and pays the rest of the RMD (required less QCD) in twelfths. A donor not yet 70½ in the first month
  gives in cash.
* **Stock gifts, ISO / NSO exercises, LTC premiums**: at the year start (Plan 32's timing for donations,
  vests and premiums); monthly conservation and the month-level `no_draw_above_cash_floor` hold.
* **Children**: the dependent care and education expenses accumulate month by month over the year; the
  529 keeps the year's first $4,000 of college costs out of its draws for the AOTC.
* **Settlement**: Plan 32 settles taxes only in December; Plan 31's year-end adjustments
  (`post_year_end_adjustments`) replace its student-loan block there.

Age rules (every Plan 31 test uses the age at the end of the tax year, `Person.age_in(year)`, except the
QCD's exact-age test at the distribution): the §63(f) amount (65 by December 31) was reading the current
month's completed age and now reads the year-end age, as do the EIC's 25-64 test, the saver's credit's
18 and the §213(d)(10) long-term care premium age band. (The senior deduction already used
`age_in(year)` after Plan 32.)

Engine/reporting fix found by the goldens on the monthly engine: `reconciliation._w2_simulated` read the
dependent-care FSA from the last booked paycheck (December's twelfth), so W-2 boxes 1, 3, 5 and 10 of
`dependent_care_mfj` were off by eleven twelfths of the election; it now reads the year's paychecks.

Test changes: `test_plan31_household.py` advances a year with `step_year()` (a `step()` is a month);
`spec_helpers.not_yet_supported()` uses a job `end_year` (Plan 27 D3) because Plan 32 made `birth`
supported.

# Part 2: tasks 6 and 7 (withholding, estimated payments, the premium tax credit, residency, states, filing statuses)

Tasks 6 and 7 add tax payments during the year (D3), the ACA premium tax credit, residency timelines and
part-year state returns (D4), eleven state packs and the qualifying surviving spouse and qualifying-relative
statuses (D5). Withholding and estimated payments are opt-in: **a household without them settles exactly as
before** (a December lump through the sized waterfall), and every packaged example spec still runs that way.
Existing goldens' `expected.json` values did not change.

## Sources (fetched 2026-10-18)

| Parameter | Source |
|---|---|
| Withholding: Worksheet 1A (Step 1g $12,900 / $8,600), the annual percentage method tables (standard and Step 2 checkbox) for 2024, 2025, 2026 | IRS Pub. 15-T (2024, 2025, 2026); the 2025 tables predate OBBBA's 2025 standard deduction (they are what employers used) |
| Supplemental wages 22% (37% over $1,000,000); FICA 6.2% to the wage base and 1.45% per employer, 0.9% Additional Medicare Tax withheld over $200,000 per employer | IRS Pub. 15 (2024-2026) sections 7 and 9; IRS Additional Medicare Tax Q&A |
| Estimated tax: 90% / 100% / 110% (prior-year AGI over $150,000; $75,000 separate), $1,000, due dates | IRC §6654(d), (e); Instructions for Form 2210 (2024, 2025); Form 1040-ES (2024-2026) |
| Underpayment rates by quarter: 2024 8%; 2025 7%; 2026 7 / 6 / 7 / 7% | IR-2023-219, IR-2024-47, -138, -220, IR-2024-290, IR-2025-29, -59, -87, IR-2025-112, Rev. Rul. 2026-5, Rev. Rul. 2026-10, IR-2026-98 |
| Form 2210 penalty worksheet rate periods (April 16-June 30, July-September, October-December, January 1-April 15) | Instructions for Form 2210 (2024, 2025), Worksheet for Part III Section B |
| Premium tax credit 2024-2025: 0 / 0-2 / 2-4 / 4-6 / 6-8.5 / 8.5%, no 400% cap; repayment limits $375/$750, $950/$1,900 ($975/$1,950), $1,575/$3,150 ($1,625/$3,250) | Instructions for Form 8962 (2024, 2025) Tables 2 and 5; Rev. Procs. 2023-34 §3.07, 2024-35 §2.01, 2024-40 §3.07; 26 CFR 1.36B-3(g) (rounding) |
| Premium tax credit 2026: 2.10 / 3.14-4.19 / 4.19-6.60 / 6.60-8.44 / 8.44-9.96 / 9.96%, the 400% cap, no repayment limit | Rev. Proc. 2025-25 §3.01 (no extension of the enhanced credit enacted through P.L. 119-124, 2026-10-15); OBBBA (P.L. 119-21) §71305; 2026 draft Form 8962 |
| Poverty guidelines (48 states + DC): 2023 $14,580 + $5,140 (2024 returns), 2024 $15,060 + $5,380 (2025), 2025 $15,650 + $5,500 (2026) | HHS ASPE; Instructions for Form 8962 Table 1-1; IRC §36B(d)(3)(B) |
| Qualifying relative gross income limit $5,050 / $5,200 / $5,300 | Rev. Procs. 2023-34 §3.24, 2024-40 §3.24, 2025-32 §3.23 |
| Qualifying surviving spouse; head of household for a dependent parent | IRC §2(a), §2(b)(1)(B); Pub. 501 |
| The ten next-largest states without a pack (OH, GA, NC, MI, NJ, VA, AZ, TN, IN, MO) and Maryland (11th; 10th in Vintage 2024) | Census Bureau Vintage 2025 state population estimates (NST-EST2025) |
| OH | Ohio Department of Taxation 2025 IT 1040 instructions; ORC 5747.02(A)(3), 5747.025 (HB 96); LSC HB 96 final analysis |
| GA | Georgia DOR 2025 IT-511 booklet; HB 463 (2026; O.C.G.A. 48-7-20, -26, -27); 2026 Employer's Tax Guide |
| NC | NCDOR 2025 D-401 instructions; G.S. 105-153.5, 105-153.7; S.L. 2026-41 §44.1; 2026 NC-30 |
| MI | Michigan Treasury 2025 MI-1040 instructions; Form 446 (2026 withholding guide) |
| NJ | NJ Division of Taxation 2025 NJ-1040 instructions; 2026 NJ-1040-ES instructions; GIT-1 & 2 (January 2026) |
| VA | Virginia Tax 2025 Form 760 instructions; 2026 Form 760ES; Va. Code 58.1-322.03 |
| AZ | Arizona DOR 2025 Form 140 instructions; 2026 Form 140ES instructions; A.R.S. 43-1041, 43-1023; Laws 2026 ch. 140 |
| TN | Tennessee Department of Revenue (Hall income tax repealed from 2021; GEN-34), read from Internet Archive captures (tn.gov returns 403 to automated fetches) |
| IN | Indiana DOR 2025 IT-40 booklet; Departmental Notice #1 (2026) |
| MO | Missouri DOR 2025 MO-1040 instructions; 2026 MO-1040ES; RSMo 143.121 |
| MD | Comptroller of Maryland 2025 Resident Tax Booklet; 2026 withholding memo and Employer Withholding Guide |
| CA (corrected 2025, new 2026, head of household, exemption credits) | FTB 2025 California Tax Rate Schedules and Form 540 / 540NR booklets; FTB Tax News October 2026 |
| NY (head of household 2025; 2026 rates) | NYS DTF IT-201-I (2025); IT-2105-I (2026) |

**TODO(verify)** (not published by 2026-10-18; the value used is stated): the 2027 first-quarter underpayment
rate (7% assumed; it reaches a 2026 penalty's last rate period); the IR numbers of the 2026 Q2 / Q3 rate
announcements (the rates are from Rev. Ruls. 2026-5 and 2026-10); the 2026 Form 8962 instructions (table and
poverty line follow Rev. Proc. 2025-25 and the statute); Ohio's 2026 exemption amounts (indexing suspended:
2025's); North Carolina's 2026 child deduction table (2025's); Maryland's 2026 joint / head-of-household
standard deduction ($6,850 by TG §10-217(c)) and pension exclusion (2025's $41,200); Arizona's 2026 standard
deduction (the federal amount, A.R.S. 43-1041(H)); California's 2026 exemption-credit phase-out thresholds
(2025's). The Form 2210 short method has not been printed since tax year 2020: the engine uses the regular
method (exact, and what the instructions require).

## Data fix

| Parameter | Old | New | Source |
|---|---|---|---|
| CA brackets ("2025") | the 2024 schedules (single 10,756 / 25,499 / ...; two thresholds mistyped: 70,612 for 70,606, 141,224 for 141,212) | 2025: 11,079 / 26,264 / 41,452 / 57,542 / 72,724 / 371,479 / 445,771 / 742,953 (joint 22,158 / ...); 2026: the October 2026 indexing; head of household (Schedule Z) added | FTB 2025 tax rate schedules; FTB Tax News October 2026 |
| CA credits | none | personal ($153 / $158 per filer), senior and dependent ($475 / $491) exemption credits with the AGI phase-out | 2025 Form 540 booklet |
| NY | 2025 single / joint only | 2025 head of household and the $1,000 dependent exemption; 2026 rates (3.9-5.9% on the first five brackets) | IT-201-I (2025), IT-2105-I (2026) |
| Head of household | an unmarried member with a child under 18 | a qualifying child (under 19 at year end, or a student under 24), or a qualifying relative | IRC §2(b), §152(c)(3) |

## Behavior changes

* **Unknown states** raise `UnknownStateError` when a `Person` is built (and in a spec, as before, a validation
  error); `get_pack` no longer falls back to `DEFAULT` for an unknown code. `state=None` still means
  `default_state` (`DEFAULT`). The dashboard, the RL households and the `married_homeowners` example now name
  `DEFAULT` explicitly (same numbers).
* **Bank-sourced contribution plans hold back unpaid tax.** A plan used to hold back the year's tax only in
  December, so a household without withholding contributed January-November and sold the contributions back to
  pay the year's taxes (`TestContributionHoldBack.test_no_december_sell_back`: on fourth-wave 1cd3555 that
  household sold $25,209 of the brokerage in December; now nothing is sold). Each month now keeps last year's
  balance due (until April) and the month's share of the year's projected tax not yet withheld or paid.
* **Marketplace health policies** pay their premium monthly while covered (other policies still pay the year's
  premium in January).

## Existing tests whose inputs or expected values changed

| Test | Old | New | Reason |
|---|---|---|---|
| `test_plan27_interactions.TestContributionsAfterSpendingCategories` (2 tests) | $60,000 salary; contributions $1,000 a month | $90,000 salary; contributions = pay - spending - a twelfth of the year's tax (derived from the same household's year) | the plan now holds back the unwithheld tax; at $60,000 the year's tax ($13,590) exceeded the $12,000 left over, so the old expectation (contribute everything, then sell it back in December, which the test avoided by stopping in November) no longer applies |
| `test_spec_validate.TestModelValidation.test_model_errors` | `Person(state="ZZ")` built, `unknown_state` reported by `model.validate()` | constructing it raises `UnknownStateError`; the validator still reports a timeline edited past the constructor | D4 |
| `test_spec_validate.TestSpecErrors.test_unknown_state` | `default_state: AZ` (unpacked) | `WY` | AZ has a pack |
| `test_properties.TestFederalAndStateBracketEnginesAgree` | scenario overrides the CA pack's brackets | overrides a new `WY` pack | CA's pack is year-keyed (an override of its top-level rows is invalid) |
| `dashboard/tests/test_dashboard.py::test_state_dropdown_maps_to_person_state` | `DEFAULT` maps to `None` | `"DEFAULT"` | D4: explicit |
| `test_privacy` | — | allows state codes, months, "ACA", "NR", "Texas"; `dependents[]` names are people | the new goldens |

No IRS-golden or household-golden expected value changed.

## Household goldens

New (worked by `scripts/household_goldens.py`, independent of the library): `withholding_single`,
`estimated_payments_penalty`, `aca_ptc_early_retirees`, `qss_widow`, `hoh_dependent_parent` (2024-2026);
`part_year_mover` and `state_oh`, `state_ga`, `state_nc`, `state_mi`, `state_nj`, `state_va`, `state_az`,
`state_tn`, `state_in`, `state_mo`, `state_md` (2025-2026). See the goldens README.

## Simulation outputs (the packaged examples and the test scenarios, before and after)

Run on `fourth-wave` (1cd3555) and on this branch:

| Run | What moved | Why |
|---|---|---|
| `single_renter` example (CA) | state tax about $400 lower a year (2026: $3,574.93 -> $3,174.16) | California's 2026 schedule (the old pack carried 2024's) and the $158 personal exemption credit |
| `married_homeowners` scenario (CA, joint) | 2026 state tax $15,440.85 -> $13,657.31, federal +$392 (a smaller SALT deduction); final net worth +$243,434 | the same CA corrections (joint schedule, two personal credits, dependent credits) |
| `renter_buys_home` scenario | 2049-2052 head of household instead of single (federal 2049 $24,458.70 -> $14,286.41: a smaller brokerage sale to pay a smaller tax); final net worth +$183,821 | the child is a college student aged 18-21, a qualifying child for head of household (the old rule required under 18) |
| `married_homeowners`, `retiree_couple`, `self_employed` examples; `mortality_and_estate`, `stochastic_retiree`, `everything_stochastic` scenarios | nothing | no CA, no 18-23-year-old students, no withholding |

Every example spec runs 50 years under `checks="strict"` (stochastic economy and mortality, seeds 1 and 2)
as written and with every W-2 job withholding by a default W-4 (the self-employed paying safe-harbor
estimates), with no violation (`test_plan31_payments.TestExamplesWithAndWithoutWithholding`).

## Deviations from the plan (and why)

* **Ledger shape.** Withholding is posted monthly and estimated payments in their months as tax outflows; in
  December the remainder of each tax line is accrued to the head's `TaxDue:` liability (or `TaxRefund:` asset),
  and April's payment is a transfer into it. So the year's tax outflows in the ledger equal the return's
  liability (as before), net worth recognizes the balance due in December, and the cash leaves in April. The
  plan's "four quarters" are monthly paychecks plus quarterly estimates.
* **Estimated payments are federal.** State estimates are not modeled: a state balance due waits for April.
* **First year's penalty.** Without last year's return (the first simulated year) the prior-year safe harbor is
  assumed met unless `estimated_payments.prior_year_tax` is given.
* **Withholding status.** A default W-4's filing status follows the return (a two-earner couple each withholding
  as married, without Step 2's checkbox, under-withholds, as real W-4s do).
* **Penalty method.** The regular method (Form 2210 no longer prints the short method).
* **Part-year returns** use the income-ratio method for every state (California's 540NR and New York's IT-203
  method; others approximated).
* **Eleven packs, not ten**: Missouri and Maryland swap places between Census vintages, so both were added.
* **QSS before the run** needs `widowed_year` (`Person(widowed_year=)`); a death during the run sets it.
* **The premium tax credit's household income** is the filers' (dependents' own MAGI is not modeled); a
  married couple filing separately gets none (the domestic-abuse exceptions are not modeled).
