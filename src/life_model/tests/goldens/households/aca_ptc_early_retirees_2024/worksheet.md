# aca ptc early retirees 2024: worked return

Pre-65 couple filing jointly on a $48,000 pension with marketplace coverage ($22,000 premium, $1,700 a month second-lowest-cost silver plan): the premium tax credit (Form 8962), no advance payments. Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.


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
| Form 1040 line 7 | none | $0.00 |
| Form 1040 line 8 | Schedule 1 line 10: no additional income | $0.00 |
| Form 1040 line 6a | SSA-1099 box 5 | $0.00 |
| Schedule 1 line 26 | Schedule 1 lines 11-25: student loan interest only | $0.00 |
| Form 1040 line 10 | Schedule 1 line 26 | $0.00 |
| Form 1040 line 6b | no benefits | $0.00 |
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7 + 8 | $48,000.00 |
| Form 1040 line 11 | line 9 - line 10 | $48,000.00 |
| Form 1040 line 12 | standard deduction (mfj) | $29,200.00 |
| Form 1040 line 13 | no qualified business income | $0.00 |
| Form 1040 line 14 | 12 + 13 | $29,200.00 |
| Form 1040 line 15 | line 11 - line 14 | $18,800.00 |
| | exact rate-schedule tax (what the engine computes): $1,880.00 | |
| Form 1040 line 16 | Tax Table row $18,800-$18,850: schedule tax on the midpoint $18,825.00, rounded | $1,883.00 |
| | Form 8962: 1 family size 2; 3 household income $48,000.00; 4 poverty line $19,720.00 (base $14,580.00 + 1 x $5,140.00); 5 = 243%; 7 applicable figure 0.0372 (linear in the band, to 0.01%); 8a = 3 x 7 = $1,786.00 | |
| Form 8962 line 3 | household income (AGI; no tax-exempt interest or Social Security) | $48,000.00 |
| Form 8962 line 5 | line 3 / line 4, truncated to a whole percent | 243 |
| Form 8962 line 7 | Table 2 | 0.0372 |
| Form 8962 line 8a | line 3 x line 7, to the dollar | $1,786.00 |
| Form 8962 line 11a | 1095-A line 33A | $22,000.00 |
| Form 8962 line 11b | 1095-A line 33B | $20,400.00 |
| Form 8962 line 11d | 11b - 11c (8a) | $18,614.00 |
| Form 8962 line 11e | smaller of 11a and 11d | $18,614.00 |
| Form 8962 line 11f | 1095-A line 33C | $0.00 |
| Form 8962 line 24 | line 11e | $18,614.00 |
| Form 8962 line 25 | line 11f | $0.00 |
| Form 8962 line 26 | 24 - 25 (Schedule 3 line 9) | $18,614.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $1,883.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $0.00 |
| Form 1040 line 22 | 18 - 21 | $1,883.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24 | 22 + 23 | $1,883.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
| Form 1040 line 25a | W-2 box 2 | $0.00 |
| Form 1040 line 25c | Form 8959 line 24 | $0.00 |
| Form 1040 line 25d | 25a + 25b + 25c | $0.00 |
| Form 1040 line 26 | Form 1040-ES payments (April, June, September and January) | $0.00 |
| Schedule 3 line 9 | Form 8962 line 26 | $18,614.00 |
| Schedule 3 line 15 | lines 9-14 | $18,614.00 |
| Form 1040 line 31 | Schedule 3 line 15 | $18,614.00 |
| Form 1040 line 32 | 27 + 28 + 29 + 30 + 31 | $18,614.00 |
| Form 1040 line 33 | 25d + 26 + 32 | $18,614.00 |
| Form 1040 line 34 | 33 - 24 (less the line 38 penalty) | $16,731.00 |
| Form 1040 line 35a | refunded | $16,731.00 |
| Form 1040 line 37 | nothing owed | $0.00 |
| Form 1040 line 38 | no estimated tax penalty | $0.00 |
