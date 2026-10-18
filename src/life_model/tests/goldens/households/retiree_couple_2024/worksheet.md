# retiree couple 2024: worked return

Retirees filing jointly (75 and 73): RMDs from two traditional IRAs, Social Security, savings interest, both 65+. Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

RMDs (Pub. 590-B): pat $48,780.49; lee $30,188.68 ($1,200,000 / 24.6 at 75; $800,000 / 26.5 at 73). Social Security (SSA-1099 box 5) is an input: $53,478.00.


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
| Form 1040 line 7 | none | $0.00 |
| Form 1040 line 8 | Schedule 1 line 10: no additional income | $0.00 |
| Form 1040 line 6a | SSA-1099 box 5 | $53,478.00 |
| Schedule 1 line 26 | Schedule 1 lines 11-25: student loan interest only | $0.00 |
| Form 1040 line 10 | Schedule 1 line 26 | $0.00 |
| | SS worksheet: 1 $53,478.00; 2 = 50% $26,739.00; 3 = 1z+2b+3b+4b+5b+7+8 $80,969.17; 5 = 2+3+2a $107,708.17; 7 = 5 - 10 $107,708.17; 8 $32,000.00; 9 $75,708.17; 10 $12,000.00; 11 $63,708.17; 12 $12,000.00; 13 $6,000.00; 14 $6,000.00; 15 = 85% x 11 $54,151.94; 16 $60,151.94; 17 = 85% x 1 $45,456.30; 18 = min(16, 17) | |
| Form 1040 line 6b | Social Security Benefits Worksheet line 18 | $45,456.30 |
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7 + 8 | $126,425.47 |
| Form 1040 line 11 | line 9 - line 10 | $126,425.47 |
| | standard deduction $29,200.00 + §63(f) 2 x $1,550.00 | |
| Form 1040 line 12 | standard deduction (mfj) | $32,300.00 |
| Form 1040 line 13 | no qualified business income | $0.00 |
| Form 1040 line 14 | 12 + 13 | $32,300.00 |
| Form 1040 line 15 | line 11 - line 14 | $94,125.47 |
| | exact rate-schedule tax (what the engine computes): $10,831.06 | |
| Form 1040 line 16 | Tax Table row $94,100-$94,150: schedule tax on the midpoint $94,125.00, rounded | $10,831.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $10,831.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $0.00 |
| Form 1040 line 22 | 18 - 21 | $10,831.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24 | 22 + 23 | $10,831.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |

## Expected failures

- `1040:12`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,550 per person on a joint return in 2024)
- `1040:14`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,550 per person on a joint return in 2024)
- `1040:15`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,550 per person on a joint return in 2024)
- `1040:16`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,550 per person on a joint return in 2024)
- `1040:18`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,550 per person on a joint return in 2024)
- `1040:22`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,550 per person on a joint return in 2024)
- `1040:24`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,550 per person on a joint return in 2024)
- `exact:1040:16`: Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for age 65+ ($1,550 per person on a joint return in 2024)
