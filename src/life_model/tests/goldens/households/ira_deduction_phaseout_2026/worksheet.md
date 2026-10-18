# ira deduction phaseout 2026: worked return

Single filer with $82,000 of wages, covered by a workplace 401(k), contributing the IRA limit to a traditional IRA: the deduction phases out by MAGI and the rest is nondeductible basis. Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

W-2 Example Analytics (sam): box 1 = $82,000.00 - 401(k) $0.00 = $82,000.00; box 3 = min(wages, $184,500.00) = $82,000.00; box 4 = 6.2% = $5,084.00; box 5 = $82,000.00; box 6 = 1.45% (+0.9% over $200,000) = $1,189.00.

| Line | How | Amount |
|---|---|---:|
| Form 1040 line 1a | W-2 box 1 Example Analytics $82,000.00 | $82,000.00 |
| Form 1040 line 1z | line 1a | $82,000.00 |
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
| Schedule 1 line 20 | Pub. 590-A Worksheet 1-2: ($91,000.00 - MAGI $82,000.00) x 0.75 = $6,750.00, up to the next $10 (at least $200) | $6,750.00 |
| Schedule 1 line 26 | Schedule 1 lines 11-25 | $6,750.00 |
| Form 1040 line 10 | Schedule 1 line 26 | $6,750.00 |
| Form 1040 line 6b | no benefits | $0.00 |
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7a + 8 | $82,000.00 |
| Form 1040 line 11a | line 9 - line 10 | $75,250.00 |
| Form 1040 line 11b | line 11a | $75,250.00 |
| Form 1040 line 12e | standard deduction (single) | $16,100.00 |
| Form 1040 line 12f | itemizes or no cash gifts (non-itemizer charitable deduction) | $0.00 |
| Form 1040 line 13a | Schedule 1-A line 44 | $0.00 |
| Form 1040 line 13b | no qualified business income | $0.00 |
| Form 1040 line 14 | 12e + 12f + 13a + 13b | $16,100.00 |
| Form 1040 line 15 | line 11b - line 14 | $59,150.00 |
| | exact rate-schedule tax (what the engine computes): $7,725.00 | |
| Form 1040 line 16 | Tax Table row $59,150-$59,200: schedule tax on the midpoint $59,175.00, rounded | $7,731.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $7,731.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $0.00 |
| Form 1040 line 22 | 18 - 21 | $7,731.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24a | 22 + 23 | $7,731.00 |
| Form 1040 line 24c | 24a + 24b (no Form 1062) | $7,731.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
