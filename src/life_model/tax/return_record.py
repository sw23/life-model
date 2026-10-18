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
* ``agi - deduction == taxable_income`` (floored at 0), where ``deduction`` is the larger of the
  standard and itemized deductions plus the senior deduction;
* ``ordinary_tax + preferential_tax + niit + amt - total_credits + total_penalties == federal_tax``;
* ``federal_tax + state_tax + social_security_tax + medicare_tax == total_tax`` (``TaxesDue.total``).

Records are stored on ``model.tax_returns[(year, unit_id)]`` (``unit_id`` is the head's
``unique_id``) and on each member's ``person.tax_returns[year]``.

All money is nominal dollars of the return's year; rates are percents (``22.0`` is 22%).
"""

from dataclasses import asdict, dataclass, fields, replace
from typing import TYPE_CHECKING, Any

from .income import IncomeType

if TYPE_CHECKING:
    from ..people.tax_unit import TaxUnit
    from .tax import TaxesDue

#: Ordinary-income entry sources that are above-the-line adjustments (Schedule 1, Part II).
ADJUSTMENT_SOURCES = frozenset({"adjustment", "ira_deduction", "hsa_deduction", "student_loan_interest"})
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

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready dict (nested records become dicts/lists)."""
        data = asdict(self)
        data["ordinary_brackets"] = [list(row) for row in self.ordinary_brackets]
        data["fica"] = [asdict(line) for line in self.fica]
        if self.state_return is not None:
            data["state_return"]["brackets"] = [list(row) for row in self.state_return.brackets]
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
            state = dict(state)
            state["brackets"] = tuple(tuple(row) for row in state["brackets"])
            data["state_return"] = StateReturn(**state)
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
            )
            for line in self.fica
        )
        if self.state_return is not None:
            s = self.state_return
            changes["state_return"] = replace(
                s,
                income=money(s.income),
                subtractions=money(s.subtractions),
                deduction=money(s.deduction),
                taxable_income=money(s.taxable_income),
                brackets=tuple((money(lo), money(hi), r, money(a), money(t)) for lo, hi, r, a, t in s.brackets),
                tax=money(s.tax),
            )
        return replace(self, **changes)


#: One-line description of every :class:`TaxReturn` field (rendered into docs/outputs.md).
FIELD_DOCS: dict[str, str] = {
    "year": "Tax year.",
    "unit_id": "The unit head's agent ``unique_id``.",
    "member_ids": "Agent ids of the members filing the return (head first).",
    "member_names": "Names of the members filing the return.",
    "filing_status": "Filing status name (``SINGLE``, ``MARRIED_FILING_JOINTLY``, ...).",
    "state": "State the unit files in (the head's).",
    "wages": "W-2 wages (salary and RSU vests, net of pre-tax 401k deferrals).",
    "taxable_interest": "Taxable interest (bank, corporate and Treasury interest).",
    "tax_exempt_interest": "Tax-exempt (municipal) interest; not in total income.",
    "ordinary_dividends": "Ordinary dividends (the model's dividends are all qualified).",
    "qualified_dividends": "Qualified dividends (taxed on the preferential schedule).",
    "ira_distributions_gross": "IRA / 401k / inherited-account distributions, gross.",
    "ira_distributions_taxable": "Taxable part of those distributions (all of it in the model).",
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
    "adjustments": "Above-the-line adjustments by source (IRA, HSA, student-loan interest).",
    "total_adjustments": "Sum of ``adjustments``.",
    "agi": "Adjusted gross income: ``max(total_income - total_adjustments, 0)``.",
    "standard_deduction": "Standard deduction for the filing status (0 for MFS when the spouse itemizes).",
    "itemized_deductions": "Itemized deductions compared against the standard deduction.",
    "itemized_components": "Itemized deductions by component (mortgage interest, SALT after the cap, medical, charity).",
    "deduction_taken": "``standard`` or ``itemized``.",
    "senior_deduction": "OBBBA senior deduction (added on top of either deduction).",
    "deduction": "Total deduction subtracted from AGI.",
    "taxable_income": "``max(agi - deduction, 0)``.",
    "taxable_ordinary_income": "Part of taxable income taxed on the ordinary brackets.",
    "taxable_preferential_income": "Part of taxable income taxed on the capital-gains schedule.",
    "ordinary_tax": "Tax on the ordinary brackets.",
    "ordinary_brackets": "Bracket slices ``(lower, upper, rate_percent, amount, tax)``; their taxes sum to ``ordinary_tax``.",
    "preferential_tax": "Tax on qualified dividends and long-term gains.",
    "niit": "Net investment income tax (IRC §1411).",
    "amt": "Alternative minimum tax (not modeled yet; always 0).",
    "credits": "Credits by name (``child_tax_credit``).",
    "nonrefundable_credits": "Credits limited to the income tax.",
    "refundable_credits": "Credits paid even beyond the income tax.",
    "total_credits": "Sum of ``credits``.",
    "penalties": "Additional taxes by source (``early_withdrawal``, ``hsa_non_medical``, ``roth_ira_earnings``, ...).",
    "total_penalties": "Sum of ``penalties``.",
    "federal_tax": "Federal income tax: ordinary + preferential + NIIT + AMT - credits + penalties (negative = refund).",
    "fica": "Payroll taxes per member.",
    "social_security_tax": "Social Security tax (all members).",
    "medicare_tax": "Medicare tax including the additional Medicare tax (all members).",
    "additional_medicare_tax": "Additional Medicare tax on combined wages over the threshold.",
    "state_return": "State return lines.",
    "state_tax": "State income tax.",
    "total_tax": "Everything the unit paid in tax this year: federal + state + payroll.",
    "marginal_rate": "Ordinary-bracket rate (percent) of the last taxable ordinary dollar.",
    "effective_rate": "``federal_tax / agi`` as a percent (0 when AGI is 0).",
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


_NOT_MONEY = frozenset({"year", "unit_id", "marginal_rate", "effective_rate"})


def _sum_by_source(entries, predicate) -> dict[str, float]:
    totals: dict[str, float] = {}
    for entry in entries:
        if predicate(entry):
            key = entry.source or "other"
            totals[key] = totals.get(key, 0.0) + entry.amount
    return totals


def build_tax_return(unit: "TaxUnit", taxes: "TaxesDue") -> TaxReturn:
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
    total_adjustments = sum(adjustments.values())
    agi = unit.agi()

    standard = float(taxes.standard_deduction)
    itemized = float(taxes.itemized_deduction)
    deduction_taken = "itemized" if itemized > standard else "standard"

    fica = tuple(
        FicaLine(
            person_id=member.unique_id,
            name=member.name,
            wages=member.fica_wages,
            social_security=taxes.ss_by_worker[i] if i < len(taxes.ss_by_worker) else 0.0,
            medicare=taxes.medicare_by_worker[i] if i < len(taxes.medicare_by_worker) else 0.0,
        )
        for i, member in enumerate(members)
    )

    detail = taxes.state_detail
    state_return = None
    if detail is not None:
        state_return = StateReturn(
            state=detail.state,
            method=detail.method,
            income=detail.income,
            subtractions=detail.subtractions,
            deduction=detail.deduction,
            taxable_income=detail.taxable_income,
            flat_rate=detail.flat_rate,
            brackets=tuple(detail.brackets),
            tax=detail.tax,
        )

    brackets = tuple(tuple(row) for row in taxes.ordinary_brackets)
    reached = [row for row in brackets if row[3] > 0]
    marginal_rate = reached[-1][2] if reached else 0.0
    federal_tax = taxes.federal + taxes.niit - taxes.credits
    effective_rate = federal_tax / agi * 100 if agi > 0 else 0.0

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
        ira_distributions_gross=distributions,
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
        amt=0.0,
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
    )
