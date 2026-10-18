# student loan phaseout 2026: worked return

Single filer with $90,000 of wages and student loan interest over the cap, inside the deduction's MAGI phase-out. Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

W-2 Example County (riley): box 1 = $90,000.00 - 401(k) $0.00 = $90,000.00; box 3 = min(wages, $184,500.00) = $90,000.00; box 4 = 6.2% = $5,580.00; box 5 = $90,000.00; box 6 = 1.45% (+0.9% over $200,000) = $1,305.00.

| Line | How | Amount |
|---|---|---:|
| Form 1040 line 1a | W-2 box 1 Example County $90,000.00 | $90,000.00 |
| Form 1040 line 1z | line 1a | $90,000.00 |
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
| Schedule 1 line 21 | Student Loan Interest Deduction Worksheet: $2,500.00 less $2,500.00 x ($90,000.00 - $85,000.00) / $15,000.00 = 0.333 | $1,667.50 |
| Schedule 1 line 26 | Schedule 1 lines 11-25: student loan interest only | $1,667.50 |
| Form 1040 line 10 | Schedule 1 line 26 | $1,667.50 |
| Form 1040 line 6b | no benefits | $0.00 |
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7a + 8 | $90,000.00 |
| Form 1040 line 11a | line 9 - line 10 | $88,332.50 |
| Form 1040 line 11b | line 11a | $88,332.50 |
| Form 1040 line 12e | standard deduction (single) | $16,100.00 |
| Form 1040 line 12f | itemizes or no cash gifts (non-itemizer charitable deduction) | $0.00 |
| Form 1040 line 13a | Schedule 1-A line 44 | $0.00 |
| Form 1040 line 13b | no qualified business income | $0.00 |
| Form 1040 line 14 | 12e + 12f + 13a + 13b | $16,100.00 |
| Form 1040 line 15 | line 11b - line 14 | $72,232.50 |
| | exact rate-schedule tax (what the engine computes): $10,603.15 | |
| Form 1040 line 16 | Tax Table row $72,200-$72,250: schedule tax on the midpoint $72,225.00, rounded | $10,602.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $10,602.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $0.00 |
| Form 1040 line 22 | 18 - 21 | $10,602.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24a | 22 + 23 | $10,602.00 |
| Form 1040 line 24c | 24a + 24b (no Form 1062) | $10,602.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
