# Household goldens (Plan 29 D3)

Synthetic households whose full-year federal return was worked from the IRS forms, independently of
the library, for 2024, 2025 and 2026. They are the external ground truth for the tax engine:
`test_household_goldens.py` reconciles each one and requires every line to match.

| Household | Exercises |
|---|---|
| `single_renter` | W-2 with a pre-tax 401(k) deferral, savings interest, student loan interest over the $2,500 cap (Schedule 1 line 21), Tax Table |
| `married_homeowners` | married filing jointly, itemizing (Schedule A: SALT cap $10,000 in 2024 vs $40,000/$40,400 after, 1098 mortgage interest, cash gifts), child tax credit for two children ($2,000 vs $2,200), Additional Medicare Tax (Form 8959), NIIT (Form 8960), Tax Computation Worksheet |
| `head_of_household` | head-of-household brackets and standard deduction, one child (CTC) |
| `retiree_couple` | RMDs from two traditional IRAs (Pub. 590-B), the Social Security Benefits Worksheet, the OBBBA senior deduction (Schedule 1-A, 2025-2026), the §63(f) amount for 65+ (Plan 31), Medicare premiums with IRMAA (2026, expected failure) |
| `early_retiree` | qualified dividends and a long-term gain straddling the 0%/15% brackets (QDCGT worksheet), a brokerage sale sized to pay the year |
| `married_separately` | two separate returns, separate-return brackets and deduction, student loan interest disallowed on a separate return |
| `eitc_head_of_household` | (Plan 31) earned income credit from the EIC Table, the child tax credit limited by the tax (Credit Limit Worksheet A) and the additional child tax credit (Schedule 8812 Part II-A) |
| `dependent_care_mfj` | (Plan 31) a dependent-care FSA (W-2 box 10, Form 2441 Part III exclusion: $5,000; $7,500 limit in 2026), the child and dependent care credit on what is left of the $6,000 limit (35%-20% rate, OBBBA's 50%-35% schedule in 2026) |
| `education_aotc_mfj` | (Plan 31) the American opportunity credit (Form 8863: 40% refundable on line 29), the 529 plan leaving $4,000 of expenses for it (Pub. 970 coordination), the credit for other dependents ($500) |
| `savers_credit_single` | (Plan 31) the retirement savings contributions credit (Form 8880, 10% tier), a cash gift: the non-itemizer charitable deduction in 2026 (line 12f) |
| `iso_amt_single` | (Plan 31) an incentive stock option exercise held: AMT (Form 6251 line 2i, the 2026 50% exemption phase-out from $500,000) and the minimum tax credit it creates (Form 8801 Part I) |
| `iso_amt_credit` | (Plan 31; 2025 and 2026, two simulated years) the year after the exercise: the prior-year minimum tax credit (Form 8801 Part II, Schedule 3 line 6b) |
| `self_employed_single` | (Plan 31) $150,000 Schedule C profit: Schedule SE, half of SE tax (Schedule 1 line 15), a SEP at a 25% plan rate (Pub. 560 worksheet, line 16), the QBI deduction (Form 8995) |
| `kiddie_tax_mfj` | (Plan 31) a child's interest and qualified dividends on the parents' return (Form 8814: line 3a share, Schedule 1 line 8z, the 10% tax on line 16) |
| `appreciated_stock_gift` | (Plan 31) long-term appreciated shares given at fair market value, limited to 30% of AGI with a carryover and no gain; in 2026 the 0.5% floor and the §68 2/37 limit |
| `qcd_retiree` | (Plan 31) a qualified charitable distribution counting toward the RMD (line 4a vs 4b), the §63(f) amount for a single 65+ filer |
| `ira_deduction_phaseout` | (Plan 31) a traditional IRA contribution (a `contribute` event) by a worker covered by a 401(k): the deduction phased out by MAGI (Pub. 590-A Worksheet 1-2, rounded up to $10), the rest nondeductible basis |
| `student_loan_phaseout` | (Plan 31) the student loan interest deduction inside its MAGI phase-out (the worksheet's three-decimal fraction) |

## Files

Each `<household>_<year>/` holds:

* `spec.yaml`: the household as of January 1 (`meta.start_year` = the year, one simulated year).
* `expected.json`: the expected return as an `actuals` record (`life_model.spec.actuals.ActualRecords`:
  Form 1040 and schedule lines by that year's line numbers, W-2 boxes, 1099s), plus
  * `exact`: line 16 by the exact rate schedule (the engine's method), compared to the cent;
  * `tolerance`: `default` (one cent) and per-line overrides, keyed `[filer/]section:line`;
  * `xfail`: lines that must still *differ* because the engine lacks a feature (with the reason and
    the plan that adds it); the test fails when one starts matching, so the entry gets removed.
* `worksheet.md`: every line's arithmetic, for review.

All three are written by [`scripts/household_goldens.py`](../../../../../scripts/household_goldens.py),
which works the forms line by line from the year's published amounts (each cited in the script) and
does not import `life_model` (a test checks it).

## Line 16: Tax Table vs exact schedule

The 1040 instructions require the Tax Table for taxable income under $100,000: the table taxes the
midpoint of a $50 row (rows are $25 below $3,000) and rounds to the dollar (verified against every row
of the 2024 and 2025 tables). The engine always computes the exact rate schedule. So a golden records
both: line 16 as the filer enters it (Tax Table, compared within the marginal rate x $25 + $0.50, set
per return in `tolerance`), and `exact` (compared to the cent). The 2026 instructions are not
published yet (October 2026); 2026 goldens apply the same rule to the Rev. Proc. 2025-32 schedule and
the 2026 draft forms' line numbers.

## Inputs that are not tax law

* `retiree_couple`: Social Security benefits (SSA-1099 box 5) are the benefit the engine's SSA formula
  pays for the spec's earnings record (that formula has its own goldens in `test_social_security.py`;
  the spec cannot state a benefit until Plan 27 D10).
* `early_retiree`: the brokerage sale is what pays the year: proceeds = spending - cash + the tax the
  sale triggers (solved as a fixed point, rounded up to the cent), with the gain pro rata on one lot.
  The year's spending is paid in one December lump (a `one_time_expense` event), so the savings and the
  fund are held all year (a full year's interest; dividends of 2% of the opening value, the fund's
  `dividend_yield_pct` being the quarterly payout that keeps its price flat under monthly compounding).
  See `docs/rebaseline-plan-32.md`.
* `married_homeowners`: the 1098 mortgage interest rounds each month's interest to the cent, the
  engine does not; lines carrying it are compared within $0.10.
* `self_employed_single`: Schedule SE line 13 and the SEP deduction are rounded to the cent before the
  form adds them; lines that add them are compared within $0.10.
* `education_aotc_mfj`: college costs are the configured college band ($28,000) and daycare the
  childcare band ($12,000 a child under 6, `dependent_care_mfj`): what the engine charges.
* `iso_amt_credit`: the spec starts the year before (the exercise year), so the credit carryforward is
  the engine's own; the script works that prior return the same way (`iso_amt_single`).

The Plan 31 goldens reproduce every line on the monthly engine (Plan 32) with their specs unchanged:
the profit, wages and dependent-care FSA are paid a twelfth a month and sum to the year's documents; the
SEP contribution is made with December's payment on the year's profit; donations, the QCD (which the
IRA makes in the year's first month and deducts from the RMD paid in twelfths), the stock gift and the ISO
exercise happen at the year start; the 529 keeps the year's first $4,000 of college costs for the AOTC
month by month. One reporting fix was needed: the reconciliation's W-2 box 10 read only December's FSA
paycheck instead of the year's (docs/rebaseline-plan-31.md).

## Expected failures

* `retiree_couple_2026`: `spending:medicare_premiums_annual`: the 2026 IRMAA tier depends on 2024 MAGI,
  which the spec cannot carry (Plan 27); the engine charges the base premium.

The §63(f) expected failures of `retiree_couple` were removed when Plan 31 applied the additional
standard deduction.

## Credits limited by the tax

When a nonrefundable credit is limited by the tax (the earned-income household's child tax credit), the
form limits it by the Tax Table amount on line 18 and the engine by the exact schedule, so the credit
lines it reaches (19, 20, 21, 28 and the credit's schedule lines) get line 16's tolerance.

## Adding a golden (e.g. for a Plan 31 credit)

1. Add the household's documents to `households()` in `scripts/household_goldens.py` (and any
   worksheet the feature needs, e.g. Schedule 8812 Part II for the refundable credit, Form 2441), and
   write its `spec.yaml` (`<name>_<year>/`, as of January 1, one simulated year, synthetic names from
   `test_privacy.py`'s allowlists).
2. Run `python scripts/household_goldens.py <name>`; review `worksheet.md` line by line against the
   form and its instructions.
3. Map any new line in `life_model/reconciliation.py` (`form_1040_lines` / `schedule_lines`; a credit
   goes to line 19/20 or 27-31 and its Schedule 3 line, by its name in `TaxReturn.credits_nonrefundable`
   / `credits_refundable`) and run `test_household_goldens.py`.
4. When a feature lands, delete its `xfail` entries (the test tells you which now match).
