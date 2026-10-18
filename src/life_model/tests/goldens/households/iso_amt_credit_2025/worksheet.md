# iso amt credit 2025: worked return

The incentive-stock-option household the year after the 2024 exercise: the prior-year minimum tax credit (Form 8801) against regular tax over the tentative minimum tax. Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

Prior year (2024): the incentive stock option exercise created AMT of $101,813.50 and a minimum tax credit carryforward of $101,813.50 (that year's `iso_amt_single_2024` golden works the return).

W-2 Example Analytics (morgan): box 1 = $200,000.00 - 401(k) $0.00 = $200,000.00; box 3 = min(wages, $176,100.00) = $176,100.00; box 4 = 6.2% = $10,918.20; box 5 = $200,000.00; box 6 = 1.45% (+0.9% over $200,000) = $2,900.00.

| Line | How | Amount |
|---|---|---:|
| Form 1040 line 1a | W-2 box 1 Example Analytics $200,000.00 | $200,000.00 |
| Form 1040 line 1z | line 1a | $200,000.00 |
| Form 1040 line 2a | no tax-exempt interest | $0.00 |
| Form 1040 line 2b | 1099-INT box 1 (Schedule B line 4) | $0.00 |
| Form 1040 line 3a | 1099-DIV box 1b | $0.00 |
| Form 1040 line 3b | 1099-DIV box 1a (all dividends here are qualified) | $0.00 |
| Form 1040 line 4a | 1099-R box 1 (required minimum distributions) | $0.00 |
| Form 1040 line 4b | 1099-R box 2a (no basis: fully taxable) | $0.00 |
| Form 1040 line 5b | no pensions | $0.00 |
| Form 1040 line 7a | none | $0.00 |
| Form 1040 line 8 | Schedule 1 line 10: no additional income | $0.00 |
| Form 1040 line 6a | SSA-1099 box 5 | $0.00 |
| Schedule 1 line 26 | Schedule 1 lines 11-25: student loan interest only | $0.00 |
| Form 1040 line 10 | Schedule 1 line 26 | $0.00 |
| Form 1040 line 6b | no benefits | $0.00 |
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7a + 8 | $200,000.00 |
| Form 1040 line 11a | line 9 - line 10 | $200,000.00 |
| Form 1040 line 11b | line 11a | $200,000.00 |
| Form 1040 line 12e | standard deduction (single) | $15,750.00 |
| Form 1040 line 13a | no qualified business income | $0.00 |
| Form 1040 line 13b | Schedule 1-A line 38 | $0.00 |
| Form 1040 line 14 | 12e + 13a + 13b | $15,750.00 |
| Form 1040 line 15 | line 11b - line 14 | $184,250.00 |
| | exact rate-schedule tax (what the engine computes): $37,067.00 | |
| Form 1040 line 16 | Tax Computation Worksheet (exact schedule) | $37,067.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $37,067.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| | Form 8801 Part II: 21 carryforward $101,813.50; 22 regular tax less credits $37,067.00; 23 tentative minimum tax $29,094.00 (Form 6251 line 9); 25 = smaller of 21 and 22 - 23 | |
| Schedule 3 line 6b | Form 8801 line 25 | $7,973.00 |
| Schedule 3 line 7 | line 6b | $7,973.00 |
| Schedule 3 line 8 | lines 1-4 and 7 | $7,973.00 |
| Form 1040 line 20 | Schedule 3 line 8 | $7,973.00 |
| Form 1040 line 21 | 19 + 20 | $7,973.00 |
| Form 1040 line 22 | 18 - 21 | $29,094.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24 | 22 + 23 | $29,094.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
