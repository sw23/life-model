# married homeowners 2024: worked return

Married filing jointly: two W-2s over the Additional Medicare threshold, two children, mortgage interest, property tax, cash gifts (itemizes), savings interest (NIIT). Synthetic household (`spec.yaml`); computed by `scripts/household_goldens.py` from the forms, independent of the library.

Tolerance: the engine accrues mortgage interest unrounded; the 1098 rounds each month's interest to the cent, so lines that carry it are compared within $0.10.

W-2 Example Consulting LLC (john): box 1 = $185,000.00 - 401(k) $18,500.00 = $166,500.00; box 3 = min(wages, $168,600.00) = $168,600.00; box 4 = 6.2% = $10,453.20; box 5 = $185,000.00; box 6 = 1.45% (+0.9% over $200,000) = $2,682.50.
W-2 Example Analytics (jane): box 1 = $95,000.00 - 401(k) $4,750.00 = $90,250.00; box 3 = min(wages, $168,600.00) = $95,000.00; box 4 = 6.2% = $5,890.00; box 5 = $95,000.00; box 6 = 1.45% (+0.9% over $200,000) = $1,377.50.

| Line | How | Amount |
|---|---|---:|
| Form 1040 line 1a | W-2 box 1 Example Consulting LLC $166,500.00 + W-2 box 1 Example Analytics $90,250.00 | $256,750.00 |
| Form 1040 line 1z | line 1a | $256,750.00 |
| Form 1040 line 2a | no tax-exempt interest | $0.00 |
| Form 1040 line 2b | 1099-INT box 1 (Schedule B line 4) | $400.00 |
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
| Form 1040 line 9 | 1z + 2b + 3b + 4b + 5b + 6b + 7 + 8 | $257,150.00 |
| Form 1040 line 11 | line 9 - line 10 | $257,150.00 |
| | Schedule A line 5b real estate tax $13,000.00; 5d = 5a (no state income tax) + 5b = $13,000.00 (not compared: the engine records SALT after the cap) | |
| Schedule A line 5e | smaller of 5d and the $10,000 cap | $10,000.00 |
| Schedule A line 7 | 5e + 6 | $10,000.00 |
| Schedule A line 8a | 1098 box 1 | $30,950.00 |
| Schedule A line 8e | 8a | $30,950.00 |
| Schedule A line 10 | 8e (no investment interest) | $30,950.00 |
| Schedule A line 11 | cash gifts (well under 60% of AGI) | $6,000.00 |
| Schedule A line 14 | 11 + 12 + 13 | $6,000.00 |
| Schedule A line 17 | 7 + 10 + 14 | $46,950.00 |
| Form 1040 line 12 | Schedule A line 17 | $46,950.00 |
| Form 1040 line 13 | no qualified business income | $0.00 |
| Form 1040 line 14 | 12 + 13 | $46,950.00 |
| Form 1040 line 15 | line 11 - line 14 | $210,200.00 |
| | exact rate-schedule tax (what the engine computes): $36,533.00 | |
| Form 1040 line 16 | Tax Computation Worksheet (exact schedule) | $36,533.00 |
| Form 1040 line 17 | no AMT (Schedule 2 line 3) | $0.00 |
| Form 1040 line 18 | 16 + 17 | $36,533.00 |
| | Schedule 8812: 2 x $2,000.00 = $4,000.00; MAGI under $400,000.00; limited by tax $36,533.00 | |
| Form 1040 line 19 | Schedule 8812 line 14 | $4,000.00 |
| Form 1040 line 20 | Schedule 3 line 8: no other credits | $0.00 |
| Form 1040 line 21 | 19 + 20 | $4,000.00 |
| Form 1040 line 22 | 18 - 21 | $32,533.00 |
| Schedule 2 line 11 | Form 8959: 0.9% x (Medicare wages $280,000.00 - $250,000.00) | $270.00 |
| Schedule 2 line 12 | Form 8960: 3.8% x min(NII $400.00, MAGI - $250,000.00) | $15.20 |
| Schedule 2 line 21 | Schedule 2 total other taxes | $285.20 |
| Form 1040 line 23 | Schedule 2 line 21 | $285.20 |
| Form 1040 line 24 | 22 + 23 | $32,818.20 |
| Form 1040 line 28 | no additional child tax credit (credit fully used) | $0.00 |
