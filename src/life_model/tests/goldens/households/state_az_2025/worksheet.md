# state az 2025: worked return

Single W-2 earner ($65,000) in AZ: the federal return and the AZ state return. Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

W-2 Example Analytics (casey): box 1 = $65,000.00 - 401(k) $0.00 = $65,000.00; box 3 = min(wages, $176,100.00) = $65,000.00; box 4 = 6.2% = $4,030.00; box 5 = $65,000.00; box 6 = 1.45% (+0.9% over $200,000) = $942.50.

| Line | How | Amount |
|---|---|---:|
| Form 1040 line 1a | W-2 box 1 Example Analytics $65,000.00 | $65,000.00 |
| Form 1040 line 1z | line 1a | $65,000.00 |
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
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7a + 8 | $65,000.00 |
| Form 1040 line 11a | line 9 - line 10 | $65,000.00 |
| Form 1040 line 11b | line 11a | $65,000.00 |
| Form 1040 line 12e | standard deduction (single) | $15,750.00 |
| Form 1040 line 13a | no qualified business income | $0.00 |
| Form 1040 line 13b | Schedule 1-A line 38 | $0.00 |
| Form 1040 line 14 | 12e + 13a + 13b | $15,750.00 |
| Form 1040 line 15 | line 11b - line 14 | $49,250.00 |
| | exact rate-schedule tax (what the engine computes): $5,749.00 | |
| Form 1040 line 16 | Tax Table row $49,250-$49,300: schedule tax on the midpoint $49,275.00, rounded | $5,755.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $5,755.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $0.00 |
| Form 1040 line 22 | 18 - 21 | $5,755.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24 | 22 + 23 | $5,755.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
| | AZ return: income $65,000.00; deductions and exemptions $15,750.00; taxable $49,250.00; tax $1,231.25 | |
