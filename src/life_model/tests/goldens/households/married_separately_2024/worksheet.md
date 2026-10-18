# married separately 2024: worked return

Married filing separately: each spouse's own W-2; the student loan interest deduction is not allowed on a separate return. Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

W-2 Example Consulting LLC (morgan): box 1 = $120,000.00 - 401(k) $9,600.00 = $110,400.00; box 3 = min(wages, $168,600.00) = $120,000.00; box 4 = 6.2% = $7,440.00; box 5 = $120,000.00; box 6 = 1.45% (+0.9% over $200,000) = $1,740.00.
W-2 Example Analytics (casey): box 1 = $48,000.00 - 401(k) $0.00 = $48,000.00; box 3 = min(wages, $168,600.00) = $48,000.00; box 4 = 6.2% = $2,976.00; box 5 = $48,000.00; box 6 = 1.45% (+0.9% over $200,000) = $696.00.

## Return of morgan (mfs)

| Line | How | Amount |
|---|---|---:|
| Form 1040 line 1a | W-2 box 1 Example Consulting LLC $110,400.00 | $110,400.00 |
| Form 1040 line 1z | line 1a | $110,400.00 |
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
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7 + 8 | $110,400.00 |
| Form 1040 line 11 | line 9 - line 10 | $110,400.00 |
| Form 1040 line 12 | standard deduction (mfs) | $14,600.00 |
| Form 1040 line 13 | no qualified business income | $0.00 |
| Form 1040 line 14 | 12 + 13 | $14,600.00 |
| Form 1040 line 15 | line 11 - line 14 | $95,800.00 |
| | exact rate-schedule tax (what the engine computes): $16,129.00 | |
| Form 1040 line 16 | Tax Table row $95,800-$95,850: schedule tax on the midpoint $95,825.00, rounded | $16,135.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $16,135.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $0.00 |
| Form 1040 line 22 | 18 - 21 | $16,135.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24 | 22 + 23 | $16,135.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |

## Return of casey (mfs)

| Line | How | Amount |
|---|---|---:|
| Form 1040 line 1a | W-2 box 1 Example Analytics $48,000.00 | $48,000.00 |
| Form 1040 line 1z | line 1a | $48,000.00 |
| Form 1040 line 2a | no tax-exempt interest | $0.00 |
| Form 1040 line 2b | 1099-INT box 1 (Schedule B line 4) | $300.00 |
| Form 1040 line 3a | 1099-DIV box 1b | $0.00 |
| Form 1040 line 3b | 1099-DIV box 1a (all dividends here are qualified) | $0.00 |
| Form 1040 line 4a | 1099-R box 1 (required minimum distributions) | $0.00 |
| Form 1040 line 4b | 1099-R box 2a (no basis: fully taxable) | $0.00 |
| Form 1040 line 5b | no pensions | $0.00 |
| Form 1040 line 7 | none | $0.00 |
| Form 1040 line 8 | Schedule 1 line 10: no additional income | $0.00 |
| Form 1040 line 6a | SSA-1099 box 5 | $0.00 |
| Schedule 1 line 21 | not allowed on a separate return (IRC §221(e)(2)) | $0.00 |
| Schedule 1 line 26 | Schedule 1 lines 11-25: student loan interest only | $0.00 |
| Form 1040 line 10 | Schedule 1 line 26 | $0.00 |
| Form 1040 line 6b | no benefits | $0.00 |
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7 + 8 | $48,300.00 |
| Form 1040 line 11 | line 9 - line 10 | $48,300.00 |
| Form 1040 line 12 | standard deduction (mfs) | $14,600.00 |
| Form 1040 line 13 | no qualified business income | $0.00 |
| Form 1040 line 14 | 12 + 13 | $14,600.00 |
| Form 1040 line 15 | line 11 - line 14 | $33,700.00 |
| | exact rate-schedule tax (what the engine computes): $3,812.00 | |
| Form 1040 line 16 | Tax Table row $33,700-$33,750: schedule tax on the midpoint $33,725.00, rounded | $3,815.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $3,815.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $0.00 |
| Form 1040 line 22 | 18 - 21 | $3,815.00 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $0.00 |
| Form 1040 line 23 | Schedule 2 line 21 | $0.00 |
| Form 1040 line 24 | 22 + 23 | $3,815.00 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
