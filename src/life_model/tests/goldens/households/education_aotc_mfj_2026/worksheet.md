# education aotc mfj 2026: worked return

Married filing jointly with a 19-year-old full-time student ($28,000 of college costs, a 529 plan paying all but the $4,000 kept for the American opportunity credit) and the credit for other dependents. Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

W-2 Example Consulting LLC (sam): box 1 = $120,000.00 - 401(k) $0.00 = $120,000.00; box 3 = min(wages, $184,500.00) = $120,000.00; box 4 = 6.2% = $7,440.00; box 5 = $120,000.00; box 6 = 1.45% (+0.9% over $200,000) = $1,740.00.

| Line | How | Amount |
|---|---|---:|
| Form 1040 line 1a | W-2 box 1 Example Consulting LLC $120,000.00 | $120,000.00 |
| Form 1040 line 1z | line 1a | $120,000.00 |
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
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7a + 8 | $120,000.00 |
| Form 1040 line 11a | line 9 - line 10 | $120,000.00 |
| Form 1040 line 11b | line 11a | $120,000.00 |
| Form 1040 line 12e | standard deduction (mfj) | $32,200.00 |
| Form 1040 line 12f | itemizes or no cash gifts (non-itemizer charitable deduction) | $0.00 |
| Form 1040 line 13a | Schedule 1-A line 44 | $0.00 |
| Form 1040 line 13b | no qualified business income | $0.00 |
| Form 1040 line 14 | 12e + 12f + 13a + 13b | $32,200.00 |
| Form 1040 line 15 | line 11b - line 14 | $87,800.00 |
| | exact rate-schedule tax (what the engine computes): $10,040.00 | |
| Form 1040 line 16 | Tax Table row $87,800-$87,850: schedule tax on the midpoint $87,825.00, rounded | $10,043.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $10,043.00 |
| | Form 8863: AOTC per student 100% of $2,000 + 25% of the next $2,000 = $2,500.00; MAGI fraction 1; 7 = $2,500.00; 8 = 40% refundable $1,000.00; 9 = $1,500.00 | |
| Form 8863 line 8 | 40% of line 7 | $1,000.00 |
| Form 8863 line 19 | line 9 limited by the Credit Limit Worksheet | $1,500.00 |
| Schedule 3 line 3 | Form 8863 line 19 | $1,500.00 |
| | Schedule 8812: 0 x $2,200.00 + 1 x $500 (other dependents) = $500.00; MAGI under $400,000.00; Credit Limit Worksheet A: line 18 less Schedule 3 lines 1-4 = $8,543.00 | |
| Form 1040 line 19 | Schedule 8812 line 14 | $500.00 |
| Form 8812 line 14 | smaller of line 12 and Credit Limit Worksheet A | $500.00 |
| Schedule 3 line 8 | lines 1-4 and 7 | $1,500.00 |
| Form 1040 line 20 | Schedule 3 line 8 | $1,500.00 |
| Form 1040 line 21 | 19 + 20 | $2,000.00 |
| Form 1040 line 22 | 18 - 21 | $8,043.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24a | 22 + 23 | $8,043.00 |
| Form 1040 line 24c | 24a + 24b (no Form 1062) | $8,043.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
| Form 1040 line 29 | Form 8863 line 8 | $1,000.00 |
