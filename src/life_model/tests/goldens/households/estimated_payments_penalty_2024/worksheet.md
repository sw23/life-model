# estimated payments penalty 2024: worked return

Single retiree on a $90,000 pension paying $2,000 quarterly estimates against a $14,000 prior-year tax: the underpayment penalty (Form 2210). Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.


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
| Form 1040 line 5a | 1099-R box 1 (pension) | $90,000.00 |
| Form 1040 line 5b | 1099-R box 2a (no employee contributions: fully taxable) | $90,000.00 |
| Form 1040 line 7 | none | $0.00 |
| Form 1040 line 8 | Schedule 1 line 10: no additional income | $0.00 |
| Form 1040 line 6a | SSA-1099 box 5 | $0.00 |
| Schedule 1 line 26 | Schedule 1 lines 11-25: student loan interest only | $0.00 |
| Form 1040 line 10 | Schedule 1 line 26 | $0.00 |
| Form 1040 line 6b | no benefits | $0.00 |
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7 + 8 | $90,000.00 |
| Form 1040 line 11 | line 9 - line 10 | $90,000.00 |
| Form 1040 line 12 | standard deduction (single) | $14,600.00 |
| Form 1040 line 13 | no qualified business income | $0.00 |
| Form 1040 line 14 | 12 + 13 | $14,600.00 |
| Form 1040 line 15 | line 11 - line 14 | $75,400.00 |
| | exact rate-schedule tax (what the engine computes): $11,641.00 | |
| Form 1040 line 16 | Tax Table row $75,400-$75,450: schedule tax on the midpoint $75,425.00, rounded | $11,647.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $11,647.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $0.00 |
| Form 1040 line 22 | 18 - 21 | $11,647.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24 | 22 + 23 | $11,647.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
| Form 1040 line 25a | W-2 box 2 | $0.00 |
| Form 1040 line 25c | Form 8959 line 24 | $0.00 |
| Form 1040 line 25d | 25a + 25b + 25c | $0.00 |
| Form 1040 line 26 | Form 1040-ES payments (April, June, September and January) | $8,000.00 |
| Form 1040 line 31 | Schedule 3 line 15 | $0.00 |
| Form 1040 line 32 | 27 + 28 + 29 + 30 + 31 | $0.00 |
| Form 1040 line 33 | 25d + 26 + 32 | $8,000.00 |
| Form 2210 line 4 | tax after credits + other taxes - refundable credits | $11,647.00 |
| Form 2210 line 6 | withholding (deemed paid a quarter on each due date) | $0.00 |
| Form 2210 line 9 | smaller of 90% of line 4 ($10,482.30) and last year's tax ($14,000.00) | $10,482.30 |
| | Form 2210: required installments $2,620.58 each (line 9 / 4); paid by each due date (withholding / 4 + estimate): $2,000.00, $2,000.00, $2,000.00, $2,000.00; penalty worksheet: $620.58 x 76/366 x 0.08 + $620.58 x 92/366 x 0.08 + $620.58 x 92/366 x 0.08 + $620.58 x 105/365 x 0.07 + $620.58 x 15/366 x 0.08 + $620.58 x 92/366 x 0.08 + $620.58 x 92/366 x 0.08 + $620.58 x 105/365 x 0.07 + $620.58 x 15/366 x 0.08 + $620.58 x 92/366 x 0.08 + $620.58 x 105/365 x 0.07 + $620.58 x 90/365 x 0.07 | |
| Form 2210 line 19 | Penalty Worksheet line 14 | $124.98 |
| Form 1040 line 34 | no overpayment | $0.00 |
| Form 1040 line 37 | 24 - 33 + the line 38 penalty | $3,771.98 |
| Form 1040 line 38 | Form 2210 line 19 | $124.98 |
