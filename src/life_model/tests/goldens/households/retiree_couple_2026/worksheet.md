# retiree couple 2026: worked return

Retirees filing jointly (75 and 73): RMDs from two traditional IRAs, Social Security, savings interest, both 65+. Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

RMDs (Pub. 590-B): pat $48,780.49; lee $30,188.68 ($1,200,000 / 24.6 at 75; $800,000 / 26.5 at 73). Social Security (SSA-1099 box 5) is an input: $56,652.00.


| Line | How | Amount |
|---|---|---:|
| Form 1040 line 1a | no W-2 | $0.00 |
| Form 1040 line 1z | line 1a | $0.00 |
| Form 1040 line 2a | no tax-exempt interest | $0.00 |
| Form 1040 line 2b | 1099-INT box 1 (Schedule B line 4) | $2,000.00 |
| Form 1040 line 3a | 1099-DIV box 1b | $0.00 |
| Form 1040 line 3b | 1099-DIV box 1a (all dividends here are qualified) | $0.00 |
| Form 1040 line 4a | 1099-R box 1 (required minimum distributions) | $78,969.17 |
| Form 1040 line 4b | 1099-R box 2a (no basis: fully taxable) | $78,969.17 |
| Form 1040 line 5b | no pensions | $0.00 |
| Form 1040 line 7a | none | $0.00 |
| Form 1040 line 8 | Schedule 1 line 10: no additional income | $0.00 |
| Form 1040 line 6a | SSA-1099 box 5 | $56,652.00 |
| Schedule 1 line 26 | Schedule 1 lines 11-25: student loan interest only | $0.00 |
| Form 1040 line 10 | Schedule 1 line 26 | $0.00 |
| | SS worksheet: 1 $56,652.00; 2 = 50% $28,326.00; 3 = 1z+2b+3b+4b+5b+7a+8 $80,969.17; 5 = 2+3+2a $109,295.17; 7 = 5 - 10 $109,295.17; 8 $32,000.00; 9 $77,295.17; 10 $12,000.00; 11 $65,295.17; 12 $12,000.00; 13 $6,000.00; 14 $6,000.00; 15 = 85% x 11 $55,500.89; 16 $61,500.89; 17 = 85% x 1 $48,154.20; 18 = min(16, 17) | |
| Form 1040 line 6b | Social Security Benefits Worksheet line 18 | $48,154.20 |
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7a + 8 | $129,123.37 |
| Form 1040 line 11a | line 9 - line 10 | $129,123.37 |
| Form 1040 line 11b | line 11a | $129,123.37 |
| | standard deduction $32,200.00 + §63(f) 2 x $1,650.00 | |
| Form 1040 line 12e | standard deduction (mfj) | $35,500.00 |
| Schedule 1-A line 43 | 2 x ($6,000 - 6% x max(MAGI - $150,000.00, 0)) | $12,000.00 |
| Schedule 1-A line 44 | no tips, overtime or car-loan interest | $12,000.00 |
| Form 1040 line 12f | itemizes or no cash gifts (non-itemizer charitable deduction) | $0.00 |
| Form 1040 line 13a | Schedule 1-A line 44 | $12,000.00 |
| Form 1040 line 13b | no qualified business income | $0.00 |
| Form 1040 line 14 | 12e + 12f + 13a + 13b | $47,500.00 |
| Form 1040 line 15 | line 11b - line 14 | $81,623.37 |
| | exact rate-schedule tax (what the engine computes): $9,298.80 | |
| Form 1040 line 16 | Tax Table row $81,600-$81,650: schedule tax on the midpoint $81,625.00, rounded | $9,299.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $9,299.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $0.00 |
| Form 1040 line 22 | 18 - 21 | $9,299.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24a | 22 + 23 | $9,299.00 |
| Form 1040 line 24c | 24a + 24b (no Form 1062) | $9,299.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |

## Expected failures

- `1040:12e`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,650 per person on a joint return in 2026)
- `1040:14`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,650 per person on a joint return in 2026)
- `1040:15`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,650 per person on a joint return in 2026)
- `1040:16`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,650 per person on a joint return in 2026)
- `1040:18`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,650 per person on a joint return in 2026)
- `1040:22`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,650 per person on a joint return in 2026)
- `1040:24a`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,650 per person on a joint return in 2026)
- `1040:24c`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,650 per person on a joint return in 2026)
- `exact:1040:16`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,650 per person on a joint return in 2026)
- `spending:medicare_premiums_annual`: missing_input (Plan 27): the spec cannot carry the 2024 MAGI the 2026 IRMAA tier is based on; the engine has no AGI history before its first year and charges the base premium
