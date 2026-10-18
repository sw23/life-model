# Household goldens (Plan 29 D3)

Synthetic households whose full-year federal return was worked from the IRS forms, independently of
the library, for 2024, 2025 and 2026. They are the external ground truth for the tax engine:
`test_household_goldens.py` reconciles each one and requires every line to match.

| Household | Exercises |
|---|---|
| `single_renter` | W-2 with a pre-tax 401(k) deferral, savings interest, student loan interest over the $2,500 cap (Schedule 1 line 21), Tax Table |
| `married_homeowners` | married filing jointly, itemizing (Schedule A: SALT cap $10,000 in 2024 vs $40,000/$40,400 after, 1098 mortgage interest, cash gifts), child tax credit for two children ($2,000 vs $2,200), Additional Medicare Tax (Form 8959), NIIT (Form 8960), Tax Computation Worksheet |
| `head_of_household` | head-of-household brackets and standard deduction, one child (CTC) |
| `retiree_couple` | RMDs from two traditional IRAs (Pub. 590-B), the Social Security Benefits Worksheet, the OBBBA senior deduction (Schedule 1-A, 2025-2026), the §63(f) amount for 65+ (expected failure), Medicare premiums with IRMAA (2026, expected failure) |
| `early_retiree` | qualified dividends and a long-term gain straddling the 0%/15% brackets (QDCGT worksheet), a brokerage sale sized to pay the year |
| `married_separately` | two separate returns, separate-return brackets and deduction, student loan interest disallowed on a separate return |

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
* `married_homeowners`: the 1098 mortgage interest rounds each month's interest to the cent, the
  engine does not; lines carrying it are compared within $0.10.

## Expected failures (Plan 31)

* `retiree_couple_2024/2025/2026`: lines 12/12e, 14, 15, 16, 18, 22, 24 (and `exact` line 16): the
  §63(f) additional standard deduction for age 65+ ($1,550 / $1,600 / $1,650 per person on a joint
  return) is not applied (Plan 31 task 1).
* `retiree_couple_2026`: `spending:medicare_premiums_annual`: the 2026 IRMAA tier depends on 2024 MAGI,
  which the spec cannot carry (Plan 27); the engine charges the base premium.

## Adding a golden (e.g. for a Plan 31 credit)

1. Add the household's documents to `households()` in `scripts/household_goldens.py` (and any
   worksheet the feature needs, e.g. Schedule 8812 Part II for the refundable credit, Form 2441), and
   write its `spec.yaml` (`<name>_<year>/`, as of January 1, one simulated year, synthetic names from
   `test_privacy.py`'s allowlists).
2. Run `python scripts/household_goldens.py <name>`; review `worksheet.md` line by line against the
   form and its instructions.
3. Map any new line in `life_model/reconciliation.py` (`form_1040_lines` / `schedule_lines`; a credit
   goes to line 19/20 or 28-31 and its Schedule 3 line) and run `test_household_goldens.py`.
4. When a feature lands, delete its `xfail` entries (the test tells you which now match).
