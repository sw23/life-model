# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Federal tax credits.

Each credit is a function ``credit_x(facts, config) -> CreditLine`` of the return in progress
(:class:`ReturnFacts`, gathered by the tax unit from the members' ledgers) and the year's config. The
tax unit applies them in Form 1040 order through :func:`apply_credits`: the nonrefundable credits of
Schedule 3 (child and dependent care, education, saver's), then the child tax credit and credit for
other dependents (line 19, limited by Schedule 8812's Credit Limit Worksheet A to what those leave),
then the prior-year minimum tax credit (Schedule 3 line 6b, Form 8801); the refundable credits
(earned income credit, additional child tax credit, refundable American opportunity credit) are paid
whatever the tax. Each nonrefundable credit is limited to the tax left after the ones before it, so the
order is the forms' order and :data:`CREDITS` is that list. Every parameter is the year's (``tax_years``).

The phase-out math lives here as pure functions so it can be unit-tested against worked examples.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from ..config.financial_config import resolve_financial_config as _fin
from .federal import FilingStatus

if TYPE_CHECKING:
    from ..config.financial_config import FinancialConfig
    from ..config.models import DependentCareYear, EITCYear


# --------------------------------------------------------------------------------------------------
# The return in progress
# --------------------------------------------------------------------------------------------------


@dataclass
class Student:
    """A dependent student this year (Form 8863): qualified expenses not paid with tax-free 529 money,
    and the years the American opportunity credit was already claimed for them."""

    expenses: float
    aotc_years_claimed: int = 0


@dataclass
class CreditLine:
    """One credit on the return, split into its nonrefundable and refundable parts."""

    name: str
    nonrefundable: float = 0.0
    refundable: float = 0.0
    #: Worksheet figures (for the return record and explanations).
    detail: dict[str, float] = field(default_factory=dict)

    @property
    def total(self) -> float:
        return self.nonrefundable + self.refundable


@dataclass
class ReturnFacts:
    """What the credits read from a return in progress (built by ``TaxUnit``)."""

    year: int
    filing_status: FilingStatus
    #: Adjusted gross income (also the MAGI of every credit modeled: no foreign exclusions).
    agi: float
    #: Form 1040 line 18: regular tax (line 16) plus AMT.
    tax_before_credits: float
    #: Form 1040 line 16 (regular tax), for the minimum tax credit limit.
    regular_tax: float = 0.0
    #: Form 6251 line 9 this year (tentative minimum tax).
    tentative_minimum_tax: float = 0.0
    #: Earned income per member (W-2 box 1 wages plus net self-employment earnings less half of SE tax).
    earned_income: list[float] = field(default_factory=list)
    #: Members' ages (end of year).
    ages: list[int] = field(default_factory=list)
    #: §32(i) investment income: interest (incl. tax-exempt), dividends and net capital gain.
    investment_income: float = 0.0
    #: Children qualifying for the child tax credit (under 17).
    ctc_children: int = 0
    #: Other dependents (credit for other dependents: children 17-18, students under 24).
    other_dependents: int = 0
    #: Qualifying children for the earned income credit (under 19, or students under 24).
    eitc_children: int = 0
    #: Qualifying persons for the dependent care credit (children under 13) and their care expenses.
    care_persons: int = 0
    care_expenses: float = 0.0
    #: Dependent care benefits excluded from wages (Form 2441 line 25).
    excluded_care_benefits: float = 0.0
    #: Dependent students (Form 8863).
    students: list[Student] = field(default_factory=list)
    #: Per member: retirement contributions less the testing-period distributions (Form 8880 line 5).
    savers_contributions: list[float] = field(default_factory=list)
    #: Social Security and Medicare tax withheld on wages, and half of SE tax (Schedule 8812 lines 21-22).
    payroll_taxes_withheld: float = 0.0
    se_tax_deduction: float = 0.0
    #: Minimum tax credit carried in from earlier years (Form 8801 line 19).
    amt_credit_carryforward: float = 0.0
    #: Nonrefundable credits applied so far (set by :func:`apply_credits`).
    nonrefundable_used: float = 0.0
    #: The earned income credit (set by :func:`apply_credits` before the child tax credit needs it).
    eitc: float = 0.0
    #: Form 8962's figures when the return has marketplace coverage (:func:`~life_model.tax.ptc.premium_tax_credit`).
    ptc: "dict[str, float] | None" = None

    @property
    def joint(self) -> bool:
        return self.filing_status == FilingStatus.MARRIED_FILING_JOINTLY

    @property
    def separate(self) -> bool:
        return self.filing_status == FilingStatus.MARRIED_FILING_SEPARATELY

    @property
    def tax_left(self) -> float:
        """Line 18 less the nonrefundable credits applied so far."""
        return max(0.0, self.tax_before_credits - self.nonrefundable_used)


def _half_up(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------------------------------
# Child tax credit / credit for other dependents (IRC §24; Schedule 8812)
# --------------------------------------------------------------------------------------------------


def _phaseout_threshold(filing_status: FilingStatus, config: "FinancialConfig | None") -> float:
    """MAGI threshold at which the CTC begins to phase out for ``filing_status``.

    Statuses without their own configured threshold (e.g. HEAD_OF_HOUSEHOLD sharing the single
    threshold) fall back to ``single``; a separate return uses half the joint threshold when the config
    has no ``married_filing_separately`` entry (IRC §24(b)(2)(C): $200,000 vs $400,000).
    """
    thresholds = _fin(config).dependents.ctc_phaseout_start
    return getattr(thresholds, filing_status.name.lower(), thresholds.single)


def child_tax_credit(
    num_qualifying_children: int,
    magi: float,
    federal_tax: float,
    filing_status: FilingStatus,
    config: "FinancialConfig | None" = None,
) -> float:
    """Child Tax Credit usable this year (nonrefundable portion plus refundable portion).

    The credit starts at ``ctc_per_child`` per qualifying child and is reduced by
    ``ctc_phaseout_rate`` percent of each $1,000 (or fraction thereof — IRC §24(b)(2)) of
    modified AGI over the filing-status threshold. The nonrefundable portion is clamped at the
    federal income-tax liability; up to ``ctc_refundable_max`` per child of the remainder is
    refundable. This helper takes no earned income, so the refundable part is not limited by the
    15%-of-earned-income rule; the settlement path uses :func:`child_tax_credit_line`, which applies
    Schedule 8812 Part II in full.

    Args:
        num_qualifying_children: Children who qualify (age within limit, alive parent in unit).
        magi: The unit's modified adjusted gross income (AGI).
        federal_tax: Federal income-tax liability before credits.
        filing_status: The unit's filing status (selects the phase-out threshold).
        config: Per-model config. Defaults to the packaged defaults.

    Returns:
        The total credit amount to record on ``TaxesDue.credits`` (>= 0).
    """
    nonrefundable, refundable = child_tax_credit_parts(
        num_qualifying_children, magi, federal_tax, filing_status, config
    )
    return nonrefundable + refundable


def child_tax_credit_parts(
    num_qualifying_children: int,
    magi: float,
    federal_tax: float,
    filing_status: FilingStatus,
    config: "FinancialConfig | None" = None,
    *,
    other_dependents: int = 0,
    earned_income: float | None = None,
    payroll_taxes: float = 0.0,
    eitc: float = 0.0,
) -> tuple[float, float]:
    """``(nonrefundable, refundable)`` portions of the child tax credit and credit for other dependents.

    ``federal_tax`` is the tax the nonrefundable part may use (Credit Limit Worksheet A line 3). With
    ``earned_income`` the refundable part follows Schedule 8812 Part II-A (15% of earned income over the
    threshold, up to ``ctc_refundable_max`` per child) and, for three or more children, Part II-B (the
    larger of that and the payroll taxes ``payroll_taxes`` less the ``eitc``); without it (the default,
    and a config without ``actc_earned_income_threshold``) the refundable part is the unused credit up to
    the per-child maximum.
    """
    line = _ctc_line(
        num_qualifying_children,
        magi,
        federal_tax,
        filing_status,
        config,
        other_dependents=other_dependents,
        earned_income=earned_income,
        payroll_taxes=payroll_taxes,
        eitc=eitc,
    )
    return line.nonrefundable, line.refundable


def _ctc_line(
    children: int,
    magi: float,
    tax_limit: float,
    filing_status: FilingStatus,
    config: "FinancialConfig | None",
    *,
    other_dependents: int = 0,
    earned_income: float | None = None,
    payroll_taxes: float = 0.0,
    eitc: float = 0.0,
) -> CreditLine:
    dep = _fin(config).dependents
    odc_each = dep.odc_per_dependent or 0.0
    others = other_dependents if odc_each > 0 else 0
    if children <= 0 and others <= 0:
        return CreditLine("child_tax_credit")
    line8 = dep.ctc_per_child * max(children, 0) + odc_each * max(others, 0)
    excess = magi - _phaseout_threshold(filing_status, config)
    reduction = 0.0
    if excess > 0:
        # $50-per-$1,000-or-fraction-thereof at the default 5% rate: round the excess up to the
        # next $1,000 step before applying the rate.
        reduction = math.ceil(excess / 1000) * 1000 * (dep.ctc_phaseout_rate / 100)
    line12 = max(0.0, line8 - reduction)
    if line12 <= 0:
        return CreditLine("child_tax_credit")
    nonrefundable = min(line12, max(tax_limit, 0.0))
    refundable = 0.0
    if children > 0:
        line16a = line12 - nonrefundable
        line16b = dep.ctc_refundable_max * children
        line17 = min(line16a, line16b)
        threshold = dep.actc_earned_income_threshold
        if earned_income is None or threshold is None:
            refundable = line17
        else:
            line20 = max(0.0, earned_income - threshold) * dep.actc_rate / 100
            refundable = min(line17, line20)
            if children >= 3 and line20 < line17:
                line25 = max(0.0, payroll_taxes - eitc)
                refundable = min(line17, max(line20, line25))
    detail = {"credit_before_limit": line12, "phaseout_reduction": reduction}
    return CreditLine("child_tax_credit", nonrefundable, refundable, detail)


def child_tax_credit_line(facts: ReturnFacts, config: "FinancialConfig") -> CreditLine:
    """Schedule 8812: the child tax credit and credit for other dependents (line 19) and the
    additional child tax credit (line 28), with MAGI = AGI (preferential income included)."""
    return _ctc_line(
        facts.ctc_children,
        facts.agi,
        facts.tax_left,
        facts.filing_status,
        config,
        other_dependents=facts.other_dependents,
        earned_income=sum(facts.earned_income),
        payroll_taxes=facts.payroll_taxes_withheld + facts.se_tax_deduction,
        eitc=facts.eitc,
    )


# --------------------------------------------------------------------------------------------------
# Earned income credit (IRC §32; EIC Table)
# --------------------------------------------------------------------------------------------------


def eic_table_amount(income: float, children: int, joint: bool, params: "EITCYear") -> float:
    """The EIC Table amount for ``income`` (Form 1040 instructions).

    The table is $50 bands; each band's credit is the §32 formula at the band's midpoint, rounded to
    the dollar, except that a band containing the earned income amount shows the maximum credit and a
    band starting below the phase-out threshold shows no reduction (this reproduces every one of the
    1,329 rows x 8 columns of the 2024 table).
    """
    if income <= 0:
        return 0.0
    n = min(max(children, 0), 3)
    low = math.floor(income / 50) * 50
    middle = low + 25
    if low + 50 > params.earned_income_amount[n]:
        phase_in = params.max_credit[n]
    else:
        phase_in = params.credit_percent[n] / 100 * middle
    threshold = (params.phaseout_start_joint if joint else params.phaseout_start)[n]
    reduction = 0.0 if low < threshold else params.phaseout_percent[n] / 100 * (middle - threshold)
    return max(0.0, _half_up(phase_in - reduction))


def earned_income_credit(
    earned_income: float,
    agi: float,
    children: int,
    filing_status: FilingStatus,
    params: "EITCYear | None",
    *,
    investment_income: float = 0.0,
    ages: "list[int] | None" = None,
    min_age: int = 25,
    max_age: int = 64,
) -> float:
    """The earned income credit (EIC Worksheet A): the table amount for earned income, or the smaller of
    that and the amount for AGI once AGI reaches the phase-out threshold.

    Not allowed on a separate return (the separated-spouse exception is not modeled), with investment
    income over the limit, or, with no qualifying child, unless a filer is 25-64.
    """
    if params is None or earned_income <= 0 or filing_status == FilingStatus.MARRIED_FILING_SEPARATELY:
        return 0.0
    if investment_income > params.investment_income_limit:
        return 0.0
    if children <= 0 and ages is not None and not any(min_age <= age <= max_age for age in ages):
        return 0.0
    joint = filing_status == FilingStatus.MARRIED_FILING_JOINTLY
    credit = eic_table_amount(earned_income, children, joint, params)
    n = min(max(children, 0), 3)
    threshold = (params.phaseout_start_joint if joint else params.phaseout_start)[n]
    if agi != earned_income and agi >= threshold:
        credit = min(credit, eic_table_amount(agi, children, joint, params))
    return credit


def earned_income_credit_line(facts: ReturnFacts, config: "FinancialConfig") -> CreditLine:
    statute = config.tax.federal.credits
    credit = earned_income_credit(
        sum(facts.earned_income),
        facts.agi,
        facts.eitc_children,
        facts.filing_status,
        config.tax.federal.eitc,
        investment_income=facts.investment_income,
        ages=facts.ages,
        min_age=statute.eitc_min_age_no_children,
        max_age=statute.eitc_max_age_no_children,
    )
    return CreditLine("earned_income_credit", refundable=credit)


# --------------------------------------------------------------------------------------------------
# Child and dependent care credit (IRC §21; Form 2441)
# --------------------------------------------------------------------------------------------------


def dependent_care_rate(agi: float, joint: bool, params: "DependentCareYear") -> float:
    """Form 2441 line 8 (percent): one point off ``max_rate`` per ``step`` (or fraction) of AGI over
    ``first_start`` down to ``first_floor``, then (2026+) one point per second step over the second
    threshold down to ``second_floor``."""
    rate = params.max_rate - math.ceil(max(0.0, agi - params.first_start) / params.step)
    rate = max(params.first_floor, rate)
    start = params.second_start_joint if joint else params.second_start
    if start is not None:
        step = params.second_step_joint if joint else params.second_step
        rate = max(params.second_floor, rate - math.ceil(max(0.0, agi - start) / step))
    return float(rate)


def excluded_dependent_care_benefits(
    benefits: float, expenses: float, earned_income: "list[float]", filing_status: FilingStatus, params
) -> float:
    """Form 2441 line 25: dependent care benefits excluded from wages: the smallest of the benefits, the
    qualified expenses, each spouse's earned income, and the §129 limit (half on a separate return)."""
    if benefits <= 0 or params is None:
        return 0.0
    limit = params.exclusion_limit / (2 if filing_status == FilingStatus.MARRIED_FILING_SEPARATELY else 1)
    earned = earned_income if filing_status == FilingStatus.MARRIED_FILING_JOINTLY else earned_income[:1]
    return max(0.0, min(benefits, expenses, limit, *earned))


def dependent_care_credit(facts: ReturnFacts, config: "FinancialConfig") -> CreditLine:
    """Form 2441: the qualified expenses (up to $3,000 / $6,000 less excluded benefits, and the lower
    earner's earned income) times the AGI-based rate, limited to the tax. Not on a separate return."""
    params = config.tax.federal.dependent_care
    if params is None or facts.care_persons <= 0 or facts.care_expenses <= 0 or facts.separate:
        return CreditLine("dependent_care_credit")
    limit = params.expense_limit_one if facts.care_persons == 1 else params.expense_limit_two
    line29 = limit - facts.excluded_care_benefits
    if line29 <= 0:
        return CreditLine("dependent_care_credit", detail={"line_29": line29})
    line31 = min(line29, max(0.0, facts.care_expenses - facts.excluded_care_benefits))
    earned = facts.earned_income if facts.joint else facts.earned_income[:1]
    line6 = max(0.0, min(line31, *earned)) if earned else 0.0
    rate = dependent_care_rate(facts.agi, facts.joint, params)
    tentative = line6 * rate / 100
    credit = min(tentative, facts.tax_left)
    return CreditLine("dependent_care_credit", credit, detail={"expenses": line6, "rate": rate})


# --------------------------------------------------------------------------------------------------
# Education credits (IRC §25A; Form 8863)
# --------------------------------------------------------------------------------------------------


def education_credits(facts: ReturnFacts, config: "FinancialConfig") -> CreditLine:
    """Form 8863: the American opportunity credit (first four years: 100% of $2,000 + 25% of the next
    $2,000 per student, 40% refundable) and the lifetime learning credit (20% of up to $10,000 per
    return, for students past their AOTC years), both phased out by MAGI. Not on a separate return."""
    edu = config.tax.federal.credits.education
    if edu is None or not facts.students or facts.separate:
        return CreditLine("education_credits")
    aotc = 0.0
    llc_expenses = 0.0
    for student in facts.students:
        expenses = max(0.0, student.expenses)
        if student.aotc_years_claimed < edu.aotc_max_years:
            full = min(expenses, edu.aotc_full_expenses)
            partial = min(max(0.0, expenses - edu.aotc_full_expenses), edu.aotc_partial_expenses)
            aotc += full + partial * edu.aotc_partial_rate / 100
        else:
            llc_expenses += expenses
    phaseout = edu.phaseout_joint if facts.joint else edu.phaseout_single
    # Form 8863 line 6: the fraction is rounded to at least three places (three here).
    fraction = round(phaseout.fraction_allowed(facts.agi), 3)
    aotc *= fraction
    llc = min(llc_expenses, edu.llc_expense_limit) * edu.llc_rate / 100 * fraction
    refundable = aotc * edu.aotc_refundable_percent / 100
    nonrefundable = min(aotc - refundable + llc, facts.tax_left)
    return CreditLine(
        "education_credits",
        nonrefundable,
        refundable,
        detail={"american_opportunity": aotc, "lifetime_learning": llc, "phaseout_fraction": fraction},
    )


# --------------------------------------------------------------------------------------------------
# Retirement savings contributions credit (IRC §25B; Form 8880)
# --------------------------------------------------------------------------------------------------


def savers_credit_rate(agi: float, filing_status: FilingStatus, params) -> float:
    """Form 8880 line 9 (percent) for the return's AGI and status."""
    if filing_status == FilingStatus.MARRIED_FILING_JOINTLY:
        ceilings = params.joint
    elif filing_status == FilingStatus.HEAD_OF_HOUSEHOLD:
        ceilings = params.head_of_household
    else:
        ceilings = params.other
    for ceiling, rate in zip(ceilings, params.rates, strict=True):
        if agi <= ceiling:
            return rate
    return 0.0


def savers_credit(facts: ReturnFacts, config: "FinancialConfig") -> CreditLine:
    """Form 8880: each filer's contributions less testing-period distributions, up to $2,000 each, times
    the AGI-tier rate, limited to the tax. Through 2026 (SECURE 2.0 replaces it with the Saver's Match)."""
    params = config.tax.federal.savers_credit
    statute = config.tax.federal.credits
    if params is None or facts.year > statute.savers_credit_last_year:
        return CreditLine("savers_credit")
    eligible = sum(
        min(max(0.0, amount), params.max_contribution)
        for amount, age in zip(facts.savers_contributions, facts.ages, strict=False)
        if age >= statute.savers_credit_min_age
    )
    rate = savers_credit_rate(facts.agi, facts.filing_status, params)
    if eligible <= 0 or rate <= 0:
        return CreditLine("savers_credit")
    credit = min(eligible * rate / 100, facts.tax_left)
    return CreditLine("savers_credit", credit, detail={"contributions": eligible, "rate": rate})


# --------------------------------------------------------------------------------------------------
# Prior-year minimum tax credit (IRC §53; Form 8801)
# --------------------------------------------------------------------------------------------------


def minimum_tax_credit(facts: ReturnFacts, config: "FinancialConfig") -> CreditLine:
    """Form 8801 Part II: the carryforward, up to the regular tax less the other nonrefundable credits
    and this year's tentative minimum tax."""
    from .amt import minimum_tax_credit_allowed

    if facts.amt_credit_carryforward <= 0:
        return CreditLine("minimum_tax_credit")
    regular_after_credits = max(0.0, facts.regular_tax - facts.nonrefundable_used)
    credit = minimum_tax_credit_allowed(
        facts.amt_credit_carryforward, regular_after_credits, facts.tentative_minimum_tax
    )
    credit = min(credit, facts.tax_left)
    return CreditLine("minimum_tax_credit", credit, detail={"carryforward": facts.amt_credit_carryforward})


# --------------------------------------------------------------------------------------------------
# Premium tax credit (IRC §36B; Form 8962)
# --------------------------------------------------------------------------------------------------


def premium_tax_credit_line(facts: ReturnFacts, config: "FinancialConfig") -> CreditLine:
    """The net premium tax credit (Form 8962 line 26; Schedule 3 line 9): refundable. Excess advance payments
    are repaid as tax instead (``finish_federal``, from ``facts.ptc['repayment']``)."""
    if facts.ptc is None:
        return CreditLine("premium_tax_credit")
    detail = {k: v for k, v in facts.ptc.items() if k != "net"}
    return CreditLine("premium_tax_credit", refundable=facts.ptc["net"], detail=detail)


# --------------------------------------------------------------------------------------------------
# The ordered list and the driver
# --------------------------------------------------------------------------------------------------

#: The credits in Form 1040 order (each nonrefundable part is limited by the tax the earlier ones left).
#: The earned income credit is refundable only; it is computed first because Schedule 8812 Part II-B
#: (three or more children) reads it.
CREDITS: "tuple[Callable[[ReturnFacts, FinancialConfig], CreditLine], ...]" = (
    earned_income_credit_line,
    dependent_care_credit,
    education_credits,
    savers_credit,
    child_tax_credit_line,
    minimum_tax_credit,
    premium_tax_credit_line,
)


def apply_credits(facts: ReturnFacts, config: "FinancialConfig") -> list[CreditLine]:
    """Run :data:`CREDITS` in order; returns the lines with a non-zero credit."""
    lines = []
    for credit in CREDITS:
        line = credit(facts, config)
        if line.name == "earned_income_credit":
            facts.eitc = line.refundable
        facts.nonrefundable_used += line.nonrefundable
        if line.total > 0:
            lines.append(line)
    return lines
