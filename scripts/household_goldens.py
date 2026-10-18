# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Compute the household goldens' expected returns from the IRS forms (Plan 29 D3).

This script is deliberately independent of ``life_model`` (it imports nothing from it, and a test
checks that): it works the 2024, 2025 and 2026 Form 1040 line by line, with the Social Security
Benefits Worksheet, the Qualified Dividends and Capital Gain Tax Worksheet, the Tax Table / Tax
Computation Worksheet rule, Schedule A, Schedule 8812, Form 8959 and Form 8960, and (Plan 31) the EIC
Table, Forms 2441, 8863, 8880, 8814, 6251 (with Part III), 8801 and 8995, Schedules C and SE, Pub.
560's self-employed SEP worksheet, Pub. 526's charitable limits, and the 2026 OBBBA changes (the
non-itemizer charitable deduction, the 0.5% floor, the 2/37 limit), from the year's published amounts
(each table below cites its source). The inputs are the household's synthetic *documents* (W-2 wages,
1099 interest, a 1098's mortgage terms, an IRA's December 31 balance, a Schedule C profit...).

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

# --- Plan 31: credits, deductions and regimes (fetched from irs.gov / govinfo 2026-10-18) -----------

#: Earned income credit table amounts for 0 / 1 / 2 / 3+ children: earned income amount, maximum credit,
#: phase-out threshold (all but joint), threshold (joint). Rev. Procs. 2023-34 §3.06, 2024-40 §2.06,
#: 2025-32 §4.06. Credit / phase-out percentages: IRC §32(b)(1). Investment income limit: §32(i) (same
#: Rev. Proc. sections).
EITC = {
    2024: {
        "eia": (8260, 12390, 17400, 17400),
        "max": (632, 4213, 6960, 7830),
        "start": (10330, 22720, 22720, 22720),
        "start_mfj": (17250, 29640, 29640, 29640),
        "investment_limit": 11600,
    },
    2025: {
        "eia": (8490, 12730, 17880, 17880),
        "max": (649, 4328, 7152, 8046),
        "start": (10620, 23350, 23350, 23350),
        "start_mfj": (17730, 30470, 30470, 30470),
        "investment_limit": 11950,
    },
    2026: {
        "eia": (8680, 13020, 18290, 18290),
        "max": (664, 4427, 7316, 8231),
        "start": (10860, 23890, 23890, 23890),
        "start_mfj": (18140, 31160, 31160, 31160),
        "investment_limit": 12200,
    },
}
EITC_RATES = (0.0765, 0.34, 0.40, 0.45)
EITC_PHASEOUT = (0.0765, 0.1598, 0.2106, 0.2106)
#: Additional child tax credit: refundable maximum per child (Rev. Procs. 2023-34 §3.05, 2024-40 §2.05,
#: 2025-32 §4.05), 15% of earned income over $2,500 (§24(d)(1)(B), §24(h)(6)); credit for other
#: dependents $500 (§24(h)(4)).
ACTC_MAX = {2024: 1700, 2025: 1700, 2026: 1700}
ODC = 500
#: AMT (Form 6251; IRC §55): exemption (unmarried, mfj, mfs), phase-out start, 28% breakpoint (mfs half)
#: and the phase-out rate. Rev. Procs. 2023-34 §3.11, 2024-40 §2.11, 2025-32 §4.10; the 50% rate from
#: OBBBA §70107 (IRC §55(d)(4)(A)(ii)(IV)).
AMT = {
    2024: {"exemption": (85700, 133300, 66650), "start": (609350, 1218700, 609350), "break": 232600, "rate": 0.25},
    2025: {"exemption": (88100, 137000, 68500), "start": (626350, 1252700, 626350), "break": 239100, "rate": 0.25},
    2026: {"exemption": (90100, 140200, 70100), "start": (500000, 1000000, 500000), "break": 244500, "rate": 0.50},
}
#: §199A threshold and phase-in width (unmarried, mfj). Rev. Procs. 2023-34 §3.27, 2024-40 §2.27,
#: 2025-32 §4.26 (OBBBA §70105: $75,000 / $150,000 widths and the $400 minimum from 2026).
QBI = {
    2024: (191950, 383900, 50000, 100000),
    2025: (197300, 394600, 50000, 100000),
    2026: (201750, 403500, 75000, 150000),
}
#: §1(g) kiddie-tax base (Form 8814 line 13): Rev. Procs. 2023-34 §3.02, 2024-40 §2.02, 2025-32 §4.02.
KIDDIE = {2024: 1300, 2025: 1350, 2026: 1350}
#: §221 student loan interest phase-out start and width (single, mfj): Rev. Procs. 2023-34 §3.30,
#: 2024-40 §2.30, 2025-32 §4.29.
STUDENT_LOAN = {2024: (80000, 165000), 2025: (85000, 170000), 2026: (85000, 175000)}
#: §25B saver's credit AGI ceilings of the 50/20/10% tiers (mfj, hoh, others): Notices 2023-75, 2024-80,
#: 2025-67.
SAVERS = {
    2024: {"mfj": (46000, 50000, 76500), "hoh": (34500, 37500, 57375), "other": (23000, 25000, 38250)},
    2025: {"mfj": (47500, 51000, 79000), "hoh": (35625, 38250, 59250), "other": (23750, 25500, 39500)},
    2026: {"mfj": (48500, 52500, 80500), "hoh": (36375, 39375, 60375), "other": (24250, 26250, 40250)},
}
#: Dependent care: §129 exclusion ($5,000; OBBBA §70404 $7,500 from 2026), §21(c) $3,000 / $6,000.
CARE_EXCLUSION = {2024: 5000, 2025: 5000, 2026: 7500}
#: §401(a)(17) compensation limit and §415(c) limit: Notices 2023-75, 2024-80, 2025-67.
COMPENSATION_LIMIT = {2024: 345000, 2025: 350000, 2026: 360000}
LIMIT_415C = {2024: 69000, 2025: 70000, 2026: 72000}
#: §408(d)(8) qualified charitable distribution limit: Notices 2023-75, 2024-80, 2025-67.
QCD_LIMIT = {2024: 105000, 2025: 108000, 2026: 111000}


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
    #: Dependent-care FSA election (box 10; excluded from boxes 1, 3 and 5).
    fsa: float = 0.0


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
    # Plan 31 documents
    dependents: list = field(default_factory=list)
    filer_ages: tuple = ()
    business_profit: float = 0.0
    sep_rate: float = 0.0
    iso_spread: float = 0.0
    amt_credit_carryforward: float = 0.0
    stock_gift: float = 0.0
    qcd: float = 0.0
    savers_contributions: list = field(default_factory=list)
    lines: dict[str, float] = field(default_factory=dict)
    schedules: dict[str, dict[str, float]] = field(default_factory=dict)
    work: list[str] = field(default_factory=list)
    exact_tax: float = 0.0
    tax_table_note: str = ""
    #: Largest Tax Table vs exact-schedule difference for this return (rate x $25 + $0.50).
    tax_table_bound: float = 0.01
    #: Minimum tax credit this return's AMT carries to next year (Form 8801 Part I).
    amt_credit_generated: float = 0.0
    #: A nonrefundable credit was limited by the tax (so it carries the Tax Table difference).
    tax_limited: bool = False

    def line(self, key: str, value: float, how: str) -> float:
        value = cents(value)
        if key.startswith("S"):
            schedule, line = key[1:].split(":")
            self.schedules.setdefault(schedule, {})[line] = value
            label = f"{'Form' if len(schedule) >= 4 else 'Schedule'} {schedule} line {line}"
        else:
            self.lines[key] = value
            label = f"Form 1040 line {key}"
        self.work.append(f"| {label} | {how} | {money(value)} |")
        return value

    def note(self, text: str) -> None:
        self.work.append(f"| | {text} | |")


def eic_table(income: float, children: int, year: int, mfj: bool) -> float:
    """The EIC Table amount (Form 1040 instructions): $50 rows, each the §32 formula at the row's
    midpoint rounded to the dollar, except that the row containing the earned income amount shows the
    maximum credit and a row starting below the phase-out threshold has no reduction (this rule reproduces
    all 1,329 rows x 8 columns of the published 2024 table)."""
    if income <= 0:
        return 0.0
    n = min(children, 3)
    p = EITC[year]
    low = math.floor(income / 50) * 50
    middle = low + 25
    phase_in = p["max"][n] if low + 50 > p["eia"][n] else EITC_RATES[n] * middle
    start = (p["start_mfj"] if mfj else p["start"])[n]
    reduction = 0.0 if low < start else EITC_PHASEOUT[n] * (middle - start)
    return max(0.0, dollars(phase_in - reduction))


def amt_rate_tax(amount: float, breakpoint: float) -> float:
    """Form 6251 line 7: 26% to the breakpoint, 28% above less 2% of the breakpoint."""
    amount = max(0.0, amount)
    return amount * 0.26 if amount <= breakpoint else amount * 0.28 - breakpoint * 0.02


@dataclass
class Dependent:
    """A dependent child on the return (age at year end)."""

    age: int
    care_expenses: float = 0.0
    student: bool = False
    #: Qualified education expenses paid without tax-free 529 money (Form 8863 line 27 before the cap).
    education_expenses: float = 0.0
    interest: float = 0.0
    dividends: float = 0.0


def work_return(r: "Return") -> "Return":
    y, status = r.year, r.status
    mfj = status == "mfj"
    v2025 = y >= 2025  # 7a / 11a-11b / 12e / 13a-13b numbering
    deps = r.dependents
    ctc_children = r.children_under_17 + sum(1 for d in deps if d.age < 17)
    other_dependents = sum(1 for d in deps if d.age >= 17 and (d.age < 19 or (d.student and d.age < 24)))
    eitc_children = r.children_under_17 + sum(1 for d in deps if d.age < 19 or (d.student and d.age < 24))

    # Form 8814 (parents' election) for each child with interest and dividends only, under 10 x base.
    base = KIDDIE[y]
    kiddie_tax = 0.0
    included_qd = included_other = 0.0
    for d in deps:
        gross = d.interest + d.dividends
        young = d.age < 19 or (d.student and d.age < 24)
        if gross <= 0 or gross >= 10 * base or not young:
            continue
        line6 = max(gross - 2 * base, 0.0)
        qd = line6 * d.dividends / gross if gross else 0.0
        tax_8814 = min(0.10 * max(gross - base, 0.0), 0.10 * base)
        r.note(
            f"Form 8814: line 4 {money(gross)}; 5 = 2 x {money(base)}; 6 = {money(line6)}; 9 (qualified dividends "
            f"share {money(d.dividends)} / {money(gross)}) {money(qd)}; 12 = {money(line6 - qd)} (Schedule 1 line 8z); "
            f"15 = 10% x min(line 4 - {money(base)}, {money(base)}) = {money(tax_8814)} (Form 1040 line 16)"
        )
        r.line("S8814:15", tax_8814, "10% of the child's income over the base, at most 10% of the base")
        kiddie_tax += tax_8814
        included_qd += qd
        included_other += line6 - qd

    # Form 2441 Part III: dependent care benefits (W-2 box 10).
    benefits = sum(w.fsa for w in r.w2)
    care_expenses = sum(d.care_expenses for d in deps if d.age < 13)
    care_persons = sum(1 for d in deps if d.age < 13 and d.care_expenses > 0)
    wages_by_person: dict[str, float] = {}
    for w in r.w2:
        wages_by_person[w.person] = wages_by_person.get(w.person, 0.0) + w.gross - w.pretax_401k - w.fsa
    earned_box1 = list(wages_by_person.values()) or [0.0]
    excluded = taxable_benefits = 0.0
    if benefits:
        limit = CARE_EXCLUSION[y] / (2 if status == "mfs" else 1)
        earned_for_limit = earned_box1 if mfj else earned_box1[:1]
        excluded = min(benefits, care_expenses, limit, *earned_for_limit)
        taxable_benefits = benefits - excluded
        r.note(
            f"Form 2441 Part III: 12 benefits {money(benefits)}; 16 expenses {money(care_expenses)}; 21 limit "
            f"{money(limit)}; 25 excluded = smallest of benefits, expenses, earned incomes, limit = {money(excluded)}"
        )
        r.line("S2441:26", taxable_benefits, "line 23 - line 25 (to Form 1040 line 1e)")

    wages = sum(w.gross - w.pretax_401k - w.fsa for w in r.w2)
    l1a = r.line(
        "1a",
        wages,
        " + ".join(f"W-2 box 1 {w.employer} {money(w.gross - w.pretax_401k - w.fsa)}" for w in r.w2) or "no W-2",
    )
    l1e = 0.0
    if benefits:
        l1e = r.line("1e", taxable_benefits, "Form 2441 line 26")
    l1z = r.line("1z", l1a + l1e, "line 1a" if not benefits else "1a + 1e")
    l2a = r.line("2a", 0.0, "no tax-exempt interest")
    l2b = r.line("2b", r.interest, "1099-INT box 1 (Schedule B line 4)")
    qd = r.qualified_dividends + included_qd
    l3a = r.line("3a", qd, "1099-DIV box 1b" + (" + Form 8814 line 9" if included_qd else ""))
    l3b = r.line(
        "3b", qd, "1099-DIV box 1a (all dividends here are qualified)" + (" + Form 8814 line 9" if included_qd else "")
    )
    if r.qcd:
        r.line("4a", r.ira_distributions + r.qcd, "1099-R box 1 (RMD, including the qualified charitable distribution)")
        l4b = r.line("4b", r.ira_distributions, "box 1 less the qualified charitable distribution (QCD)")
    else:
        r.line("4a", r.ira_distributions, "1099-R box 1 (required minimum distributions)")
        l4b = r.line("4b", r.ira_distributions, "1099-R box 2a (no basis: fully taxable)")
    l5b = r.line("5b", 0.0, "no pensions")
    line7 = "7a" if v2025 else "7"
    l7 = r.line(
        line7,
        r.long_term_gain,
        "Schedule D line 16 (long-term gain; no losses or carryovers)" if r.long_term_gain else "none",
    )

    # Schedule SE and Schedule 1 Part I.
    se_tax = se_half = se_net = 0.0
    if r.business_profit:
        se_net = r.business_profit * 0.9235
        w2_ss = sum(min(w.gross - w.fsa, WAGE_BASE[y]) for w in r.w2)
        ss_room = max(WAGE_BASE[y] - w2_ss, 0.0)
        r.line("SC:31", r.business_profit, "net profit (gross receipts less expenses)")
        r.line("SSE:2", r.business_profit, "Schedule C line 31")
        r.line("SSE:3", r.business_profit, "line 2")
        se_net = r.line("SSE:4a", se_net, "line 3 x 92.35%")
        r.line("SSE:4c", se_net, "line 4a")
        r.line("SSE:6", se_net, "line 4c")
        l10 = cents(min(se_net, ss_room) * 0.124)
        l11 = cents(se_net * 0.029)
        r.note(
            f"Schedule SE: 7 = {money(WAGE_BASE[y])}; 8d W-2 SS wages {money(w2_ss)}; 10 = 12.4% x min(6, 9) = {money(l10)}; 11 = 2.9% x 6 = {money(l11)}"
        )
        se_tax = r.line("SSE:12", l10 + l11, "10 + 11")
        se_half = r.line("SSE:13", se_tax * 0.5, "50% of line 12")
        r.line("S1:3", r.business_profit, "Schedule C line 31")
    if included_other:
        r.line("S1:8z", included_other, "Form 8814 line 12")
    s1_10 = r.business_profit + included_other
    if r.business_profit or included_other:
        if included_other:
            r.line("S1:9", included_other, "line 8z")
        r.line("S1:10", s1_10, "lines 1-7 and 9")
        l8 = r.line("8", s1_10, "Schedule 1 line 10")
    else:
        l8 = r.line("8", 0.0, "Schedule 1 line 10: no additional income")
    r.line("6a", r.social_security, "SSA-1099 box 5")

    # Schedule 1 Part II (adjustments). SEP: Pub. 560 Deduction Worksheet for Self-Employed.
    sep = 0.0
    if r.sep_rate:
        rate = r.sep_rate / 100
        reduced = round(rate / (1 + rate), 6)
        step3 = r.business_profit - se_half
        step7 = min(step3 * reduced, COMPENSATION_LIMIT[y] * rate)
        sep = min(step7, LIMIT_415C[y])
        r.note(
            f"Pub. 560 worksheet: 1 {money(r.business_profit)}; 2 {money(se_half)}; 3 {money(step3)}; 4 rate "
            f"{reduced:.6f} (plan rate {r.sep_rate:g}%); 5 = {money(step3 * reduced)}; 6 = {money(COMPENSATION_LIMIT[y])} x "
            f"{rate:g}; 8 = {money(LIMIT_415C[y])}; 21 = smallest"
        )
        sep = r.line("S1:16", sep, "SEP deduction (Pub. 560 worksheet step 21)")
    if se_half:
        r.line("S1:15", se_half, "Schedule SE line 13")
    pre_sli = l1z + l2b + l3b + l4b + l5b + l7 + l8  # before Social Security (none with a student loan here)
    student = 0.0
    if r.student_loan_interest:
        if status == "mfs":
            how = "not allowed on a separate return (IRC §221(e)(2))"
        else:
            start = STUDENT_LOAN[y][1 if mfj else 0]
            width = 30000 if mfj else 15000
            capped = min(r.student_loan_interest, 2500.0)
            magi = pre_sli - se_half - sep
            if magi <= start:
                student = capped
                how = (
                    f"smaller of 1098-E interest {money(r.student_loan_interest)} and $2,500 (MAGI below the phase-out)"
                )
            else:
                fraction = max(0.0, min(1.0, (magi - start) / width))
                fraction = float(Decimal(str(fraction)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
                student = capped - capped * fraction
                how = (
                    f"Student Loan Interest Deduction Worksheet: {money(capped)} less {money(capped)} x "
                    f"({money(magi)} - {money(start)}) / {money(width)} = {fraction:.3f}"
                )
        r.line("S1:21", student, how)
    s1_26 = r.line(
        "S1:26",
        student + se_half + sep,
        "Schedule 1 lines 11-25" + ("" if (se_half or sep) else ": student loan interest only"),
    )
    l10 = r.line("10", s1_26, "Schedule 1 line 26")
    # Social Security Benefits Worksheet (1040 instructions)
    if r.social_security:
        ws1 = r.social_security
        ws2 = ws1 * 0.5
        ws3 = l1z + l2b + l3b + l4b + l5b + l7 + l8
        ws5 = ws2 + ws3 + l2a
        ws7 = max(ws5 - l10, 0.0)
        base_ss, extra = (32000.0, 12000.0) if mfj else (25000.0, 9000.0)
        ws9 = max(ws7 - base_ss, 0.0)
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
            f"5 = 2+3+2a {money(ws5)}; 7 = 5 - 10 {money(ws7)}; 8 {money(base_ss)}; 9 {money(ws9)}; 10 {money(extra)}; "
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
    std_total = standard + extra_65
    itemized = salt = 0.0
    limitation = 0.0
    itemizes = False
    non_itemizer = 0.0
    senior = 0.0
    if y in SENIOR and r.ages_65_plus and status != "mfs":
        threshold = 150000.0 if mfj else 75000.0
        per_person = max(SENIOR[y] - 0.06 * max(agi - threshold, 0.0), 0.0)
        senior = per_person * r.ages_65_plus
    if r.mortgage_interest or r.real_estate_tax or r.charity_cash or r.stock_gift:
        salt = min(r.real_estate_tax, SALT_CAP[y] / (2 if status == "mfs" else 1))
        cash = min(r.charity_cash, 0.6 * agi)
        prop = min(r.stock_gift, 0.3 * agi, max(0.5 * agi - r.charity_cash, 0.0))
        floor_prop = floor_cash = 0.0
        if y >= 2026:
            floor = 0.005 * agi
            floor_prop = min(prop, floor)
            floor_cash = min(cash, floor - floor_prop)
        if r.real_estate_tax:
            r.note(
                f"Schedule A line 5b real estate tax {money(r.real_estate_tax)}; 5d = 5a (no state income tax) + 5b "
                f"= {money(r.real_estate_tax)} (not compared: the engine records SALT after the cap)"
            )
        sa5e = r.line("SA:5e", salt, f"smaller of 5d and the ${SALT_CAP[y]:,} cap")
        r.line("SA:7", sa5e, "5e + 6")
        sa8a = r.line("SA:8a", r.mortgage_interest, "1098 box 1")
        r.line("SA:8e", sa8a, "8a")
        sa10 = r.line("SA:10", sa8a, "8e (no investment interest)")
        if y >= 2026 and (floor_prop or floor_cash):
            r.note(
                f"0.5% floor (IRC §170(b)(1)(I), OBBBA): 0.5% x AGI {money(agi)} = {money(0.005 * agi)}, taken from "
                f"property first ({money(floor_prop)}) then cash ({money(floor_cash)})"
            )
        sa11 = r.line(
            "SA:11",
            cash - floor_cash,
            "cash gifts (within 60% of AGI)" + (" less the 0.5% floor" if floor_cash else ""),
        )
        sa12 = 0.0
        if r.stock_gift:
            sa12 = r.line(
                "SA:12",
                prop - floor_prop,
                f"appreciated long-term shares at FMV {money(r.stock_gift)}, limited to 30% of AGI {money(0.3 * agi)}"
                + " and 50% of AGI less cash gifts"
                + (" less the 0.5% floor" if floor_prop else ""),
            )
        sa14 = r.line("SA:14", sa11 + sa12, "11 + 12 + 13")
        itemized = sa5e + sa10 + sa14
    if y >= 2026 and r.charity_cash:
        non_itemizer = min(r.charity_cash, 2000.0 if mfj else 1000.0)
    # QBI (Form 8995) is figured without §68; §68 uses taxable income before it plus the itemized deductions.
    tentative_itemize = itemized > std_total + non_itemizer
    qbi_amount = r.business_profit - se_half - sep
    qbi_deduction = 0.0

    def qbi_for(itemize_now: bool) -> float:
        before = agi - (itemized if itemize_now else std_total + non_itemizer) - senior
        return max(before, 0.0)

    if r.business_profit:
        threshold_qbi = QBI[y][1 if mfj else 0]
        ti_before = qbi_for(tentative_itemize)
        assert ti_before <= threshold_qbi, "the goldens use Form 8995 (below the threshold)"
        component = qbi_amount * 0.20
        net_gain = qd + max(l7, 0.0)
        income_limit = max(ti_before - net_gain, 0.0) * 0.20
        qbi_deduction = min(component, income_limit)
        if y >= 2026 and qbi_amount >= 1000:
            qbi_deduction = max(qbi_deduction, 400.0)
    if itemized:
        if y >= 2026:
            top = BRACKETS[y][status][5]
            income_before = agi - senior - qbi_deduction
            limitation = 2 / 37 * min(itemized, max(income_before - top, 0.0))
            if limitation:
                r.note(
                    f"IRC §68 (OBBBA): 2/37 x min(itemized {money(itemized)}, taxable income before §68 plus itemized "
                    f"{money(income_before)} - 37% bracket start {money(top)}) = {money(limitation)}"
                )
        itemized = r.line(
            "SA:17", itemized - limitation, "5e/7 + 10 + 14" + (" less the §68 reduction" if limitation else "")
        )
    itemizes = itemized > std_total + non_itemizer
    if extra_65:
        r.note(f"standard deduction {money(standard)} + §63(f) {r.ages_65_plus} x {money(extra_65 / r.ages_65_plus)}")
    deduction = itemized if itemizes else std_total
    which = "Schedule A line 17" if itemizes else f"standard deduction ({status})"
    r.line("12e" if v2025 else "12", deduction, which)
    if r.business_profit:
        ti_before = qbi_for(itemizes)
        net_gain = qd + max(l7, 0.0)
        r.line("S8995:1", qbi_amount, "net profit - Schedule 1 lines 15 and 16 (attributable to the business)")
        r.note(
            f"Form 8995: 5 = 20% x {money(qbi_amount)} = {money(qbi_amount * 0.2)}; 11 taxable income before QBI "
            f"{money(ti_before)}; 12 net capital gain {money(net_gain)}; 14 = 20% x (11 - 12) "
            f"{money(max(ti_before - net_gain, 0.0) * 0.2)}"
        )
        qbi_deduction = r.line("S8995:15", qbi_deduction, "smaller of line 5 and line 14")
    if senior:
        threshold = 150000.0 if mfj else 75000.0
        sched = "1-A"
        line_senior, line_total = ("37", "38") if y == 2025 else ("43", "44")
        r.line(
            f"S{sched}:{line_senior}", senior, f"{r.ages_65_plus} x ($6,000 - 6% x max(MAGI - {money(threshold)}, 0))"
        )
        r.line(f"S{sched}:{line_total}", senior, "no tips, overtime or car-loan interest")
    if y == 2024:
        r.line("13", qbi_deduction, "Form 8995 line 15" if qbi_deduction else "no qualified business income")
        l14 = r.line("14", deduction + qbi_deduction, "12 + 13")
    elif y == 2025:
        r.line("13a", qbi_deduction, "Form 8995 line 15" if qbi_deduction else "no qualified business income")
        r.line("13b", senior, "Schedule 1-A line 38")
        l14 = r.line("14", deduction + qbi_deduction + senior, "12e + 13a + 13b")
    else:
        nonitem = 0.0 if itemizes else non_itemizer
        r.line(
            "12f",
            nonitem,
            "cash gifts to public charities, up to $1,000 ($2,000 joint), for non-itemizers (IRC §170(p))"
            if nonitem
            else "itemizes or no cash gifts (non-itemizer charitable deduction)",
        )
        r.line("13a", senior, "Schedule 1-A line 44")
        r.line("13b", qbi_deduction, "Form 8995 line 15" if qbi_deduction else "no qualified business income")
        l14 = r.line("14", deduction + nonitem + senior + qbi_deduction, "12e + 12f + 13a + 13b")
    l15 = r.line("15", max(agi - l14, 0.0), f"line {'11b' if v2025 else '11'} - line 14")
    # Line 16
    preferential = l3a + max(l7, 0.0)
    q5 = l15
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
    r.exact_tax = cents(exact + kiddie_tax)
    r.note(f"exact rate-schedule tax (what the engine computes): {money(r.exact_tax)}")
    how16 = r.tax_table_note if preferential == 0 else "QDCGT worksheet line 25"
    if kiddie_tax:
        how16 += f" + Form 8814 line 15 {money(kiddie_tax)}"
    l16 = r.line("16", tax + kiddie_tax, how16)
    r.tax_table_bound = round(marginal_rate(bound_income, y, status) * 25 + 0.5, 2) if bound_income < 100000 else 0.01
    regular_tax = l16  # Form 6251 line 10 and the credit limits read the tax as entered

    # Form 6251 (AMT) with Part III, and Form 8801 Part I for the credit it creates.
    a = AMT[y]
    k = 1 if mfj else 2 if status == "mfs" else 0
    breakpoint = a["break"] / (2 if status == "mfs" else 1)

    def tentative_minimum_tax(include_iso: bool) -> tuple[float, float, float]:
        line1 = (agi - l14) + (senior if y >= 2025 else 0.0)
        line2a = salt if itemizes else std_total
        amti = line1 + line2a - (limitation if itemizes else 0.0) + (r.iso_spread if include_iso else 0.0)
        exemption = max(a["exemption"][k] - a["rate"] * max(amti - a["start"][k], 0.0), 0.0)
        line6 = max(amti - exemption, 0.0)
        if preferential > 0 and line6 > 0:
            zero_top, fifteen_top = CAPITAL_GAINS[y][status]
            line13 = l3a + max(l7, 0.0)
            line16 = min(line6, line13)
            line17 = line6 - line16
            line18 = amt_rate_tax(line17, breakpoint)
            line20 = max(q5, 0.0)
            line21 = max(zero_top - line20, 0.0)
            line22 = min(line6, line13)
            line23 = min(line21, line22)
            line24 = line22 - line23
            line29 = max(fifteen_top - (line21 + line20), 0.0)
            line30 = min(line24, line29)
            line32 = line23 + line30
            line34 = (line22 - line32) * 0.20 if abs(line32 - line6) > 1e-9 else 0.0
            tmt = min(line18 + line30 * 0.15 + line34, amt_rate_tax(line6, breakpoint))
        else:
            tmt = amt_rate_tax(line6, breakpoint)
        return amti, exemption, tmt

    amti, exemption, tmt = tentative_minimum_tax(True)
    amt = max(tmt - regular_tax, 0.0)
    amt_generated = 0.0
    if amt > 0 or r.iso_spread:
        r.note(
            f"Form 6251: 1 = taxable income {money(agi - l14)}"
            + (f" + senior {money(senior)}" if y >= 2025 and senior else "")
            + f"; 2a = {'SALT' if itemizes else 'standard deduction'} {money(salt if itemizes else std_total)}; 2i ISO "
            f"{money(r.iso_spread)}; 4 AMTI {money(amti)}; 5 exemption {money(exemption)}; 6 {money(max(amti - exemption, 0))}; "
            f"7 = 26%/28% (breakpoint {money(breakpoint)}) -> 9 tentative minimum tax {money(tmt)}; 10 regular tax "
            f"{money(regular_tax)}"
        )
        r.line("S6251:4", amti, "alternative minimum taxable income")
        r.line("S6251:9", tmt, "tentative minimum tax")
        r.line("S6251:11", amt, "line 9 - line 10")
        if r.iso_spread and amt > 0:
            _, _, tmt_excl = tentative_minimum_tax(False)
            amt_generated = max(amt - max(tmt_excl - regular_tax, 0.0), 0.0)
            r.note(
                f"Form 8801 Part I (next year's credit): AMT on exclusion items only: tentative minimum tax "
                f"{money(tmt_excl)} - regular tax = {money(max(tmt_excl - regular_tax, 0.0))}; credit carried forward "
                f"= {money(amt)} - that = {money(amt_generated)}"
            )
    r.amt_credit_generated = amt_generated
    l17 = r.line("17", amt, "Form 6251 line 11 (Schedule 2 line 3)" if amt else "no AMT (Schedule 2 line 3)")
    if amt:
        r.line("S2:2", amt, "Form 6251 line 11")
        r.line("S2:3", amt, "1z + 2")
    l18 = r.line("18", l16 + l17, "16 + 17")
    tax18 = l18

    def limited(tentative: float) -> float:
        allowed = max(tax18 - used, 0.0)
        if tentative > allowed:
            r.tax_limited = True
        return min(tentative, allowed)

    # Nonrefundable credits, Form 1040 order (each limited to the tax the earlier ones left).
    se_earned = r.business_profit - se_half if r.business_profit else 0.0
    earned_by_person = dict(wages_by_person)
    if r.business_profit:
        earned_by_person[r.filer or "self"] = earned_by_person.get(r.filer or "self", 0.0) + se_earned
    earned = list(earned_by_person.values()) or [0.0]
    used = 0.0
    care_credit = 0.0
    if care_persons and status != "mfs":
        limit = (3000.0 if care_persons == 1 else 6000.0) - excluded
        if limit > 0:
            line31 = min(limit, care_expenses - excluded)
            earned_care = earned if mfj else earned[:1]
            line6 = max(min(line31, *earned_care), 0.0)
            if y >= 2026:
                rate = max(35, 50 - math.ceil(max(agi - 15000, 0.0) / 2000))
                start2, step2 = (150000.0, 4000.0) if mfj else (75000.0, 2000.0)
                rate = max(20, rate - math.ceil(max(agi - start2, 0.0) / step2))
            else:
                rate = max(20, 35 - math.ceil(max(agi - 15000, 0.0) / 2000))
            care_credit = limited(line6 * rate / 100)
            r.note(
                f"Form 2441: 3 = min($3,000/$6,000 - excluded benefits {money(excluded)}, expenses not covered "
                f"{money(care_expenses - excluded)}) = {money(line31)}; 6 = smallest of 3 and earned incomes = {money(line6)}; "
                f"8 = {rate / 100:.2f} (AGI {money(agi)}); 9 = {money(line6 * rate / 100)}; 11 = limited by tax"
            )
            care_credit = r.line("S2441:11", care_credit, "line 9 limited by line 10")
            r.line("S3:2", care_credit, "Form 2441 line 11")
    used += care_credit
    edu_nonref = edu_ref = 0.0
    students = [d for d in deps if d.student and d.education_expenses > 0]
    if students and status != "mfs":
        aotc = sum(
            min(d.education_expenses, 2000.0) + 0.25 * min(max(d.education_expenses - 2000.0, 0.0), 2000.0)
            for d in students
        )
        top, width = (180000.0, 20000.0) if mfj else (90000.0, 10000.0)
        fraction = min(max((top - agi) / width, 0.0), 1.0)
        fraction = (
            float(Decimal(str(fraction)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)) if fraction < 1 else 1.0
        )
        aotc_phased = aotc * fraction
        edu_ref = aotc_phased * 0.40
        edu_nonref = limited(aotc_phased - edu_ref)
        r.note(
            f"Form 8863: AOTC per student 100% of $2,000 + 25% of the next $2,000 = {money(aotc)}; MAGI fraction "
            f"{fraction:g}; 7 = {money(aotc_phased)}; 8 = 40% refundable {money(edu_ref)}; 9 = {money(aotc_phased - edu_ref)}"
        )
        edu_ref = r.line("S8863:8", edu_ref, "40% of line 7")
        edu_nonref = r.line("S8863:19", edu_nonref, "line 9 limited by the Credit Limit Worksheet")
        r.line("S3:3", edu_nonref, "Form 8863 line 19")
    used += edu_nonref
    savers = 0.0
    if y <= 2026 and r.savers_contributions:
        group = "mfj" if mfj else "hoh" if status == "hoh" else "other"
        ceilings = SAVERS[y][group]
        rate = next((rt for c, rt in zip(ceilings, (0.5, 0.2, 0.1)) if agi <= c), 0.0)
        eligible = sum(min(c, 2000.0) for c in r.savers_contributions)
        if rate:
            savers = limited(eligible * rate)
            r.note(
                f"Form 8880: 6 = contributions up to $2,000 each ({', '.join(money(c) for c in r.savers_contributions)}); "
                f"7 = {money(eligible)}; 9 = {rate} (AGI {money(agi)} vs {ceilings}); 10 = {money(eligible * rate)}; "
                "12 = limited by tax"
            )
            savers = r.line("S8880:12", savers, "line 10 limited by line 11")
            r.line("S3:4", savers, "Form 8880 line 12")
    used += savers
    # Schedule 8812 (child tax credit, credit for other dependents; Credit Limit Worksheet A)
    credit = 0.0
    line12 = 0.0
    if ctc_children or other_dependents:
        limit_ctc = 400000.0 if mfj else 200000.0
        full = CTC[y] * ctc_children + ODC * other_dependents
        reduction = math.ceil(max(agi - limit_ctc, 0.0) / 1000) * 50
        line12 = max(full - reduction, 0.0)
        credit = limited(line12)
        r.note(
            f"Schedule 8812: {ctc_children} x {money(CTC[y])}"
            + (f" + {other_dependents} x $500 (other dependents)" if other_dependents else "")
            + f" = {money(full)}; MAGI under {money(limit_ctc)}; Credit Limit Worksheet A: line 18 less Schedule 3 lines 1-4 "
            f"= {money(max(tax18 - used, 0.0))}"
        )
    l19 = r.line("19", credit, "Schedule 8812 line 14" if credit else "no qualifying children")
    if credit:
        r.line("S8812:14", credit, "smaller of line 12 and Credit Limit Worksheet A")
    used_19 = credit
    # Form 8801: prior-year minimum tax credit
    mtc = 0.0
    if r.amt_credit_carryforward:
        regular_line = regular_tax - used_19 - used
        mtc = max(min(r.amt_credit_carryforward, regular_line - tmt), 0.0)
        r.note(
            f"Form 8801 Part II: 21 carryforward {money(r.amt_credit_carryforward)}; 22 regular tax less credits "
            f"{money(regular_line)}; 23 tentative minimum tax {money(tmt)} (Form 6251 line 9); 25 = smaller of 21 and 22 - 23"
        )
        mtc = r.line("S3:6b", mtc, "Form 8801 line 25")
        r.line("S3:7", mtc, "line 6b")
    nonref_3 = care_credit + edu_nonref + savers + mtc
    if nonref_3:
        s3_8 = r.line("S3:8", nonref_3, "lines 1-4 and 7")
        l20 = r.line("20", s3_8, "Schedule 3 line 8")
    else:
        l20 = r.line("20", 0.0, "Schedule 3 line 8: no other credits")
    l21 = r.line("21", l19 + l20, "19 + 20")
    l22 = r.line("22", max(l18 - l21, 0.0), "18 - 21")
    # Schedule 2: self-employment tax, Additional Medicare Tax (Form 8959), NIIT (Form 8960)
    medicare_wages = sum(w.gross - w.fsa for w in r.w2)
    threshold = {"mfj": 250000.0, "mfs": 125000.0}.get(status, 200000.0)
    add_wages = max(medicare_wages - threshold, 0.0) * 0.009
    add_se = max(se_net - max(threshold - medicare_wages, 0.0), 0.0) * 0.009 if se_net else 0.0
    add_medicare = add_wages + add_se
    nii = r.interest + qd + max(r.long_term_gain, 0.0)
    niit_threshold = {"mfj": 250000.0, "mfs": 125000.0}.get(status, 200000.0)
    niit = min(nii, max(agi - niit_threshold, 0.0)) * 0.038
    lines_2026 = y == 2026
    if se_tax:
        r.line("S2:4", se_tax, "Schedule SE line 12")
    if add_medicare:
        if lines_2026 and add_se:
            r.line("S2:11", add_se, "Form 8959 Part II (self-employment income)")
        if lines_2026:
            if add_wages:
                r.line(
                    "S2:17b",
                    add_wages,
                    f"Form 8959: 0.9% x (Medicare wages {money(medicare_wages)} - {money(threshold)})",
                )
        else:
            r.line(
                "S2:11",
                add_medicare,
                f"Form 8959: 0.9% x (Medicare wages {money(medicare_wages)} - {money(threshold)})",
            )
    if niit:
        r.line(
            "S2:6" if lines_2026 else "S2:12",
            niit,
            f"Form 8960: 3.8% x min(NII {money(nii)}, MAGI - {money(niit_threshold)})",
        )
    s2_21 = r.line("S2:21", add_medicare + niit + se_tax, "Schedule 2 total other taxes")
    l23 = r.line("23", s2_21, "Schedule 2 line 21")
    total = l22 + l23
    if lines_2026:
        r.line("24a", total, "22 + 23")
        r.line("24c", total, "24a + 24b (no Form 1062)")
    else:
        r.line("24", total, "22 + 23")

    # Refundable credits: earned income credit (EIC Worksheet A), additional child tax credit, AOTC.
    earned_total = sum(earned)
    eitc = 0.0
    if status != "mfs" and earned_total > 0 and nii <= EITC[y]["investment_limit"]:
        ages_ok = eitc_children > 0 or any(25 <= age <= 64 for age in r.filer_ages)
        if ages_ok:
            eitc = eic_table(earned_total, eitc_children, y, mfj)
            n = min(eitc_children, 3)
            start = (EITC[y]["start_mfj"] if mfj else EITC[y]["start"])[n]
            how = f"EIC Table, {eitc_children} children, earned income {money(earned_total)}"
            if agi != earned_total and agi >= start:
                eitc = min(eitc, eic_table(agi, eitc_children, y, mfj))
                how += f"; smaller of that and the amount for AGI {money(agi)}"
            if eitc:
                r.line("27a" if v2025 else "27", eitc, how)
    actc = 0.0
    if ctc_children:
        line16a = line12 - credit
        line16b = ACTC_MAX[y] * ctc_children
        line17 = min(line16a, line16b)
        line20 = max(earned_total - 2500.0, 0.0) * 0.15
        actc = min(line17, line20)
        how = f"Schedule 8812 Part II-A: 16a {money(line16a)}; 16b {money(line16b)}; 17 {money(line17)}; 20 = 15% x (earned {money(earned_total)} - $2,500) {money(line20)}"
        if ctc_children >= 3 and line20 < line17:
            fica_withheld = sum(min(w.gross - w.fsa, WAGE_BASE[y]) * 0.062 + (w.gross - w.fsa) * 0.0145 for w in r.w2)
            line25 = max(fica_withheld + se_half - eitc, 0.0)
            actc = min(line17, max(line20, line25))
            how += (
                f"; Part II-B: 21 {money(fica_withheld)} + 22 {money(se_half)} - 24 EIC {money(eitc)} = {money(line25)}"
            )
        if actc:
            r.line("S8812:27", actc, how)
    r.line("28", actc, "Schedule 8812 line 27" if actc else "no additional child tax credit (credit fully used)")
    if edu_ref:
        r.line("29", edu_ref, "Form 8863 line 8")
    return r


def w2_boxes(w: W2, year: int) -> dict[str, float]:
    medicare_wages = w.gross - w.fsa
    ss_wages = min(medicare_wages, WAGE_BASE[year])
    boxes = {
        "1": cents(w.gross - w.pretax_401k - w.fsa),
        "3": cents(ss_wages),
        "4": cents(ss_wages * 0.062),
        "5": cents(medicare_wages),
        "6": cents(medicare_wages * 0.0145 + max(medicare_wages - 200000, 0.0) * 0.009),
    }
    if w.fsa:
        boxes["10"] = cents(w.fsa)
    return boxes


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
    out.update(plan31_households(year))
    return out


def plan31_households(year: int) -> dict[str, dict]:
    """The Plan 31 goldens of ``year`` (credits, deductions and regimes; each spec's documents)."""
    out = {}
    out["eitc_head_of_household"] = {
        "description": "head of household with two school-age children and $28,000 of wages: earned income credit, "
        "child tax credit limited by the tax and the additional child tax credit",
        "returns": [
            Return(
                year,
                "hoh",
                w2=[W2("robin", "Example County", 28000.0)],
                dependents=[Dependent(10), Dependent(7)],
                filer_ages=(34,),
            )
        ],
    }
    out["dependent_care_mfj"] = {
        "description": "married filing jointly, two earners, two children in daycare ($12,000 each) and a $5,000 "
        "dependent-care FSA: Form 2441 Part III exclusion and the credit on the $1,000 left of the $6,000 limit",
        "returns": [
            Return(
                year,
                "mfj",
                w2=[W2("john", "Example Analytics", 70000.0, fsa=5000.0), W2("jane", "Example County", 45000.0)],
                dependents=[Dependent(4, care_expenses=12000.0), Dependent(2, care_expenses=12000.0)],
                filer_ages=(36, 34),
            )
        ],
    }
    out["education_aotc_mfj"] = {
        "description": "married filing jointly with a 19-year-old full-time student ($28,000 of college costs, a 529 "
        "plan paying all but the $4,000 kept for the American opportunity credit) and the credit for other dependents",
        "returns": [
            Return(
                year,
                "mfj",
                w2=[W2("sam", "Example Consulting LLC", 120000.0)],
                dependents=[Dependent(19, student=True, education_expenses=4000.0)],
                filer_ages=(50, 48),
            )
        ],
    }
    out["savers_credit_single"] = {
        "description": "single 24-year-old with $30,000 of wages and a 10% pre-tax 401(k) deferral: retirement savings "
        "contributions credit at the 10% tier, and a $500 cash gift (the non-itemizer deduction from 2026)",
        "returns": [
            Return(
                year,
                "single",
                w2=[W2("alex", "Example Analytics", 30000.0, 3000.0)],
                charity_cash=500.0,
                savers_contributions=[3000.0],
                filer_ages=(24,),
            )
        ],
    }
    out["iso_amt_single"] = {
        "description": "single filer with $200,000 of wages who exercises incentive stock options and holds the shares "
        "(a $400,000 bargain element): alternative minimum tax and the minimum tax credit it creates",
        "returns": [Return(year, "single", w2=[W2("morgan", "Example Analytics", 200000.0)], iso_spread=400000.0)],
    }
    if year >= 2025:
        prior = work_return(
            Return(year - 1, "single", w2=[W2("morgan", "Example Analytics", 200000.0)], iso_spread=400000.0)
        )
        out["iso_amt_credit"] = {
            "description": f"the incentive-stock-option household the year after the {year - 1} exercise: the "
            "prior-year minimum tax credit (Form 8801) against regular tax over the tentative minimum tax",
            "returns": [
                Return(
                    year,
                    "single",
                    w2=[W2("morgan", "Example Analytics", 200000.0)],
                    amt_credit_carryforward=prior.amt_credit_generated,
                )
            ],
            "prior": prior,
        }
    out["self_employed_single"] = {
        "description": "single self-employed consultant with $150,000 of net profit: self-employment tax (Schedule SE), "
        "the deductible half, a SEP contribution at a 25% plan rate (Pub. 560: 20% of net earnings) and the qualified "
        "business income deduction (Form 8995)",
        "returns": [Return(year, "single", business_profit=150000.0, sep_rate=25.0, filer_ages=(45,))],
        "tolerance_note": "the forms round Schedule SE line 13 and the SEP deduction to the cent before adding them; "
        "the engine carries them unrounded, so lines that add them are compared within $0.10",
        "loose_lines": [
            "1040:10",
            "1040:11",
            "1040:11a",
            "1040:11b",
            "1040:14",
            "1040:15",
            "schedule 1:26",
            "schedule 8995:1",
            "schedule 8995:15",
        ],
    }
    out["kiddie_tax_mfj"] = {
        "description": "married filing jointly, one earner, a 12-year-old with $2,000 of interest and $3,000 of "
        "qualified dividends reported on the parents' return (Form 8814)",
        "returns": [
            Return(
                year,
                "mfj",
                w2=[W2("john", "Example Analytics", 150000.0)],
                dependents=[Dependent(12, interest=2000.0, dividends=3000.0)],
                filer_ages=(45, 43),
            )
        ],
    }
    out["appreciated_stock_gift"] = {
        "description": "single filer with $800,000 of wages giving $300,000 of long-term appreciated shares (basis "
        "$60,000): deducted at fair market value up to 30% of AGI with the rest carried over, no capital gain; "
        "from 2026 the 0.5% floor and the 2/37 limit on itemized deductions",
        "returns": [Return(year, "single", w2=[W2("pat", "Example Consulting LLC", 800000.0)], stock_gift=300000.0)],
    }
    rmd_amount = cents(500000 / 24.6)
    out["qcd_retiree"] = {
        "description": "single 75-year-old taking a required minimum distribution from a traditional IRA, $10,000 of "
        "it paid to charity as a qualified charitable distribution, and savings interest",
        "returns": [
            Return(
                year,
                "single",
                interest=200000 * 0.04,
                ira_distributions=cents(rmd_amount - 10000.0),
                qcd=10000.0,
                ages_65_plus=1,
                filer_ages=(75,),
            )
        ],
        "rmds_gross": {"lee": rmd_amount},
    }
    loan_payment = standard_payment(45000, 0.075, 10)
    out["student_loan_phaseout"] = {
        "description": "single filer with $90,000 of wages and student loan interest over the cap, inside the "
        "deduction's MAGI phase-out",
        "returns": [
            Return(
                year,
                "single",
                w2=[W2("riley", "Example County", 90000.0)],
                student_loan_interest=amortized_interest(40000, 0.075, loan_payment),
                filer_ages=(31,),
            )
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
    directory.mkdir(exist_ok=True)
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
        if r.tax_limited:
            # A credit limited by the tax inherits the Tax Table difference (the engine limits it by the
            # exact schedule): the same tolerance as line 16, on every line the limited credit reaches.
            for line in ("19", "20", "21", "28"):
                if line in r.lines:
                    tolerances[f"{prefix}1040:{line}"] = r.tax_table_bound
            for schedule, lines in r.schedules.items():
                if schedule in ("3", "8812", "2441", "8863", "8880"):
                    for line in lines:
                        tolerances[f"{prefix}schedule {schedule}:{line}"] = r.tax_table_bound
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
    if "rmds_gross" in info:
        expected["actuals"]["form_1099"] = [
            {
                "form": "1099-R",
                "person": person,
                "account": f"{person}_ira",
                "boxes": {"1": amount, "2a": amount},
                "code": "7",
            }
            for person, amount in info["rmds_gross"].items()
        ]
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
    if "prior" in info:
        prior = info["prior"]
        md += [
            (
                f"Prior year ({prior.year}): the incentive stock option exercise created AMT of {money(prior.lines['17'])} "
                f"and a minimum tax credit carryforward of {money(prior.amt_credit_generated)} (that year's "
                f"`iso_amt_single_{prior.year}` golden works the return)."
            ),
            "",
        ]
    if "rmds_gross" in info:
        md += [
            "RMD (Pub. 590-B): "
            + "; ".join(f"{p} {money(a)}" for p, a in info["rmds_gross"].items())
            + " ($500,000 / 24.6 at 75); the $10,000 qualified charitable distribution counts toward it (1099-R box 1 "
            "and box 2a show the whole distribution; the return excludes the QCD on line 4b).",
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
            f"W-2 {w.employer} ({w.person}): box 1 = {money(w.gross)} - 401(k) {money(w.pretax_401k)}"
            + (f" - dependent-care FSA {money(w.fsa)}" if w.fsa else "")
            + f" = {money(boxes['1'])}; "
            f"box 3 = min(wages, {money(WAGE_BASE[year])}) = {money(boxes['3'])}; box 4 = 6.2% = {money(boxes['4'])}; "
            f"box 5 = {money(boxes['5'])}; box 6 = 1.45% (+0.9% over $200,000) = {money(boxes['6'])}"
            + (f"; box 10 = {money(w.fsa)}." if w.fsa else ".")
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
