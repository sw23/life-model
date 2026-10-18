# aca ptc early retirees 2026: worked return

Pre-65 couple filing jointly on a $48,000 pension with marketplace coverage ($22,000 premium, $1,700 a month second-lowest-cost silver plan): the premium tax credit (Form 8962), $1,600 a month of advance payments. Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.


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
| Form 1040 line 12e | standard deduction (mfj) | $32,200.00 |
| Form 1040 line 12f | itemizes or no cash gifts (non-itemizer charitable deduction) | $0.00 |
| Form 1040 line 13a | Schedule 1-A line 44 | $0.00 |
| Form 1040 line 13b | no qualified business income | $0.00 |
| Form 1040 line 14 | 12e + 12f + 13a + 13b | $32,200.00 |
| Form 1040 line 15 | line 11b - line 14 | $15,800.00 |
| | exact rate-schedule tax (what the engine computes): $1,580.00 | |
| Form 1040 line 16 | Tax Table row $15,800-$15,850: schedule tax on the midpoint $15,825.00, rounded | $1,583.00 |
| | Form 8962: 1 family size 2; 3 household income $48,000.00; 4 poverty line $21,150.00 (base $15,650.00 + 1 x $5,500.00); 5 = 226%; 7 applicable figure 0.0756 (linear in the band, to 0.01%); 8a = 3 x 7 = $3,629.00 | |
| Form 8962 line 3 | household income (AGI; no tax-exempt interest or Social Security) | $48,000.00 |
| Form 8962 line 5 | line 3 / line 4, truncated to a whole percent | 226 |
| Form 8962 line 7 | Table 2 | 0.0756 |
| Form 8962 line 8a | line 3 x line 7, to the dollar | $3,629.00 |
| Form 8962 line 11a | 1095-A line 33A | $22,000.00 |
| Form 8962 line 11b | 1095-A line 33B | $20,400.00 |
| Form 8962 line 11d | 11b - 11c (8a) | $16,771.00 |
| Form 8962 line 11e | smaller of 11a and 11d | $16,771.00 |
| Form 8962 line 11f | 1095-A line 33C | $19,200.00 |
| Form 8962 line 24 | line 11e | $16,771.00 |
| Form 8962 line 25 | line 11f | $19,200.00 |
| Form 8962 line 26 | 24 - 25 (Schedule 3 line 9) | $0.00 |
| Form 8962 line 27 | 25 - 24 | $2,429.00 |
| | 2026: no repayment limit (OBBBA §71305); line 27 is repaid in full (lines 28-29 reserved) | |
| Schedule 2 line 1a | Form 8962 line 29 | $2,429.00 |
| Schedule 2 line 1z | line 1a | $2,429.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) + the excess advance premium tax credit (Schedule 2 line 1a) | $2,429.00 |
| Schedule 2 line 3 | 1z + 2 | $2,429.00 |
| Form 1040 line 18 | 16 + 17 | $4,012.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $0.00 |
| Form 1040 line 22 | 18 - 21 | $4,012.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24a | 22 + 23 | $4,012.00 |
| Form 1040 line 24c | 24a + 24b (no Form 1062) | $4,012.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
| Form 1040 line 25a | W-2 box 2 | $0.00 |
| Form 1040 line 25c | Form 8959 line 24 | $0.00 |
| Form 1040 line 25d | 25a + 25b + 25c | $0.00 |
| Form 1040 line 26 | Form 1040-ES payments (April, June, September and January) | $0.00 |
| Schedule 3 line 9 | Form 8962 line 26 | $0.00 |
| Schedule 3 line 15 | lines 9-14 | $0.00 |
| Form 1040 line 31 | Schedule 3 line 15 | $0.00 |
| Form 1040 line 32c | 27 + 28 + 29 + 30 + 31 | $0.00 |
| Form 1040 line 33 | 25d + 26 + 32 | $0.00 |
| Form 1040 line 34 | no overpayment | $0.00 |
| Form 1040 line 37 | 24c - 33 + the line 38 penalty | $4,012.00 |
| Form 1040 line 38 | no estimated tax penalty | $0.00 |
