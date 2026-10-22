# self employed single 2026: worked return

Single self-employed consultant with $150,000 of net profit: self-employment tax (Schedule SE), the deductible half, a SEP contribution at a 25% plan rate (Pub. 560: 20% of net earnings) and the qualified business income deduction (Form 8995). Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

Tolerance: the forms round Schedule SE line 13 and the SEP deduction to the cent before adding them; the engine carries them unrounded, so lines that add them are compared within $0.10.


| Line | How | Amount |
|---|---|---:|
| Form 1040 line 1a | no W-2 | $0.00 |
| Form 1040 line 1z | line 1a | $0.00 |
| Form 1040 line 2a | no tax-exempt interest | $0.00 |
| Form 1040 line 2b | 1099-INT box 1 (Schedule B line 4) | $0.00 |
| Form 1040 line 3a | 1099-DIV box 1b | $0.00 |
| Form 1040 line 3b | 1099-DIV box 1a (all dividends here are qualified) | $0.00 |
| Form 1040 line 4a | 1099-R box 1 (required minimum distributions) | $0.00 |
| Form 1040 line 4b | 1099-R box 2a (no basis: fully taxable) | $0.00 |
| Form 1040 line 5b | no pensions | $0.00 |
| Form 1040 line 7a | none | $0.00 |
| Schedule C line 31 | net profit (gross receipts less expenses) | $150,000.00 |
| Schedule SE line 2 | Schedule C line 31 | $150,000.00 |
| Schedule SE line 3 | line 2 | $150,000.00 |
| Schedule SE line 4a | line 3 x 92.35% | $138,525.00 |
| Schedule SE line 4c | line 4a | $138,525.00 |
| Schedule SE line 6 | line 4c | $138,525.00 |
| | Schedule SE: 7 = $184,500.00; 8d W-2 SS wages $0.00; 10 = 12.4% x min(6, 9) = $17,177.10; 11 = 2.9% x 6 = $4,017.23 | |
| Schedule SE line 12 | 10 + 11 | $21,194.33 |
| Schedule SE line 13 | 50% of line 12 | $10,597.17 |
| Schedule 1 line 3 | Schedule C line 31 | $150,000.00 |
| Schedule 1 line 10 | lines 1-7 and 9 | $150,000.00 |
| Form 1040 line 8 | Schedule 1 line 10 | $150,000.00 |
| Form 1040 line 6a | SSA-1099 box 5 | $0.00 |
| | Pub. 560 worksheet: 1 $150,000.00; 2 $10,597.17; 3 $139,402.83; 4 rate 0.200000 (plan rate 25%); 5 = $27,880.57; 6 = $360,000.00 x 0.25; 8 = $72,000.00; 21 = smallest | |
| Schedule 1 line 16 | SEP deduction (Pub. 560 worksheet step 21) | $27,880.57 |
| Schedule 1 line 15 | Schedule SE line 13 | $10,597.17 |
| Schedule 1 line 26 | Schedule 1 lines 11-25 | $38,477.74 |
| Form 1040 line 10 | Schedule 1 line 26 | $38,477.74 |
| Form 1040 line 6b | no benefits | $0.00 |
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7a + 8 | $150,000.00 |
| Form 1040 line 11a | line 9 - line 10 | $111,522.26 |
| Form 1040 line 11b | line 11a | $111,522.26 |
| Form 1040 line 12e | standard deduction (single) | $16,100.00 |
| Form 8995 line 1 | net profit - Schedule 1 lines 15 and 16 (attributable to the business) | $111,522.26 |
| | Form 8995: 5 = 20% x $111,522.26 = $22,304.45; 11 taxable income before QBI $95,422.26; 12 net capital gain $0.00; 14 = 20% x (11 - 12) $19,084.45 | |
| Form 8995 line 15 | smaller of line 5 and line 14 | $19,084.45 |
| Form 1040 line 12f | itemizes or no cash gifts (non-itemizer charitable deduction) | $0.00 |
| Form 1040 line 13a | Schedule 1-A line 44 | $0.00 |
| Form 1040 line 13b | Form 8995 line 15 | $19,084.45 |
| Form 1040 line 14 | 12e + 12f + 13a + 13b | $35,184.45 |
| Form 1040 line 15 | line 11b - line 14 | $76,337.81 |
| | exact rate-schedule tax (what the engine computes): $11,506.32 | |
| Form 1040 line 16 | Tax Table row $76,300-$76,350: schedule tax on the midpoint $76,325.00, rounded | $11,504.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $11,504.00 |
| Form 1040 line 19 | no qualifying children | $0.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $0.00 |
| Form 1040 line 22 | 18 - 21 | $11,504.00 |
| Schedule 2 line 4 | Schedule SE line 12 | $21,194.33 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $21,194.33 |
| Form 1040 line 23 | Schedule 2 line 21 | $21,194.33 |
| Form 1040 line 24a | 22 + 23 | $32,698.33 |
| Form 1040 line 24c | 24a + 24b (no Form 1062) | $32,698.33 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
