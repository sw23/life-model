# qss widow 2024: worked return

A parent whose spouse died the year before, with a ten-year-old: qualifying surviving spouse and the child tax credit. Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

W-2 Example County (morgan): box 1 = $70,000.00 - 401(k) $0.00 = $70,000.00; box 3 = min(wages, $168,600.00) = $70,000.00; box 4 = 6.2% = $4,340.00; box 5 = $70,000.00; box 6 = 1.45% (+0.9% over $200,000) = $1,015.00.

| Line | How | Amount |
|---|---|---:|
| Form 1040 line 1a | W-2 box 1 Example County $70,000.00 | $70,000.00 |
| Form 1040 line 1z | line 1a | $70,000.00 |
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
| Schedule 1 line 26 | Schedule 1 lines 11-25: student loan interest only | $0.00 |
| Form 1040 line 10 | Schedule 1 line 26 | $0.00 |
| Form 1040 line 6b | no benefits | $0.00 |
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7 + 8 | $70,000.00 |
| Form 1040 line 11 | line 9 - line 10 | $70,000.00 |
| Form 1040 line 12 | standard deduction (qss) | $29,200.00 |
| Form 1040 line 13 | no qualified business income | $0.00 |
| Form 1040 line 14 | 12 + 13 | $29,200.00 |
| Form 1040 line 15 | line 11 - line 14 | $40,800.00 |
| | exact rate-schedule tax (what the engine computes): $4,432.00 | |
| Form 1040 line 16 | Tax Table row $40,800-$40,850: schedule tax on the midpoint $40,825.00, rounded | $4,435.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $4,435.00 |
| | Schedule 8812: 1 x $2,000.00 = $2,000.00; MAGI under $200,000.00; Credit Limit Worksheet A: line 18 less Schedule 3 lines 1-4 = $4,435.00 | |
| Form 1040 line 19 | Schedule 8812 line 14 | $2,000.00 |
| Form 8812 line 14 | smaller of line 12 and Credit Limit Worksheet A | $2,000.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $2,000.00 |
| Form 1040 line 22 | 18 - 21 | $2,435.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24 | 22 + 23 | $2,435.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
