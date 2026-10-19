# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Return-level pieces of a tax unit's federal computation.

:class:`~life_model.people.tax_unit.TaxUnit` owns the settlement; the return-level rules it applies
live here so they stay with the rest of the tax code:

* :func:`plan_deductions`: standard (with §63(f)) vs itemized (after the charitable floor and the §68
  2/37 limit), the non-itemizer charitable deduction, the senior deduction and the QBI deduction;
* :func:`finish_federal`: the Form 8814 tax, AMT (Form 6251, with the minimum tax credit it generates)
  and every credit (``credits.apply_credits``), recorded on the ``TaxesDue``;
* :func:`post_year_end_adjustments`: the adjustments settled once a year before the waterfall (half of
  self-employment tax, taxable dependent care benefits, the Form 8814 inclusion, the IRA deduction and
  Roth contribution phase-outs, the student loan interest deduction and its phase-out);
* :func:`record_year_end`: the carryforwards and counters a settled return leaves for later years
  (minimum tax credit, charitable property carryover, AOTC years, saver's-credit distributions).

MAGI for the IRA, Roth and student-loan phase-outs is the return's AGI at the start of settlement,
before the year's waterfall draws (a draw sized later in the year does not move these deductions).
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .amt import AMTInputs, alternative_minimum_tax, minimum_tax_credit_generated
from .credits import ReturnFacts, Student, apply_credits, excluded_dependent_care_benefits
from .deductions import itemized_limitation, settle_property_carryforwards
from .federal import FilingStatus
from .income import IncomeType
from .qbi import QBIDeduction, qbi_deduction
from .self_employment import self_employment_tax

if TYPE_CHECKING:
    from ..people.person import Person
    from ..people.tax_unit import TaxUnit
    from .tax import TaxesDue

#: Ledger sources of the year-end adjustments posted by :func:`post_year_end_adjustments`.
SE_DEDUCTION_SOURCE = "se_tax_deduction"
SELF_EMPLOYED_PLAN_SOURCE = "self_employed_plan"
FORM_8814_SOURCE = "form_8814"
TAXABLE_CARE_BENEFITS_SOURCE = "taxable_dependent_care_benefits"


# --------------------------------------------------------------------------------------------------
# Facts about members and children
# --------------------------------------------------------------------------------------------------


def _children(unit: "TaxUnit"):
    return [child for member in unit.members for child in member.children if child.age >= 0]


def _is_student(child) -> bool:
    return bool(getattr(child, "in_college_band", False))


def _is_dependent_child(child, dep) -> bool:
    """A qualifying child (IRC §152(c)(3)): under 19 at year end, or a student under 24."""
    age = child.age
    return 0 <= age and (
        age < dep.dependent_age_limit or (_is_student(child) and age < dep.student_dependent_age_limit)
    )


def has_dependent_child(member: "Person") -> bool:
    """Whether ``member`` has a dependent child this year (a qualifying child)."""
    dep = member.model.config.dependents
    return any(_is_dependent_child(child, dep) for child in member.children)


def qualifying_relatives(unit: "TaxUnit") -> list:
    """The unit's qualifying relatives this year (a supported parent)."""
    year = unit.members[0].model.year
    return [d for m in unit.members for d in getattr(m, "qualifying_relatives", ()) if d.qualifies(year)]


def dependent_counts(unit: "TaxUnit") -> dict[str, int]:
    """Children by the credit they qualify for: ``ctc`` (under 17), ``other`` (credit for other
    dependents: 17-18, a student under 24, or a qualifying relative), ``eitc`` (under 19, or a student
    under 24), ``care`` (under 13 with care expenses this year) and ``relatives`` (qualifying relatives, a
    supported parent: in ``other``, not EITC children)."""
    dep = unit.config.dependents
    ctc = other = eitc = care = 0
    for child in _children(unit):
        age = child.age
        dependent = _is_dependent_child(child, dep)
        if age <= dep.ctc_qualifying_age_max:
            ctc += 1
        elif dependent:
            other += 1
        if dependent:
            eitc += 1
        if age < 13 and getattr(child, "care_expenses_this_year", 0.0) > 0:
            care += 1
    relatives = len(qualifying_relatives(unit))
    return {"ctc": ctc, "other": other + relatives, "eitc": eitc, "care": care, "relatives": relatives}


def care_expenses(unit: "TaxUnit") -> float:
    return sum(getattr(child, "care_expenses_this_year", 0.0) for child in _children(unit) if child.age < 13)


def students(unit: "TaxUnit") -> list[Student]:
    """Dependent students in college this year with expenses not paid by tax-free 529 withdrawals."""
    out = []
    for child in _children(unit):
        if not _is_student(child):
            continue
        expenses = getattr(child, "education_expenses_this_year", 0.0) - getattr(child, "education_paid_by_529", 0.0)
        if expenses > 0:
            out.append(Student(expenses, getattr(child, "aotc_years_claimed", 0)))
    return out


def se_profits(unit: "TaxUnit") -> list[float]:
    return [m.income.self_employment_income for m in unit.members]


def ss_wages(unit: "TaxUnit") -> list[float]:
    """Each member's W-2 Social Security wages (FICA wages capped at the wage base)."""
    base = unit.config.tax.fica.social_security_max_income
    return [min(max(0.0, m.fica_wages), base) for m in unit.members]


def earned_incomes(unit: "TaxUnit", taxes: "TaxesDue | None" = None) -> list[float]:
    """Earned income per member (EIC / Schedule 8812 / Form 2441): W-2 box 1 wages plus net profit less
    the deductible half of SE tax."""
    out = []
    for index, member in enumerate(unit.members):
        se_half = 0.0
        if taxes is not None and index < len(taxes.se_by_worker):
            se_half = taxes.se_by_worker[index].deduction
        out.append(member.income.wages + member.income.self_employment_income - se_half)
    return out


def investment_income(unit: "TaxUnit", additional_preferential: float = 0.0, additional_short_term: float = 0.0):
    """§32(i) disqualified income: interest (incl. tax-exempt), dividends and net capital gain."""
    total = additional_preferential + additional_short_term
    gains = 0.0
    for member in unit.members:
        totals = member.income.totals_by_type()
        total += (
            totals[IncomeType.INTEREST]
            + totals[IncomeType.TREASURY_INTEREST]
            + totals[IncomeType.TAX_EXEMPT_INTEREST]
            + totals[IncomeType.QUALIFIED_DIVIDEND]
        )
        gains += totals[IncomeType.SHORT_TERM_CAPITAL_GAIN] + totals[IncomeType.LONG_TERM_CAPITAL_GAIN]
    return total + max(0.0, gains)


def amt_credit_carryforward(member: "Person") -> float:
    return member.__dict__.get("amt_credit_carryforward", 0.0)


def _distribution_history(member: "Person") -> dict:
    return member.__dict__.setdefault("retirement_distribution_history", {})


def retirement_distributions(member: "Person") -> float:
    """Taxable retirement-plan and IRA distributions this year (Form 8880 line 4; HSA excluded)."""
    return sum(
        e.amount for e in member.income.entries if e.income_type == IncomeType.PRETAX_DISTRIBUTION and e.source != "hsa"
    )


def savers_contributions(unit: "TaxUnit") -> list[float]:
    """Form 8880 line 5 per member: elective deferrals and IRA contributions less the distributions of
    the testing period (this year and the two before; both spouses' on a joint return)."""
    year = unit.members[0].model.year
    distributions = 0.0
    for member in unit.members:
        history = _distribution_history(member)
        distributions += retirement_distributions(member) + history.get(year - 1, 0.0) + history.get(year - 2, 0.0)
    # Joint filers count both spouses' distributions against each spouse's contributions (Form 8880).
    return [
        max(0.0, member.elective_deferrals_ytd + member.ira_contributions_ytd - distributions)
        for member in unit.members
    ]


# --------------------------------------------------------------------------------------------------
# Deductions
# --------------------------------------------------------------------------------------------------


@dataclass
class DeductionPlan:
    """The return's deductions (Form 1040 lines 12e-14)."""

    standard: float
    additional_standard: float
    itemized_before_limit: float
    itemized: float
    itemized_limitation: float
    non_itemizer_charitable: float
    senior: float
    qbi: QBIDeduction
    itemize: bool
    charitable: object = None

    @property
    def total(self) -> float:
        base = self.itemized if self.itemize else self.standard + self.non_itemizer_charitable
        return base + self.senior + self.qbi.deduction


def _top_bracket_start(unit: "TaxUnit") -> float:
    brackets = unit.config.get_federal_tax_brackets(unit.filing_status)
    return float(brackets[-2][1]) if len(brackets) > 1 else float("inf")


def _qbi_amount(unit: "TaxUnit") -> float:
    """Qualified business income: net profit less the deductible half of SE tax and the self-employed
    plan deduction (both already on the ledger as adjustments)."""
    profit = sum(m.income.self_employment_income for m in unit.members)
    if profit <= 0:
        return profit
    adjustments = sum(
        -e.amount
        for m in unit.members
        for e in m.income.entries
        if e.income_type == IncomeType.ORDINARY and e.source in (SE_DEDUCTION_SOURCE, SELF_EMPLOYED_PLAN_SOURCE)
    )
    return profit - adjustments


def plan_deductions(
    unit: "TaxUnit",
    agi: float,
    standard: float,
    itemized: float,
    senior: float,
    preferential: float,
    additional_standard: float = 0.0,
    charitable=None,
) -> DeductionPlan:
    """Choose standard vs itemized and add the deductions taken on top of either.

    The non-itemizer charitable deduction (2026+) rides with the standard deduction; QBI is figured on
    taxable income before it and without §68 (§199A(e)(1)); §68 then cuts the itemized deductions by
    2/37 of the lesser of them and the income above the 37% bracket start; a return itemizes only when
    the itemized deductions after that cut beat the standard deduction plus the non-itemizer deduction.
    """
    year = unit.members[0].model.year
    non_itemizer = charitable.non_itemizer if charitable is not None else 0.0
    params = unit.config.tax.federal.qbi

    def qbi_for(itemize_now: bool) -> QBIDeduction:
        before = agi - (itemized if itemize_now else standard + non_itemizer) - senior
        return qbi_deduction(_qbi_amount(unit), max(0.0, before), preferential, unit.filing_status, params)

    itemize = itemized > standard + non_itemizer
    qbi = qbi_for(itemize)
    limitation = itemized_limitation(
        itemized, agi - senior - qbi.deduction, _top_bracket_start(unit), year, unit.config
    )
    itemized_after = itemized - limitation
    final = itemized_after > standard + non_itemizer
    if final != itemize:
        qbi = qbi_for(final)
    return DeductionPlan(
        standard=standard,
        additional_standard=additional_standard,
        itemized_before_limit=itemized,
        itemized=itemized_after,
        itemized_limitation=limitation,
        non_itemizer_charitable=0.0 if final else non_itemizer,
        senior=senior,
        qbi=qbi,
        itemize=final,
        charitable=charitable,
    )


# --------------------------------------------------------------------------------------------------
# Kiddie tax (Form 8814, the parents' election)
# --------------------------------------------------------------------------------------------------


def _child_unearned(child) -> tuple[float, float]:
    return getattr(child, "interest_annual", 0.0), getattr(child, "dividends_annual", 0.0)


def _form_8814_children(unit: "TaxUnit"):
    """``(child, interest, dividends, base)`` for each child whose income the parents report (Form 8814:
    under 19 or a student under 24, interest and dividends only, gross under 10 x the base amount)."""
    params = unit.config.tax.federal.kiddie_tax
    if params is None:
        return []
    dep = unit.config.dependents
    out = []
    for child in _children(unit):
        interest, dividends = _child_unearned(child)
        gross = interest + dividends
        young = child.age < dep.dependent_age_limit or (
            _is_student(child) and child.age < dep.student_dependent_age_limit
        )
        if gross > 0 and young and gross < 10 * params.base_amount:
            out.append((child, interest, dividends, params.base_amount))
    return out


def form_8814_tax(unit: "TaxUnit") -> float:
    """Form 8814 Part II: 10% of each child's income over the base amount, at most 10% of the base."""
    return sum(min(0.10 * max(0.0, i + d - base), 0.10 * base) for _c, i, d, base in _form_8814_children(unit))


def _post_form_8814(unit: "TaxUnit") -> None:
    """Form 8814 lines 5-12: the child's income over twice the base goes on the head's return, the
    qualified-dividend share as qualified dividends (line 3a), the rest on Schedule 1 line 8z."""
    head = unit.members[0]
    for _child, interest, dividends, base in _form_8814_children(unit):
        gross = interest + dividends
        included = gross - 2 * base
        if included <= 0:
            continue
        qualified = included * dividends / gross
        if qualified > 0:
            head.income.add(IncomeType.QUALIFIED_DIVIDEND, qualified, source=FORM_8814_SOURCE)
        if included - qualified > 0:
            head.income.add(IncomeType.ORDINARY, included - qualified, source=FORM_8814_SOURCE)


def marketplace_months(unit: "TaxUnit") -> "list[tuple[float, float, float]]":
    """The unit's marketplace coverage months this year, summed across its members' policies by month."""
    months: list[tuple[float, float, float]] = []
    for member in unit.members:
        for policy in member.model.registries.general_insurance_policies.get_items(member):
            if getattr(policy, "marketplace", None) is None:
                continue
            for index, month in enumerate(policy.ptc_months):
                if index < len(months):
                    months[index] = tuple(a + b for a, b in zip(months[index], month, strict=True))
                else:
                    months.append(month)
    return months


def premium_tax_credit_figures(unit: "TaxUnit", agi: float, counts: dict) -> "dict[str, float] | None":
    """Form 8962 for the unit's marketplace coverage (None without any): household income is AGI plus
    tax-exempt interest and the nontaxable part of Social Security; the family is the filers and their
    dependents."""
    from .ptc import premium_tax_credit

    params = unit.config.tax.federal.premium_tax_credit
    months = marketplace_months(unit)
    if params is None or not months:
        return None
    exempt = sum(m.income.tax_exempt_interest for m in unit.members)
    nontaxable_ss = sum(m.income.social_security_benefits - m.income.taxable_social_security for m in unit.members)
    household_income = max(0.0, agi + exempt + nontaxable_ss)
    filers = 2 if unit.filing_status.name == "MARRIED_FILING_JOINTLY" else 1
    size = filers + counts["ctc"] + counts["other"]
    return premium_tax_credit(household_income, size, months, unit.filing_status, params)


# --------------------------------------------------------------------------------------------------
# AMT, kiddie tax and credits on the TaxesDue
# --------------------------------------------------------------------------------------------------


def finish_federal(
    unit: "TaxUnit",
    taxes: "TaxesDue",
    agi: float,
    plan: DeductionPlan,
    salt: float,
    *,
    additional_preferential: float = 0.0,
    additional_short_term: float = 0.0,
) -> None:
    """Add the Form 8814 tax and AMT to ``taxes.federal``, then apply every credit."""
    config = unit.config
    status = unit.filing_status
    kiddie = form_8814_tax(unit)
    taxes.kiddie_tax = kiddie
    taxes.federal += kiddie
    regular_tax = taxes.ordinary_tax + taxes.preferential_tax + kiddie

    params = config.tax.federal.amt
    carryforward = sum(amt_credit_carryforward(m) for m in unit.members)
    tentative = 0.0
    if params is not None:
        iso = sum(m.income.amt_adjustments.get("iso", 0.0) for m in unit.members)
        inputs = AMTInputs(
            taxable_income=agi - plan.total,
            senior_deduction=plan.senior,
            deduction_addback=salt if plan.itemize else plan.standard,
            iso_adjustment=iso,
            itemized_limitation=plan.itemized_limitation if plan.itemize else 0.0,
            preferential_income=taxes.taxable_preferential,
            regular_taxable_ordinary=taxes.taxable_ordinary,
            regular_tax=regular_tax,
        )
        brackets = config.get_capital_gains_brackets(status)
        result = alternative_minimum_tax(inputs, status, params, brackets)
        taxes.amt_detail = result
        taxes.amt = result.amt
        tentative = result.tentative_minimum_tax
        taxes.federal += result.amt
        if result.amt > 0 and iso > 0:
            exclusion = alternative_minimum_tax(inputs, status, params, brackets, include_deferral_items=False)
            taxes.amt_credit_generated = minimum_tax_credit_generated(result, exclusion, regular_tax)

    counts = dependent_counts(unit)
    # Form 8962: the excess advance credit repaid is Schedule 2 line 1a, part of line 17 (before the credits).
    ptc = premium_tax_credit_figures(unit, agi, counts)
    if ptc is not None:
        taxes.ptc_detail = dict(ptc)
        taxes.excess_advance_ptc = ptc["repayment"]
        taxes.federal += ptc["repayment"]
    earned = earned_incomes(unit, taxes)
    taxes.earned_income = sum(earned)
    benefits = sum(m.income.dependent_care_benefits for m in unit.members)
    expenses = care_expenses(unit)
    excluded = excluded_dependent_care_benefits(benefits, expenses, earned, status, config.tax.federal.dependent_care)
    facts = ReturnFacts(
        year=unit.members[0].model.year,
        filing_status=status,
        agi=agi,
        tax_before_credits=regular_tax + taxes.amt + taxes.excess_advance_ptc,
        regular_tax=regular_tax,
        tentative_minimum_tax=tentative,
        earned_income=earned,
        # Ages at the end of the tax year (the EIC's 25-64 test, the saver's credit's 18).
        ages=[m.age_in(m.model.year) for m in unit.members],
        investment_income=investment_income(unit, additional_preferential, additional_short_term),
        ctc_children=counts["ctc"],
        other_dependents=counts["other"],
        eitc_children=counts["eitc"],
        care_persons=counts["care"],
        care_expenses=expenses,
        excluded_care_benefits=excluded,
        students=students(unit),
        savers_contributions=savers_contributions(unit),
        payroll_taxes_withheld=sum(taxes.ss_by_worker) + sum(taxes.medicare_by_worker),
        se_tax_deduction=sum(se.deduction for se in taxes.se_by_worker),
        amt_credit_carryforward=carryforward,
        ptc=ptc,
    )
    for line in apply_credits(facts, config):
        taxes.credits += line.total
        taxes.nonrefundable_credits += line.nonrefundable
        taxes.refundable_credits += line.refundable
        taxes.credits_detail[line.name] = taxes.credits_detail.get(line.name, 0.0) + line.total
        if line.nonrefundable:
            taxes.credits_nonrefundable[line.name] = line.nonrefundable
        if line.refundable:
            taxes.credits_refundable[line.name] = line.refundable
        taxes.credit_details[line.name] = dict(line.detail)


# --------------------------------------------------------------------------------------------------
# Year-end adjustments (posted once, before the waterfall)
# --------------------------------------------------------------------------------------------------


def _round_ira_limit(amount: float, *, floor_200: bool = True) -> float:
    """§219(g)(2)(C) / §408A(c)(3)(A): a phased-down limit is rounded up to the next $10, and is at
    least $200 while not fully phased out."""
    if amount <= 0:
        return 0.0
    rounded = -(-amount // 10) * 10
    return max(rounded, 200.0) if floor_200 else rounded


def active_participant(member: "Person") -> bool:
    """Whether ``member`` was an active participant in a workplace plan this year (a job with a 401(k),
    or a self-employed plan)."""
    for job in member.jobs:
        if job.retired:
            continue
        if getattr(job, "retirement_account", None) is not None or getattr(job, "sep_account", None) is not None:
            return True
    return False


def _ira_contributions(member: "Person", kind: str) -> float:
    accounts = member.traditional_iras if kind == "traditional" else member.roth_iras
    return sum(a.contributions_ytd for a in accounts)


def _apply_ira_phaseouts(unit: "TaxUnit") -> None:
    """Traditional IRA deduction (§219(g)) and Roth contribution (§408A(c)(3)) phase-outs."""
    params = unit.config.tax.federal.ira_phaseouts
    if params is None:
        return
    status = unit.filing_status
    deducted = sum(
        -e.amount
        for m in unit.members
        for e in m.income.entries
        if e.income_type == IncomeType.ORDINARY and e.source == "ira_deduction"
    )
    magi = unit.agi() + deducted
    from ..account.traditional_IRA import ira_contribution_limit

    for member in unit.members:
        # The phase-out reduces the member's own limit, the age-50 catch-up included (Pub. 590-A worksheets).
        limit = ira_contribution_limit(member, member.model.year)
        contributed = _ira_contributions(member, "traditional")
        if contributed > 0:
            spouse_covered = any(active_participant(m) for m in unit.members if m is not member)
            if active_participant(member):
                range_ = (
                    params.separate
                    if status == FilingStatus.MARRIED_FILING_SEPARATELY
                    else params.traditional_joint
                    if status.joint_rates
                    else params.traditional_single
                )
            elif spouse_covered and status == FilingStatus.MARRIED_FILING_JOINTLY:
                range_ = params.traditional_spouse_covered
            elif spouse_covered and status == FilingStatus.MARRIED_FILING_SEPARATELY:
                range_ = params.separate
            else:
                range_ = None
            if range_ is not None:
                fraction = range_.fraction_allowed(magi)
                allowed = min(contributed, _round_ira_limit(limit * fraction)) if fraction > 0 else 0.0
                nondeductible = contributed - allowed
                if nondeductible > 0:
                    member.income.add(IncomeType.ORDINARY, nondeductible, source="ira_deduction")
                    _add_nondeductible_basis(member, nondeductible)
        roth = _ira_contributions(member, "roth")
        if roth > 0:
            range_ = (
                params.separate
                if status == FilingStatus.MARRIED_FILING_SEPARATELY
                else params.roth_joint
                if status.joint_rates
                else params.roth_single
            )
            fraction = range_.fraction_allowed(magi)
            allowed = min(roth, _round_ira_limit(limit * fraction)) if fraction > 0 else 0.0
            if roth - allowed > 0.005:
                _return_excess_roth(member, roth - allowed)


def _add_nondeductible_basis(member: "Person", amount: float) -> None:
    """Record nondeductible traditional IRA contributions as Form 8606 basis on the contributed IRAs."""
    remaining = amount
    for ira in member.traditional_iras:
        take = min(remaining, ira.contributions_ytd)
        if take > 0:
            ira.nondeductible_basis = getattr(ira, "nondeductible_basis", 0.0) + take
            remaining -= take


def _return_excess_roth(member: "Person", excess: float) -> None:
    """A Roth contribution over the MAGI-reduced limit is withdrawn before the due date (a corrective
    distribution; its earnings are ignored) and lands back in the bank."""
    from ..ledger import FlowKind

    remaining = excess
    for ira in member.roth_iras:
        take = min(remaining, ira.contributions_ytd, ira.balance)
        if take <= 0:
            continue
        ira.balance -= take
        ira.contributions_ytd -= take
        ira.contribution_basis = max(0.0, ira.contribution_basis - take)
        destination = member.cash_destination
        member.receive_cash(take, post=False)
        member.model.ledger.post(
            take,
            FlowKind.WITHDRAWAL,
            from_account=ira,
            to_account=destination,
            cause="excess Roth IRA contribution returned (MAGI over the limit)",
            agent=member,
        )
        remaining -= take


def _student_loan_deduction(unit: "TaxUnit") -> None:
    """§221: student loan interest paid, at most the cap per return, phased out by MAGI; not allowed on a
    separate return."""
    if unit.filing_status == FilingStatus.MARRIED_FILING_SEPARATELY:
        return
    interest = {m.unique_id: sum(sl.interest_paid_this_year for sl in m.student_loans) for m in unit.members}
    total = sum(interest.values())
    if total <= 0:
        return
    cap = unit.config.debt.student_loan.interest_deduction_limit
    deduction = min(total, cap)
    params = unit.config.tax.federal.student_loan_phaseout
    if params is not None:
        range_ = params.joint if unit.filing_status == FilingStatus.MARRIED_FILING_JOINTLY else params.single
        # Student Loan Interest Deduction Worksheet (Form 1040 instructions): the reduction fraction is
        # rounded to at least three places (three here).
        reduced = round(1.0 - range_.fraction_allowed(unit.agi()), 3)
        deduction -= deduction * reduced
    if deduction <= 0:
        return
    for member in unit.members:
        share = deduction * interest[member.unique_id] / total
        if share > 0:
            member.income.add(IncomeType.ORDINARY, -share, source="student_loan_interest")


def post_year_end_adjustments(unit: "TaxUnit") -> None:
    """Post the year's settlement-time adjustments to the members' ledgers, once, before the waterfall.

    Order follows the forms: half of SE tax (Schedule 1 line 15), taxable dependent care benefits
    (line 1e), the Form 8814 inclusion, the IRA deduction and Roth phase-outs (MAGI before the student
    loan deduction), then the student loan interest deduction (MAGI after the IRA deduction).
    """
    config = unit.config
    base = config.tax.fica.social_security_max_income
    for member in unit.members:
        profit = member.income.self_employment_income
        if profit > 0:
            se = self_employment_tax(profit, min(max(0.0, member.fica_wages), base), config)
            if se.deduction > 0:
                member.income.add(IncomeType.ORDINARY, -se.deduction, source=SE_DEDUCTION_SOURCE)
    benefits = sum(m.income.dependent_care_benefits for m in unit.members)
    if benefits > 0:
        earned = [m.income.wages + m.income.self_employment_income for m in unit.members]
        excluded = excluded_dependent_care_benefits(
            benefits, care_expenses(unit), earned, unit.filing_status, config.tax.federal.dependent_care
        )
        taxable = benefits - excluded
        if taxable > 0:
            # Form 2441 line 26 -> Form 1040 line 1e: wages for income tax (FICA was already withheld
            # only on the excluded part's complement, which the model does not track).
            unit.members[0].income.add(IncomeType.WAGES, taxable, 0.0, source=TAXABLE_CARE_BENEFITS_SOURCE)
    _post_form_8814(unit)
    _apply_ira_phaseouts(unit)
    _student_loan_deduction(unit)


# --------------------------------------------------------------------------------------------------
# After the return is settled
# --------------------------------------------------------------------------------------------------


def record_year_end(unit: "TaxUnit", taxes: "TaxesDue", agi: float) -> None:
    """Carry the year's results forward: the minimum tax credit, charitable carryovers, the AOTC years
    claimed per student and each member's retirement distributions (for later saver's credits)."""
    from .deductions import settle_charitable_carryforwards

    year = unit.members[0].model.year
    head = unit.members[0]
    used = taxes.credits_nonrefundable.get("minimum_tax_credit", 0.0)
    carried = sum(amt_credit_carryforward(m) for m in unit.members)
    for member in unit.members:
        member.__dict__.pop("amt_credit_carryforward", None)
    remaining = max(0.0, carried - used) + taxes.amt_credit_generated
    if remaining > 0:
        head.amt_credit_carryforward = remaining

    charity = taxes.charitable
    if charity is not None:
        settle_charitable_carryforwards(unit.members, agi, year, unit.config, floor_disallowed=charity.floor_cash)
        settle_property_carryforwards(
            unit.members, charity.property_allowed, year, unit.config, floor_disallowed=charity.floor_property
        )
    else:
        settle_charitable_carryforwards(unit.members, agi, year, unit.config)

    education = taxes.credit_details.get("education_credits", {})
    edu = unit.config.tax.federal.credits.education
    if edu is not None and education.get("american_opportunity", 0.0) > 0:
        for child in _children(unit):
            if _is_student(child) and getattr(child, "aotc_years_claimed", 0) < edu.aotc_max_years:
                expenses = getattr(child, "education_expenses_this_year", 0.0) - getattr(
                    child, "education_paid_by_529", 0.0
                )
                if expenses > 0:
                    child.aotc_years_claimed = getattr(child, "aotc_years_claimed", 0) + 1

    for member in unit.members:
        history = _distribution_history(member)
        history[year] = retirement_distributions(member)
        for old in [y for y in history if y < year - 2]:
            del history[old]
