# retiree couple 2025: worked return

Retirees filing jointly (75 and 73): RMDs from two traditional IRAs, Social Security, savings interest, both 65+. Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

RMDs (Pub. 590-B): pat $48,780.49; lee $30,188.68 ($1,200,000 / 24.6 at 75; $800,000 / 26.5 at 73). Social Security (SSA-1099 box 5) is an input: $54,766.80.


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
| Form 1040 line 6a | SSA-1099 box 5 | $54,766.80 |
| Schedule 1 line 26 | Schedule 1 lines 11-25: student loan interest only | $0.00 |
| Form 1040 line 10 | Schedule 1 line 26 | $0.00 |
| | SS worksheet: 1 $54,766.80; 2 = 50% $27,383.40; 3 = 1z+2b+3b+4b+5b+7a+8 $80,969.17; 5 = 2+3+2a $108,352.57; 7 = 5 - 10 $108,352.57; 8 $32,000.00; 9 $76,352.57; 10 $12,000.00; 11 $64,352.57; 12 $12,000.00; 13 $6,000.00; 14 $6,000.00; 15 = 85% x 11 $54,699.68; 16 $60,699.68; 17 = 85% x 1 $46,551.78; 18 = min(16, 17) | |
| Form 1040 line 6b | Social Security Benefits Worksheet line 18 | $46,551.78 |
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7a + 8 | $127,520.95 |
| Form 1040 line 11a | line 9 - line 10 | $127,520.95 |
| Form 1040 line 11b | line 11a | $127,520.95 |
| | standard deduction $31,500.00 + §63(f) 2 x $1,600.00 | |
| Form 1040 line 12e | standard deduction (mfj) | $34,700.00 |
| Schedule 1-A line 37 | 2 x ($6,000 - 6% x max(MAGI - $150,000.00, 0)) | $12,000.00 |
| Schedule 1-A line 38 | no tips, overtime or car-loan interest | $12,000.00 |
| Form 1040 line 13a | no qualified business income | $0.00 |
| Form 1040 line 13b | Schedule 1-A line 38 | $12,000.00 |
| Form 1040 line 14 | 12e + 13a + 13b | $46,700.00 |
| Form 1040 line 15 | line 11b - line 14 | $80,820.95 |
| | exact rate-schedule tax (what the engine computes): $9,221.51 | |
| Form 1040 line 16 | Tax Table row $80,800-$80,850: schedule tax on the midpoint $80,825.00, rounded | $9,222.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $9,222.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $0.00 |
| Form 1040 line 22 | 18 - 21 | $9,222.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24 | 22 + 23 | $9,222.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |

## Expected failures

- `1040:12e`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,600 per person on a joint return in 2025)
- `1040:14`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,600 per person on a joint return in 2025)
- `1040:15`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,600 per person on a joint return in 2025)
- `1040:16`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,600 per person on a joint return in 2025)
- `1040:18`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,600 per person on a joint return in 2025)
- `1040:22`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,600 per person on a joint return in 2025)
- `1040:24`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,600 per person on a joint return in 2025)
- `exact:1040:16`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,600 per person on a joint return in 2025)
