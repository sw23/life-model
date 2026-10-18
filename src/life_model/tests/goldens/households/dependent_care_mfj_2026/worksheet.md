# dependent care mfj 2026: worked return

Married filing jointly, two earners, two children in daycare ($12,000 each) and a $5,000 dependent-care FSA: Form 2441 Part III exclusion and the credit on the $1,000 left of the $6,000 limit. Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

W-2 Example Analytics (john): box 1 = $70,000.00 - 401(k) $0.00 - dependent-care FSA $5,000.00 = $65,000.00; box 3 = min(wages, $184,500.00) = $65,000.00; box 4 = 6.2% = $4,030.00; box 5 = $65,000.00; box 6 = 1.45% (+0.9% over $200,000) = $942.50; box 10 = $5,000.00.
W-2 Example County (jane): box 1 = $45,000.00 - 401(k) $0.00 = $45,000.00; box 3 = min(wages, $184,500.00) = $45,000.00; box 4 = 6.2% = $2,790.00; box 5 = $45,000.00; box 6 = 1.45% (+0.9% over $200,000) = $652.50.

| Line | How | Amount |
|---|---|---:|
| | Form 2441 Part III: 12 benefits $5,000.00; 16 expenses $24,000.00; 21 limit $7,500.00; 25 excluded = smallest of benefits, expenses, earned incomes, limit = $5,000.00 | |
| Form 2441 line 26 | line 23 - line 25 (to Form 1040 line 1e) | $0.00 |
| Form 1040 line 1a | W-2 box 1 Example Analytics $65,000.00 + W-2 box 1 Example County $45,000.00 | $110,000.00 |
| Form 1040 line 1e | Form 2441 line 26 | $0.00 |
| Form 1040 line 1z | 1a + 1e | $110,000.00 |
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
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7a + 8 | $110,000.00 |
| Form 1040 line 11a | line 9 - line 10 | $110,000.00 |
| Form 1040 line 11b | line 11a | $110,000.00 |
| Form 1040 line 12e | standard deduction (mfj) | $32,200.00 |
| Form 1040 line 12f | itemizes or no cash gifts (non-itemizer charitable deduction) | $0.00 |
| Form 1040 line 13a | Schedule 1-A line 44 | $0.00 |
| Form 1040 line 13b | no qualified business income | $0.00 |
| Form 1040 line 14 | 12e + 12f + 13a + 13b | $32,200.00 |
| Form 1040 line 15 | line 11b - line 14 | $77,800.00 |
| | exact rate-schedule tax (what the engine computes): $8,840.00 | |
| Form 1040 line 16 | Tax Table row $77,800-$77,850: schedule tax on the midpoint $77,825.00, rounded | $8,843.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $8,843.00 |
| | Form 2441: 3 = min($3,000/$6,000 - excluded benefits $5,000.00, expenses not covered $19,000.00) = $1,000.00; 6 = smallest of 3 and earned incomes = $1,000.00; 8 = 0.35 (AGI $110,000.00); 9 = $350.00; 11 = limited by tax | |
| Form 2441 line 11 | line 9 limited by line 10 | $350.00 |
| Schedule 3 line 2 | Form 2441 line 11 | $350.00 |
| | Schedule 8812: 2 x $2,200.00 = $4,400.00; MAGI under $400,000.00; Credit Limit Worksheet A: line 18 less Schedule 3 lines 1-4 = $8,493.00 | |
| Form 1040 line 19 | Schedule 8812 line 14 | $4,400.00 |
| Form 8812 line 14 | smaller of line 12 and Credit Limit Worksheet A | $4,400.00 |
| Schedule 3 line 8 | lines 1-4 and 7 | $350.00 |
| Form 1040 line 20 | Schedule 3 line 8 | $350.00 |
| Form 1040 line 21 | 19 + 20 | $4,750.00 |
| Form 1040 line 22 | 18 - 21 | $4,093.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24a | 22 + 23 | $4,093.00 |
| Form 1040 line 24c | 24a + 24b (no Form 1062) | $4,093.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
