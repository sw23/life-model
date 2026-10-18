# Plan 31 re-baseline log (tasks 1-5)

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
