# Plan 29 re-baseline log

Plan 29 adds reconciliation against real records, household goldens, the invariant checker and a
backtest. Three parts of it change simulation outputs; every change is listed here with its source.
**No existing test's expected value changed.**

## Invariant checker finding: brokerage sales sized before loss netting

The new `no_draw_above_cash_floor` invariant (see [reconciliation.md](reconciliation.md)) flagged
years in the stochastic test scenarios where the waterfall sold brokerage and the unit still ended
the year with $16-$491 in the bank. Cause: settlement nets capital gains and losses (and applies a
prior-year capital-loss carryforward) only *after* the brokerage sale, so the sale was sized against
tax on gains the carryforward was about to cancel and over-sold by that tax. Sizing now previews the
year's netting on a scratch copy of the members' ledgers (`TaxUnit._taxes_with_sale`).

Effect: only years with a capital-loss carryforward or a net capital loss change; the sale is
smaller by the over-estimated tax (brokerage balance higher, year-end bank lower, identical settled
taxes). Across 51 seeds x 4 broad scenarios no violation remains. Runs without losses are
byte-identical (the plain preview is kept when netting would change nothing).

## RL action ledger posting

RL actions (between `model.step()` calls) now post the money they move: bank-to-account transfers
as contributions, the employer match on a bank-to-401k deferral as an employer inflow, and the Roth
401k early-withdrawal penalty as an outflow. IRA/HSA transfers used to post as new money while the
bank debit went unposted. Balances are unchanged; only the ledger differs.

## Task 3: tax parameters verified and moved into `tax_years`

Sources were fetched on 2026-10-18 from irs.gov (Rev. Procs. 2021-45, 2022-38, 2023-34, 2024-40,
2025-32; Notices 2022-55, 2023-75, 2024-80, 2025-67; HSA Rev. Procs. 2022-24, 2023-23, 2024-25,
2025-19), govinfo (OBBBA, P.L. 119-21, 139 Stat. 72) and SSA's contribution and benefit base page
(via a web.archive.org capture, as ssa.gov refuses automated fetches). Every 2023-2026 standard
deduction, bracket, wage base, 401(k)/415(c)/IRA/HSA limit and gift exclusion already in the table
matched its source, except the one fixed below.

| Parameter | Old | New | Source |
|---|---|---|---|
| 2026 head-of-household 24% bracket top | $201,775 | $201,750 | Rev. Proc. 2025-32 §4.01 Table 2 ("over $105,700 but not over $201,750"; the next row's $39,207 base confirms it) |
| Capital-gains brackets 2022 | static 2026 table, every year | 0% to $41,675 / $83,350 / $55,800 / $41,675 (S / MFJ / HoH / MFS), 15% to $459,750 / $517,200 / $488,500 / $258,600 | Rev. Proc. 2021-45 §3.03 |
| Capital-gains brackets 2023 | static 2026 table | $44,625 / $89,250 / $59,750 / $44,625; $492,300 / $553,850 / $523,050 / $276,900 | Rev. Proc. 2022-38 §3.03 |
| Capital-gains brackets 2024 | static 2026 table | $47,025 / $94,050 / $63,000 / $47,025; $518,900 / $583,750 / $551,350 / $291,850 | Rev. Proc. 2023-34 §3.03 |
| Capital-gains brackets 2025 | static 2026 table | $48,350 / $96,700 / $64,750 / $48,350; $533,400 / $600,050 / $566,700 / $300,000 | Rev. Proc. 2024-40 §2.03 |
| Capital-gains brackets, separate returns | joint table halved | set explicitly (the published 15% top is $25 below half the joint one in 2023-2025) | same Rev. Procs. |
| Child Tax Credit 2022 / 2023 / 2024 | $2,200, refundable $1,700 | $2,000, refundable $1,500 / $1,600 / $1,700 | IRC §24(h)(2) before OBBBA (OBBBA §70104(a)(2) strikes "$2,000"); Rev. Procs. 2021-45, 2022-38, 2023-34 §3.05 |
| Child Tax Credit 2025, 2026 | $2,200 / $1,700 | unchanged; projected years now indexed (rounded down to $100) instead of frozen | OBBBA §70104; Rev. Proc. 2025-32 §§2.03, 4.05 |
| SALT cap 2022-2024 | $40,000 | $10,000 ($5,000 separate) | IRC §164(b)(6) (TCJA) |
| SALT cap 2025 | $40,000 | $40,000, reduced by 30% of MAGI over $500,000, not below $10,000 | OBBBA §70120 (IRC §164(b)(7)) |
| SALT cap 2026 | $40,000 | $40,400, threshold $505,000 | OBBBA §70120 (101% of 2025) |
| SALT cap 2027-2029 | $40,000 | +1% a year (cap and threshold; unrounded, TODO(verify) against IRS guidance) | OBBBA §70120 |
| SALT cap from 2030 | $40,000 | $10,000, no phase-down | OBBBA §70120 |
| SALT cap scope | per person (a joint return could deduct twice the cap) | per return | IRC §164(b)(6) |
| Senior deduction | static, 2025-2028 | per-year amount ($0 before 2025, $6,000 2025-2026; statutory sunset after 2028 kept) | OBBBA §70103 |
| NIIT thresholds | static | per-year (statutory $200k / $250k / $125k, never indexed) | IRC §1411(b) |
| §63(f) additional standard deduction | absent | recorded per year for Plan 31 (not applied): $1,400/$1,750 (2022), $1,500/$1,850, $1,550/$1,950, $1,600/$2,000, $1,650/$2,050 (2026) | Rev. Procs. above, §3.15(3) / §2.15(3) / §4.14(3) |

Output changes no test pinned (probe: the packaged examples and the broad test scenarios, before and
after, in a scratch worktree):

* **Itemizers after 2029 pay more** (the SALT cap reverts to $10,000): e.g. the `single_renter`
  example's 2036 return deducts $10,000 of SALT instead of $10,391.89 (+$86.22 federal tax); the
  `married_homeowners` test scenario pays up to $4,318 more a year and ends with $286,776 less net
  worth over 45 years. 2026-2029 itemizers deduct slightly more (the cap grows).
* **Households with children after 2026** get the indexed credit ($2,300 in 2028 at 3% inflation
  instead of $2,200 forever).
* **Runs starting before 2026** with capital gains or itemized SALT over $10,000 (2022-2024) now use
  that year's published values; the packaged examples all start in 2026, so they are unaffected
  there. The `retiree_couple` example is unchanged.
* **2026 head-of-household returns** with taxable income between $201,750 and $201,775: $2 more tax.
