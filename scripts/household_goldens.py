# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Compute the household goldens' expected returns from the IRS forms (Plan 29 D3).

This script is deliberately independent of ``life_model`` (it imports nothing from it, and a test
checks that): it works the 2024, 2025 and 2026 Form 1040 line by line, with the Social Security
Benefits Worksheet, the Qualified Dividends and Capital Gain Tax Worksheet, the Tax Table / Tax
Computation Worksheet rule, Schedule A, Schedule 8812, Form 8959 and Form 8960, from the year's
published amounts (each table below cites its source). The inputs are the household's synthetic
*documents* (W-2 wages, 1099 interest, a 1098's mortgage terms, an IRA's December 31 balance...).

For every golden it writes ``expected.json`` (the return lines, W-2 boxes and checks the test
compares) and ``worksheet.md`` (every line's arithmetic, for review) next to the golden's
``spec.yaml``. Run it after changing a golden's inputs::

    python scripts/household_goldens.py            # rewrite every golden
    python scripts/household_goldens.py retiree    # only goldens whose name contains "retiree"

Tax Table: the 1040 instructions require the Tax Table for taxable income under $100,000. Each row
is $50 wide from $3,000 ($25 below), and its tax is the rate schedule applied to the row's midpoint,
rounded to the dollar (checked against every row of the 2024 and 2025 tables). The engine computes
the exact rate schedule, so line 16 is recorded twice: the Tax Table amount a filer enters (compared
with a tolerance of the marginal rate x $25 + $0.50) and the exact schedule amount (compared to the
cent). The 2026 Tax Table is not published yet (no 2026 instructions as of October 2026); 2026
goldens apply the same rule to the 2026 rate schedule (Rev. Proc. 2025-32).
"""

import json
import math
import sys
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

GOLDENS = Path(__file__).resolve().parents[1] / "src" / "life_model" / "tests" / "goldens" / "households"
INF = float("inf")

# --------------------------------------------------------------------------------------------------
# Published amounts (each from the cited primary source; fetched from irs.gov 2026-10-18)
# --------------------------------------------------------------------------------------------------

#: Ordinary rate schedules: upper bounds of the 10/12/22/24/32/35% brackets (37% above).
BRACKETS = {
    # Rev. Proc. 2023-34 §3.01 Tables 1-4
    2024: {
        "single": (11600, 47150, 100525, 191950, 243725, 609350),
        "mfj": (23200, 94300, 201050, 383900, 487450, 731200),
        "hoh": (16550, 63100, 100500, 191950, 243700, 609350),
        "mfs": (11600, 47150, 100525, 191950, 243725, 365600),
    },
    # Rev. Proc. 2024-40 §2.01 Tables 1-4 (OBBBA did not change the 2025 brackets)
    2025: {
        "single": (11925, 48475, 103350, 197300, 250525, 626350),
        "mfj": (23850, 96950, 206700, 394600, 501050, 751600),
        "hoh": (17000, 64850, 103350, 197300, 250500, 626350),
        "mfs": (11925, 48475, 103350, 197300, 250525, 375800),
    },
    # Rev. Proc. 2025-32 §4.01 Tables 1-4
    2026: {
        "single": (12400, 50400, 105700, 201775, 256225, 640600),
        "mfj": (24800, 100800, 211400, 403550, 512450, 768700),
        "hoh": (17700, 67450, 105700, 201750, 256200, 640600),
        "mfs": (12400, 50400, 105700, 201775, 256225, 384350),
    },
}
RATES = (0.10, 0.12, 0.22, 0.24, 0.32, 0.35, 0.37)

#: Standard deduction. 2024: Rev. Proc. 2023-34 §3.15(1); 2025: OBBBA §70102 as stated in Rev. Proc.
#: 2025-32 §3.01; 2026: Rev. Proc. 2025-32 §4.14(1).
STANDARD = {
    2024: {"single": 14600, "mfj": 29200, "hoh": 21900, "mfs": 14600},
    2025: {"single": 15750, "mfj": 31500, "hoh": 23625, "mfs": 15750},
    2026: {"single": 16100, "mfj": 32200, "hoh": 24150, "mfs": 16100},
}
#: §63(f) additional standard deduction per box (married, unmarried). Rev. Procs. 2023-34 §3.15(3),
#: 2024-40 §2.15(3), 2025-32 §4.14(3).
ADDITIONAL_65 = {2024: (1550, 1950), 2025: (1600, 2000), 2026: (1650, 2050)}
#: QDCGT worksheet lines 6 (0% top) and 13 (15% top). Rev. Procs. 2023-34 §3.03, 2024-40 §2.03,
#: 2025-32 §4.03.
CAPITAL_GAINS = {
    2024: {"single": (47025, 518900), "mfj": (94050, 583750), "hoh": (63000, 551350), "mfs": (47025, 291850)},
    2025: {"single": (48350, 533400), "mfj": (96700, 600050), "hoh": (64750, 566700), "mfs": (48350, 300000)},
    2026: {"single": (49450, 545500), "mfj": (98900, 613700), "hoh": (66200, 579600), "mfs": (49450, 306850)},
}
#: Child tax credit per child. 2024: IRC §24(h)(2) before OBBBA; 2025: OBBBA §70104; 2026: Rev. Proc.
#: 2025-32 §4.05. Phase-out from $400,000 (joint) / $200,000 (§24(h)(3)).
CTC = {2024: 2000, 2025: 2200, 2026: 2200}
#: SALT cap (§164(b)(6)/(7)): 2024 $10,000; OBBBA §70120: 2025 $40,000, 2026 $40,400 (phase-down above
#: $500,000 / $505,000 MAGI, not reached here).
SALT_CAP = {2024: 10000, 2025: 40000, 2026: 40400}
#: Social Security wage base (SSA contribution and benefit base).
WAGE_BASE = {2024: 168600, 2025: 176100, 2026: 184500}
#: OBBBA §70103 senior deduction (2025-2028): $6,000 per person 65+, less 6% of MAGI over $75,000 /
#: $150,000 (joint).
SENIOR = {2025: 6000, 2026: 6000}
#: Medicare Part B standard premium, Part D base premium and the second IRMAA tier for 2026 (monthly),
#: and the joint MAGI that starts it: CMS 2026 Medicare Parts B premiums fact sheet (the values the
#: package config carries, stamped with that source).
MEDICARE_2026 = {
    "part_b": 202.90,
    "part_d": 34.50,
    "tier2_part_b": 284.06,
    "tier2_part_d_add": 14.50,
    "tier2_mfj": 218000,
}


# --------------------------------------------------------------------------------------------------
# Arithmetic helpers
# --------------------------------------------------------------------------------------------------


def cents(x: float) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def dollars(x: float) -> float:
    return float(Decimal(str(x)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def schedule_tax(income: float, year: int, status: str) -> float:
    """The rate schedule (Rev. Proc. tables) on ``income``: the exact tax."""
    tax, lower = 0.0, 0.0
    for upper, rate in zip((*BRACKETS[year][status], INF), RATES, strict=True):
        if income <= lower:
            break
        tax += (min(income, upper) - lower) * rate
        lower = upper
    return tax


def marginal_rate(income: float, year: int, status: str) -> float:
    for upper, rate in zip((*BRACKETS[year][status], INF), RATES, strict=True):
        if income <= upper:
            return rate
    return RATES[-1]


def table_tax(income: float, year: int, status: str) -> tuple[float, str]:
    """Line 16 by the 1040 instructions: the Tax Table below $100,000 (row midpoint, rounded to the
    dollar), the Tax Computation Worksheet (the exact schedule) at or above it."""
    if income >= 100000:
        return schedule_tax(income, year, status), "Tax Computation Worksheet (exact schedule)"
    if income <= 0:
        return 0.0, "no taxable income"
    if income < 5:
        low, width = 0.0, 5.0
    elif income < 25:
        low, width = (5.0, 10.0) if income < 15 else (15.0, 10.0)
    elif income < 3000:
        width = 25.0
        low = math.floor(income / width) * width
    else:
        width = 50.0
        low = math.floor(income / width) * width
    middle = low + width / 2
    tax = dollars(schedule_tax(middle, year, status))
    return tax, f"Tax Table row ${low:,.0f}-${low + width:,.0f}: schedule tax on the midpoint ${middle:,.2f}, rounded"


def money(x: float) -> str:
    return f"{'-' if x < 0 else ''}${abs(x):,.2f}"


# --------------------------------------------------------------------------------------------------
# The return
# --------------------------------------------------------------------------------------------------


@dataclass
class W2:
    person: str
    employer: str
    gross: float
    pretax_401k: float = 0.0


@dataclass
class Return:
    """One return's documents (inputs) and the lines worked from them."""

    year: int
    status: str  # single / mfj / hoh / mfs
    filer: str | None = None
    w2: list[W2] = field(default_factory=list)
    interest: float = 0.0
    qualified_dividends: float = 0.0
    long_term_gain: float = 0.0
    ira_distributions: float = 0.0
    social_security: float = 0.0
    student_loan_interest: float = 0.0
    mortgage_interest: float = 0.0
    real_estate_tax: float = 0.0
    charity_cash: float = 0.0
    children_under_17: int = 0
    ages_65_plus: int = 0
    lines: dict[str, float] = field(default_factory=dict)
    schedules: dict[str, dict[str, float]] = field(default_factory=dict)
    work: list[str] = field(default_factory=list)
    exact_tax: float = 0.0
    tax_table_note: str = ""
    #: Largest Tax Table vs exact-schedule difference for this return (rate x $25 + $0.50).
    tax_table_bound: float = 0.01

    def line(self, key: str, value: float, how: str) -> float:
        value = cents(value)
        if key.startswith("S"):
            schedule, line = key[1:].split(":")
            self.schedules.setdefault(schedule, {})[line] = value
            label = f"Schedule {schedule} line {line}"
        else:
            self.lines[key] = value
            label = f"Form 1040 line {key}"
        self.work.append(f"| {label} | {how} | {money(value)} |")
        return value

    def note(self, text: str) -> None:
        self.work.append(f"| | {text} | |")


def work_return(r: Return) -> Return:
    y, status = r.year, r.status
    v2025 = y >= 2025  # 7a / 11a-11b / 12e / 13a-13b numbering
    wages = sum(w.gross - w.pretax_401k for w in r.w2)
    l1a = r.line(
        "1a", wages, " + ".join(f"W-2 box 1 {w.employer} {money(w.gross - w.pretax_401k)}" for w in r.w2) or "no W-2"
    )
    l1z = r.line("1z", l1a, "line 1a")
    l2a = r.line("2a", 0.0, "no tax-exempt interest")
    l2b = r.line("2b", r.interest, "1099-INT box 1 (Schedule B line 4)")
    l3a = r.line("3a", r.qualified_dividends, "1099-DIV box 1b")
    l3b = r.line("3b", r.qualified_dividends, "1099-DIV box 1a (all dividends here are qualified)")
    r.line("4a", r.ira_distributions, "1099-R box 1 (required minimum distributions)")
    l4b = r.line("4b", r.ira_distributions, "1099-R box 2a (no basis: fully taxable)")
    l5b = r.line("5b", 0.0, "no pensions")
    line7 = "7a" if v2025 else "7"
    l7 = r.line(
        line7,
        r.long_term_gain,
        "Schedule D line 16 (long-term gain; no losses or carryovers)" if r.long_term_gain else "none",
    )
    l8 = r.line("8", 0.0, "Schedule 1 line 10: no additional income")
    r.line("6a", r.social_security, "SSA-1099 box 5")
    # Schedule 1 Part II (adjustments)
    student = 0.0 if status == "mfs" else min(r.student_loan_interest, 2500.0)
    if r.student_loan_interest:
        how = (
            "not allowed on a separate return (IRC §221(e)(2))"
            if status == "mfs"
            else f"smaller of 1098-E interest {money(r.student_loan_interest)} and $2,500 (MAGI below the phase-out)"
        )
        r.line("S1:21", student, how)
    s1_26 = r.line("S1:26", student, "Schedule 1 lines 11-25: student loan interest only")
    l10 = r.line("10", s1_26, "Schedule 1 line 26")
    # Social Security Benefits Worksheet (1040 instructions)
    if r.social_security:
        ws1 = r.social_security
        ws2 = ws1 * 0.5
        ws3 = l1z + l2b + l3b + l4b + l5b + l7 + l8
        ws5 = ws2 + ws3 + l2a
        ws7 = max(ws5 - l10, 0.0)
        base, extra = (32000.0, 12000.0) if status == "mfj" else (25000.0, 9000.0)
        ws9 = max(ws7 - base, 0.0)
        ws11 = max(ws9 - extra, 0.0)
        ws12 = min(ws9, extra)
        ws13 = ws12 / 2
        ws14 = min(ws2, ws13)
        ws15 = ws11 * 0.85
        ws16 = ws14 + ws15
        ws17 = ws1 * 0.85
        taxable = min(ws16, ws17)
        r.note(
            f"SS worksheet: 1 {money(ws1)}; 2 = 50% {money(ws2)}; 3 = 1z+2b+3b+4b+5b+{line7}+8 {money(ws3)}; "
            f"5 = 2+3+2a {money(ws5)}; 7 = 5 - 10 {money(ws7)}; 8 {money(base)}; 9 {money(ws9)}; 10 {money(extra)}; "
            f"11 {money(ws11)}; 12 {money(ws12)}; 13 {money(ws13)}; 14 {money(ws14)}; 15 = 85% x 11 {money(ws15)}; "
            f"16 {money(ws16)}; 17 = 85% x 1 {money(ws17)}; 18 = min(16, 17)"
        )
        l6b = r.line("6b", taxable, "Social Security Benefits Worksheet line 18")
    else:
        l6b = r.line("6b", 0.0, "no benefits")
    l9 = r.line("9", l1z + l2b + l3b + l4b + l5b + l6b + l7 + l8, f"1z + 2b + 3b + 4b + 5b + 6b + {line7} + 8")
    agi = r.line("11a" if v2025 else "11", max(l9 - l10, 0.0), "line 9 - line 10")
    if v2025:
        r.line("11b", agi, "line 11a")
    # Deductions
    standard = STANDARD[y][status]
    married_amount, unmarried_amount = ADDITIONAL_65[y]
    extra_65 = r.ages_65_plus * (married_amount if status in ("mfj", "mfs") else unmarried_amount)
    itemized = 0.0
    if r.mortgage_interest or r.real_estate_tax or r.charity_cash:
        salt = min(r.real_estate_tax, SALT_CAP[y] / (2 if status == "mfs" else 1))
        r.note(
            f"Schedule A line 5b real estate tax {money(r.real_estate_tax)}; 5d = 5a (no state income tax) + 5b "
            f"= {money(r.real_estate_tax)} (not compared: the engine records SALT after the cap)"
        )
        sa5e = r.line("SA:5e", salt, f"smaller of 5d and the ${SALT_CAP[y]:,} cap")
        r.line("SA:7", sa5e, "5e + 6")
        sa8a = r.line("SA:8a", r.mortgage_interest, "1098 box 1")
        r.line("SA:8e", sa8a, "8a")
        sa10 = r.line("SA:10", sa8a, "8e (no investment interest)")
        sa11 = r.line("SA:11", r.charity_cash, "cash gifts (well under 60% of AGI)")
        sa14 = r.line("SA:14", sa11, "11 + 12 + 13")
        itemized = r.line("SA:17", sa5e + sa10 + sa14, "7 + 10 + 14")
    std_total = standard + extra_65
    if extra_65:
        r.note(f"standard deduction {money(standard)} + §63(f) {r.ages_65_plus} x {money(extra_65 / r.ages_65_plus)}")
    deduction = max(std_total, itemized)
    which = "Schedule A line 17" if itemized > std_total else f"standard deduction ({status})"
    r.line("12e" if v2025 else "12", deduction, which)
    senior = 0.0
    if y in SENIOR and r.ages_65_plus and status != "mfs":
        threshold = 150000.0 if status == "mfj" else 75000.0
        per_person = max(SENIOR[y] - 0.06 * max(agi - threshold, 0.0), 0.0)
        senior = per_person * r.ages_65_plus
        sched = "1-A"
        line_senior, line_total = ("37", "38") if y == 2025 else ("43", "44")
        r.line(
            f"S{sched}:{line_senior}", senior, f"{r.ages_65_plus} x ($6,000 - 6% x max(MAGI - {money(threshold)}, 0))"
        )
        r.line(f"S{sched}:{line_total}", senior, "no tips, overtime or car-loan interest")
    if y == 2024:
        r.line("13", 0.0, "no qualified business income")
        l14 = r.line("14", deduction, "12 + 13")
    elif y == 2025:
        r.line("13a", 0.0, "no qualified business income")
        r.line("13b", senior, "Schedule 1-A line 38")
        l14 = r.line("14", deduction + senior, "12e + 13a + 13b")
    else:
        r.line("12f", 0.0, "itemizes or no cash gifts (non-itemizer charitable deduction)")
        r.line("13a", senior, "Schedule 1-A line 44")
        r.line("13b", 0.0, "no qualified business income")
        l14 = r.line("14", deduction + senior, "12e + 12f + 13a + 13b")
    l15 = r.line("15", max(agi - l14, 0.0), f"line {'11b' if v2025 else '11'} - line 14")
    # Line 16
    preferential = l3a + max(l7, 0.0)
    if preferential > 0:
        zero_top, fifteen_top = CAPITAL_GAINS[y][status]
        q1, q2, q3 = l15, l3a, max(l7, 0.0)
        q4 = q2 + q3
        q5 = max(q1 - q4, 0.0)
        q6 = zero_top
        q7 = min(q1, q6)
        q8 = min(q5, q7)
        q9 = q7 - q8
        q10 = min(q1, q4)
        q12 = q10 - q9
        q13 = fifteen_top
        q14 = min(q1, q13)
        q15 = q5 + q9
        q16 = max(q14 - q15, 0.0)
        q17 = min(q12, q16)
        q18 = q17 * 0.15
        q19 = q9 + q17
        q20 = q10 - q19
        q21 = q20 * 0.20
        q22, how22 = table_tax(q5, y, status)
        q23 = q18 + q21 + q22
        q24, _ = table_tax(q1, y, status)
        tax = min(q23, q24)
        r.note(
            f"QDCGT worksheet: 1 {money(q1)}; 2 {money(q2)}; 3 {money(q3)}; 4 {money(q4)}; 5 {money(q5)}; "
            f"6 {money(q6)}; 7 {money(q7)}; 8 {money(q8)}; 9 (0%) {money(q9)}; 10 {money(q10)}; 12 {money(q12)}; "
            f"13 {money(q13)}; 14 {money(q14)}; 15 {money(q15)}; 16 {money(q16)}; 17 {money(q17)}; "
            f"18 = 15% {money(q18)}; 19 {money(q19)}; 20 {money(q20)}; 21 = 20% {money(q21)}; "
            f"22 = tax on line 5 {money(q22)} ({how22}); 23 {money(q23)}; 24 = tax on line 1 {money(q24)}; 25 = min"
        )
        exact = schedule_tax(q5, y, status) + q18 + q21
        r.tax_table_note = how22
        bound_income = q5
    else:
        tax, how = table_tax(l15, y, status)
        exact = schedule_tax(l15, y, status)
        r.tax_table_note = how
        bound_income = l15
    r.exact_tax = cents(exact)
    r.note(f"exact rate-schedule tax (what the engine computes): {money(r.exact_tax)}")
    l16 = r.line("16", tax, r.tax_table_note if preferential == 0 else "QDCGT worksheet line 25")
    r.tax_table_bound = round(marginal_rate(bound_income, y, status) * 25 + 0.5, 2) if bound_income < 100000 else 0.01
    l17 = r.line("17", 0.0, "no AMT (Schedule 2 line 3)")
    l18 = r.line("18", l16 + l17, "16 + 17")
    # Schedule 8812: child tax credit (nonrefundable part limited by tax)
    credit = 0.0
    if r.children_under_17:
        limit = 400000.0 if status == "mfj" else 200000.0
        full = CTC[y] * r.children_under_17
        reduction = math.ceil(max(agi - limit, 0.0) / 1000) * 50
        credit = min(max(full - reduction, 0.0), l18)
        r.note(
            f"Schedule 8812: {r.children_under_17} x {money(CTC[y])} = {money(full)}; MAGI under {money(limit)}; limited by tax {money(l18)}"
        )
    l19 = r.line("19", credit, "Schedule 8812 line 14" if credit else "no qualifying children")
    l20 = r.line("20", 0.0, "Schedule 3 line 8: no other credits")
    l21 = r.line("21", l19 + l20, "19 + 20")
    l22 = r.line("22", max(l18 - l21, 0.0), "18 - 21")
    # Schedule 2: Additional Medicare Tax (Form 8959) and NIIT (Form 8960)
    medicare_wages = sum(w.gross for w in r.w2)
    threshold = {"mfj": 250000.0, "mfs": 125000.0}.get(status, 200000.0)
    add_medicare = max(medicare_wages - threshold, 0.0) * 0.009
    nii = r.interest + r.qualified_dividends + max(r.long_term_gain, 0.0)
    niit_threshold = {"mfj": 250000.0, "mfs": 125000.0}.get(status, 200000.0)
    niit = min(nii, max(agi - niit_threshold, 0.0)) * 0.038
    lines_2026 = y == 2026
    if add_medicare:
        r.line(
            "S2:17b" if lines_2026 else "S2:11",
            add_medicare,
            f"Form 8959: 0.9% x (Medicare wages {money(medicare_wages)} - {money(threshold)})",
        )
    if niit:
        r.line(
            "S2:6" if lines_2026 else "S2:12",
            niit,
            f"Form 8960: 3.8% x min(NII {money(nii)}, MAGI - {money(niit_threshold)})",
        )
    s2_21 = r.line("S2:21", add_medicare + niit, "Schedule 2 total other taxes")
    l23 = r.line("23", s2_21, "Schedule 2 line 21")
    total = l22 + l23
    if lines_2026:
        r.line("24a", total, "22 + 23")
        r.line("24c", total, "24a + 24b (no Form 1062)")
    else:
        r.line("24", total, "22 + 23")
    r.line("28", 0.0, "no additional child tax credit (credit fully used)")
    return r


def w2_boxes(w: W2, year: int) -> dict[str, float]:
    ss_wages = min(w.gross, WAGE_BASE[year])
    return {
        "1": cents(w.gross - w.pretax_401k),
        "3": cents(ss_wages),
        "4": cents(ss_wages * 0.062),
        "5": cents(w.gross),
        "6": cents(w.gross * 0.0145 + max(w.gross - 200000, 0.0) * 0.009),
    }


# --------------------------------------------------------------------------------------------------
# Documents of each household (synthetic) — must match each golden's spec.yaml
# --------------------------------------------------------------------------------------------------


def amortized_interest(balance: float, annual_rate: float, payment: float, months: int = 12) -> float:
    """Interest a servicer reports for ``months`` payments: each month's interest on the balance,
    rounded to the cent (a 1098 / 1098-E figure)."""
    total = 0.0
    for _ in range(months):
        interest = cents(balance * annual_rate / 12)
        total += interest
        balance -= payment - interest
    return cents(total)


def standard_payment(principal: float, annual_rate: float, years: int) -> float:
    i = annual_rate / 12
    n = years * 12
    return principal * i * (1 + i) ** n / ((1 + i) ** n - 1)


def rmd(balance: float, age: int) -> float:
    """Pub. 590-B: the prior December 31 balance over the Uniform Lifetime Table period."""
    period = {73: 26.5, 75: 24.6}[age]
    return cents(balance / period)


#: Social Security benefits (SSA-1099 box 5) of the retiree couple. INPUT, not tax law: the yearly
#: benefit the engine's SSA formula pays for the spec's earnings records (that formula is verified
#: against SSA's own worked examples in test_social_security). Each year's spec is a separate
#: household (same ages, so different birth years and benefits).
RETIREE_BENEFITS = {2024: 53478.00, 2025: 54766.80, 2026: 56652.00}


def households(year: int) -> dict[str, dict]:
    """The goldens of ``year``: name -> {returns, w2 (person, employer, boxes, box12), extra}."""
    out = {}

    alex = W2("alex", "Example Analytics", 68000.0, 68000.0 * 0.06)
    loan_payment = standard_payment(45000, 0.068, 10)
    out["single_renter"] = {
        "description": "single renter: W-2 with a 6% 401(k) deferral, 4% savings interest, student loan interest over the $2,500 cap",
        "returns": [
            Return(
                year,
                "single",
                w2=[alex],
                interest=10000 * 0.04,
                student_loan_interest=amortized_interest(40000, 0.068, loan_payment),
            ),
        ],
    }
    john = W2("john", "Example Consulting LLC", 185000.0, 18500.0)
    jane = W2("jane", "Example Analytics", 95000.0, 4750.0)
    out["married_homeowners"] = {
        "description": "married filing jointly: two W-2s over the Additional Medicare threshold, two children, "
        "mortgage interest, property tax, cash gifts (itemizes), savings interest (NIIT)",
        "returns": [
            Return(
                year,
                "mfj",
                w2=[john, jane],
                interest=20000 * 0.02,
                mortgage_interest=amortized_interest(480000, 0.065, 3286.75),
                real_estate_tax=650000 * 0.02,
                charity_cash=6000.0,
                children_under_17=2,
            ),
        ],
        "tolerance_note": "the engine accrues mortgage interest unrounded; the 1098 rounds each month's interest to "
        "the cent, so lines that carry it are compared within $0.10",
        "loose_lines": [
            "schedule A:8a",
            "schedule A:8e",
            "schedule A:10",
            "schedule A:17",
            "1040:12",
            "1040:12e",
            "1040:14",
            "1040:15",
        ],
    }
    riley = W2("riley", "Example County", 72000.0, 3600.0)
    out["head_of_household"] = {
        "description": "head of household: one W-2 with a 5% deferral and one child under 17",
        "returns": [Return(year, "hoh", w2=[riley], children_under_17=1)],
    }
    ira = rmd(1200000, 75) + rmd(800000, 73)
    out["retiree_couple"] = {
        "description": "retirees filing jointly (75 and 73): RMDs from two traditional IRAs, Social Security, savings "
        "interest, both 65+",
        "returns": [
            Return(
                year,
                "mfj",
                interest=50000 * 0.04,
                ira_distributions=ira,
                social_security=RETIREE_BENEFITS[year],
                ages_65_plus=2,
            ),
        ],
        "rmds": {"pat": rmd(1200000, 75), "lee": rmd(800000, 73)},
    }
    # Early retiree: the brokerage sale pays the year's spending and its own tax. Cash on hand: $0
    # checking + $10,000 savings + $400 interest credited before the bills; spending $80,000. The sale
    # x solves x = 80,000 - 10,400 + tax(gain), gain = x x (900,000 - 300,000) / 900,000 (one lot,
    # FIFO); proceeds are rounded up to the cent.
    sale, gain = early_retiree_sale(year)
    out["early_retiree"] = {
        "description": "early retiree (58, single): qualified dividends and a long-term gain straddling the 0%/15% "
        "brackets, savings interest",
        "returns": [Return(year, "single", interest=400.0, qualified_dividends=18000.0, long_term_gain=gain)],
        "sale": sale,
    }
    morgan = W2("morgan", "Example Consulting LLC", 120000.0, 9600.0)
    casey = W2("casey", "Example Analytics", 48000.0, 0.0)
    casey_payment = standard_payment(30000, 0.07, 10)
    out["married_separately"] = {
        "description": "married filing separately: each spouse's own W-2; the student loan interest deduction is not "
        "allowed on a separate return",
        "returns": [
            Return(year, "mfs", filer="morgan", w2=[morgan]),
            Return(
                year,
                "mfs",
                filer="casey",
                w2=[casey],
                interest=7500 * 0.04,
                student_loan_interest=amortized_interest(25000, 0.07, casey_payment),
            ),
        ],
    }
    return out


def early_retiree_sale(year: int) -> tuple[float, float]:
    """Solve proceeds = 69,600 + tax(gain(proceeds)) (fixed point), then round up to the cent."""
    need = 80000.0 - 10400.0
    proceeds = need
    for _ in range(200):
        gain = proceeds * 2 / 3
        r = work_return(Return(year, "single", interest=400.0, qualified_dividends=18000.0, long_term_gain=gain))
        exact_tax = r.exact_tax  # the household pays the exact tax the engine settles
        nxt = need + exact_tax
        if abs(nxt - proceeds) < 1e-7:
            break
        proceeds = nxt
    proceeds = math.ceil(proceeds * 100 - 1e-6) / 100
    return proceeds, proceeds * 2 / 3


# --------------------------------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------------------------------


def write(name: str, year: int, info: dict) -> None:
    directory = GOLDENS / f"{name}_{year}"
    returns = [work_return(r) for r in info["returns"]]
    w2s = [w for r in info["returns"] for w in r.w2]
    tolerances: dict[str, float] = {}
    xfail: dict[str, str] = {}
    exact = {}
    for r in returns:
        prefix = f"{r.filer}/" if r.filer else ""
        exact[f"{prefix}1040:16"] = r.exact_tax
        for line in ("16", "18", "22", "24", "24a", "24c"):
            if line in r.lines:
                tolerances[f"{prefix}1040:{line}"] = r.tax_table_bound
        for key in info.get("loose_lines", []):
            tolerances[f"{prefix}{key}"] = 0.10
        if r.ages_65_plus:
            reason = (
                "Plan 31 task 1: the engine does not apply the IRC §63(f) additional standard deduction for "
                f"age 65+ (${ADDITIONAL_65[year][0]:,} per person on a joint return in {year})"
            )
            for line in ("12", "12e", "14", "15", "16", "18", "22", "24", "24a", "24c"):
                if line in r.lines:
                    xfail[f"{prefix}1040:{line}"] = reason
            xfail[f"{prefix}exact:1040:16"] = reason
    expected = {
        "golden": f"{name}_{year}",
        "year": year,
        "description": info["description"],
        "method": (
            "Worked by scripts/household_goldens.py from the year's Form 1040 and instructions (see worksheet.md); "
            "independent of the library."
        ),
        "actuals": {},
        "exact": exact,
        "tolerance": {"default": 0.01, **tolerances},
        "xfail": xfail,
    }
    actual_returns = []
    for r in returns:
        entry = {"form_1040": r.lines, "schedules": r.schedules}
        if r.filer:
            entry = {"filer": r.filer, **entry}
        actual_returns.append(entry)
    if len(actual_returns) == 1 and "filer" not in actual_returns[0]:
        expected["actuals"] = dict(actual_returns[0])
    else:
        expected["actuals"] = {"returns": actual_returns}
    w2_out = []
    for w in w2s:
        boxes = w2_boxes(w, year)
        box12 = {"D": cents(w.pretax_401k)} if w.pretax_401k else {}
        w2_out.append({"person": w.person, "employer": w.employer, "boxes": boxes, "box12": box12})
    if w2_out:
        expected["actuals"]["w2"] = w2_out
    if "rmds" in info:
        expected["actuals"]["form_1099"] = [
            {
                "form": "1099-R",
                "person": person,
                "account": f"{person}_ira",
                "boxes": {"1": amount, "2a": amount},
                "code": "7",
            }
            for person, amount in info["rmds"].items()
        ]
    if "sale" in info:
        expected["actuals"]["form_1099"] = [
            {
                "form": "1099-B",
                "person": "sam",
                "account": "sam_brokerage",
                "boxes": {"1d": cents(info["sale"])},
                "code": "long",
            }
        ]
    if name == "retiree_couple" and year == 2026:
        # Medicare: the 2024 joint MAGI on file was $230,000 (synthetic), over the $218,000 2026 IRMAA
        # threshold, so both pay the second tier: (Part B $284.06 + Part D base $34.50 + IRMAA $14.50) x 12.
        m = MEDICARE_2026
        premium = cents(2 * 12 * (m["tier2_part_b"] + m["part_d"] + m["tier2_part_d_add"]))
        expected["actuals"]["spending"] = {"medicare_premiums_annual": premium}
        expected["prior_magi"] = {"2024": 230000}
        xfail["spending:medicare_premiums_annual"] = (
            "missing_input (Plan 27): the spec cannot carry the 2024 MAGI the 2026 IRMAA tier is based on; the "
            "engine has no AGI history before its first year and charges the base premium"
        )
    (directory / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    md = [
        f"# {name.replace('_', ' ')} {year}: worked return",
        "",
        (
            f"{info['description'][0].upper()}{info['description'][1:]}. Synthetic household (`spec.yaml`); "
            "computed by `scripts/household_goldens.py` from the forms, independent of the library."
        ),
        "",
    ]
    if info.get("tolerance_note"):
        md += [f"Tolerance: {info['tolerance_note']}.", ""]
    if "sale" in info:
        md += [
            (
                "Brokerage sale (1099-B box 1d): the sale pays $80,000 of spending less $10,400 of cash (savings "
                f"plus its interest) plus the tax it triggers: proceeds {money(info['sale'])}, gain 2/3 of it "
                f"{money(info['sale'] * 2 / 3)} (basis $300,000 of $900,000)."
            ),
            "",
        ]
    if "rmds" in info:
        md += [
            "RMDs (Pub. 590-B): "
            + "; ".join(f"{p} {money(a)}" for p, a in info["rmds"].items())
            + " ($1,200,000 / 24.6 at 75; $800,000 / 26.5 at 73). Social Security (SSA-1099 box 5) is an input: "
            f"{money(RETIREE_BENEFITS[year])}.",
            "",
        ]
    for w in w2s:
        boxes = w2_boxes(w, year)
        md.append(
            f"W-2 {w.employer} ({w.person}): box 1 = {money(w.gross)} - 401(k) {money(w.pretax_401k)} = {money(boxes['1'])}; "
            f"box 3 = min(wages, {money(WAGE_BASE[year])}) = {money(boxes['3'])}; box 4 = 6.2% = {money(boxes['4'])}; "
            f"box 5 = {money(boxes['5'])}; box 6 = 1.45% (+0.9% over $200,000) = {money(boxes['6'])}."
        )
    md.append("")
    for r in returns:
        if r.filer:
            md += [f"## Return of {r.filer} ({r.status})", ""]
        md += ["| Line | How | Amount |", "|---|---|---:|", *r.work, ""]
    if xfail:
        md += ["## Expected failures", ""] + [f"- `{k}`: {v}" for k, v in sorted(xfail.items())] + [""]
    (directory / "worksheet.md").write_text("\n".join(md), encoding="utf-8")


def main(argv: list[str]) -> None:
    pattern = argv[0] if argv else ""
    for year in (2024, 2025, 2026):
        for name, info in households(year).items():
            if pattern in f"{name}_{year}":
                write(name, year, info)
                print(f"wrote {name}_{year}")


if __name__ == "__main__":
    main(sys.argv[1:])
