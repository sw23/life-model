# estimated payments penalty 2026: worked return

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
| Form 1040 line 7a | none | $0.00 |
| Form 1040 line 8 | Schedule 1 line 10: no additional income | $0.00 |
| Form 1040 line 6a | SSA-1099 box 5 | $0.00 |
| Schedule 1 line 26 | Schedule 1 lines 11-25: student loan interest only | $0.00 |
| Form 1040 line 10 | Schedule 1 line 26 | $0.00 |
| Form 1040 line 6b | no benefits | $0.00 |
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7a + 8 | $90,000.00 |
| Form 1040 line 11a | line 9 - line 10 | $90,000.00 |
| Form 1040 line 11b | line 11a | $90,000.00 |
| Form 1040 line 12e | standard deduction (single) | $16,100.00 |
| Form 1040 line 12f | itemizes or no cash gifts (non-itemizer charitable deduction) | $0.00 |
| Form 1040 line 13a | Schedule 1-A line 44 | $0.00 |
| Form 1040 line 13b | no qualified business income | $0.00 |
| Form 1040 line 14 | 12e + 12f + 13a + 13b | $16,100.00 |
| Form 1040 line 15 | line 11b - line 14 | $73,900.00 |
| | exact rate-schedule tax (what the engine computes): $10,970.00 | |
| Form 1040 line 16 | Tax Table row $73,900-$73,950: schedule tax on the midpoint $73,925.00, rounded | $10,976.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $10,976.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $0.00 |
| Form 1040 line 22 | 18 - 21 | $10,976.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24a | 22 + 23 | $10,976.00 |
| Form 1040 line 24c | 24a + 24b (no Form 1062) | $10,976.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
| Form 1040 line 25a | W-2 box 2 | $0.00 |
| Form 1040 line 25c | Form 8959 line 24 | $0.00 |
| Form 1040 line 25d | 25a + 25b + 25c | $0.00 |
| Form 1040 line 26 | Form 1040-ES payments (April, June, September and January) | $8,000.00 |
| Form 1040 line 31 | Schedule 3 line 15 | $0.00 |
| Form 1040 line 32c | 27 + 28 + 29 + 30 + 31 | $0.00 |
| Form 1040 line 33 | 25d + 26 + 32 | $8,000.00 |
| Form 2210 line 4 | tax after credits + other taxes - refundable credits | $10,976.00 |
| Form 2210 line 6 | withholding (deemed paid a quarter on each due date) | $0.00 |
| Form 2210 line 9 | smaller of 90% of line 4 ($9,878.40) and last year's tax ($14,000.00) | $9,878.40 |
| | Form 2210: required installments $2,469.60 each (line 9 / 4); paid by each due date (withholding / 4 + estimate): $2,000.00, $2,000.00, $2,000.00, $2,000.00; penalty worksheet: $469.60 x 76/365 x 0.06 + $469.60 x 92/365 x 0.07 + $469.60 x 92/365 x 0.07 + $469.60 x 105/365 x 0.07 + $469.60 x 15/365 x 0.06 + $469.60 x 92/365 x 0.07 + $469.60 x 92/365 x 0.07 + $469.60 x 105/365 x 0.07 + $469.60 x 15/365 x 0.07 + $469.60 x 92/365 x 0.07 + $469.60 x 105/365 x 0.07 + $469.60 x 90/365 x 0.07 | |
| Form 2210 line 19 | Penalty Worksheet line 14 | $86.28 |
| Form 1040 line 34 | no overpayment | $0.00 |
| Form 1040 line 37 | 24c - 33 + the line 38 penalty | $3,062.28 |
| Form 1040 line 38 | Form 2210 line 19 | $86.28 |
