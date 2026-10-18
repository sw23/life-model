# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Reconcile a simulated year against the household's real documents (Plan 29 D2).

:func:`reconcile` runs a household spec through ``year`` and compares the year's results with the
spec's :class:`~life_model.spec.actuals.ActualRecords` (or records passed in): every Form 1040 and
schedule line, W-2 box, 1099 box, paystub amount, state-return line and statement balance the
records carry. Each comparison is a :class:`ReconciliationLine` with the simulated and actual values,
the difference, a status from the :data:`TOLERANCES` table (``green`` within rounding, ``yellow``
close, ``red`` off, ``not_modeled`` when the engine has no equivalent yet) and, for anything not
green, the likely cause:

* ``missing_income_source``: the document shows income the household spec does not have;
* ``input_difference``: both have it but the amounts differ (a spec input, such as a salary or a
  balance, differs from the document);
* ``unmodeled_credit`` / ``unmodeled_deduction``: a credit or deduction the engine does not compute
  yet (the foreign tax credit, the ACA premium tax credit (Plan 31 task 6), energy credits...), or one
  it computes from an input the spec lacks (care expenses, education expenses);
* ``unit_mismatch``: off by a factor of 12 or 100 (a monthly amount entered as annual, a fraction
  entered as a percent);
* ``timing``: withholding, estimated payments and the refund/balance due (the engine settles taxes
  as one year-end lump; Plan 31 D3);
* ``missing_input``: a line that needs a spec input the engine does not take yet (Plan 27: payroll
  deductions, IRA basis, lot-level basis);
* ``unmodeled_line``: a line the engine has no equivalent for (household-employee wages, ...);
* ``propagated``: a total that is off only because a line it adds up is off (the report names it);
* ``unexplained``: none of the above: investigate.

Line mapping (``TaxReturn`` field -> line) follows each year's forms (``life_model.spec.actuals``
line tables). Notable conventions: line 16 is ordinary plus preferential tax (the engine computes
the exact rate schedule; the IRS Tax Table below $100,000 taxes the midpoint of a $50 row, so line
16 and the totals after it have a wider green tolerance); line 23 adds the NIIT, the Additional
Medicare Tax, additional taxes on early distributions and self-employment tax (Schedule 2); each
credit goes to its own line (Plan 31): line 19 / 28 the child tax credit and the additional child tax
credit (Schedule 8812), line 20 the Schedule 3 credits (dependent care line 2, education line 3,
saver's line 4, prior-year minimum tax line 6b), line 27 (27a) the earned income credit, line 29 the
refundable American opportunity credit; line 17 is AMT and line 16 includes the Form 8814 tax.
"""

import json
import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from .ledger import FlowKind, account_label

if TYPE_CHECKING:
    from .model import LifeModel
    from .spec import HouseholdSpec
    from .spec.actuals import ActualRecords, ReturnActuals
    from .tax.return_record import TaxReturn

GREEN, YELLOW, RED, NOT_MODELED = "green", "yellow", "red", "not_modeled"
STATUSES = (RED, YELLOW, GREEN, NOT_MODELED)

#: Every cause a line can be classified with (see the module docstring).
CAUSES = (
    "missing_income_source",
    "input_difference",
    "unmodeled_credit",
    "unmodeled_deduction",
    "unit_mismatch",
    "timing",
    "missing_input",
    "unmodeled_line",
    "propagated",
    "unexplained",
)


@dataclass(frozen=True)
class Tolerance:
    """Green within ``max(green_abs, green_rel x |actual|)``, yellow within the yellow bounds, else red."""

    green_abs: float = 2.0
    green_rel: float = 0.0005
    yellow_abs: float = 100.0
    yellow_rel: float = 0.02

    def status(self, difference: float, actual: float) -> str:
        size = abs(difference)
        if size <= max(self.green_abs, self.green_rel * abs(actual)):
            return GREEN
        if size <= max(self.yellow_abs, self.yellow_rel * abs(actual)):
            return YELLOW
        return RED


#: Tax Table rounding: the 1040 taxes taxable income under $100,000 at the midpoint of a $50 row,
#: rounded to the dollar, so the table differs from the exact schedule by up to rate x $25 + $0.50.
_TAX_TABLE = Tolerance(green_abs=10.0)

#: Tolerance by ``"<section>:<line>"`` (most specific first), ``"<section>:*"``, then ``"*"``.
#: Filed returns are in whole dollars, so the default green band is $2.
TOLERANCES: dict[str, Tolerance] = {
    "*": Tolerance(),
    **{f"1040:{line}": _TAX_TABLE for line in ("16", "18", "22", "24", "24a", "24c", "34", "37")},
    "balance:*": Tolerance(green_abs=5.0, green_rel=0.005, yellow_abs=250.0, yellow_rel=0.03),
    "paystub:*": Tolerance(green_abs=5.0, green_rel=0.002, yellow_abs=50.0, yellow_rel=0.03),
    "spending:*": Tolerance(green_abs=50.0, green_rel=0.02, yellow_abs=500.0, yellow_rel=0.10),
}


def tolerance_for(section: str, line: str, table: "dict[str, Tolerance] | None" = None) -> Tolerance:
    table = TOLERANCES if table is None else {**TOLERANCES, **table}
    for key in (f"{section}:{line}", f"{section}:*", "*"):
        if key in table:
            return table[key]
    return Tolerance()


@dataclass
class ReconciliationLine:
    """One compared amount."""

    section: str  #: ``1040``, ``schedule 1``, ``W-2``, ``1099-INT``, ``balance``, ``paystub``, ``state``, ``spending``
    line: str
    label: str
    actual: float
    simulated: float | None
    status: str = GREEN
    cause: str | None = None
    note: str = ""
    #: Which document it came from (``"Acme / alex"``, ``"return of alex"``), when there are several.
    source: str = ""

    @property
    def key(self) -> str:
        return f"{self.section}:{self.line}"

    @property
    def difference(self) -> float | None:
        return None if self.simulated is None else self.simulated - self.actual

    @property
    def relative(self) -> float | None:
        if self.simulated is None or self.actual == 0:
            return None
        return (self.simulated - self.actual) / abs(self.actual)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["key"] = self.key
        data["difference"] = self.difference
        data["relative"] = self.relative
        return data


@dataclass
class ReconciliationReport:
    """Simulated vs actual for one household year."""

    household: str
    year: int
    seed: int | None
    lines: list[ReconciliationLine] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def by_status(self, status: str) -> list[ReconciliationLine]:
        return [line for line in self.lines if line.status == status]

    @property
    def red(self) -> list[ReconciliationLine]:
        return self.by_status(RED)

    @property
    def counts(self) -> dict[str, int]:
        return {status: len(self.by_status(status)) for status in STATUSES}

    def find(self, section: str, line: str, source: str | None = None) -> ReconciliationLine:
        for item in self.lines:
            if item.section == section and item.line == line and (source is None or item.source == source):
                return item
        raise KeyError(f"{section}:{line}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "household": self.household,
            "year": self.year,
            "seed": self.seed,
            "counts": self.counts,
            "lines": [line.to_dict() for line in self.lines],
            "notes": list(self.notes),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_markdown(self) -> str:
        counts = self.counts
        out = [
            f"# Reconciliation: {self.household}, {self.year}",
            "",
            (
                f"{counts[GREEN]} green, {counts[YELLOW]} yellow, {counts[RED]} red, "
                f"{counts[NOT_MODELED]} not modeled (seed {self.seed})."
            ),
            "",
        ]
        if self.red or self.by_status(YELLOW):
            out.append("## Lines to look at")
            out.append("")
            for item in self.red + self.by_status(YELLOW):
                out.append(
                    f"- **{item.status.upper()}** {_where(item)} {item.label}: simulated {_money(item.simulated)}, "
                    f"actual {_money(item.actual)} ({item.cause}){': ' + item.note if item.note else ''}"
                )
            out.append("")
        sections: dict[str, list[ReconciliationLine]] = {}
        for item in self.lines:
            sections.setdefault(item.section, []).append(item)
        for section, items in sections.items():
            out.append(f"## {section}")
            out.append("")
            out.append("| Line | Label | Simulated | Actual | Difference | Status | Cause / note |")
            out.append("|---|---|---:|---:|---:|---|---|")
            for item in items:
                why = " ".join(part for part in (item.cause or "", item.note) if part)
                line = f"{item.line} ({item.source})" if item.source else item.line
                out.append(
                    f"| {line} | {item.label} | {_money(item.simulated)} | {_money(item.actual)} | "
                    f"{_money(item.difference)} | {item.status} | {why} |"
                )
            out.append("")
        if self.notes:
            out.append("## Notes")
            out.append("")
            out.extend(f"- {note}" for note in self.notes)
            out.append("")
        return "\n".join(out)


def _where(item: ReconciliationLine) -> str:
    return f"{item.section} line {item.line}" + (f" ({item.source})" if item.source else "")


def _money(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{'-' if value < 0 else ''}${abs(value):,.2f}"


# --------------------------------------------------------------------------------------------------
# Simulated lines
# --------------------------------------------------------------------------------------------------


def form_1040_lines(r: "TaxReturn") -> dict[str, float]:
    """The return's Form 1040 lines by the year's line numbers (only lines the engine computes)."""
    from .spec.actuals import line_table_year

    year = line_table_year(r.year)
    # Standard (with §63(f)) or itemized (after §68): line 12 / 12e.
    deduction = r.deduction - r.senior_deduction - r.qbi_deduction - r.charitable_deduction_non_itemizer
    tax = r.ordinary_tax + r.preferential_tax + r.kiddie_tax
    line_18 = tax + r.amt
    line_19 = r.credits_nonrefundable.get("child_tax_credit", 0.0)
    line_20 = r.nonrefundable_credits - line_19
    line_22 = max(line_18 - line_19 - line_20, 0.0)
    other_taxes = r.niit + r.additional_medicare_tax + r.total_penalties + r.self_employment_tax
    total_tax = line_22 + other_taxes
    refundable = r.credits_refundable
    lines = {
        "1a": r.wages - r.taxable_dependent_care_benefits,
        "1e": r.taxable_dependent_care_benefits,
        "1z": r.wages,
        "2a": r.tax_exempt_interest,
        "2b": r.taxable_interest,
        "3a": r.qualified_dividends,
        "3b": r.ordinary_dividends,
        "4a": r.ira_distributions_gross,
        "4b": r.ira_distributions_taxable,
        "5a": r.pensions_and_annuities,
        "5b": r.pensions_and_annuities,
        "6a": r.social_security_gross,
        "6b": r.social_security_taxable,
        "8": r.other_income + r.business_income,
        "9": r.total_income,
        "10": r.total_adjustments,
        "15": r.taxable_income,
        "16": tax,
        "17": r.amt,
        "18": line_18,
        "19": line_19,
        "20": line_20,
        "21": line_19 + line_20,
        "22": line_22,
        "23": other_taxes,
        "28": refundable.get("child_tax_credit", 0.0),
        "29": refundable.get("education_credits", 0.0),
        "31": 0.0,
    }
    eitc = refundable.get("earned_income_credit", 0.0)
    if year == 2024:
        lines.update(
            {
                "7": r.capital_gain_or_loss,
                "11": r.agi,
                "12": deduction,
                "13": r.qbi_deduction,
                "14": r.deduction,
                "24": total_tax,
                "27": eitc,
            }
        )
    else:
        lines.update(
            {
                "7a": r.capital_gain_or_loss,
                "11a": r.agi,
                "11b": r.agi,
                "12e": deduction,
                "14": r.deduction,
                "27a": eitc,
                "30": 0.0,
            }
        )
        if year == 2025:
            lines.update({"13a": r.qbi_deduction, "13b": r.senior_deduction, "24": total_tax})
        else:
            lines.update(
                {
                    "12f": r.charitable_deduction_non_itemizer,
                    "13a": r.senior_deduction,
                    "13b": r.qbi_deduction,
                    "24a": total_tax,
                    "24b": 0.0,
                    "24c": total_tax,
                }
            )
    return lines


def schedule_lines(r: "TaxReturn") -> dict[str, dict[str, float]]:
    """The return's schedule lines the engine computes, by schedule name."""
    from .spec.actuals import line_table_year

    year = line_table_year(r.year)
    hsa_penalty = r.penalties.get("hsa_non_medical", 0.0)
    retirement_penalties = r.total_penalties - hsa_penalty
    adjustments = r.adjustments
    nonrefundable = r.credits_nonrefundable
    refundable = r.credits_refundable
    other_8z = sum(amount for source, amount in r.other_income_by_source.items() if source != "hsa")
    schedules: dict[str, dict[str, float]] = {
        "1": {
            "3": r.business_income,
            "8f": r.other_income_by_source.get("hsa", 0.0),
            "8z": other_8z,
            "9": r.other_income,
            "10": r.other_income + r.business_income,
            "13": adjustments.get("hsa_deduction", 0.0),
            "15": adjustments.get("se_tax_deduction", 0.0),
            "16": adjustments.get("self_employed_plan", 0.0),
            "20": adjustments.get("ira_deduction", 0.0),
            "21": adjustments.get("student_loan_interest", 0.0),
            "26": r.total_adjustments,
        },
        "3": {
            "1": 0.0,
            "2": nonrefundable.get("dependent_care_credit", 0.0),
            "3": nonrefundable.get("education_credits", 0.0),
            "4": nonrefundable.get("savers_credit", 0.0),
            "6b": nonrefundable.get("minimum_tax_credit", 0.0),
            "7": nonrefundable.get("minimum_tax_credit", 0.0),
            "8": r.nonrefundable_credits - nonrefundable.get("child_tax_credit", 0.0),
            "9": 0.0,
            "15": 0.0,
        },
        "8812": {
            "14": nonrefundable.get("child_tax_credit", 0.0),
            "27": refundable.get("child_tax_credit", 0.0),
        },
        "2441": {"11": nonrefundable.get("dependent_care_credit", 0.0), "26": r.taxable_dependent_care_benefits},
        "8863": {
            "8": refundable.get("education_credits", 0.0),
            "19": nonrefundable.get("education_credits", 0.0),
        },
        "8880": {"12": nonrefundable.get("savers_credit", 0.0)},
        "8995": {"1": r.qualified_business_income, "15": r.qbi_deduction},
        "6251": {
            "4": r.alternative_minimum_taxable_income,
            "9": r.tentative_minimum_tax,
            "11": r.amt,
        },
        "8814": {"15": r.kiddie_tax},
        "A": {
            "4": r.itemized_components.get("medical", 0.0),
            "5e": r.itemized_components.get("salt", 0.0),
            "7": r.itemized_components.get("salt", 0.0),  # no "other taxes" (line 6) in the engine
            "8a": r.itemized_components.get("mortgage_interest", 0.0),
            "8e": r.itemized_components.get("mortgage_interest", 0.0),
            "10": r.itemized_components.get("mortgage_interest", 0.0),
            "11": r.itemized_components.get("charity", 0.0),
            "12": r.itemized_components.get("charity_noncash", 0.0),
            "14": r.itemized_components.get("charity", 0.0) + r.itemized_components.get("charity_noncash", 0.0),
            "17": r.itemized_deductions,
        },
        "B": {"2": r.taxable_interest, "4": r.taxable_interest, "6": r.ordinary_dividends},
    }
    if any(line.self_employment_income for line in r.fica):
        profit = sum(line.self_employment_income for line in r.fica)
        net = sum(line.self_employment_net_earnings for line in r.fica)
        schedules["SE"] = {
            "2": profit,
            "3": profit,
            "4a": net,
            "4c": net,
            "6": net,
            "12": r.self_employment_tax,
            "13": r.self_employment_tax_deduction,
        }
        schedules["C"] = {"31": r.business_income}
    if r.capital_loss_deduction > 0:
        schedules["D"] = {"21": -r.capital_loss_deduction}
    else:
        schedules["D"] = {
            "7": r.short_term_gains,
            "15": r.long_term_gains,
            "16": r.short_term_gains + r.long_term_gains,
        }
    total_other = r.niit + r.additional_medicare_tax + r.total_penalties + r.self_employment_tax
    if year == 2026:
        se_medicare = r.additional_medicare_tax_self_employment
        schedules["2"] = {
            "2": r.amt,
            "3": r.amt,
            "4": r.self_employment_tax,
            "5": retirement_penalties,
            "6": r.niit,
            "11": se_medicare,
            "13c": hsa_penalty,
            "17b": r.additional_medicare_tax - se_medicare,
            "21": total_other,
        }
        schedules["1-A"] = {"15": 0.0, "27": 0.0, "36": 0.0, "43": r.senior_deduction, "44": r.senior_deduction}
    else:
        schedules["2"] = {
            "2": r.amt,
            "3": r.amt,
            "4": r.self_employment_tax,
            "8": retirement_penalties,
            "11": r.additional_medicare_tax,
            "12": r.niit,
            "17c": hsa_penalty,
            "21": total_other,
        }
        if year == 2025:
            schedules["1-A"] = {"13": 0.0, "21": 0.0, "30": 0.0, "37": r.senior_deduction, "38": r.senior_deduction}
    return schedules


#: Form 1040 totals and the lines they add up (to name the root of a propagated difference).
_1040_INPUTS = {
    "1z": ("1a",),
    "9": ("1z", "2b", "3b", "4b", "5b", "6b", "7", "7a", "8"),
    "6b": ("1z", "2a", "2b", "3b", "4b", "5b", "6a", "7", "7a", "8", "10"),
    "11": ("9", "10"),
    "11a": ("9", "10"),
    "11b": ("11a",),
    "14": ("12", "12e", "12f", "13", "13a", "13b"),
    "15": ("11", "11b", "14"),
    "16": ("15", "3a", "7", "7a"),
    "18": ("16", "17"),
    "19": ("18", "11", "11b"),
    "21": ("19", "20"),
    "22": ("18", "21"),
    "24": ("22", "23"),
    "24a": ("22", "23"),
    "24c": ("24a", "24b"),
    "28": ("19", "22"),
    "8": ("schedule 1:10",),
    "10": ("schedule 1:26",),
    "12": ("schedule A:17",),
    "12e": ("schedule A:17",),
    "17": ("schedule 2:3",),
    "20": ("schedule 3:8",),
    "23": ("schedule 2:21",),
}

#: Schedules and forms of credits (a larger filed credit than simulated is an unmodeled credit or input).
_CREDIT_SECTIONS = frozenset({"schedule 3", "schedule 8812", "schedule 2441", "schedule 8863", "schedule 8880"})
_INCOME_LINES = frozenset({"1a", "1z", "2a", "2b", "3a", "3b", "4a", "4b", "5a", "5b", "6a", "7", "7a", "8"})
_CREDIT_LINES = frozenset({"19", "20", "27", "27a", "28", "29", "30", "31"})
_DEDUCTION_LINES = frozenset({"10", "12", "12e", "12f", "13", "13a", "13b", "14"})
_PAYMENT_LINES = frozenset(
    {"25a", "25b", "25c", "25d", "26", "32", "32a", "32b", "32c", "33", "34", "35a", "36", "37", "38"}
)


# --------------------------------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------------------------------


@dataclass
class _Year:
    """The simulated year reconcile reads (the model ended with this year)."""

    model: "LifeModel"
    year: int
    built: Any

    def entries(self) -> list:
        balances = self.model.balance_sheets[self.year]
        return self.model.ledger.between(balances.ledger_start, balances.ledger_end)

    def person(self, person_id: str | None):
        people = self.built.people
        if person_id is not None:
            return people[person_id]
        return next(iter(people.values())) if len(people) == 1 else None

    def label(self, item_id: str) -> str | None:
        agent = self.built.items.get(item_id)
        return None if agent is None else account_label(agent)


def run_for_reconciliation(
    spec: "HouseholdSpec", year: int, *, seed: int | None = None, config=None, checks: str = "off"
) -> _Year:
    """Build ``spec`` and run it through ``year`` (the year's balances and returns are then final).
    ``checks`` runs the invariant checker over the simulated years (``LifeModel(checks=)``)."""
    import warnings

    from .spec import build_household

    if year < spec.meta.start_year:
        raise ValueError(
            f"{year} is before the spec's start_year {spec.meta.start_year}: describe the household as of the start "
            f"of {year} (meta.start_year: {year}) to reconcile it"
        )
    meta = spec.meta.model_copy(update={"end_year": year})
    spec = spec.model_copy(update={"meta": meta})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        built = build_household(spec, seed=seed, config=config, check=checks != "off")
        built.model.checks = checks
        built.model.run()
    return _Year(built.model, year, built)


def _returns_for(sim: _Year, records: "ActualRecords") -> "list[tuple[ReturnActuals, TaxReturn | None, str]]":
    returns = sim.model.tax_returns.for_year(sim.year)
    pairs = []
    for actual in records.all_returns():
        match = None
        if actual.filer is not None:
            uid = sim.built.people[actual.filer].unique_id
            match = next((r for r in returns if uid in r.member_ids), None)
            source = f"return of {actual.filer}"
        else:
            match = returns[0] if len(returns) == 1 else None
            source = "" if len(returns) == 1 else "return (filer not given)"
        pairs.append((actual, match, source))
    return pairs


def _employer_flows(sim: _Year, person, employer: str) -> dict[str, float]:
    from .account.job401k import Job401kAccount

    agents = {account_label(a): a for a in sim.model.agents}
    gross = pretax = roth = 0.0
    for entry in sim.entries():
        if entry.agent_id != person.unique_id:
            continue
        if entry.kind in (FlowKind.WAGE.value, FlowKind.BONUS.value, FlowKind.VEST.value) and entry.source == employer:
            if entry.cause and "ISO exercise spread (held)" in entry.cause:
                continue  # a held ISO's bargain element is not wages (an AMT adjustment)
            gross += entry.amount
        elif entry.kind == FlowKind.CONTRIBUTION.value and isinstance(agents.get(entry.to_account), Job401kAccount):
            account = agents[entry.to_account]
            if account.job is not None and account.job.company == employer:
                if entry.cause == "pre-tax 401k deferral":
                    pretax += entry.amount
                elif entry.cause == "Roth 401k deferral":
                    roth += entry.amount
    return {"gross": gross, "pretax": pretax, "roth": roth}


def _w2_simulated(sim: _Year, person, employer: str) -> dict[str, float | None]:
    flows = _employer_flows(sim, person, employer)
    fica = sim.model.config_for_year(sim.year).tax.fica
    # A dependent-care FSA election is paid out of gross pay but excluded from boxes 1, 3 and 5 (box 10).
    fsa = sum(
        job._booked.fsa
        for job in person.jobs
        if job.company == employer and job._booked is not None and job._booked_year == sim.year
    )
    gross = flows["gross"] - fsa
    ss_wages = min(gross, fica.social_security_max_income)
    # Employers withhold the Additional Medicare Tax on wages over $200,000 whatever the filing status.
    medicare = gross * fica.medicare_rate / 100 + max(0.0, gross - 200000) * fica.medicare_additional_rate / 100
    return {
        "1": gross - flows["pretax"],
        "2": None,
        "3": ss_wages,
        "4": ss_wages * fica.social_security_rate / 100,
        "5": gross,
        "6": medicare,
        "10": fsa,
        "12:D": flows["pretax"],
        "12:AA": flows["roth"],
    }


def _account_flows(sim: _Year, labels: Iterable[str], kinds: Iterable[str], *, inbound: bool) -> float:
    labels, kinds = set(labels), set(kinds)
    total = 0.0
    for entry in sim.entries():
        endpoint = entry.to_account if inbound else entry.from_account
        if endpoint in labels and entry.kind in kinds:
            total += entry.amount
    return total


def _owned_labels(sim: _Year, person, classes) -> list[str]:
    return [
        account_label(a)
        for a in sim.model.agents
        if isinstance(a, classes) and (person is None or getattr(a, "person", None) is person)
    ]


def _information_return_simulated(sim: _Year, item, r: "TaxReturn | None") -> dict[str, tuple[float | None, str]]:
    """``box -> (simulated, cause when None)`` for a 1099 / 1098 / 5498 / 8606."""
    from .account.bank import BankAccount
    from .account.brokerage import BrokerageAccount
    from .account.job401k import Job401kAccount
    from .account.traditional_IRA import TraditionalIRA

    person = sim.person(item.person)
    labels = [sim.label(item.account)] if item.account is not None else None
    agent = sim.built.items.get(item.account) if item.account is not None else None
    form = item.form
    if form == "1099-INT":
        labels = labels or _owned_labels(sim, person, BankAccount)
        return {
            "1": (_account_flows(sim, labels, [FlowKind.INTEREST.value], inbound=True), ""),
            "8": (r.tax_exempt_interest if r is not None and item.account is None else 0.0, ""),
            "4": (None, "timing"),
        }
    if form == "1099-DIV":
        labels = labels or _owned_labels(sim, person, BrokerageAccount)
        dividends = _account_flows(sim, labels, [FlowKind.DIVIDEND.value], inbound=True)
        return {"1a": (dividends, ""), "1b": (dividends, ""), "2a": (0.0, ""), "4": (None, "timing")}
    if form == "1099-B":
        labels = labels or _owned_labels(sim, person, BrokerageAccount)
        return {
            "1d": (_account_flows(sim, labels, [FlowKind.SALE.value], inbound=False), ""),
            "1e": (None, "missing_input"),
            "4": (None, "timing"),
        }
    if form == "1099-R":
        labels = labels or _owned_labels(sim, person, (TraditionalIRA, Job401kAccount))
        # A qualified charitable distribution (a gift straight from the IRA) is a distribution too.
        kinds = [FlowKind.RMD.value, FlowKind.WITHDRAWAL.value, FlowKind.GIFT.value]
        paid = _account_flows(sim, labels, kinds, inbound=False)
        return {"1": (paid, ""), "2a": (paid, ""), "4": (None, "timing")}
    if form == "SSA-1099":
        benefits = sum(
            e.amount
            for e in sim.entries()
            if e.kind == FlowKind.BENEFIT.value
            and e.source == "Social Security"
            and (person is None or e.agent_id == person.unique_id or _owner_of(sim, e.to_account) == person)
        )
        return {"3": (benefits, ""), "4": (0.0, ""), "5": (benefits, ""), "6": (None, "timing")}
    if form == "1098":
        mortgage = getattr(agent, "mortgage", None) if agent is not None else None
        tax = getattr(agent, "property_tax_for_year", None) if agent is not None else None
        return {
            "1": (mortgage.interest_paid_this_year if mortgage is not None else None, "missing_input"),
            "10": (tax, "missing_input"),
        }
    if form == "1098-E":
        return {"1": (getattr(agent, "interest_paid_this_year", None), "missing_input")}
    if form == "5498":
        contributions = _account_flows(sim, labels or [], [FlowKind.CONTRIBUTION.value], inbound=True)
        closing = sim.model.balance_sheets[sim.year].closing.lines.get(labels[0]) if labels else None
        return {"1": (contributions if labels else None, "missing_input"), "5": (closing, "missing_input")}
    return {box: (None, "missing_input") for box in item.boxes}  # Form 8606 basis: Plan 27 D1


def _owner_of(sim: _Year, label: str | None):
    if label is None:
        return None
    for agent in sim.model.agents:
        if account_label(agent) == label:
            return getattr(agent, "person", None)
    return None


# --------------------------------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------------------------------


def _classify(item: ReconciliationLine, rows: dict[tuple[str, str], ReconciliationLine]) -> str:
    if item.simulated is None:
        return item.cause or "missing_input"
    simulated, actual = item.simulated, item.actual
    if actual and simulated:
        for factor in (12.0, 100.0):
            for ratio in (factor, 1 / factor):
                if math.isclose(actual, simulated * ratio, rel_tol=0.01):
                    return "unit_mismatch"
    line = item.line
    if item.section == "1040":
        for upstream in _1040_INPUTS.get(line, ()):
            key = upstream if ":" in upstream else f"1040:{upstream}"
            other = rows.get((item.source, key))
            if other is not None and other.status in (RED, YELLOW):
                root = getattr(other, "_root", None) or other
                item._root = root
                item.note = (item.note + " " if item.note else "") + f"follows {root.section} line {root.line}"
                return "propagated"
        if line in _CREDIT_LINES and actual > simulated:
            return "unmodeled_credit"
        if line in _DEDUCTION_LINES and actual > simulated:
            return "unmodeled_deduction"
        if line in _INCOME_LINES:
            return "missing_income_source" if abs(simulated) < 0.005 else "input_difference"
        return "unexplained"
    if item.section in _CREDIT_SECTIONS:
        return "unmodeled_credit" if actual > simulated else "unexplained"
    adjustment = item.section == "schedule 1" and int("".join(c for c in line if c.isdigit()) or 0) >= 11
    if (adjustment or item.section in ("schedule A", "schedule 1-A")) and actual > simulated:
        return "unmodeled_deduction"
    if abs(simulated) < 0.005 and actual > 0:
        return "missing_income_source"
    return "input_difference"


# --------------------------------------------------------------------------------------------------
# reconcile()
# --------------------------------------------------------------------------------------------------


def reconcile(
    spec: "HouseholdSpec",
    year: int,
    *,
    actuals: "ActualRecords | None" = None,
    seed: int | None = None,
    config=None,
    tolerances: "dict[str, Tolerance] | None" = None,
    checks: str = "off",
) -> ReconciliationReport:
    """Run ``spec`` through ``year`` and compare it with the year's actual records.

    Args:
        spec: The household (balances as of the start of ``meta.start_year``; for the cleanest
            comparison start the spec in ``year``).
        year: The tax year to reconcile (``>= meta.start_year``).
        actuals: The records to compare (default: ``spec.actuals[year]``).
        seed: Random seed (overrides ``meta.seed``).
        config: Financial config for the run.
        tolerances: Overrides of :data:`TOLERANCES` (same keys).
        checks: Invariant-checker mode for the run (``"strict"``, ``"warn"``, ``"off"``).
    """
    from .spec.actuals import FORM_1040_LINES, SCHEDULE_LINES, W2_BOXES, line_table_year

    if actuals is None:
        actuals = (spec.actuals or {}).get(year)
    if actuals is None:
        raise ValueError(f"No actual records for {year}: add actuals.{year} to the spec or pass actuals=")
    sim = run_for_reconciliation(spec, year, seed=seed, config=config, checks=checks)
    report = ReconciliationReport(household=spec.meta.name, year=year, seed=sim.model.initial_seed)
    table_year = line_table_year(year)
    labels_1040 = FORM_1040_LINES[table_year]
    schedule_labels = SCHEDULE_LINES[table_year]
    rows: list[ReconciliationLine] = []

    def add(section, line, label, actual, simulated, *, cause=None, note="", source=""):
        rows.append(
            ReconciliationLine(section, line, label, float(actual), simulated, cause=cause, note=note, source=source)
        )

    for actual_return, sim_return, source in _returns_for(sim, actuals):
        if sim_return is None:
            report.notes.append(f"{source or 'a return'}: no simulated return matched (name the filer)")
        sim_1040 = form_1040_lines(sim_return) if sim_return is not None else {}
        for line, amount in actual_return.form_1040.items():
            cause = "timing" if line in _PAYMENT_LINES else "unmodeled_line" if line not in sim_1040 else None
            note = "withholding and the April settlement are not modeled (Plan 31 D3)" if line in _PAYMENT_LINES else ""
            add(
                "1040",
                line,
                labels_1040.get(line, line),
                amount,
                sim_1040.get(line),
                cause=cause,
                note=note,
                source=source,
            )
        sim_schedules = schedule_lines(sim_return) if sim_return is not None else {}
        for name, lines in actual_return.schedules.items():
            for line, amount in lines.items():
                simulated = sim_schedules.get(name, {}).get(line)
                label = schedule_labels.get(name, {}).get(line, line)
                add(
                    f"schedule {name}",
                    line,
                    label,
                    amount,
                    simulated,
                    cause=None if simulated is not None else "unmodeled_line",
                    source=source,
                )
        state = actual_return.state_return
        if state is not None and sim_return is not None:
            detail = sim_return.state_return
            for name, value, sim_value in (
                ("agi", state.agi, detail.income if detail else None),
                ("taxable_income", state.taxable_income, detail.taxable_income if detail else None),
                ("tax", state.tax, sim_return.state_tax),
                ("withheld", state.withheld, None),
            ):
                if value is not None:
                    add(
                        "state",
                        name,
                        f"{state.state} {name.replace('_', ' ')}",
                        value,
                        sim_value,
                        cause="timing" if name == "withheld" else None,
                        source=source,
                    )
            if detail is not None and detail.state != state.state:
                report.notes.append(f"state return is {state.state} but the model filed in {detail.state}")

    for w2 in actuals.w2:
        person = sim.person(w2.person)
        source = f"{w2.employer} / {w2.person or (person.name if person else '?')}"
        simulated = _w2_simulated(sim, person, w2.employer) if person is not None else {}
        for box, amount in w2.boxes.items():
            cause = "timing" if box in ("2", "17", "19") else None
            sim_value = simulated.get(box)
            if sim_value is None and cause is None:
                cause = "unmodeled_line"
            add("W-2", f"box {box}", W2_BOXES.get(box, box), amount, sim_value, cause=cause, source=source)
        for code, amount in w2.box12.items():
            sim_value = simulated.get(f"12:{code}")
            add(
                "W-2",
                f"box 12{code}",
                f"Box 12 code {code}",
                amount,
                sim_value,
                cause=None if sim_value is not None else "missing_input",
                note="" if sim_value is not None else "payroll deductions other than 401k are Plan 27 D3",
                source=source,
            )

    from .spec.actuals import FORM_1099_BOXES

    returns = sim.model.tax_returns.for_year(year)
    for item in actuals.form_1099:
        sim_return = returns[0] if len(returns) == 1 else None
        simulated = _information_return_simulated(sim, item, sim_return)
        source = " / ".join(part for part in (item.payer, item.account, item.person) if part)
        for box, amount in item.boxes.items():
            sim_value, cause = simulated.get(box, (None, "unmodeled_line"))
            add(
                item.form,
                f"box {box}",
                FORM_1099_BOXES.get(item.form, {}).get(box, box),
                amount,
                sim_value,
                cause=cause if sim_value is None else None,
                source=source,
            )

    for stub in actuals.paystub:
        person = sim.person(stub.person)
        if person is None:
            continue
        employers = [stub.employer] if stub.employer else sorted({j.company for j in person.jobs})
        flows = {"gross": 0.0, "pretax": 0.0, "roth": 0.0}
        for employer in employers:
            for k, v in _employer_flows(sim, person, employer).items():
                flows[k] += v
        source = f"{stub.employer or 'all jobs'} / {stub.person or person.name}"
        if stub.gross_monthly is not None:
            add("paystub", "gross", "Gross pay (monthly)", stub.gross_monthly, flows["gross"] / 12, source=source)
        for name, amount in stub.pretax_deductions_monthly.items():
            sim_value = {"401k": flows["pretax"] / 12, "roth_401k": flows["roth"] / 12}.get(name)
            add(
                "paystub",
                name,
                f"{name} deduction (monthly)",
                amount,
                sim_value,
                cause=None if sim_value is not None else "missing_input",
                note="" if sim_value is not None else "payroll deductions are Plan 27 D3",
                source=source,
            )
        for name, amount in (("federal_withholding", stub.federal_withholding_monthly), ("net", stub.net_monthly)):
            if amount is not None:
                add(
                    "paystub",
                    name,
                    f"{name.replace('_', ' ')} (monthly)",
                    amount,
                    None,
                    cause="timing",
                    note="withholding is not modeled (Plan 31 D3)",
                    source=source,
                )

    closing = sim.model.balance_sheets[year].closing.lines
    for item_id, amount in actuals.balances.items():
        label = sim.label(item_id)
        value = closing.get(label) if label is not None else None
        add(
            "balance",
            item_id,
            f"{sim.model.ledger.describe(label) if label else item_id} at Dec 31",
            amount,
            None if value is None else abs(value),
            cause=None if value is not None else "missing_input",
        )

    if actuals.spending is not None:
        _spending_lines(sim, actuals.spending, add)

    by_key: dict[tuple[str, str], ReconciliationLine] = {}
    for row in rows:
        tolerance = tolerance_for(row.section, row.line, tolerances)
        if row.simulated is None:
            row.status = NOT_MODELED
            row.cause = row.cause or "missing_input"
        else:
            row.status = tolerance.status(row.simulated - row.actual, row.actual)
            row.cause = None
        by_key.setdefault((row.source, row.key), row)
    # Classify schedules and documents first, then the 1040 in line order, so a total finds the root
    # of a difference it carries.
    for row in sorted(rows, key=lambda r: (r.section == "1040", _row_order(r))):
        if row.status in (RED, YELLOW):
            row.cause = _classify(row, by_key)
    report.lines = sorted(rows, key=_row_order)
    if any(r.cause == "timing" for r in rows):
        report.notes.append(
            "Withholding, estimated payments and the refund are not modeled: taxes settle as one year-end lump."
        )
    return report


_SECTION_ORDER = ("1040", "schedule 1", "schedule 1-A", "schedule 2", "schedule 3", "schedule A", "schedule B")


def _line_number(line: str) -> tuple:
    import re

    match = re.match(r"(?:box )?(\d+)(.*)", line)
    return (int(match.group(1)), match.group(2)) if match else (10**6, line)


def _row_order(row: ReconciliationLine) -> tuple:
    section = _SECTION_ORDER.index(row.section) if row.section in _SECTION_ORDER else len(_SECTION_ORDER)
    return (
        row.source if row.section in _SECTION_ORDER or row.section == "state" else "",
        section,
        row.section,
        row.source,
        _line_number(row.line),
    )


def _spending_lines(sim: _Year, spending, add) -> None:
    """Calibration (D6): the model's assumed amounts next to the household's actual spending."""
    sinks: dict[str, float] = {}
    housing = 0.0
    for entry in sim.entries():
        if entry.sink is not None and entry.kind in (FlowKind.SPENDING.value, FlowKind.PREMIUM.value):
            sinks[entry.sink] = sinks.get(entry.sink, 0.0) + entry.amount
        if entry.kind == FlowKind.HOUSING.value and entry.sink is not None:
            housing += entry.amount
    lines = (
        ("living_annual", "Living spending", sinks.get("living expenses", 0.0), "people[].spending.amount_annual"),
        (
            "medical_out_of_pocket_annual",
            "Out-of-pocket medical",
            sinks.get("medical", 0.0),
            "config healthcare.medical_cost_bands (per-person override: Plan 27 D9)",
        ),
        (
            "medicare_premiums_annual",
            "Medicare premiums",
            sinks.get("medicare premium", 0.0),
            "config healthcare.medicare (IRMAA from MAGI two years back)",
        ),
        (
            "dependent_costs_annual",
            "Child and dependent costs",
            sinks.get("dependents", 0.0),
            "config dependents cost bands (per-child override: Plan 27 D6)",
        ),
        ("housing_annual", "Housing costs", housing, "people[].housing"),
    )
    for name, label, assumed, knob in lines:
        actual = getattr(spending, name)
        if actual is not None:
            add("spending", name, label, actual, assumed, note=f"assumed by: {knob}")
