# withholding single 2024: worked return

Single W-2 earner with a 5% 401(k) deferral, a default Form W-4 (Pub. 15-T withholding) and savings interest: the refund or balance due settled in April. Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

W-2 Example Analytics (alex): box 1 = $85,000.00 - 401(k) $4,250.00 = $80,750.00; box 3 = min(wages, $168,600.00) = $85,000.00; box 4 = 6.2% = $5,270.00; box 5 = $85,000.00; box 6 = 1.45% (+0.9% over $200,000) = $1,232.50.

W-2 box 2 (single Form W-4, no other entries): Pub. 15-T Worksheet 1A, each month: 1a $6,729.17; 1c x 12 = $80,750.00; 1g $8,600.00; 1i $72,150.00; table row over $53,150.00: $5,426.00 + 22% = $9,606.00; 2h / 12 = $800.50; box 2 = 12 paychecks = $9,606.00.

| Line | How | Amount |
|---|---|---:|
| Form 1040 line 1a | W-2 box 1 Example Analytics $80,750.00 | $80,750.00 |
| Form 1040 line 1z | line 1a | $80,750.00 |
| Form 1040 line 2a | no tax-exempt interest | $0.00 |
| Form 1040 line 2b | 1099-INT box 1 (Schedule B line 4) | $1,000.00 |
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
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7 + 8 | $81,750.00 |
| Form 1040 line 11 | line 9 - line 10 | $81,750.00 |
| Form 1040 line 12 | standard deduction (single) | $14,600.00 |
| Form 1040 line 13 | no qualified business income | $0.00 |
| Form 1040 line 14 | 12 + 13 | $14,600.00 |
| Form 1040 line 15 | line 11 - line 14 | $67,150.00 |
| | exact rate-schedule tax (what the engine computes): $9,826.00 | |
| Form 1040 line 16 | Tax Table row $67,150-$67,200: schedule tax on the midpoint $67,175.00, rounded | $9,832.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $9,832.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $0.00 |
| Form 1040 line 22 | 18 - 21 | $9,832.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24 | 22 + 23 | $9,832.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
| Form 1040 line 25a | W-2 box 2 | $9,606.00 |
| Form 1040 line 25c | Form 8959 line 24 | $0.00 |
| Form 1040 line 25d | 25a + 25b + 25c | $9,606.00 |
| Form 1040 line 26 | Form 1040-ES payments (April, June, September and January) | $0.00 |
| Form 1040 line 31 | Schedule 3 line 15 | $0.00 |
| Form 1040 line 32 | 27 + 28 + 29 + 30 + 31 | $0.00 |
| Form 1040 line 33 | 25d + 26 + 32 | $9,606.00 |
| Form 1040 line 34 | no overpayment | $0.00 |
| Form 1040 line 37 | 24 - 33 + the line 38 penalty | $226.00 |
| Form 1040 line 38 | no estimated tax penalty | $0.00 |
