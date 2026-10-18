# student loan phaseout 2024: worked return

Single filer with $90,000 of wages and student loan interest over the cap, inside the deduction's MAGI phase-out. Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

W-2 Example County (riley): box 1 = $90,000.00 - 401(k) $0.00 = $90,000.00; box 3 = min(wages, $168,600.00) = $90,000.00; box 4 = 6.2% = $5,580.00; box 5 = $90,000.00; box 6 = 1.45% (+0.9% over $200,000) = $1,305.00.

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
| Form 1040 line 7 | none | $0.00 |
| Form 1040 line 8 | Schedule 1 line 10: no additional income | $0.00 |
| Form 1040 line 6a | SSA-1099 box 5 | $0.00 |
| Schedule 1 line 21 | Student Loan Interest Deduction Worksheet: $2,500.00 less $2,500.00 x ($90,000.00 - $80,000.00) / $15,000.00 = 0.667 | $832.50 |
| Schedule 1 line 26 | Schedule 1 lines 11-25: student loan interest only | $832.50 |
| Form 1040 line 10 | Schedule 1 line 26 | $832.50 |
| Form 1040 line 6b | no benefits | $0.00 |
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7 + 8 | $90,000.00 |
| Form 1040 line 11 | line 9 - line 10 | $89,167.50 |
| Form 1040 line 12 | standard deduction (single) | $14,600.00 |
| Form 1040 line 13 | no qualified business income | $0.00 |
| Form 1040 line 14 | 12 + 13 | $14,600.00 |
| Form 1040 line 15 | line 11 - line 14 | $74,567.50 |
| | exact rate-schedule tax (what the engine computes): $11,457.85 | |
| Form 1040 line 16 | Tax Table row $74,550-$74,600: schedule tax on the midpoint $74,575.00, rounded | $11,460.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $11,460.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $0.00 |
| Form 1040 line 22 | 18 - 21 | $11,460.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24 | 22 + 23 | $11,460.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
