# kiddie tax mfj 2024: worked return

Married filing jointly, one earner, a 12-year-old with $2,000 of interest and $3,000 of qualified dividends reported on the parents' return (Form 8814). Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

W-2 Example Analytics (john): box 1 = $150,000.00 - 401(k) $0.00 = $150,000.00; box 3 = min(wages, $168,600.00) = $150,000.00; box 4 = 6.2% = $9,300.00; box 5 = $150,000.00; box 6 = 1.45% (+0.9% over $200,000) = $2,175.00.

| Line | How | Amount |
|---|---|---:|
| | Form 8814: line 4 $5,000.00; 5 = 2 x $1,300.00; 6 = $2,400.00; 9 (qualified dividends share $3,000.00 / $5,000.00) $1,440.00; 12 = $960.00 (Schedule 1 line 8z); 15 = 10% x min(line 4 - $1,300.00, $1,300.00) = $130.00 (Form 1040 line 16) | |
| Form 8814 line 15 | 10% of the child's income over the base, at most 10% of the base | $130.00 |
| Form 1040 line 1a | W-2 box 1 Example Analytics $150,000.00 | $150,000.00 |
| Form 1040 line 1z | line 1a | $150,000.00 |
| Form 1040 line 2a | no tax-exempt interest | $0.00 |
| Form 1040 line 2b | 1099-INT box 1 (Schedule B line 4) | $0.00 |
| Form 1040 line 3a | 1099-DIV box 1b + Form 8814 line 9 | $1,440.00 |
| Form 1040 line 3b | 1099-DIV box 1a (all dividends here are qualified) + Form 8814 line 9 | $1,440.00 |
| Form 1040 line 4a | 1099-R box 1 (required minimum distributions) | $0.00 |
| Form 1040 line 4b | 1099-R box 2a (no basis: fully taxable) | $0.00 |
| Form 1040 line 5b | no pensions | $0.00 |
| Form 1040 line 7 | none | $0.00 |
| Schedule 1 line 8z | Form 8814 line 12 | $960.00 |
| Schedule 1 line 9 | line 8z | $960.00 |
| Schedule 1 line 10 | lines 1-7 and 9 | $960.00 |
| Form 1040 line 8 | Schedule 1 line 10 | $960.00 |
| Form 1040 line 6a | SSA-1099 box 5 | $0.00 |
| Schedule 1 line 26 | Schedule 1 lines 11-25: student loan interest only | $0.00 |
| Form 1040 line 10 | Schedule 1 line 26 | $0.00 |
| Form 1040 line 6b | no benefits | $0.00 |
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7 + 8 | $152,400.00 |
| Form 1040 line 11 | line 9 - line 10 | $152,400.00 |
| Form 1040 line 12 | standard deduction (mfj) | $29,200.00 |
| Form 1040 line 13 | no qualified business income | $0.00 |
| Form 1040 line 14 | 12 + 13 | $29,200.00 |
| Form 1040 line 15 | line 11 - line 14 | $123,200.00 |
| | QDCGT worksheet: 1 $123,200.00; 2 $1,440.00; 3 $0.00; 4 $1,440.00; 5 $121,760.00; 6 $94,050.00; 7 $94,050.00; 8 $94,050.00; 9 (0%) $0.00; 10 $1,440.00; 12 $1,440.00; 13 $583,750.00; 14 $123,200.00; 15 $121,760.00; 16 $1,440.00; 17 $1,440.00; 18 = 15% $216.00; 19 $1,440.00; 20 $0.00; 21 = 20% $0.00; 22 = tax on line 5 $16,893.20 (Tax Computation Worksheet (exact schedule)); 23 $17,109.20; 24 = tax on line 1 $17,210.00; 25 = min | |
| | exact rate-schedule tax (what the engine computes): $17,239.20 | |
| Form 1040 line 16 | QDCGT worksheet line 25 + Form 8814 line 15 $130.00 | $17,239.20 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $17,239.20 |
| | Schedule 8812: 1 x $2,000.00 = $2,000.00; MAGI under $400,000.00; Credit Limit Worksheet A: line 18 less Schedule 3 lines 1-4 = $17,239.20 | |
| Form 1040 line 19 | Schedule 8812 line 14 | $2,000.00 |
| Form 8812 line 14 | smaller of line 12 and Credit Limit Worksheet A | $2,000.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $2,000.00 |
| Form 1040 line 22 | 18 - 21 | $15,239.20 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24 | 22 + 23 | $15,239.20 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
