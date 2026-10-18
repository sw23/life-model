# appreciated stock gift 2026: worked return

Single filer with $800,000 of wages giving $300,000 of long-term appreciated shares (basis $60,000): deducted at fair market value up to 30% of AGI with the rest carried over, no capital gain; from 2026 the 0.5% floor and the 2/37 limit on itemized deductions. Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

W-2 Example Consulting LLC (pat): box 1 = $800,000.00 - 401(k) $0.00 = $800,000.00; box 3 = min(wages, $184,500.00) = $184,500.00; box 4 = 6.2% = $11,439.00; box 5 = $800,000.00; box 6 = 1.45% (+0.9% over $200,000) = $17,000.00.

| Line | How | Amount |
|---|---|---:|
| Form 1040 line 1a | W-2 box 1 Example Consulting LLC $800,000.00 | $800,000.00 |
| Form 1040 line 1z | line 1a | $800,000.00 |
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
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7a + 8 | $800,000.00 |
| Form 1040 line 11a | line 9 - line 10 | $800,000.00 |
| Form 1040 line 11b | line 11a | $800,000.00 |
| Schedule A line 5e | smaller of 5d and the $40,400 cap | $0.00 |
| Schedule A line 7 | 5e + 6 | $0.00 |
| Schedule A line 8a | 1098 box 1 | $0.00 |
| Schedule A line 8e | 8a | $0.00 |
| Schedule A line 10 | 8e (no investment interest) | $0.00 |
| | 0.5% floor (IRC §170(b)(1)(I), OBBBA): 0.5% x AGI $800,000.00 = $4,000.00, taken from property first ($4,000.00) then cash ($0.00) | |
| Schedule A line 11 | cash gifts (within 60% of AGI) | $0.00 |
| Schedule A line 12 | appreciated long-term shares at FMV $300,000.00, limited to 30% of AGI $240,000.00 and 50% of AGI less cash gifts less the 0.5% floor | $236,000.00 |
| Schedule A line 14 | 11 + 12 + 13 | $236,000.00 |
| | IRC §68 (OBBBA): 2/37 x min(itemized $236,000.00, taxable income before §68 plus itemized $800,000.00 - 37% bracket start $640,600.00) = $8,616.22 | |
| Schedule A line 17 | 5e/7 + 10 + 14 less the §68 reduction | $227,383.78 |
| Form 1040 line 12e | Schedule A line 17 | $227,383.78 |
| Form 1040 line 12f | itemizes or no cash gifts (non-itemizer charitable deduction) | $0.00 |
| Form 1040 line 13a | Schedule 1-A line 44 | $0.00 |
| Form 1040 line 13b | no qualified business income | $0.00 |
| Form 1040 line 14 | 12e + 12f + 13a + 13b | $227,383.78 |
| Form 1040 line 15 | line 11b - line 14 | $572,616.22 |
| | exact rate-schedule tax (what the engine computes): $169,184.93 | |
| Form 1040 line 16 | Tax Computation Worksheet (exact schedule) | $169,184.93 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $169,184.93 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $0.00 |
| Form 1040 line 22 | 18 - 21 | $169,184.93 |
| Schedule 2 line 17b | Form 8959: 0.9% x (Medicare wages $800,000.00 - $200,000.00) | $5,400.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $5,400.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $5,400.00 |
| Form 1040 line 24a | 22 + 23 | $174,584.93 |
| Form 1040 line 24c | 24a + 24b (no Form 1062) | $174,584.93 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
