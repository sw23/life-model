# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The per-year tax return record (one per tax unit per year).

A :class:`TaxReturn` is built inside ``TaxUnit.settle_year`` from the final
:class:`~life_model.tax.tax.TaxesDue` the settlement paid and the members' income ledgers at that
moment, so it shows exactly the numbers the year was settled with; nothing on it is recomputed. Its
lines follow Form 1040's structure:

* income lines → ``total_income``; ``total_income - total_adjustments == agi`` (AGI is floored at 0);
* ``agi - deduction == taxable_income`` (floored at 0), where ``deduction`` is the itemized deductions
  (after the §68 limit) or the standard deduction (with §63(f)) plus the non-itemizer charitable
  deduction, plus the senior deduction and the QBI deduction;
* ``ordinary_tax + preferential_tax + kiddie_tax + niit + amt + excess_advance_ptc_repayment - total_credits +
  total_penalties == federal_tax``;
* (Plan 31 D3) ``amount_owed - overpayment == federal_tax + refundable_credits + self_employment_tax +
  additional_medicare_tax - total_payments + estimated_tax_penalty`` (Form 1040 lines 24-38);
* ``federal_tax + state_tax + social_security_tax + medicare_tax + self_employment_tax == total_tax``
  (``TaxesDue.total``).

Each credit is split into its nonrefundable and refundable parts (``credits_nonrefundable`` /
``credits_refundable``), so reconciliation can put it on its own Form 1040 / Schedule 3 line.

Records are stored on ``model.tax_returns[(year, unit_id)]`` (``unit_id`` is the head's
``unique_id``) and on each member's ``person.tax_returns[year]``.

All money is nominal dollars of the return's year; rates are percents (``22.0`` is 22%).
"""

from dataclasses import asdict, dataclass, field, fields, replace
from typing import TYPE_CHECKING, Any

from .income import IncomeType

if TYPE_CHECKING:
    from ..people.tax_unit import TaxUnit
    from .tax import TaxesDue

#: Ordinary-income entry sources that are above-the-line adjustments (Schedule 1, Part II).
ADJUSTMENT_SOURCES = frozenset(
    {
        "adjustment",
        "ira_deduction",
        "hsa_deduction",
        "student_loan_interest",
        "se_tax_deduction",
        "self_employed_plan",
        # Plan 27 D2: a CD's early withdrawal penalty (IRC §62(a)(9), Schedule 1 line 18).
        "early_withdrawal_penalty",
    }
)
#: Capital-gain entry sources that are netting adjustments, not realized gains.
_NETTING_SOURCES = frozenset({"capital_loss_netting", "capital_loss_carryforward"})


@dataclass(frozen=True)
class FicaLine:
    """One member's payroll taxes on the return."""

    person_id: int
    name: str
    wages: float
    social_security: float
    medicare: float
    #: Schedule SE: net profit (line 3), net earnings (line 6) and self-employment tax (line 12); not part
    #: of the FICA columns above.
    self_employment_income: float = 0.0
    self_employment_tax: float = 0.0
    self_employment_net_earnings: float = 0.0


@dataclass(frozen=True)
class StateReturn:
    """The state lines of a return (see :class:`~life_model.tax.state.StateTaxDetail`)."""

    state: str
    method: str
    income: float
    subtractions: float
    deduction: float
    taxable_income: float
    flat_rate: float | None
    brackets: tuple[tuple[float, float, float, float, float], ...]
    tax: float
    #: Plan 31: exemptions (in ``deduction``), credits (out of ``tax``) and a part-year return's states.
    exemptions: float = 0.0
    credits: float = 0.0
    parts: "tuple[StateReturn, ...]" = ()

    @classmethod
    def from_detail(cls, detail) -> "StateReturn":
        return cls(
            state=detail.state,
            method=detail.method,
            income=detail.income,
            subtractions=detail.subtractions,
            deduction=detail.deduction,
            taxable_income=detail.taxable_income,
            flat_rate=detail.flat_rate,
            brackets=tuple(detail.brackets),
            tax=detail.tax,
            exemptions=getattr(detail, "exemptions", 0.0),
            credits=getattr(detail, "credits", 0.0),
            parts=tuple(cls.from_detail(part) for part in getattr(detail, "parts", ())),
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["brackets"] = [list(row) for row in self.brackets]
        data["parts"] = [part.to_dict() for part in self.parts]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "StateReturn":
        data = dict(data)
        data["brackets"] = tuple(tuple(row) for row in data["brackets"])
        data["parts"] = tuple(cls.from_dict(part) for part in data.get("parts", ()))
        return cls(**data)

    def scaled(self, divisor: float) -> "StateReturn":
        def money(value: float) -> float:
            return value / divisor

        return replace(
            self,
            income=money(self.income),
            subtractions=money(self.subtractions),
            deduction=money(self.deduction),
            taxable_income=money(self.taxable_income),
            brackets=tuple((money(lo), money(hi), r, money(a), money(t)) for lo, hi, r, a, t in self.brackets),
            tax=money(self.tax),
            exemptions=money(self.exemptions),
            credits=money(self.credits),
            parts=tuple(part.scaled(divisor) for part in self.parts),
        )


@dataclass(frozen=True)
class TaxReturn:
    """One tax unit's federal (and state) return for one simulated year."""

    year: int
    unit_id: int
    member_ids: tuple[int, ...]
    member_names: tuple[str, ...]
    filing_status: str
    state: str
    # Income (Form 1040 lines 1-8)
    wages: float
    taxable_interest: float
    tax_exempt_interest: float
    ordinary_dividends: float
    qualified_dividends: float
    ira_distributions_gross: float
    ira_distributions_taxable: float
    pensions_and_annuities: float
    social_security_gross: float
    social_security_taxable: float
    short_term_gains_realized: float
    long_term_gains_realized: float
    capital_loss_carryforward_used: float
    short_term_gains: float
    long_term_gains: float
    capital_loss_deduction: float
    capital_gain_or_loss: float
    other_income: float
    other_income_by_source: dict[str, float]
    total_income: float
    # Adjustments → AGI
    adjustments: dict[str, float]
    total_adjustments: float
    agi: float
    # Deductions → taxable income
    standard_deduction: float
    itemized_deductions: float
    itemized_components: dict[str, float]
    deduction_taken: str
    senior_deduction: float
    deduction: float
    taxable_income: float
    taxable_ordinary_income: float
    taxable_preferential_income: float
    # Tax
    ordinary_tax: float
    ordinary_brackets: tuple[tuple[float, float, float, float, float], ...]
    preferential_tax: float
    niit: float
    amt: float
    credits: dict[str, float]
    nonrefundable_credits: float
    refundable_credits: float
    total_credits: float
    penalties: dict[str, float]
    total_penalties: float
    federal_tax: float
    fica: tuple[FicaLine, ...]
    social_security_tax: float
    medicare_tax: float
    additional_medicare_tax: float
    state_return: StateReturn | None
    state_tax: float
    total_tax: float
    marginal_rate: float
    effective_rate: float
    # Plan 31 (defaults let records saved before it load)
    business_income: float = 0.0
    taxable_dependent_care_benefits: float = 0.0
    additional_standard_deduction: float = 0.0
    charitable_deduction_non_itemizer: float = 0.0
    itemized_limitation: float = 0.0
    qualified_business_income: float = 0.0
    qbi_deduction: float = 0.0
    kiddie_tax: float = 0.0
    alternative_minimum_taxable_income: float = 0.0
    tentative_minimum_tax: float = 0.0
    amt_credit_generated: float = 0.0
    credits_nonrefundable: dict[str, float] = field(default_factory=dict)
    credits_refundable: dict[str, float] = field(default_factory=dict)
    earned_income: float = 0.0
    self_employment_tax: float = 0.0
    self_employment_tax_deduction: float = 0.0
    additional_medicare_tax_self_employment: float = 0.0
    # Plan 31 tasks 6-7: payments (Form 1040 lines 25-38) and the premium tax credit (Form 8962)
    federal_income_tax_withheld: float = 0.0
    additional_medicare_tax_withheld: float = 0.0
    social_security_withheld: float = 0.0
    medicare_withheld: float = 0.0
    state_withheld: float = 0.0
    excess_social_security_withheld: float = 0.0
    estimated_tax_payments: float = 0.0
    estimated_tax_penalty: float = 0.0
    required_annual_payment: float = 0.0
    tax_for_estimates: float = 0.0
    total_payments: float = 0.0
    amount_owed: float = 0.0
    overpayment: float = 0.0
    state_balance_due: float = 0.0
    settled_in_april: bool = False
    advance_premium_tax_credit: float = 0.0
    excess_advance_ptc_repayment: float = 0.0
    premium_tax_credit_allowed: float = 0.0
    ptc_fpl_percent: float = 0.0
    ptc_applicable_figure: float = 0.0
    ptc_contribution: float = 0.0
    ptc_household_income: float = 0.0
    ptc_enrollment_premiums: float = 0.0
    ptc_slcsp_premiums: float = 0.0
    ptc_repayment_limit: float = -1.0

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready dict (nested records become dicts/lists)."""
        data = asdict(self)
        data["ordinary_brackets"] = [list(row) for row in self.ordinary_brackets]
        data["fica"] = [asdict(line) for line in self.fica]
        if self.state_return is not None:
            data["state_return"] = self.state_return.to_dict()
        data["member_ids"] = list(self.member_ids)
        data["member_names"] = list(self.member_names)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaxReturn":
        """Rebuild a record from :meth:`to_dict` output."""
        data = dict(data)
        data["member_ids"] = tuple(data["member_ids"])
        data["member_names"] = tuple(data["member_names"])
        data["ordinary_brackets"] = tuple(tuple(row) for row in data["ordinary_brackets"])
        data["fica"] = tuple(FicaLine(**line) for line in data["fica"])
        state = data.get("state_return")
        if state is not None:
            data["state_return"] = StateReturn.from_dict(state)
        return cls(**data)

    def summary_row(self) -> dict[str, Any]:
        """The scalar lines as one flat row (for tables and exports)."""
        row = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, (int, float, str)) or value is None:
                row[f.name] = value
            elif isinstance(value, tuple) and f.name in ("member_ids", "member_names"):
                row[f.name] = ", ".join(str(v) for v in value)
        return row

    def scaled(self, divisor: float) -> "TaxReturn":
        """A copy with every money amount divided by ``divisor`` (e.g. a price deflator); rates and
        identifiers are unchanged."""

        def money(value: float) -> float:
            return value / divisor

        changes: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name in _NOT_MONEY:
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                changes[f.name] = money(value)
            elif isinstance(value, dict):
                changes[f.name] = {k: money(v) for k, v in value.items()}
        changes["ordinary_brackets"] = tuple(
            (money(lo), money(hi), rate, money(amount), money(tax))
            for lo, hi, rate, amount, tax in self.ordinary_brackets
        )
        changes["fica"] = tuple(
            replace(
                line,
                wages=money(line.wages),
                social_security=money(line.social_security),
                medicare=money(line.medicare),
                self_employment_income=money(line.self_employment_income),
                self_employment_tax=money(line.self_employment_tax),
                self_employment_net_earnings=money(line.self_employment_net_earnings),
            )
            for line in self.fica
        )
        if self.state_return is not None:
            changes["state_return"] = self.state_return.scaled(divisor)
        return replace(self, **changes)


#: One-line description of every :class:`TaxReturn` field (rendered into docs/outputs.md).
FIELD_DOCS: dict[str, str] = {
    "year": "Tax year.",
    "unit_id": "The unit head's agent ``unique_id``.",
    "member_ids": "Agent ids of the members filing the return (head first).",
    "member_names": "Names of the members filing the return.",
    "filing_status": "Filing status name (``SINGLE``, ``MARRIED_FILING_JOINTLY``, ...).",
    "state": "State the unit files in (the head's).",
    "wages": "W-2 wages (salary and RSU vests, net of pre-tax 401k deferrals and excluded dependent care benefits), "
    "plus taxable dependent care benefits (line 1e).",
    "taxable_interest": "Taxable interest (bank, corporate and Treasury interest).",
    "tax_exempt_interest": "Tax-exempt (municipal) interest; not in total income.",
    "ordinary_dividends": "Ordinary dividends (the model's dividends are all qualified).",
    "qualified_dividends": "Qualified dividends (taxed on the preferential schedule).",
    "ira_distributions_gross": "IRA / 401k / inherited-account distributions, gross (qualified charitable "
    "distributions included).",
    "ira_distributions_taxable": "Taxable part of those distributions (all but qualified charitable distributions).",
    "pensions_and_annuities": "Taxable pension income and the taxable part of annuity payments.",
    "social_security_gross": "Social Security benefits received.",
    "social_security_taxable": "Taxable part of the benefits (IRC §86).",
    "short_term_gains_realized": "Short-term gains realized before loss netting.",
    "long_term_gains_realized": "Long-term gains realized before loss netting (incl. home sales).",
    "capital_loss_carryforward_used": "Prior-year capital-loss carryforward absorbed this year.",
    "short_term_gains": "Net short-term gain taxed (after netting).",
    "long_term_gains": "Net long-term gain taxed (after netting).",
    "capital_loss_deduction": "Net capital loss deducted against ordinary income (up to $3,000).",
    "capital_gain_or_loss": "Line 7: net gain, or the deductible loss as a negative number.",
    "other_income": "Other income (non-medical HSA draws, 529 earnings, forgiven debt, ...).",
    "other_income_by_source": "``other_income`` by source.",
    "total_income": "Line 9: sum of the income lines above (excluding tax-exempt interest).",
    "adjustments": "Above-the-line adjustments by source (IRA, HSA, student-loan interest, half of SE tax, "
    "self-employed plan).",
    "total_adjustments": "Sum of ``adjustments``.",
    "agi": "Adjusted gross income: ``max(total_income - total_adjustments, 0)``.",
    "standard_deduction": "Standard deduction for the filing status plus the §63(f) amount for each member 65+ "
    "(0 for MFS when the spouse itemizes).",
    "itemized_deductions": "Itemized deductions (after the 2026+ §68 limit) compared against the standard deduction.",
    "itemized_components": "Itemized deductions by component before the §68 limit (mortgage interest, SALT after the "
    "cap, medical, charity in cash and charity_noncash, each after the 2026+ 0.5% floor).",
    "deduction_taken": "``standard`` or ``itemized``.",
    "senior_deduction": "OBBBA senior deduction (added on top of either deduction).",
    "deduction": "Total deduction subtracted from AGI (lines 12e-14: standard or itemized, the non-itemizer charitable "
    "deduction, the senior deduction and the QBI deduction).",
    "taxable_income": "``max(agi - deduction, 0)``.",
    "taxable_ordinary_income": "Part of taxable income taxed on the ordinary brackets.",
    "taxable_preferential_income": "Part of taxable income taxed on the capital-gains schedule.",
    "ordinary_tax": "Tax on the ordinary brackets.",
    "ordinary_brackets": "Bracket slices ``(lower, upper, rate_percent, amount, tax)``; their taxes sum to ``ordinary_tax``.",
    "preferential_tax": "Tax on qualified dividends and long-term gains.",
    "niit": "Net investment income tax (IRC §1411).",
    "amt": "Alternative minimum tax (Form 6251 line 11).",
    "credits": "Credits by name (``child_tax_credit``, ``earned_income_credit``, ``dependent_care_credit``, "
    "``education_credits``, ``savers_credit``, ``minimum_tax_credit``).",
    "nonrefundable_credits": "Credits limited to the income tax.",
    "refundable_credits": "Credits paid even beyond the income tax.",
    "total_credits": "Sum of ``credits``.",
    "penalties": "Additional taxes by source (``early_withdrawal``, ``hsa_non_medical``, ``roth_ira_earnings``, ...).",
    "total_penalties": "Sum of ``penalties``.",
    "federal_tax": "Federal income tax: ordinary + preferential + Form 8814 tax + NIIT + AMT - credits + penalties "
    "(negative = refund).",
    "fica": "Payroll taxes per member (and each member's Schedule SE profit and tax).",
    "social_security_tax": "Social Security tax (all members).",
    "medicare_tax": "Medicare tax including the additional Medicare tax (all members).",
    "additional_medicare_tax": "Additional Medicare tax on combined wages over the threshold.",
    "state_return": "State return lines.",
    "state_tax": "State income tax.",
    "total_tax": "Everything the unit paid in tax this year: federal + state + payroll + self-employment tax.",
    "marginal_rate": "Ordinary-bracket rate (percent) of the last taxable ordinary dollar.",
    "effective_rate": "``federal_tax / agi`` as a percent (0 when AGI is 0).",
    "business_income": "Schedule C net profit (Schedule 1 line 3).",
    "taxable_dependent_care_benefits": "Dependent care benefits over the Form 2441 exclusion (line 1e; in ``wages``).",
    "additional_standard_deduction": "The §63(f) part of ``standard_deduction`` (members 65+).",
    "charitable_deduction_non_itemizer": "Non-itemizer cash charitable deduction (2026+, line 12f).",
    "itemized_limitation": "§68 reduction of itemized deductions (2026+, 2/37 rule).",
    "qualified_business_income": "Qualified business income (profit less half of SE tax and the self-employed plan).",
    "qbi_deduction": "Qualified business income deduction (Form 8995).",
    "kiddie_tax": "Form 8814 tax on a child's interest and dividends (part of line 16).",
    "alternative_minimum_taxable_income": "Form 6251 line 4.",
    "tentative_minimum_tax": "Form 6251 line 9.",
    "amt_credit_generated": "Minimum tax credit this year's AMT creates for later years (Form 8801).",
    "credits_nonrefundable": "The nonrefundable part of each credit.",
    "credits_refundable": "The refundable part of each credit.",
    "earned_income": "Earned income for the earned income, additional child and dependent care credits.",
    "self_employment_tax": "Self-employment tax (Schedule SE line 12, all members).",
    "self_employment_tax_deduction": "Deductible half of self-employment tax (Schedule 1 line 15).",
    "additional_medicare_tax_self_employment": "The part of ``additional_medicare_tax`` on self-employment income "
    "(Form 8959 Part II; in ``medicare_tax``, on no member's FICA line).",
    "federal_income_tax_withheld": "Federal income tax withheld (W-2 box 2; 1040 line 25a).",
    "additional_medicare_tax_withheld": "Additional Medicare Tax withheld (Form 8959 line 24; 1040 line 25c).",
    "social_security_withheld": "Social Security tax withheld (all employers; W-2 box 4).",
    "medicare_withheld": "Medicare tax withheld, with the Additional Medicare Tax (W-2 box 6).",
    "state_withheld": "State income tax withheld (W-2 box 17).",
    "excess_social_security_withheld": "Social Security withheld over the wage base by several employers (Schedule 3 "
    "line 11).",
    "estimated_tax_payments": "Federal estimated tax payments for the year (1040 line 26; January's included).",
    "estimated_tax_penalty": "Underpayment of estimated tax penalty (Form 2210; 1040 line 38).",
    "required_annual_payment": "Form 2210 line 9 (0 when no penalty test applied).",
    "tax_for_estimates": "Form 2210 line 4: tax after credits plus self-employment tax, Additional Medicare Tax, NIIT "
    "and additional taxes, less refundable credits.",
    "total_payments": "1040 line 33: withholding, estimated payments, refundable credits and excess Social Security.",
    "amount_owed": "1040 line 37: the balance due, with the estimated tax penalty.",
    "overpayment": "1040 line 34: the overpayment (refund), net of the estimated tax penalty.",
    "state_balance_due": "State income tax less state withholding (negative: a state refund).",
    "settled_in_april": "Whether the balance due or refund was settled in April of the next year (the unit withholds "
    "or pays estimates) rather than in December.",
    "advance_premium_tax_credit": "Advance premium tax credit paid to the insurer (Form 8962 line 25).",
    "excess_advance_ptc_repayment": "Excess advance premium tax credit repaid (Form 8962 line 29; Schedule 2 line 1a).",
    "premium_tax_credit_allowed": "Premium tax credit allowed (Form 8962 line 24); the net credit is "
    "``credits_refundable['premium_tax_credit']``.",
    "ptc_fpl_percent": "Household income as a percent of the poverty line (Form 8962 line 5; 401 above 400%).",
    "ptc_applicable_figure": "Applicable figure (Form 8962 line 7).",
    "ptc_contribution": "Annual contribution amount (Form 8962 line 8a).",
    "ptc_household_income": "Household income (Form 8962 line 3).",
    "ptc_enrollment_premiums": "Enrollment premiums for the coverage months (Form 1095-A column A).",
    "ptc_slcsp_premiums": "Second-lowest-cost silver plan premiums for the coverage months (Form 1095-A column B).",
    "ptc_repayment_limit": "Repayment limitation on excess advance payments (Form 8962 line 28; -1: no limit).",
}


class TaxReturns(dict):
    """``{(year, unit_id): TaxReturn}`` that also answers ``returns[year]`` when that year has a single
    return (one tax unit), and lists a year's returns with :meth:`for_year`."""

    def __getitem__(self, key):
        if isinstance(key, int):
            matches = self.for_year(key)
            if len(matches) == 1:
                return matches[0]
            if not matches:
                raise KeyError(key)
            raise KeyError(f"{len(matches)} returns were filed in {key}; index by (year, unit_id) or use for_year()")
        return super().__getitem__(key)

    def for_year(self, year: int) -> "list[TaxReturn]":
        """The returns filed for ``year`` (one per tax unit), in unit order."""
        return [tax_return for (y, _), tax_return in sorted(self.items()) if y == year]


_NOT_MONEY = frozenset(
    {
        "year",
        "unit_id",
        "marginal_rate",
        "effective_rate",
        "settled_in_april",
        "ptc_fpl_percent",
        "ptc_applicable_figure",
        "ptc_repayment_limit",
    }
)


def _sum_by_source(entries, predicate) -> dict[str, float]:
    totals: dict[str, float] = {}
    for entry in entries:
        if predicate(entry):
            key = entry.source or "other"
            totals[key] = totals.get(key, 0.0) + entry.amount
    return totals


def build_tax_return(unit: "TaxUnit", taxes: "TaxesDue", payments: "dict | None" = None) -> TaxReturn:
    """Build the record for ``unit``'s year from the final ``taxes`` its settlement paid.

    Must be called at the moment of settlement (after the waterfall, before any later ledger change),
    so the members' income ledgers hold exactly the entries ``taxes`` was computed from.
    """
    members = unit.members
    year = members[0].model.year
    entries = [entry for member in members for entry in member.income.entries]

    def total(*types: IncomeType, exclude_sources=frozenset()) -> float:
        return sum(e.amount for e in entries if e.income_type in types and e.source not in exclude_sources)

    wages = total(IncomeType.WAGES)
    taxable_interest = total(IncomeType.INTEREST, IncomeType.TREASURY_INTEREST)
    tax_exempt_interest = total(IncomeType.TAX_EXEMPT_INTEREST)
    qualified_dividends = total(IncomeType.QUALIFIED_DIVIDEND)
    distributions = sum(
        e.amount for e in entries if e.income_type == IncomeType.PRETAX_DISTRIBUTION and e.source != "hsa"
    )
    # Qualified charitable distributions: on line 4a (gross) but not taxable (line 4b).
    qcd = sum(e.gross for e in entries if e.income_type == IncomeType.PRETAX_DISTRIBUTION and e.source == "qcd")
    hsa_distributions = sum(
        e.amount for e in entries if e.income_type == IncomeType.PRETAX_DISTRIBUTION and e.source == "hsa"
    )
    pensions = total(IncomeType.PENSION) + sum(
        e.amount for e in entries if e.income_type == IncomeType.ORDINARY and e.source == "annuity"
    )
    ss_gross = sum(e.gross for e in entries if e.income_type == IncomeType.SS_BENEFIT)
    ss_taxable = total(IncomeType.SS_BENEFIT)

    st_realized = total(IncomeType.SHORT_TERM_CAPITAL_GAIN, exclude_sources=_NETTING_SOURCES)
    lt_realized = total(IncomeType.LONG_TERM_CAPITAL_GAIN, exclude_sources=_NETTING_SOURCES)
    carryforward_used = -sum(
        e.amount
        for e in entries
        if e.source == "capital_loss_carryforward"
        and e.income_type in (IncomeType.SHORT_TERM_CAPITAL_GAIN, IncomeType.LONG_TERM_CAPITAL_GAIN)
    )
    short_term = total(IncomeType.SHORT_TERM_CAPITAL_GAIN)
    long_term = total(IncomeType.LONG_TERM_CAPITAL_GAIN)
    loss_deduction = -sum(
        e.amount for e in entries if e.income_type == IncomeType.ORDINARY and e.source == "capital_loss_deduction"
    )
    capital_line = short_term + long_term - loss_deduction

    adjustments = {
        source: -amount
        for source, amount in _sum_by_source(
            entries, lambda e: e.income_type == IncomeType.ORDINARY and e.source in ADJUSTMENT_SOURCES
        ).items()
    }
    other_by_source = _sum_by_source(
        entries,
        lambda e: (
            e.income_type == IncomeType.ORDINARY
            and e.source not in ADJUSTMENT_SOURCES
            and e.source not in ("annuity", "capital_loss_deduction")
        ),
    )
    if hsa_distributions:
        other_by_source["hsa"] = other_by_source.get("hsa", 0.0) + hsa_distributions
    other_income = sum(other_by_source.values())

    total_income = (
        wages
        + taxable_interest
        + qualified_dividends
        + distributions
        + pensions
        + ss_taxable
        + capital_line
        + other_income
    )
    business_income = total(IncomeType.SELF_EMPLOYMENT)
    total_income += business_income
    taxable_care_benefits = sum(
        e.amount for e in entries if e.income_type == IncomeType.WAGES and e.source == "taxable_dependent_care_benefits"
    )
    total_adjustments = sum(adjustments.values())
    agi = unit.agi()

    standard = float(taxes.standard_deduction)
    itemized = float(taxes.itemized_deduction)
    deduction_taken = "itemized" if taxes.itemize else "standard"

    fica = tuple(
        FicaLine(
            person_id=member.unique_id,
            name=member.name,
            wages=member.fica_wages,
            social_security=taxes.ss_by_worker[i] if i < len(taxes.ss_by_worker) else 0.0,
            medicare=taxes.medicare_by_worker[i] if i < len(taxes.medicare_by_worker) else 0.0,
            self_employment_income=member.income.self_employment_income,
            self_employment_tax=taxes.se_by_worker[i].total if i < len(taxes.se_by_worker) else 0.0,
            self_employment_net_earnings=taxes.se_by_worker[i].net_earnings if i < len(taxes.se_by_worker) else 0.0,
        )
        for i, member in enumerate(members)
    )

    detail = taxes.state_detail
    state_return = StateReturn.from_detail(detail) if detail is not None else None

    brackets = tuple(tuple(row) for row in taxes.ordinary_brackets)
    reached = [row for row in brackets if row[3] > 0]
    marginal_rate = reached[-1][2] if reached else 0.0
    federal_tax = taxes.federal + taxes.niit - taxes.credits
    effective_rate = federal_tax / agi * 100 if agi > 0 else 0.0

    # Payments (Form 1040 lines 24-38): line 24 is the income tax after nonrefundable credits plus the other
    # taxes; line 33 adds withholding, estimated payments, the refundable credits and excess Social Security.
    pay = payments or {}
    line_24 = taxes.federal + taxes.niit + taxes.se_tax + taxes.additional_medicare - taxes.nonrefundable_credits
    total_payments = (
        pay.get("federal_income_tax_withheld", 0.0)
        + pay.get("additional_medicare_tax_withheld", 0.0)
        + pay.get("estimated_tax_payments", 0.0)
        + taxes.refundable_credits
        + pay.get("excess_social_security_withheld", 0.0)
    )
    penalty = pay.get("estimated_tax_penalty", 0.0)
    balance = line_24 - total_payments + penalty
    ptc = taxes.ptc_detail or {}

    return TaxReturn(
        year=year,
        unit_id=members[0].unique_id,
        member_ids=tuple(m.unique_id for m in members),
        member_names=tuple(m.name for m in members),
        filing_status=unit.filing_status.name,
        state=detail.state if detail is not None else str(unit.state),
        wages=wages,
        taxable_interest=taxable_interest,
        tax_exempt_interest=tax_exempt_interest,
        ordinary_dividends=qualified_dividends,
        qualified_dividends=qualified_dividends,
        ira_distributions_gross=distributions + qcd,
        ira_distributions_taxable=distributions,
        pensions_and_annuities=pensions,
        social_security_gross=ss_gross,
        social_security_taxable=ss_taxable,
        short_term_gains_realized=st_realized,
        long_term_gains_realized=lt_realized,
        capital_loss_carryforward_used=carryforward_used,
        short_term_gains=short_term,
        long_term_gains=long_term,
        capital_loss_deduction=loss_deduction,
        capital_gain_or_loss=capital_line,
        other_income=other_income,
        other_income_by_source=other_by_source,
        total_income=total_income,
        adjustments=adjustments,
        total_adjustments=total_adjustments,
        agi=agi,
        standard_deduction=standard,
        itemized_deductions=itemized,
        itemized_components=unit.itemized_components(taxes.state),
        deduction_taken=deduction_taken,
        senior_deduction=taxes.senior_deduction,
        deduction=taxes.deductions,
        taxable_income=taxes.taxable_income,
        taxable_ordinary_income=taxes.taxable_ordinary,
        taxable_preferential_income=taxes.taxable_preferential,
        ordinary_tax=taxes.ordinary_tax,
        ordinary_brackets=brackets,
        preferential_tax=taxes.preferential_tax,
        niit=taxes.niit,
        amt=taxes.amt,
        credits=dict(taxes.credits_detail),
        nonrefundable_credits=taxes.nonrefundable_credits,
        refundable_credits=taxes.refundable_credits,
        total_credits=taxes.credits,
        penalties=dict(taxes.penalties_detail),
        total_penalties=taxes.penalties,
        federal_tax=federal_tax,
        fica=fica,
        social_security_tax=taxes.ss,
        medicare_tax=taxes.medicare,
        additional_medicare_tax=taxes.additional_medicare,
        state_return=state_return,
        state_tax=taxes.state,
        total_tax=taxes.total,
        marginal_rate=marginal_rate,
        effective_rate=effective_rate,
        business_income=business_income,
        taxable_dependent_care_benefits=taxable_care_benefits,
        additional_standard_deduction=taxes.additional_standard_deduction,
        charitable_deduction_non_itemizer=taxes.charitable_non_itemizer,
        itemized_limitation=taxes.itemized_limitation,
        qualified_business_income=taxes.qbi_detail.qbi if taxes.qbi_detail is not None else 0.0,
        qbi_deduction=taxes.qbi_deduction,
        kiddie_tax=taxes.kiddie_tax,
        alternative_minimum_taxable_income=taxes.amt_detail.amti if taxes.amt_detail is not None else 0.0,
        tentative_minimum_tax=taxes.amt_detail.tentative_minimum_tax if taxes.amt_detail is not None else 0.0,
        amt_credit_generated=taxes.amt_credit_generated,
        credits_nonrefundable=dict(taxes.credits_nonrefundable),
        credits_refundable=dict(taxes.credits_refundable),
        earned_income=taxes.earned_income,
        self_employment_tax=taxes.se_tax,
        self_employment_tax_deduction=sum(se.deduction for se in taxes.se_by_worker),
        additional_medicare_tax_self_employment=taxes.additional_medicare_se,
        federal_income_tax_withheld=pay.get("federal_income_tax_withheld", 0.0),
        additional_medicare_tax_withheld=pay.get("additional_medicare_tax_withheld", 0.0),
        social_security_withheld=pay.get("social_security_withheld", 0.0),
        medicare_withheld=pay.get("medicare_withheld", 0.0),
        state_withheld=pay.get("state_withheld", 0.0),
        excess_social_security_withheld=pay.get("excess_social_security_withheld", 0.0),
        estimated_tax_payments=pay.get("estimated_tax_payments", 0.0),
        estimated_tax_penalty=penalty,
        required_annual_payment=pay.get("required_annual_payment", 0.0),
        tax_for_estimates=taxes.federal + taxes.niit + taxes.se_tax + taxes.additional_medicare - taxes.credits,
        total_payments=total_payments,
        amount_owed=max(0.0, balance),
        overpayment=max(0.0, -balance),
        state_balance_due=taxes.state - pay.get("state_withheld", 0.0),
        settled_in_april=bool(pay.get("settled_in_april", False)),
        advance_premium_tax_credit=ptc.get("advance", 0.0),
        excess_advance_ptc_repayment=taxes.excess_advance_ptc,
        premium_tax_credit_allowed=ptc.get("allowed", 0.0),
        ptc_fpl_percent=ptc.get("fpl_percent", 0.0),
        ptc_applicable_figure=ptc.get("applicable_figure", 0.0),
        ptc_contribution=ptc.get("contribution", 0.0),
        ptc_household_income=ptc.get("household_income", 0.0),
        ptc_enrollment_premiums=ptc.get("enrollment_premiums", 0.0),
        ptc_slcsp_premiums=ptc.get("slcsp_premiums", 0.0),
        ptc_repayment_limit=ptc.get("repayment_limit", -1.0),
    )
