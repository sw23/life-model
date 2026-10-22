# aca ptc early retirees 2025: worked return

Pre-65 couple filing jointly on a $48,000 pension with marketplace coverage ($22,000 premium, $1,700 a month second-lowest-cost silver plan): the premium tax credit (Form 8962), $1,800 a month of advance payments. Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.


| Line | How | Amount |
|---|---|---:|
| Form 1040 line 1a | no W-2 | $0.00 |
| Form 1040 line 1z | line 1a | $0.00 |
| Form 1040 line 2a | no tax-exempt interest | $0.00 |
| Form 1040 line 2b | 1099-INT box 1 (Schedule B line 4) | $0.00 |
| Form 1040 line 3a | 1099-DIV box 1b | $0.00 |
| Form 1040 line 3b | 1099-DIV box 1a (all dividends here are qualified) | $0.00 |
| Form 1040 line 4a | 1099-R box 1 (required minimum distributions) | $0.00 |
| Form 1040 line 4b | 1099-R box 2a (no basis: fully taxable) | $0.00 |
| Form 1040 line 5a | 1099-R box 1 (pension) | $48,000.00 |
| Form 1040 line 5b | 1099-R box 2a (no employee contributions: fully taxable) | $48,000.00 |
| Form 1040 line 7a | none | $0.00 |
| Form 1040 line 8 | Schedule 1 line 10: no additional income | $0.00 |
| Form 1040 line 6a | SSA-1099 box 5 | $0.00 |
| Schedule 1 line 26 | Schedule 1 lines 11-25: student loan interest only | $0.00 |
| Form 1040 line 10 | Schedule 1 line 26 | $0.00 |
| Form 1040 line 6b | no benefits | $0.00 |
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7a + 8 | $48,000.00 |
| Form 1040 line 11a | line 9 - line 10 | $48,000.00 |
| Form 1040 line 11b | line 11a | $48,000.00 |
| Form 1040 line 12e | standard deduction (mfj) | $31,500.00 |
| Form 1040 line 13a | no qualified business income | $0.00 |
| Form 1040 line 13b | Schedule 1-A line 38 | $0.00 |
| Form 1040 line 14 | 12e + 13a + 13b | $31,500.00 |
| Form 1040 line 15 | line 11b - line 14 | $16,500.00 |
| | exact rate-schedule tax (what the engine computes): $1,650.00 | |
| Form 1040 line 16 | Tax Table row $16,500-$16,550: schedule tax on the midpoint $16,525.00, rounded | $1,653.00 |
| | Form 8962: 1 family size 2; 3 household income $48,000.00; 4 poverty line $20,440.00 (base $15,060.00 + 1 x $5,380.00); 5 = 234%; 7 applicable figure 0.0336 (linear in the band, to 0.01%); 8a = 3 x 7 = $1,613.00 | |
| Form 8962 line 3 | household income (AGI; no tax-exempt interest or Social Security) | $48,000.00 |
| Form 8962 line 5 | line 3 / line 4, truncated to a whole percent | 234 |
| Form 8962 line 7 | Table 2 | 0.0336 |
| Form 8962 line 8a | line 3 x line 7, to the dollar | $1,613.00 |
| Form 8962 line 11a | 1095-A line 33A | $22,000.00 |
| Form 8962 line 11b | 1095-A line 33B | $20,400.00 |
| Form 8962 line 11d | 11b - 11c (8a) | $18,787.00 |
| Form 8962 line 11e | smaller of 11a and 11d | $18,787.00 |
| Form 8962 line 11f | 1095-A line 33C | $21,600.00 |
| Form 8962 line 24 | line 11e | $18,787.00 |
| Form 8962 line 25 | line 11f | $21,600.00 |
| Form 8962 line 26 | 24 - 25 (Schedule 3 line 9) | $0.00 |
| Form 8962 line 27 | 25 - 24 | $2,813.00 |
| Form 8962 line 28 | Table 5 (household income under 400%) | $1,950.00 |
| Form 8962 line 29 | smaller of line 27 and the Table 5 limit $1,950.00 | $1,950.00 |
| Schedule 2 line 1a | Form 8962 line 29 | $1,950.00 |
| Schedule 2 line 1z | line 1a | $1,950.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) + the excess advance premium tax credit (Schedule 2 line 1a) | $1,950.00 |
| Schedule 2 line 3 | 1z + 2 | $1,950.00 |
| Form 1040 line 18 | 16 + 17 | $3,603.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $0.00 |
| Form 1040 line 22 | 18 - 21 | $3,603.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24 | 22 + 23 | $3,603.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
| Form 1040 line 25a | W-2 box 2 | $0.00 |
| Form 1040 line 25c | Form 8959 line 24 | $0.00 |
| Form 1040 line 25d | 25a + 25b + 25c | $0.00 |
| Form 1040 line 26 | Form 1040-ES payments (April, June, September and January) | $0.00 |
| Schedule 3 line 9 | Form 8962 line 26 | $0.00 |
| Schedule 3 line 15 | lines 9-14 | $0.00 |
| Form 1040 line 31 | Schedule 3 line 15 | $0.00 |
| Form 1040 line 32 | 27 + 28 + 29 + 30 + 31 | $0.00 |
| Form 1040 line 33 | 25d + 26 + 32 | $0.00 |
| Form 1040 line 34 | no overpayment | $0.00 |
| Form 1040 line 37 | 24 - 33 + the line 38 penalty | $3,603.00 |
| Form 1040 line 38 | no estimated tax penalty | $0.00 |
