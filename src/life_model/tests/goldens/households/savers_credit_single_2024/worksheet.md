# savers credit single 2024: worked return

Single 24-year-old with $30,000 of wages and a 10% pre-tax 401(k) deferral: retirement savings contributions credit at the 10% tier, and a $500 cash gift (the non-itemizer deduction from 2026). Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

W-2 Example Analytics (alex): box 1 = $30,000.00 - 401(k) $3,000.00 = $27,000.00; box 3 = min(wages, $168,600.00) = $30,000.00; box 4 = 6.2% = $1,860.00; box 5 = $30,000.00; box 6 = 1.45% (+0.9% over $200,000) = $435.00.

| Line | How | Amount |
|---|---|---:|
| Form 1040 line 1a | W-2 box 1 Example Analytics $27,000.00 | $27,000.00 |
| Form 1040 line 1z | line 1a | $27,000.00 |
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
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7 + 8 | $27,000.00 |
| Form 1040 line 11 | line 9 - line 10 | $27,000.00 |
| Schedule A line 5e | smaller of 5d and the $10,000 cap | $0.00 |
| Schedule A line 7 | 5e + 6 | $0.00 |
| Schedule A line 8a | 1098 box 1 | $0.00 |
| Schedule A line 8e | 8a | $0.00 |
| Schedule A line 10 | 8e (no investment interest) | $0.00 |
| Schedule A line 11 | cash gifts (within 60% of AGI) | $500.00 |
| Schedule A line 14 | 11 + 12 + 13 | $500.00 |
| Schedule A line 17 | 5e/7 + 10 + 14 | $500.00 |
| Form 1040 line 12 | standard deduction (single) | $14,600.00 |
| Form 1040 line 13 | no qualified business income | $0.00 |
| Form 1040 line 14 | 12 + 13 | $14,600.00 |
| Form 1040 line 15 | line 11 - line 14 | $12,400.00 |
| | exact rate-schedule tax (what the engine computes): $1,256.00 | |
| Form 1040 line 16 | Tax Table row $12,400-$12,450: schedule tax on the midpoint $12,425.00, rounded | $1,259.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $1,259.00 |
| | Form 8880: 6 = contributions up to $2,000 each ($3,000.00); 7 = $2,000.00; 9 = 0.1 (AGI $27,000.00 vs (23000, 25000, 38250)); 10 = $200.00; 12 = limited by tax | |
| Form 8880 line 12 | line 10 limited by line 11 | $200.00 |
| Schedule 3 line 4 | Form 8880 line 12 | $200.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Schedule 3 line 8 | lines 1-4 and 7 | $200.00 |
| Form 1040 line 20 | Schedule 3 line 8 | $200.00 |
| Form 1040 line 21 | 19 + 20 | $200.00 |
| Form 1040 line 22 | 18 - 21 | $1,059.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24 | 22 + 23 | $1,059.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
