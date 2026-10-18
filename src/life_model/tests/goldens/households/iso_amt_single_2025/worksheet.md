# iso amt single 2025: worked return

Single filer with $200,000 of wages who exercises incentive stock options and holds the shares (a $400,000 bargain element): alternative minimum tax and the minimum tax credit it creates. Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

W-2 Example Analytics (morgan): box 1 = $200,000.00 - 401(k) $0.00 = $200,000.00; box 3 = min(wages, $176,100.00) = $176,100.00; box 4 = 6.2% = $10,918.20; box 5 = $200,000.00; box 6 = 1.45% (+0.9% over $200,000) = $2,900.00.

| Line | How | Amount |
|---|---|---:|
| Form 1040 line 1a | W-2 box 1 Example Analytics $200,000.00 | $200,000.00 |
| Form 1040 line 1z | line 1a | $200,000.00 |
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
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7a + 8 | $200,000.00 |
| Form 1040 line 11a | line 9 - line 10 | $200,000.00 |
| Form 1040 line 11b | line 11a | $200,000.00 |
| Form 1040 line 12e | standard deduction (single) | $15,750.00 |
| Form 1040 line 13a | no qualified business income | $0.00 |
| Form 1040 line 13b | Schedule 1-A line 38 | $0.00 |
| Form 1040 line 14 | 12e + 13a + 13b | $15,750.00 |
| Form 1040 line 15 | line 11b - line 14 | $184,250.00 |
| | exact rate-schedule tax (what the engine computes): $37,067.00 | |
| Form 1040 line 16 | Tax Computation Worksheet (exact schedule) | $37,067.00 |
| | Form 6251: 1 = taxable income $184,250.00; 2a = standard deduction $15,750.00; 2i ISO $400,000.00; 4 AMTI $600,000.00; 5 exemption $88,100.00; 6 $511,900.00; 7 = 26%/28% (breakpoint $239,100.00) -> 9 tentative minimum tax $138,550.00; 10 regular tax $37,067.00 | |
| Form 6251 line 4 | alternative minimum taxable income | $600,000.00 |
| Form 6251 line 9 | tentative minimum tax | $138,550.00 |
| Form 6251 line 11 | line 9 - line 10 | $101,483.00 |
| | Form 8801 Part I (next year's credit): AMT on exclusion items only: tentative minimum tax $29,094.00 - regular tax = $0.00; credit carried forward = $101,483.00 - that = $101,483.00 | |
| Form 1040 line 17 | Form 6251 line 11 (Schedule 2 line 3) | $101,483.00 |
| Schedule 2 line 2 | Form 6251 line 11 | $101,483.00 |
| Schedule 2 line 3 | 1z + 2 | $101,483.00 |
| Form 1040 line 18 | 16 + 17 | $138,550.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $0.00 |
| Form 1040 line 22 | 18 - 21 | $138,550.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24 | 22 + 23 | $138,550.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
