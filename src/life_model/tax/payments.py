# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tax payments during the year: withholding, estimated payments and the underpayment penalty.

* **Withholding** is a payroll policy (``PayrollDeductions(withholding=...)``): ``"w4_default"`` (a Form W-4
  with no entries, its filing status from the employee's return), a :class:`W4`, or a
  :class:`FlatWithholding` (a percent of taxable wages or dollars a month). Federal income tax uses IRS Pub.
  15-T's percentage method for automated payroll (Worksheet 1A) on each monthly paycheck's taxable wages
  (gross less pre-tax deferrals and cafeteria-plan items), with bonuses and RSU vests withheld as
  supplemental wages (Pub. 15 section 7: 22%, 37% over $1,000,000 of the year's supplemental wages). Social
  Security (6.2% up to the wage base) and Medicare (1.45%, plus 0.9% on the employer's wages over
  $200,000) are withheld per employer, so two employers can over-withhold Social Security (credited on
  Schedule 3 line 11). State income tax is withheld where the state pack has a rate or brackets: the pack's
  tax on the paycheck's taxable wages annualized (as if the only income), a twelfth a month; supplemental
  wages at the pack's flat rate, or its marginal rate at the employee's annualized regular wages. That is an
  approximation of each state's own withholding formula (most annualize the same way).
* **Estimated payments** (:class:`EstimatedPayments`) are federal: fixed quarterly amounts, or a policy
  (``"safe_harbor"``: 100% of last year's tax, 110% when last year's AGI was over $150,000; ``"current_year"``:
  90% of this year's projected tax), less the withholding expected, paid on the Form 1040-ES due dates (April,
  June, September and January of the next year; the model pays in that month).
* **Settlement.** December computes the year's return; a unit that withholds or pays estimates then
  carries the balance due (or the refund) to April of the next year, a liability (or receivable) on the
  balance sheet in between. The underpayment penalty is Form 2210's regular method (:func:`underpayment_penalty`).
"""

import datetime
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..config.financial_config import FinancialConfig
    from .federal import FilingStatus

#: Months the estimated tax installments are paid in (Form 1040-ES due dates April 15, June 15, September 15
#: and January 15 of the next year); the January payment belongs to the previous tax year.
ESTIMATED_TAX_MONTHS = (4, 6, 9, 1)
#: Each installment's due date as ``(year offset, month, day)``.
DUE_DATES = ((0, 4, 15), (0, 6, 15), (0, 9, 15), (1, 1, 15))
#: The month the balance due is paid / the refund arrives (the return's April 15 due date).
SETTLEMENT_MONTH = 4

ESTIMATED_POLICIES = ("safe_harbor", "current_year")


# --------------------------------------------------------------------------------------------------
# Withholding policies
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class W4:
    """A 2020-or-later Form W-4 (IRS Pub. 15-T Worksheet 1A's inputs).

    ``filing_status``: ``"single"`` (also married filing separately), ``"married_filing_jointly"`` or
    ``"head_of_household"``; None takes the employee's return status each year. ``multiple_jobs`` is the
    Step 2 checkbox. ``dependents_annual`` is Step 3, ``other_income_annual`` 4(a), ``deductions_annual``
    4(b), ``extra_monthly`` 4(c) (dollars a paycheck; the model pays monthly).
    """

    filing_status: str | None = None
    multiple_jobs: bool = False
    dependents_annual: float = 0.0
    other_income_annual: float = 0.0
    deductions_annual: float = 0.0
    extra_monthly: float = 0.0

    def __post_init__(self):
        if self.filing_status not in (None, "single", "married_filing_jointly", "head_of_household"):
            raise ValueError(
                f"W4.filing_status must be single, married_filing_jointly or head_of_household, got {self.filing_status!r}"
            )
        for name in ("dependents_annual", "other_income_annual", "deductions_annual", "extra_monthly"):
            if getattr(self, name) < 0:
                raise ValueError(f"W4.{name} must be non-negative")


@dataclass(frozen=True)
class FlatWithholding:
    """Withhold ``pct`` percent of each paycheck's taxable wages, or ``amount_monthly`` dollars a month."""

    pct: float | None = None
    amount_monthly: float | None = None

    def __post_init__(self):
        if (self.pct is None) == (self.amount_monthly is None):
            raise ValueError("FlatWithholding: give exactly one of pct or amount_monthly")
        if (self.pct or 0) < 0 or (self.amount_monthly or 0) < 0 or (self.pct or 0) > 100:
            raise ValueError("FlatWithholding: pct must be 0-100 and amount_monthly non-negative")


WithholdingPolicy = W4 | FlatWithholding


def resolve_withholding(value: Any) -> "WithholdingPolicy | None":
    """Normalize a withholding setting: None (no withholding: the year-end lump), ``"w4_default"``, a
    :class:`W4` / :class:`FlatWithholding`, or a mapping ``{"w4": {...}}``, ``{"pct": 15}`` or
    ``{"amount_monthly": 900}``."""
    if value is None or isinstance(value, (W4, FlatWithholding)):
        return value
    if value == "w4_default":
        return W4()
    if isinstance(value, dict):
        if "w4" in value:
            return W4(**(value["w4"] or {}))
        return FlatWithholding(**value)
    raise ValueError(
        f"withholding must be 'w4_default', a W4, a FlatWithholding or a mapping (w4 / pct / amount_monthly); got {value!r}"
    )


def w4_status(filing_status: "FilingStatus") -> str:
    """The W-4 status matching a return's filing status."""
    name = filing_status.name
    if name in ("MARRIED_FILING_JOINTLY", "QUALIFYING_SURVIVING_SPOUSE"):
        return "married_filing_jointly"
    if name == "HEAD_OF_HOUSEHOLD":
        return "head_of_household"
    return "single"


_W4_TO_FILING = {"married_filing_jointly": 2, "head_of_household": 3, "single": 1}


def derived_withholding_table(config: "FinancialConfig", status: str, *, checkbox: bool) -> list[list[float]]:
    """The Pub. 15-T annual percentage method table built from the year's brackets and standard deduction
    (how the published tables are made: the standard schedule is the rate schedule shifted up by the
    standard deduction less Step 1g's amount; the Step 2 checkbox schedule is the rate schedule halved,
    shifted by half the standard deduction). Used for projected years; it reproduces the published 2024-2026
    tables (thresholds of the checkbox schedules rounded to the dollar)."""
    from .federal import FilingStatus

    filing = FilingStatus(_W4_TO_FILING[status])
    brackets = config.get_federal_tax_brackets(filing)
    standard = config.get_federal_standard_deduction(filing)
    params = config.tax.federal.withholding
    step1g = params.step1g_joint if status == "married_filing_jointly" else params.step1g_other
    if checkbox:
        offset, scale = standard / 2, 0.5
    else:
        offset, scale = standard - step1g, 1.0
    rows: list[list[float]] = [[0.0, 0.0, 0.0]]
    previous_upper = 0.0
    tax = 0.0
    for _low, upper, rate in brackets:
        start = previous_upper * scale
        over = round(offset + start) if checkbox else offset + start
        rows.append([float(over), round(tax, 2), float(rate)])
        if upper == float("inf"):
            break
        tax += (upper * scale - start) * rate / 100
        previous_upper = upper
    return rows


def withholding_table(config: "FinancialConfig", status: str, *, checkbox: bool) -> list[list[float]]:
    params = config.tax.federal.withholding
    table = params.checkbox if checkbox else params.standard
    if table is not None:
        return getattr(table, status)
    return derived_withholding_table(config, status, checkbox=checkbox)


def percentage_method_annual(adjusted_annual_wages: float, table: list[list[float]]) -> float:
    """Worksheet 1A step 2: the tentative annual withholding from the table row the amount falls in."""
    row = table[0]
    for candidate in table:
        if adjusted_annual_wages >= candidate[0]:
            row = candidate
        else:
            break
    over, base, rate = row
    return base + (adjusted_annual_wages - over) * rate / 100


def federal_withholding(
    taxable_wages: float, policy: WithholdingPolicy, status: str, config: "FinancialConfig", periods: int = 12
) -> float:
    """Federal income tax to withhold from one paycheck of ``taxable_wages`` (regular wages, after pre-tax
    deferrals) under ``policy``: IRS Pub. 15-T Worksheet 1A for a :class:`W4` (``status``: the W-4 filing
    status), else the flat amount."""
    if isinstance(policy, FlatWithholding):
        if policy.amount_monthly is not None:
            return policy.amount_monthly * 12 / periods
        return max(0.0, taxable_wages) * (policy.pct or 0.0) / 100
    params = config.tax.federal.withholding
    if params is None:
        return 0.0
    status = policy.filing_status or status
    annual = max(0.0, taxable_wages) * periods + policy.other_income_annual  # 1c, 1e
    step1g = 0.0
    if not policy.multiple_jobs:
        step1g = params.step1g_joint if status == "married_filing_jointly" else params.step1g_other
    adjusted = max(0.0, annual - (policy.deductions_annual + step1g))  # 1h, 1i
    tentative = percentage_method_annual(adjusted, withholding_table(config, status, checkbox=policy.multiple_jobs))
    per_period = tentative / periods  # 2h
    per_period = max(0.0, per_period - policy.dependents_annual / periods)  # 3a-3c
    return per_period + policy.extra_monthly * 12 / periods  # 4a-4b


def supplemental_withholding(amount: float, supplemental_ytd: float, config: "FinancialConfig") -> float:
    """Federal withholding on ``amount`` of supplemental wages (a bonus, an RSU vest) when the employee has
    already been paid ``supplemental_ytd`` of them this year (Pub. 15 section 7: the optional flat rate, and
    the mandatory rate on the year's supplemental wages over $1,000,000)."""
    params = config.tax.federal.withholding
    if params is None or amount <= 0:
        return 0.0
    threshold = params.supplemental_threshold
    below = max(0.0, min(amount, threshold - supplemental_ytd))
    return below * params.supplemental_rate / 100 + (amount - below) * params.supplemental_over_1m_rate / 100


def state_withholding_monthly(
    taxable_wages: float,
    supplemental: float,
    filing_status: "FilingStatus",
    state: str | None,
    config: "FinancialConfig",
) -> float:
    """State income tax withheld from a paycheck (see the module docstring for the approximation): the pack's
    tax on the regular taxable wages annualized, a twelfth, plus the supplemental wages at the pack's flat rate
    or its marginal rate at the annualized regular wages. ``DEFAULT`` and no-tax states withhold nothing."""
    from ..config.models import DEFAULT_STATE_KEY
    from .income import IncomeType
    from .state import _bracket_rows, state_income_tax_detail

    state_config = config.tax.state
    code = state_config.resolve_state_code(state)
    if code == DEFAULT_STATE_KEY:
        return 0.0
    pack = state_config.get_pack(code)
    if (pack.flat_rate or 0.0) == 0.0 and pack.brackets is None:
        return 0.0
    annual = max(0.0, taxable_wages) * 12
    totals = {income_type: 0.0 for income_type in IncomeType}
    totals[IncomeType.WAGES] = annual
    detail = state_income_tax_detail(totals, filing_status, code, annual, config)
    regular = detail.tax / 12
    if supplemental <= 0:
        return regular
    if pack.brackets is None:
        rate = pack.flat_rate or 0.0
    else:
        rate = 0.0
        for low, high, row_rate, *_ in _bracket_rows(pack, filing_status):
            rate = row_rate
            if detail.taxable_income < high:
                break
    return regular + supplemental * rate / 100


# --------------------------------------------------------------------------------------------------
# Estimated payments
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EstimatedPayments:
    """Federal estimated tax payments (Form 1040-ES).

    Give ``quarterly`` (four dollar amounts for the April, June, September and January installments, or one
    amount for each) or ``policy``: ``"safe_harbor"`` pays a quarter of last year's tax (100%, or 110% when
    last year's AGI was over $150,000; $75,000 married filing separately) or ``"current_year"`` a quarter of
    90% of this year's tax projected from the year so far, each less the withholding expected for the year.
    ``prior_year_tax`` / ``prior_year_agi`` describe the year before the first simulated year (Form 2210's
    prior-year safe harbor; without them the first year's penalty assumes the prior-year safe harbor was met).
    """

    quarterly: "tuple[float, float, float, float] | float | None" = None
    policy: str | None = None
    prior_year_tax: float | None = None
    prior_year_agi: float | None = None

    def __post_init__(self):
        if (self.quarterly is None) == (self.policy is None):
            raise ValueError("EstimatedPayments: give exactly one of quarterly or policy")
        if self.policy is not None and self.policy not in ESTIMATED_POLICIES:
            raise ValueError(f"EstimatedPayments.policy must be one of {ESTIMATED_POLICIES}, got {self.policy!r}")
        if self.quarterly is not None:
            amounts = (self.quarterly,) * 4 if isinstance(self.quarterly, (int, float)) else tuple(self.quarterly)
            if len(amounts) != 4 or any(a < 0 for a in amounts):
                raise ValueError("EstimatedPayments.quarterly must be four non-negative amounts (or one)")
            object.__setattr__(self, "quarterly", amounts)


def installment_index(month: int) -> int | None:
    """The installment (0-3) due in ``month``, or None."""
    return ESTIMATED_TAX_MONTHS.index(month) if month in ESTIMATED_TAX_MONTHS else None


# --------------------------------------------------------------------------------------------------
# The year's payments record
# --------------------------------------------------------------------------------------------------


@dataclass
class TaxPayments:
    """A person's payments toward one tax year's taxes."""

    federal_withheld: float = 0.0
    #: Social Security / Medicare withheld (Medicare includes the Additional Medicare Tax withheld).
    social_security_withheld: float = 0.0
    medicare_withheld: float = 0.0
    additional_medicare_withheld: float = 0.0
    state_withheld: float = 0.0
    #: Federal withholding by employer (W-2 box 2), and the state withholding by employer (box 17).
    federal_by_employer: dict[str, float] = field(default_factory=dict)
    state_by_employer: dict[str, float] = field(default_factory=dict)
    ss_by_employer: dict[str, float] = field(default_factory=dict)
    medicare_by_employer: dict[str, float] = field(default_factory=dict)
    #: Estimated payments for the year: ``(installment 0-3, amount)``.
    estimated: list[tuple[int, float]] = field(default_factory=list)

    @property
    def estimated_total(self) -> float:
        return sum(amount for _, amount in self.estimated)

    @property
    def withheld_total(self) -> float:
        return self.federal_withheld + self.social_security_withheld + self.medicare_withheld + self.state_withheld

    def add_withholding(self, employer: str, *, federal=0.0, ss=0.0, medicare=0.0, additional=0.0, state=0.0) -> None:
        self.federal_withheld += federal
        self.social_security_withheld += ss
        self.medicare_withheld += medicare + additional
        self.additional_medicare_withheld += additional
        self.state_withheld += state
        for book, amount in (
            (self.federal_by_employer, federal),
            (self.state_by_employer, state),
            (self.ss_by_employer, ss),
            (self.medicare_by_employer, medicare + additional),
        ):
            if amount:
                book[employer] = book.get(employer, 0.0) + amount


def payments_of(person, year: int) -> TaxPayments:
    """``person``'s payments record for tax ``year`` (an empty one when nothing was paid; not stored)."""
    return getattr(person, "tax_payments", {}).get(year) or TaxPayments()


def payments_for(person, year: int) -> TaxPayments:
    """``person``'s payments record for tax ``year`` (created on first use)."""
    record = person.tax_payments.get(year)
    if record is None:
        record = person.tax_payments[year] = TaxPayments()
    return record


# --------------------------------------------------------------------------------------------------
# Form 2210 (regular method)
# --------------------------------------------------------------------------------------------------


def _day_rate(day: datetime.date, rates) -> float:
    """The daily rate on ``day`` by Form 2210's penalty worksheet rate periods (April 16-June 30, July-September,
    October-December, January 1-April 15): the period's first quarter's rate, so April 1-15 keeps the first
    quarter's (the printed 2024 and 2025 worksheets), over the days of that calendar year."""
    quarter = 1 if day.month == 4 and day.day <= 15 else (day.month - 1) // 3 + 1
    days_in_year = 366 if (day.year % 4 == 0 and (day.year % 100 != 0 or day.year % 400 == 0)) else 365
    return rates.rate_for(day.year, quarter) / 100 / days_in_year


def _interest(amount: float, start: datetime.date, end: datetime.date, rates) -> float:
    """Simple interest on ``amount`` for each day from ``start`` (exclusive of the due date itself, as Form
    2210 counts days after it) to ``end`` (inclusive)."""
    total = 0.0
    day = start + datetime.timedelta(days=1)
    while day <= end:
        total += amount * _day_rate(day, rates)
        day += datetime.timedelta(days=1)
    return total


@dataclass(frozen=True)
class Form2210:
    """Form 2210's figures for one return."""

    current_year_tax: float = 0.0
    withholding: float = 0.0
    required_annual_payment: float = 0.0
    underpayments: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    penalty: float = 0.0


def underpayment_penalty(
    year: int,
    current_year_tax: float,
    withholding: float,
    estimated: "list[tuple[int, float]]",
    *,
    prior_year_tax: float | None,
    prior_year_agi: float | None,
    separate: bool,
    config: "FinancialConfig",
) -> Form2210:
    """The underpayment of estimated tax penalty (IRC §6654; Form 2210, regular method).

    ``current_year_tax``: Form 2210 line 4 (tax after nonrefundable credits plus self-employment tax, the
    Additional Medicare Tax, NIIT and additional taxes on distributions, less refundable credits);
    ``withholding``: line 6 (withholding, the Additional Medicare Tax withheld and excess Social Security),
    deemed paid a quarter on each due date; ``estimated``: ``(installment, amount)`` paid on its due date.
    No penalty when line 4 or line 7 is under $1,000, when last year's tax was zero, or (a modeling choice)
    when last year's tax is unknown (the prior-year safe harbor is assumed met). Each underpayment accrues
    interest at the quarter's underpayment rate from its due date until a later installment's excess pays it
    (oldest first) or April 15 of the next year.
    """
    rules = config.tax.federal.estimated_tax
    if current_year_tax < rules.minimum_balance_due or current_year_tax - withholding < rules.minimum_balance_due:
        return Form2210(current_year_tax, withholding)
    if prior_year_tax is None or prior_year_tax <= 0:
        return Form2210(current_year_tax, withholding)
    threshold = rules.high_income_agi / (2 if separate else 1)
    prior_pct = (
        rules.required_prior_high_income_pct if (prior_year_agi or 0.0) > threshold else rules.required_prior_pct
    )
    required = min(current_year_tax * rules.required_current_pct / 100, prior_year_tax * prior_pct / 100)
    if required <= withholding:
        return Form2210(current_year_tax, withholding, required)
    dates = [datetime.date(year + dy, m, d) for dy, m, d in DUE_DATES]
    end = datetime.date(year + 1, 4, 15)
    paid_by_date = [withholding / 4 for _ in range(4)]
    for index, amount in estimated:
        paid_by_date[index] += amount
    queue: list[list[Any]] = []  # [amount, start date]
    penalty = 0.0
    carry = 0.0
    underpayments = []
    for i, due in enumerate(dates):
        available = paid_by_date[i] + carry
        carry = 0.0
        # Payments first cover earlier underpayments, oldest first (Form 2210 lines 14-16).
        while queue and available > 0:
            piece = queue[0]
            take = min(piece[0], available)
            penalty += _interest(take, piece[1], due, config.tax.federal.estimated_tax)
            piece[0] -= take
            available -= take
            if piece[0] <= 1e-9:
                queue.pop(0)
        installment = required / 4
        if available >= installment:
            carry = available - installment
            underpayments.append(0.0)
        else:
            short = installment - available
            queue.append([short, due])
            underpayments.append(short)
    for amount, start in queue:
        penalty += _interest(amount, start, end, config.tax.federal.estimated_tax)
    return Form2210(current_year_tax, withholding, required, tuple(underpayments), round(penalty, 2))
