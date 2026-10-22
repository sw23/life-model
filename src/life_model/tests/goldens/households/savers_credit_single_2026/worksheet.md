# savers credit single 2026: worked return

Single 24-year-old with $30,000 of wages and a 10% pre-tax 401(k) deferral: retirement savings contributions credit at the 10% tier, and a $500 cash gift (the non-itemizer deduction from 2026). Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

W-2 Example Analytics (alex): box 1 = $30,000.00 - 401(k) $3,000.00 = $27,000.00; box 3 = min(wages, $184,500.00) = $30,000.00; box 4 = 6.2% = $1,860.00; box 5 = $30,000.00; box 6 = 1.45% (+0.9% over $200,000) = $435.00.

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
| Form 1040 line 7a | none | $0.00 |
| Form 1040 line 8 | Schedule 1 line 10: no additional income | $0.00 |
| Form 1040 line 6a | SSA-1099 box 5 | $0.00 |
| Schedule 1 line 26 | Schedule 1 lines 11-25: student loan interest only | $0.00 |
| Form 1040 line 10 | Schedule 1 line 26 | $0.00 |
| Form 1040 line 6b | no benefits | $0.00 |
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7a + 8 | $27,000.00 |
| Form 1040 line 11a | line 9 - line 10 | $27,000.00 |
| Form 1040 line 11b | line 11a | $27,000.00 |
| Schedule A line 5e | smaller of 5d and the $40,400 cap | $0.00 |
| Schedule A line 7 | 5e + 6 | $0.00 |
| Schedule A line 8a | 1098 box 1 | $0.00 |
| Schedule A line 8e | 8a | $0.00 |
| Schedule A line 10 | 8e (no investment interest) | $0.00 |
| | 0.5% floor (IRC §170(b)(1)(I), OBBBA): 0.5% x AGI $27,000.00 = $135.00, taken from property first ($0.00) then cash ($135.00) | |
| Schedule A line 11 | cash gifts (within 60% of AGI) less the 0.5% floor | $365.00 |
| Schedule A line 14 | 11 + 12 + 13 | $365.00 |
| Schedule A line 17 | 5e/7 + 10 + 14 | $365.00 |
| Form 1040 line 12e | standard deduction (single) | $16,100.00 |
| Form 1040 line 12f | cash gifts to public charities, up to $1,000 ($2,000 joint), for non-itemizers (IRC §170(p)) | $500.00 |
| Form 1040 line 13a | Schedule 1-A line 44 | $0.00 |
| Form 1040 line 13b | no qualified business income | $0.00 |
| Form 1040 line 14 | 12e + 12f + 13a + 13b | $16,600.00 |
| Form 1040 line 15 | line 11b - line 14 | $10,400.00 |
| | exact rate-schedule tax (what the engine computes): $1,040.00 | |
| Form 1040 line 16 | Tax Table row $10,400-$10,450: schedule tax on the midpoint $10,425.00, rounded | $1,043.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $1,043.00 |
| | Form 8880: 6 = contributions up to $2,000 each ($3,000.00); 7 = $2,000.00; 9 = 0.1 (AGI $27,000.00 vs (24250, 26250, 40250)); 10 = $200.00; 12 = limited by tax | |
| Form 8880 line 12 | line 10 limited by line 11 | $200.00 |
| Schedule 3 line 4 | Form 8880 line 12 | $200.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Schedule 3 line 8 | lines 1-4 and 7 | $200.00 |
| Form 1040 line 20 | Schedule 3 line 8 | $200.00 |
| Form 1040 line 21 | 19 + 20 | $200.00 |
| Form 1040 line 22 | 18 - 21 | $843.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24a | 22 + 23 | $843.00 |
| Form 1040 line 24c | 24a + 24b (no Form 1062) | $843.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
