# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Validate a household before it runs.

:func:`validate_spec` checks a :class:`~life_model.spec.schema.HouseholdSpec` (or raw dict / JSON
data, whose schema errors are reported as findings too); :func:`validate_model` runs the same
checks on an already-constructed :class:`~life_model.model.LifeModel` (``LifeModel.validate()``),
so households written in Python get them as well.

Each problem is a :class:`Finding` ``(level, path, message, fix, code)``.

Errors (the builder refuses to build): schema errors, unknown state pack, person without a bank
account, negative balance, event before the start year, ``retirement_age < age`` for a person who
still has a job, Social Security claim age below 62, a ``not_yet_supported`` field set, duplicate
ids and dangling references.

Warnings: fraction-looking percent, two unmarried adults in one family, every investment account
on fixed growth (Monte Carlo becomes a no-op for them), mortgage term/origination/balance
inconsistent, rent left at the 5% core default, spending or salary with 0% growth, a bank account
standing in for bonds/CDs/Treasuries, several bank accounts without a primary, an event after the
end year, a dependent-care FSA with no child under 13, a child whose income is over the Form 8814
limit (the child's own return is not modeled).
"""

import re
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import BaseModel, ValidationError

from ..config.financial_config import FinancialConfig, default_financial_config
from ..config.models import DEFAULT_STATE_KEY
from . import schema as s

Level = Literal["error", "warning"]
ERROR: Level = "error"
WARNING: Level = "warning"

#: Adults (for the "two adults not married" warning) are at least this old.
ADULT_AGE = 18
#: Relative difference between an entered mortgage balance and the amortized one that warns.
MORTGAGE_BALANCE_TOLERANCE = 0.15
#: Relative difference between an entered payment and the computed P&I payment that warns.
MORTGAGE_PAYMENT_TOLERANCE = 0.05
#: Bank account names/types that look like a stand-in for a fixed-income holding.
_BOND_LIKE = re.compile(r"\b(bonds?|treasur(y|ies)|t-?bills?|cds?|certificates?|i-?bonds?)\b", re.IGNORECASE)
#: Account kinds whose growth follows the economy when growth_pct is "economy".
_INVESTMENT_KINDS = ("brokerage", "401k", "traditional_ira", "roth_ira", "hsa", "529", "trust")


@dataclass(frozen=True)
class Finding:
    """One validation finding: ``level`` is ``"error"`` (the household cannot be built as written) or
    ``"warning"``; ``path`` locates it in the spec (e.g. ``people[0].accounts[1].interest_pct``; for
    a model, ``person[Alex].bank_accounts``); ``message`` says what is wrong; ``fix`` how to fix it
    (None when obvious); ``code`` is a stable machine-readable code such as ``not_yet_supported``
    or ``fraction_percent``."""

    level: Level
    path: str
    message: str
    fix: str | None = None
    code: str = "invalid"

    def __str__(self) -> str:
        fix = f" Fix: {self.fix}" if self.fix else ""
        return f"[{self.level}] {self.path}: {self.message}{fix}"


def errors(findings: list[Finding]) -> list[Finding]:
    """The error-level findings."""
    return [f for f in findings if f.level == ERROR]


def warnings_of(findings: list[Finding]) -> list[Finding]:
    """The warning-level findings."""
    return [f for f in findings if f.level == WARNING]


# --- Generic walks ---------------------------------------------------------------------------------


def _walk(obj: Any, path: str):
    """Yield ``(path, model)`` for every spec model nested in ``obj``."""
    if isinstance(obj, BaseModel):
        yield path, obj
        for name in type(obj).model_fields:
            yield from _walk(getattr(obj, name), f"{path}.{name}" if path else name)
    elif isinstance(obj, (list, tuple)):
        for index, item in enumerate(obj):
            yield from _walk(item, f"{path}[{index}]")
    elif isinstance(obj, dict):
        for key, item in obj.items():
            yield from _walk(item, f"{path}[{key}]")


def _extra(field_info) -> dict:
    extra = field_info.json_schema_extra
    return extra if isinstance(extra, dict) else {}


def not_yet_supported_findings(spec: s.HouseholdSpec) -> list[Finding]:
    """An error for every ``not_yet_supported`` model or field the spec uses."""
    findings: list[Finding] = []
    for path, model in _walk(spec, ""):
        plan = getattr(type(model), "NOT_YET_SUPPORTED", None)
        if plan and not any(f.path == path for f in findings):
            label = getattr(model, "kind", None) or getattr(model, "action", None) or type(model).__name__
            findings.append(
                Finding(
                    ERROR,
                    path,
                    f"'{label}' is not yet supported by the engine ({plan}).",
                    "Remove it, or model it another way until that plan lands.",
                    "not_yet_supported",
                )
            )
        for name, info in type(model).model_fields.items():
            plan = _extra(info).get(s.NYS_KEY)
            if not plan:
                continue
            value = getattr(model, name)
            if value != info.get_default(call_default_factory=True):
                findings.append(
                    Finding(
                        ERROR,
                        f"{path}.{name}" if path else name,
                        f"'{name}' is not yet supported by the engine ({plan}).",
                        "Remove the field (the engine would silently ignore it).",
                        "not_yet_supported",
                    )
                )
    return findings


def fraction_percent_findings(spec: s.HouseholdSpec) -> list[Finding]:
    """Warn for ``_pct`` fields holding a fraction where the typical value is above 1."""
    findings: list[Finding] = []
    for path, model in _walk(spec, ""):
        for name, info in type(model).model_fields.items():
            if not _extra(info).get(s.ABOVE_ONE_KEY):
                continue
            value = getattr(model, name)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value < 1:
                findings.append(_fraction_finding(f"{path}.{name}" if path else name, value))
    return findings


def _fraction_finding(path: str, value: float) -> Finding:
    return Finding(
        WARNING,
        path,
        f"{value:g} looks like a fraction; percent fields take 4.5 for 4.5%, so this is {value:g}%.",
        f"did you mean {value * 100:g}?",
        "fraction_percent",
    )


# --- Spec validation -----------------------------------------------------------------------------


def _schema_findings(error: ValidationError) -> list[Finding]:
    findings = []
    for err in error.errors():
        loc = ""
        for part in err["loc"]:
            if isinstance(part, int):
                loc += f"[{part}]"
            else:
                loc += f".{part}" if loc else str(part)
        findings.append(Finding(ERROR, loc or "(root)", err["msg"], None, f"schema.{err['type']}"))
    return findings


def validate_spec(spec: s.HouseholdSpec | dict | str, *, config: FinancialConfig | None = None) -> list[Finding]:
    """Validate a spec (a ``HouseholdSpec``, a dict, or JSON text); returns every finding.

    Raw data that fails the schema returns the schema errors (the semantic checks need a valid
    spec). ``config`` supplies the state packs and Social Security ages (packaged defaults when
    None).
    """
    if not isinstance(spec, s.HouseholdSpec):
        try:
            spec = (
                s.HouseholdSpec.model_validate_json(spec)
                if isinstance(spec, str)
                else s.HouseholdSpec.model_validate(spec)
            )
        except ValidationError as error:
            return _schema_findings(error)
    config = config or default_financial_config()
    findings: list[Finding] = []
    findings += not_yet_supported_findings(spec)
    findings += fraction_percent_findings(spec)
    findings += _SpecChecker(spec, config).run()
    return findings


class _SpecChecker:
    def __init__(self, spec: s.HouseholdSpec, config: FinancialConfig):
        self.spec = spec
        self.config = config
        self.findings: list[Finding] = []
        self.start = spec.meta.start_year
        #: The first simulated month (meta.start's month; January when unset).
        self.start_month = int(spec.meta.start.split("-")[1]) if spec.meta.start is not None else 1
        self.end = spec.meta.end_year if spec.meta.end_year is not None else self.start + 50
        self.people = {p.id: p for p in spec.people}
        self.person_index = {p.id: i for i, p in enumerate(spec.people)}

    def error(self, path: str, message: str, fix: str | None = None, code: str = "invalid") -> None:
        self.findings.append(Finding(ERROR, path, message, fix, code))

    def warn(self, path: str, message: str, fix: str | None = None, code: str = "warning") -> None:
        self.findings.append(Finding(WARNING, path, message, fix, code))

    def run(self) -> list[Finding]:
        self.check_ids()
        self.check_start()
        self.check_states()
        self.check_births()
        self.check_people()
        self.check_marriages()
        self.check_events()
        self.check_unmarried_adults()
        self.check_growth()
        self.check_actuals()
        self.check_withholding_inputs()
        self.check_tax_inputs()
        return self.findings

    # --- Plan 31 tax inputs ---

    def check_tax_inputs(self) -> None:
        """Warn about Plan 31 inputs the engine treats in a way the user may not expect."""
        children = [child for p in self.spec.people for child in p.children]
        young = any(0 <= self.start - child.birth_year < 13 for child in children)
        for p_index, person in enumerate(self.spec.people):
            for j_index, job in enumerate(person.jobs):
                if job.payroll is not None and job.payroll.dependent_care_fsa_annual and not young:
                    self.warn(
                        f"people[{p_index}].jobs[{j_index}].payroll.dependent_care_fsa_annual",
                        "A dependent-care FSA with no child under 13 in the household: with no care expenses the "
                        "election is taxable wages (Form 2441 line 26).",
                        "Add the child (children[]), or remove the election.",
                        "fsa_without_care",
                    )
            for c_index, child in enumerate(person.children):
                gross = child.interest_annual + child.dividends_annual
                params = self.config.tax_year(self.start).kiddie_tax
                if params is not None and gross >= 10 * params.base_amount:
                    self.warn(
                        f"people[{p_index}].children[{c_index}]",
                        f"The child's interest and dividends (${gross:,.0f}) are over the Form 8814 limit "
                        f"(${10 * params.base_amount:,.0f}): the child files their own return (Form 8615), which "
                        "the model does not include.",
                        None,
                        "child_files_own_return",
                    )

    # --- the first month and birth months ---

    def check_start(self) -> None:
        start = self.spec.meta.start
        if start is not None and int(start.split("-")[0]) != self.start:
            self.error(
                "meta.start",
                f"start {start} is not in start_year {self.start}.",
                f"use start: {self.start}-MM, or change start_year.",
                "start_mismatch",
            )

    def check_births(self) -> None:
        for i, p in enumerate(self.spec.people):
            path = f"people[{i}]"
            if p.birth is None:
                self.warn(
                    f"{path}.birth",
                    f"{p.name} has no birth month; January is assumed, so 59.5, the retirement month and other "
                    "exact-age thresholds fall in January-based months.",
                    f"set birth: YYYY-MM (age {p.age} in {self.start}-{self.start_month:02d}).",
                    "birth_assumed",
                )
                continue
            year, month = (int(part) for part in p.birth.split("-"))
            age = ((self.start * 12 + self.start_month) - (year * 12 + month)) // 12
            if age != p.age:
                self.error(
                    f"{path}.birth",
                    f"birth {p.birth} makes {p.name} {age} in {self.start}-{self.start_month:02d}, not {p.age}.",
                    "make age the completed years in the first simulated month.",
                    "birth_age_mismatch",
                )

    # --- actual records (Plan 29) ---

    def check_actuals(self) -> None:
        """``actuals``: line names exist on that year's forms, and every person/account id resolves."""
        if not self.spec.actuals:
            return
        from .actuals import LINE_TABLE_YEARS, unknown_lines

        ids = self.item_ids()
        for year, records in self.spec.actuals.items():
            base = f"actuals.{year}"
            if year < self.start or year > self.end:
                self.warn(
                    base,
                    f"actual records for {year} are outside the simulated years {self.start}-{self.end}",
                    "reconcile a simulated year (start the spec at the year of the records), or run a backtest",
                    "actuals_outside_run",
                )
            if not LINE_TABLE_YEARS[0] <= year <= LINE_TABLE_YEARS[-1]:
                self.warn(
                    base,
                    f"no Form 1040 line table for {year}; reconcile reads it with the nearest year's line numbers",
                    None,
                    "actuals_line_table",
                )
            for path, line in unknown_lines(records, year):
                self.error(
                    f"{base}.{path}",
                    f"{line!r} is not a line of the {year} forms",
                    "use the official line number of that year (docs/reconciliation.md lists them)",
                    "unknown_line",
                )
            for i, tax_return in enumerate(records.returns):
                if tax_return.filer is not None and tax_return.filer not in self.people:
                    self.error(
                        f"{base}.returns[{i}].filer", f"unknown person {tax_return.filer!r}", None, "unknown_ref"
                    )
            for collection, items in (
                ("w2", records.w2),
                ("form_1099", records.form_1099),
                ("paystub", records.paystub),
            ):
                for i, item in enumerate(items):
                    if item.person is not None and item.person not in self.people:
                        self.error(
                            f"{base}.{collection}[{i}].person", f"unknown person {item.person!r}", None, "unknown_ref"
                        )
                    account = getattr(item, "account", None)
                    if account is not None and account not in ids:
                        self.error(
                            f"{base}.{collection}[{i}].account", f"unknown account id {account!r}", None, "unknown_ref"
                        )
            for account in records.balances:
                if account not in ids:
                    self.error(
                        f"{base}.balances.{account}",
                        f"unknown account or debt id {account!r}",
                        "give the account an 'id' in the spec and use it here",
                        "unknown_ref",
                    )

    # --- ids and references ---

    def item_ids(self) -> dict[str, tuple[str, str, Any]]:
        """Every item id -> (person id, collection, item), including items added by events."""
        ids: dict[str, tuple[str, str, Any]] = {}
        for p in self.spec.people:
            for collection in ("jobs", "accounts", "debts", "housing", "insurance", "giving", "children"):
                for item in getattr(p, collection):
                    if item.id is not None:
                        ids.setdefault(item.id, (p.id, collection, item))
        for event in self.spec.events:
            for collection, item in _event_items(event):
                if item.id is not None:
                    ids.setdefault(item.id, (event.person, collection, item))
        return ids

    def check_ids(self) -> None:
        seen: dict[str, str] = {}

        def claim(identifier: str | None, path: str) -> None:
            if identifier is None:
                return
            if identifier in seen:
                self.error(path, f"duplicate id {identifier!r} (also at {seen[identifier]})", code="duplicate_id")
            else:
                seen[identifier] = path

        for i, p in enumerate(self.spec.people):
            claim(p.id, f"people[{i}].id")
            for collection in ("jobs", "accounts", "debts", "housing", "insurance", "giving", "children"):
                for j, item in enumerate(getattr(p, collection)):
                    claim(item.id, f"people[{i}].{collection}[{j}].id")
        for i, event in enumerate(self.spec.events):
            claim(event.id, f"events[{i}].id")
            for collection, item in _event_items(event):
                claim(item.id, f"events[{i}].{collection}.id")

    def check_states(self) -> None:
        packs = set(self.config.tax.state.packs)

        def check(code: str | None, path: str) -> None:
            if code is None or code == DEFAULT_STATE_KEY:
                return
            if code not in packs:
                self.error(
                    path,
                    f"no state tax pack for {code!r}; the engine refuses a state it has no tax pack for.",
                    f"use one of {sorted(c for c in packs if c != DEFAULT_STATE_KEY)}, or 'DEFAULT' (a flat "
                    "rate on the federal-style base) deliberately.",
                    "unknown_state",
                )

        check(self.spec.meta.default_state, "meta.default_state")
        for i, p in enumerate(self.spec.people):
            check(p.state, f"people[{i}].state")
            for k, (when, code) in enumerate(p.residency or ()):
                check(code, f"people[{i}].residency[{k}]")
        for i, event in enumerate(self.spec.events):
            if isinstance(event, s.MoveEvent):
                check(event.state, f"events[{i}].state")

    # --- people ---

    def check_people(self) -> None:
        min_claim = self.config.social_security.min_early_retirement_age
        claim_events = {e.person: e for e in self.spec.events if isinstance(e, s.ClaimSocialSecurityEvent)}
        bank_added_later = {
            e.person for e in self.spec.events if isinstance(e, s.AddAccountEvent) and e.account.kind == "bank"
        }
        for i, p in enumerate(self.spec.people):
            path = f"people[{i}]"
            banks = [a for a in p.accounts if a.kind == "bank"]
            if not banks:
                hint = (
                    " (an add_account event opens one later, but income before then is lost)"
                    if p.id in bank_added_later
                    else ""
                )
                self.error(
                    f"{path}.accounts",
                    f"{p.name} has no bank account{hint}; income would go to an untracked cash bucket.",
                    "add {kind: bank, balance: ...}.",
                    "no_bank_account",
                )
            if banks and all(a.reserve for a in banks):
                self.error(
                    f"{path}.accounts",
                    f"{p.name}'s only bank accounts are emergency reserves; income needs a spending account.",
                    "add a bank account without reserve: true.",
                    "only_reserve_banks",
                )
            primaries = [a for a in banks if a.primary]
            if len(primaries) > 1:
                self.error(
                    f"{path}.accounts", f"{p.name} has {len(primaries)} primary bank accounts.", "mark only one."
                )
            elif len(banks) > 1 and not primaries:
                self.warn(
                    f"{path}.accounts",
                    f"{p.name} has {len(banks)} bank accounts and none is primary; income goes to the first in "
                    "canonical order.",
                    "set primary: true on the account that receives income.",
                    "no_primary_bank",
                )
            for j, bank in enumerate(p.accounts):
                if bank.kind == "bank" and (_BOND_LIKE.search(bank.company) or _BOND_LIKE.search(bank.type)):
                    self.warn(
                        f"{path}.accounts[{j}]",
                        f"bank account '{bank.company} {bank.type}' looks like a stand-in for bonds/CDs/Treasuries; "
                        "it is spent like checking and its interest is not taxed.",
                        "use kind: fixed_income (a CD, Treasury, I bond or bond fund), or reserve: true for an emergency "
                        "fund.",
                        "bonds_as_bank",
                    )
            if p.jobs and p.retirement_age < p.age:
                self.error(
                    f"{path}.retirement_age",
                    f"retirement_age {p.retirement_age:g} is below age {p.age}; every job stops in the first year.",
                    "raise retirement_age, or remove the jobs of a person who is already retired.",
                    "retirement_before_age",
                )
            if p.social_security is not None:
                claim = p.social_security.claim_age
                source = f"{path}.social_security.claim_age"
                if p.id in claim_events:
                    claim = None  # the event's age is checked in check_events
                elif claim is None:
                    claim, source = p.retirement_age, f"{path}.retirement_age"
                if claim is not None and claim < min_claim:
                    self.error(
                        source,
                        f"Social Security claim age {claim:g} is below {min_claim} (core raises).",
                        f"set social_security.claim_age to {min_claim} or later.",
                        "ss_claim_too_early",
                    )
            if p.spending.growth_pct == 0:
                self.warn(
                    f"{path}.spending.growth_pct",
                    "spending grows 0%/yr (the core default), so it shrinks in real terms.",
                    "set growth_pct: economy (follows inflation) or a percentage.",
                    "zero_growth",
                )
            for j, account in enumerate(p.accounts):
                if isinstance(account, s.Job401k) and account.company_match_pct:
                    pct = account.company_match_pct
                    self.warn(
                        f"{path}.accounts[{j}].company_match_pct",
                        f"company_match_pct is deprecated: {pct:g} means a {pct:g}% match on each deferred dollar, "
                        f"capped at {pct:g}% of pay.",
                        f"use match_tiers; a dollar-for-dollar match up to {pct:g}% of pay is "
                        f"[{{match_pct: 100, up_to_pay_pct: {pct:g}}}].",
                        "deprecated_match",
                    )
            for j, job in enumerate(p.jobs):
                if job.raise_pct == 0:
                    self.warn(
                        f"{path}.jobs[{j}].raise_pct",
                        f"salary at {job.company} never rises (0%/yr, the core default).",
                        "set raise_pct: economy (follows wage growth) or a percentage.",
                        "zero_growth",
                    )
            job_ids = {job.id for job in p.jobs if job.id is not None} | {
                e.new_job.id
                for e in self.spec.events
                if isinstance(e, s.ChangeJobEvent) and e.person == p.id and e.new_job is not None and e.new_job.id
            }
            child_ids = {c.id for c in p.children if c.id is not None}
            for j, account in enumerate(p.accounts):
                apath = f"{path}.accounts[{j}]"
                self.check_account_refs(account, apath, job_ids, child_ids)
                self.check_account_plan27(account, apath)
            self.check_policies(p, path)
            self.check_payroll(p, path)
            for e_index, event in enumerate(self.spec.events):
                if isinstance(event, s.AddAccountEvent) and event.person == p.id:
                    self.check_account_refs(event.account, f"events[{e_index}].account", job_ids, child_ids)
            for j, item in enumerate(p.housing):
                if isinstance(item, s.Rental) and "rent_growth_pct" not in item.model_fields_set:
                    self.warn(
                        f"{path}.housing[{j}].rent_growth_pct",
                        "rent grows 5%/yr by default (the core default), well above typical inflation.",
                        "set rent_growth_pct explicitly (or 'economy').",
                        "default_rent_growth",
                    )
                if isinstance(item, s.Home) and item.mortgage is not None:
                    self.check_mortgage(item.mortgage, f"{path}.housing[{j}].mortgage")
            home_ids = {h.id for h in p.housing if isinstance(h, s.Home) and h.id is not None}
            for j, debt in enumerate(p.debts):
                if isinstance(debt, s.CarLoan | s.StudentLoan):
                    self.check_loan(debt, f"{path}.debts[{j}]")
                if isinstance(debt, s.HomeEquityLine) and debt.home not in home_ids:
                    self.error(
                        f"{path}.debts[{j}].home",
                        f"unknown home {debt.home!r} (must be one of this person's homes with an id)",
                        code="unknown_reference",
                    )
            for j, policy in enumerate(p.insurance):
                if isinstance(policy, s.LifeInsurance) and policy.beneficiary is not None:
                    self.check_person_ref(policy.beneficiary, f"{path}.insurance[{j}].beneficiary")
                if (
                    isinstance(policy, s.LifeInsurance)
                    and policy.policy == "term"
                    and (policy.cash_value or policy.loan_balance)
                ):
                    self.error(
                        f"{path}.insurance[{j}]",
                        "a term policy has no cash value or policy loan.",
                        "remove cash_value / loan_balance, or set policy: whole.",
                    )
                if (
                    isinstance(policy, s.LifeInsurance)
                    and policy.issue_year is not None
                    and policy.issue_year > self.start
                ):
                    self.error(
                        f"{path}.insurance[{j}].issue_year",
                        f"issue_year {policy.issue_year} is after the start year (a later policy belongs in an event).",
                    )
            self.check_plan27_insurance_and_benefits(p, path)

    def check_plan27_insurance_and_benefits(self, p: s.Person, path: str) -> None:
        """Plan 27 PR D cross-field checks: annuities in payout, pension rollovers, Social Security."""
        ira_ids = {a.id for a in p.accounts if a.kind == "traditional_ira" and a.id is not None}
        for j, account in enumerate(p.accounts):
            apath = f"{path}.accounts[{j}]"
            if isinstance(account, s.Annuity) and account.in_payout:
                if not account.payout_monthly:
                    self.error(f"{apath}.payout_monthly", "an annuity in payout needs its payout_monthly.")
                if account.balance:
                    self.error(f"{apath}.balance", "an annuity in payout has no accumulation balance (set it to 0).")
            if isinstance(account, s.Annuity) and account.qualified and account.basis:
                self.error(f"{apath}.basis", "a qualified annuity has no after-tax basis.")
            if isinstance(account, s.Pension) and account.rollover_account is not None:
                if account.rollover_account not in ira_ids:
                    self.error(
                        f"{apath}.rollover_account",
                        f"unknown traditional IRA {account.rollover_account!r} (must be one of this person's "
                        "traditional_ira ids)",
                        code="unknown_reference",
                    )
                if not account.lump_sum_option:
                    self.warn(
                        f"{apath}.rollover_account",
                        "rollover_account is only used with lump_sum_option.",
                        code="unused_field",
                    )
        ss = p.social_security
        if ss is not None:
            birth_year = int(p.birth.split("-")[0]) if p.birth is not None else self.start - p.age
            if not ss.fra_from_birth_year and birth_year < 1960:
                self.warn(
                    f"{path}.social_security.fra_from_birth_year",
                    f"{p.name} was born in {birth_year}: the full retirement age for that birth year is below the "
                    "configured 67, so early reductions and delayed credits are off.",
                    "set fra_from_birth_year: true.",
                    "ss_fra_by_birth_year",
                )
            if ss.spousal_benefit:
                spouse_ids = {
                    pid for m in self.spec.relationships.marriages if p.id in m.spouses for pid in m.spouses
                } - {p.id}
                spouses = [q for q in self.spec.people if q.id in spouse_ids]
                if not spouses or all(q.social_security is None for q in spouses):
                    self.warn(
                        f"{path}.social_security.spousal_benefit",
                        f"{p.name} has no spouse with social_security, so there is no spousal benefit.",
                        code="unused_field",
                    )
        if any(isinstance(e, s.DisabilityEvent) and e.person == p.id for e in self.spec.events) and not any(
            isinstance(policy, s.GeneralInsurance) and policy.kind == "disability" and policy.benefit_pct
            for policy in p.insurance
        ):
            self.warn(
                f"{path}.insurance",
                f"{p.name} has a disability event but no disability policy with benefit_pct: the jobs stop with "
                "no income replacement.",
                code="no_disability_policy",
            )

    def check_account_plan27(self, account, path: str) -> None:
        """Plan 27 account rules: a standalone 401k takes no contributions; an allocation needs growth to
        follow the economy."""
        if isinstance(account, s.Job401k) and account.job is None:
            if account.pretax_contrib_pct or account.roth_contrib_pct or account.after_tax_contrib_pct:
                self.error(
                    f"{path}.job",
                    "a 401k without a job (an old employer's plan) takes no contributions.",
                    "remove the contribution percentages, or name the job offering the plan.",
                    "standalone_401k_contributions",
                )
            if account.match_tiers or account.company_match_pct:
                self.error(
                    f"{path}.match_tiers",
                    "a 401k without a job has no employer match.",
                    code="standalone_401k_contributions",
                )
        allocation = getattr(account, "allocation_pct", None)
        if allocation is not None:
            total = sum(allocation.values())
            if abs(total - 100) > 1e-6:
                self.error(
                    f"{path}.allocation_pct",
                    f"allocation must sum to 100 percent, got {total:g}.",
                    code="allocation_sum",
                )
            if getattr(account, "growth_pct", "economy") != "economy":
                self.warn(
                    f"{path}.allocation_pct",
                    "a numeric growth_pct overrides the allocation (and disconnects the account from stochastic runs).",
                    "set growth_pct: economy to grow at the allocation's blend of the economy's returns.",
                    "allocation_ignored",
                )

    def _person_accounts(self, p: s.Person) -> dict:
        accounts = {a.id: a for a in p.accounts if a.id is not None}
        for event in self.spec.events:
            if isinstance(event, s.AddAccountEvent) and event.person == p.id and event.account.id is not None:
                accounts[event.account.id] = event.account
        return accounts

    def check_policies(self, p: s.Person, path: str) -> None:
        """Contribution plans, the savings sweep and the Roth conversion name the person's own accounts of
        a kind they can use."""
        accounts = self._person_accounts(p)
        limited = ("401k", "traditional_ira", "roth_ira", "hsa", "529")
        for k, plan in enumerate(p.contribution_plans or ()):
            ppath = f"{path}.contribution_plans[{k}]"
            account = accounts.get(plan.account)
            if account is None:
                self.error(
                    f"{ppath}.account",
                    f"unknown account {plan.account!r} (one of {p.name}'s account ids)",
                    code="unknown_reference",
                )
                continue
            kind = account.kind
            if kind in ("pension", "annuity", "inherited_pretax", "trust", "daf"):
                self.error(f"{ppath}.account", f"recurring contributions to a {kind} account are not supported.")
            if kind == "401k":
                if plan.source != "payroll":
                    self.error(f"{ppath}.source", "401k contributions come from payroll (source: payroll).")
                if account.job is None:
                    self.error(f"{ppath}.account", "a 401k without a job takes no contributions.")
            elif plan.bucket is not None:
                self.error(f"{ppath}.bucket", "bucket is for 401k plans.")
            if plan.source == "payroll" and kind not in ("401k", "hsa"):
                self.error(f"{ppath}.source", "payroll contributions go to a 401k or an HSA; use source: bank.")
            if plan.source == "payroll" and kind == "hsa" and not p.jobs:
                self.error(f"{ppath}.source", f"{p.name} has no W-2 job to deduct the HSA contribution from.")
            if plan.max_out and kind not in limited:
                self.error(f"{ppath}.max_out", f"a {kind} account has no annual limit to max out.")
        policy = p.savings_policy
        if policy is not None:
            account = accounts.get(policy.sweep_to)
            if account is None:
                self.error(
                    f"{path}.savings_policy.sweep_to", f"unknown account {policy.sweep_to!r}", code="unknown_reference"
                )
            elif account.kind not in ("brokerage", "fixed_income", "bank", "traditional_ira", "roth_ira", "hsa", "529"):
                self.error(f"{path}.savings_policy.sweep_to", f"cannot sweep cash into a {account.kind} account.")
        rc = p.roth_conversion
        if rc is not None:
            self.check_conversion_refs(accounts, rc.source, rc.target, f"{path}.roth_conversion")

    def check_conversion_refs(self, accounts: dict, source, target, path: str) -> None:
        if source is not None:
            account = accounts.get(source)
            if account is None or account.kind not in ("traditional_ira", "401k"):
                self.error(
                    f"{path}.source",
                    f"{source!r} is not a traditional_ira or 401k of the person",
                    code="unknown_reference",
                )
        if target is not None:
            account = accounts.get(target)
            if account is None or account.kind != "roth_ira":
                self.error(f"{path}.target", f"{target!r} is not a roth_ira of the person", code="unknown_reference")

    def check_withholding_inputs(self) -> None:
        """Suggest withholding when the records show it (W-2 box 2) but no job withholds (Plan 31 D3)."""
        if not self.spec.actuals:
            return
        withholds = any(
            job.payroll is not None and job.payroll.withholding is not None for p in self.spec.people for job in p.jobs
        )
        estimates = any(p.estimated_payments is not None for p in self.spec.people)
        for year, records in self.spec.actuals.items():
            if not withholds and any(w2.boxes.get("2") for w2 in records.w2):
                self.warn(
                    f"actuals.{year}.w2",
                    "the W-2s show federal tax withheld (box 2) but no job withholds: the model pays the year's "
                    "taxes as a December lump, so box 2, the refund and the April settlement cannot reconcile.",
                    "set payroll.withholding on the jobs ('w4_default', or the W-4's entries) so withholding, the "
                    "refund or balance due and its April settlement are modeled.",
                    "withholding_suggested",
                )
            lines = [r.form_1040 for r in records.all_returns()]
            if not estimates and any(line.get("26") for line in lines):
                self.warn(
                    f"actuals.{year}",
                    "the return shows estimated tax payments (1040 line 26) but no one pays estimates.",
                    "add estimated_payments (quarterly amounts or a policy) to the person who pays them.",
                    "estimated_payments_suggested",
                )

    def check_payroll(self, p: s.Person, path: str) -> None:
        """Payroll HSA money needs an HSA; a health FSA over the year's limit is cut to it."""
        has_hsa = any(a.kind == "hsa" for a in p.accounts)
        fsa_limit = self.config.tax_year(self.start).limit_health_fsa
        for j, job in enumerate(p.jobs):
            payroll = job.payroll
            if payroll is None:
                continue
            if (payroll.hsa_employee_annual or payroll.hsa_employer_annual) and not has_hsa:
                self.error(
                    f"{path}.jobs[{j}].payroll",
                    "payroll HSA contributions need an HSA account (kind: hsa).",
                    "add {kind: hsa, ...} to the person's accounts.",
                    "payroll_hsa_without_hsa",
                )
            if fsa_limit is not None and payroll.fsa_annual > fsa_limit:
                self.warn(
                    f"{path}.jobs[{j}].payroll.fsa_annual",
                    f"the health FSA election {payroll.fsa_annual:,.0f} is over the {self.start} limit "
                    f"({fsa_limit:,.0f}); only the limit is excluded from wages.",
                    None,
                    "fsa_over_limit",
                )

    def check_person_ref(self, pid: str, path: str) -> None:
        if pid not in self.people:
            self.error(path, f"unknown person {pid!r}", code="unknown_reference")

    def check_account_refs(self, account, path: str, job_ids: set, child_ids: set) -> None:
        if isinstance(account, s.Job401k) and account.job is not None and account.job not in job_ids:
            self.error(
                f"{path}.job",
                f"unknown job {account.job!r} (must be one of this person's job ids)",
                code="unknown_reference",
            )
        if isinstance(account, s.Plan529) and account.beneficiary is not None and account.beneficiary not in child_ids:
            self.error(
                f"{path}.beneficiary",
                f"unknown child {account.beneficiary!r} (must be one of this person's child ids)",
                code="unknown_reference",
            )
        if isinstance(account, s.Trust):
            for k, pid in enumerate(account.beneficiaries):
                self.check_person_ref(pid, f"{path}.beneficiaries[{k}]")
        if isinstance(account, s.Annuity) and account.joint_annuitant is not None:
            self.check_person_ref(account.joint_annuitant, f"{path}.joint_annuitant")

    def check_loan(self, m, path: str, *, as_of: tuple[int, int] | None = None) -> bool:
        """Resolve a loan's statement inputs like the builder does; an inconsistency is an error naming the
        field (Plan 27 D1). Returns True when the loan resolved."""
        from ..debt.terms import LoanTermsError, resolve_loan_terms

        payment = m.payment_monthly
        escrow = getattr(m, "escrow_monthly", None)
        if escrow is not None and payment is not None:
            if escrow > payment:
                self.error(
                    f"{path}.escrow_monthly", "escrow is larger than the payment it is part of.", code="loan_terms"
                )
                return False
            payment -= escrow
        term = m.term_months if m.term_months is not None else (None if m.term_years is None else m.term_years * 12)
        origination = m.origination
        start_year = getattr(m, "start_year", None)
        legacy_origin = start_year is not None and m.balance is None and m.payments_made is None
        if origination is None and legacy_origin and start_year < self.start:
            origination = f"{start_year}-01"
        try:
            resolve_loan_terms(
                rate_pct=m.rate_pct,
                as_of=as_of or (self.start, self.start_month),
                original_amount=m.original_amount,
                term_months=term,
                origination=origination,
                payments_made=m.payments_made,
                remaining_months=m.remaining_months,
                current_balance=m.balance,
                monthly_payment=payment,
                names=_LOAN_FIELD_NAMES,
            )
        except LoanTermsError as exc:
            field = exc.field
            self.error(
                f"{path}.{field}",
                str(exc).split(": ", 1)[-1],
                "recheck it against the statement (see docs/units-and-conventions.md, loans).",
                "loan_terms",
            )
            return False
        return True

    def check_mortgage(self, m: s.Mortgage, path: str, *, as_of: tuple[int, int] | None = None) -> None:
        if not self.check_loan(m, path, as_of=as_of):
            return
        if m.original_amount is None or m.term_years is None or m.origination is not None:
            return  # statement inputs: resolved (and checked) above
        origin = m.start_year if m.start_year is not None else self.start
        elapsed = self.start - origin
        payment = _amortized_payment(m.original_amount, m.rate_pct, m.term_years)
        if origin > self.start:
            self.warn(
                f"{path}.start_year",
                f"the mortgage originates in {origin}, after the start year.",
                code="mortgage_inconsistent",
            )
        payment_off = m.payment_monthly is not None and payment > 0 and abs(m.payment_monthly - payment) / payment
        if m.escrow_monthly is None and payment_off and payment_off > MORTGAGE_PAYMENT_TOLERANCE:
            self.warn(
                f"{path}.payment_monthly",
                f"payment ${m.payment_monthly:,.0f}/mo differs from the ${payment:,.0f}/mo principal+interest of "
                f"{m.original_amount:,.0f} at {m.rate_pct:g}% over {m.term_years}y (escrow included?).",
                "enter principal and interest only, give escrow_monthly, or leave payment_monthly unset.",
                "mortgage_inconsistent",
            )
        if elapsed <= 0:
            return
        if elapsed >= m.term_years and (m.balance is None or m.balance > 0):
            self.warn(
                path,
                f"a {m.term_years}-year mortgage from {origin} should be paid off by {self.start}.",
                "check start_year/term_years, or remove the mortgage.",
                "mortgage_inconsistent",
            )
            return
        expected = _remaining_balance(m.original_amount, m.rate_pct, m.term_years, elapsed * 12)
        if m.balance is None and m.payments_made is None:
            self.warn(
                f"{path}.start_year",
                f"no current balance or origination month: the mortgage is taken to originate in January {origin} "
                f"(amortized balance ~${expected:,.0f} at the start).",
                "enter origination (YYYY-MM) or the statement's current principal as balance.",
                "mortgage_inconsistent",
            )
        elif (
            m.balance is not None and expected > 0 and abs(m.balance - expected) / expected > MORTGAGE_BALANCE_TOLERANCE
        ):
            self.warn(
                f"{path}.balance",
                f"balance ${m.balance:,.0f} is inconsistent with ${m.original_amount:,.0f} at {m.rate_pct:g}% over "
                f"{m.term_years}y from {origin} (amortized balance ~${expected:,.0f}).",
                "check original_amount, rate_pct, term_years and start_year against the statement.",
                "mortgage_inconsistent",
            )

    # --- marriages and events ---

    def check_marriages(self) -> None:
        married: dict[str, str] = {}
        for i, marriage in enumerate(self.spec.relationships.marriages):
            path = f"relationships.marriages[{i}]"
            a, b = marriage.spouses
            for k, pid in enumerate(marriage.spouses):
                self.check_person_ref(pid, f"{path}.spouses[{k}]")
            if a == b:
                self.error(path, "a person cannot marry themselves")
            for pid in (a, b):
                if pid in married:
                    self.error(path, f"{pid!r} is already married at {married[pid]}", code="married_twice")
                married[pid] = path

    def year_at_age(self, person: s.Person, age: int) -> int:
        """The year a person turns ``age``: the engine's ``Person.get_year_at_age`` identity (the birth
        year plus ``age``; without ``birth``, ``start_year + (age - constructor age)``)."""
        if person.birth is not None:
            return int(person.birth.split("-")[0]) + age
        return self.start + (age - person.age)

    def resolve(self, at: s.At, person_id: str, by_id: dict, stack: tuple = ()) -> int | None:
        if at.year is not None:
            return at.year
        if at.age is not None:
            person = self.people.get(at.person or person_id)
            return None if person is None else self.year_at_age(person, at.age)
        relative = cast(s.Relative, at.relative)
        anchor = by_id.get(relative.after)
        if anchor is None or relative.after in stack:
            return None
        base = self.resolve(anchor.at, anchor.person, by_id, (*stack, relative.after))
        return None if base is None else base + relative.years

    def check_events(self) -> None:
        by_id = {e.id: e for e in self.spec.events if e.id is not None}
        item_ids = self.item_ids()
        min_claim = self.config.social_security.min_early_retirement_age
        for i, event in enumerate(self.spec.events):
            path = f"events[{i}]"
            self.check_person_ref(event.person, f"{path}.person")
            if event.at.person is not None:
                self.check_person_ref(event.at.person, f"{path}.at.person")
            rel = event.at.relative
            if rel is not None:
                if rel.after not in by_id:
                    self.error(f"{path}.at.relative.after", f"unknown event {rel.after!r}", code="unknown_reference")
                elif self._cycle(event, by_id):
                    self.error(f"{path}.at.relative", "relative event timing has a cycle", code="event_cycle")
                    continue
            year = self.resolve(event.at, event.person, by_id)
            if year == self.start and event.at.month is not None and event.at.month < self.start_month:
                self.error(
                    f"{path}.at.month",
                    f"'{event.action}' is dated {year}-{event.at.month:02d}, before the first simulated month "
                    f"{self.start}-{self.start_month:02d}; it would never fire.",
                    "move it to the first simulated month or later.",
                    "event_before_start",
                )
            if year is not None and year < self.start:
                self.error(
                    f"{path}.at",
                    f"'{event.action}' resolves to {year}, before start_year {self.start}; it would never fire.",
                    "move it to start_year or later, or express its effect in the starting state "
                    "(e.g. a marriage in relationships).",
                    "event_before_start",
                )
            elif year is not None and year > self.end:
                self.warn(
                    f"{path}.at", f"'{event.action}' resolves to {year}, after end_year {self.end}; it never fires."
                )
            if isinstance(event, s.MarryEvent):
                self.check_person_ref(event.spouse, f"{path}.spouse")
            if isinstance(event, s.ChangeJobEvent):
                if event.job is not None and item_ids.get(event.job, (None, None))[1] != "jobs":
                    self.error(f"{path}.job", f"unknown job {event.job!r}", code="unknown_reference")
                if event.job is None and event.new_job is None:
                    self.error(path, "change_job needs 'job' (to change or stop) and/or 'new_job'")

            def is_kind(item_id, model_type) -> bool:
                return isinstance(item_ids.get(item_id, (None, None, None))[2], model_type)

            if isinstance(event, s.MoveEvent):
                if event.end_rental is not None and not is_kind(event.end_rental, s.Rental):
                    self.error(f"{path}.end_rental", f"unknown rental {event.end_rental!r}", code="unknown_reference")
                if event.sell_home is not None and not is_kind(event.sell_home, s.Home):
                    self.error(f"{path}.sell_home", f"unknown home {event.sell_home!r}", code="unknown_reference")
            if isinstance(event, s.SellHomeEvent) and not is_kind(event.home, s.Home):
                self.error(f"{path}.home", f"unknown home {event.home!r}", code="unknown_reference")
            if isinstance(event, s.RefinanceEvent):
                target = item_ids.get(event.debt, (None, None, None))[2]
                if not isinstance(target, s.Home | s.CarLoan | s.StudentLoan):
                    self.error(
                        f"{path}.debt",
                        f"unknown home or loan {event.debt!r} (a home with a mortgage, or a car / student loan)",
                        code="unknown_reference",
                    )
                elif isinstance(target, s.Home) and target.mortgage is None:
                    self.error(f"{path}.debt", f"home {event.debt!r} has no mortgage to refinance", code="invalid")
            if isinstance(event, s.HelocDrawEvent) and not is_kind(event.heloc, s.HomeEquityLine):
                self.error(f"{path}.heloc", f"unknown home equity line {event.heloc!r}", code="unknown_reference")
            if isinstance(event, s.ContributeEvent):
                target = item_ids.get(event.account)
                if target is None or target[1] != "accounts":
                    self.error(f"{path}.account", f"unknown account {event.account!r}", code="unknown_reference")
                elif target[2].kind in ("401k", "pension", "annuity", "inherited_pretax", "trust"):
                    self.error(
                        f"{path}.account",
                        f"one-time contributions to a {target[2].kind} account are not supported.",
                        "use the 401k's contribution percentages, or a brokerage/IRA/HSA/529/bank account.",
                    )
            if isinstance(event, s.ConvertToRothEvent) and event.person in self.people:
                self.check_conversion_refs(
                    self._person_accounts(self.people[event.person]), event.source, event.target, path
                )
            if isinstance(event, s.RecurringExpenseEvent) and event.until is not None:
                last = self.resolve(event.until, event.person, by_id)
                if year is not None and last is not None and last < year:
                    self.error(f"{path}.until", f"'until' ({last}) is before 'at' ({year}).")
            if isinstance(event, s.ClaimSocialSecurityEvent):
                person = self.people.get(event.person)
                if person is not None and person.social_security is None:
                    self.error(path, f"{person.name} has no social_security to claim.", code="unknown_reference")
                own_age = event.at.person is None or event.at.person == event.person
                age = event.at.age if own_age else None
                if age is None and year is not None and person is not None:
                    age = person.age + (year - self.start)
                if age is not None and age < min_claim:
                    self.error(
                        f"{path}.at",
                        f"Social Security claim age {age} is below {min_claim} (core raises).",
                        f"claim at {min_claim} or later.",
                        "ss_claim_too_early",
                    )

    def _cycle(self, event, by_id: dict) -> bool:
        seen = set()
        current = event
        while current is not None and current.at.relative is not None:
            key = id(current)
            if key in seen:
                return True
            seen.add(key)
            current = by_id.get(current.at.relative.after)
        return False

    def check_unmarried_adults(self) -> None:
        married_at_start: set[str] = set()
        for marriage in self.spec.relationships.marriages:
            if marriage.year is None or marriage.year <= self.start:
                married_at_start.update(marriage.spouses)
        single_adults = [p for p in self.spec.people if p.age >= ADULT_AGE and p.id not in married_at_start]
        if len(single_adults) >= 2:
            names = ", ".join(p.name for p in single_adults)
            self.warn(
                "relationships.marriages",
                f"{len(single_adults)} adults in one family are not married at the start ({names}); they file "
                "separate SINGLE returns.",
                "add a marriage to relationships if they are married.",
                "unmarried_adults",
            )

    def check_growth(self) -> None:
        investments = [
            (i, j, a)
            for i, p in enumerate(self.spec.people)
            for j, a in enumerate(p.accounts)
            if a.kind in _INVESTMENT_KINDS
        ]
        if investments and all(getattr(a, "growth_pct", None) != "economy" for _, _, a in investments):
            self.warn(
                "people[*].accounts[*].growth_pct",
                f"all {len(investments)} investment account(s) use a fixed growth_pct, so stochastic/Monte Carlo "
                "economies do not move them.",
                "use growth_pct: economy for accounts that should follow market returns.",
                "fixed_growth",
            )


#: Core argument names (as :func:`~life_model.debt.terms.resolve_loan_terms` reports them) to spec fields.
_LOAN_FIELD_NAMES = {
    "original_amount": "original_amount",
    "current_balance": "balance",
    "monthly_payment": "payment_monthly",
    "rate_pct": "rate_pct",
    "term_months": "term_months",
    "origination": "origination",
    "payments_made": "payments_made",
    "remaining_months": "remaining_months",
}


def _event_items(event) -> list[tuple[str, Any]]:
    """Items an event creates (with the collection they join)."""
    items: list[tuple[str, Any]] = []
    if isinstance(event, s.ChangeJobEvent) and event.new_job is not None:
        items.append(("jobs", event.new_job))
    if isinstance(event, s.MoveEvent):
        if event.buy_home is not None:
            items.append(("housing", event.buy_home))
        if event.new_rental is not None:
            items.append(("housing", event.new_rental))
    if isinstance(event, s.BuyHomeEvent):
        items.append(("housing", event.home))
    if isinstance(event, s.AddAccountEvent):
        items.append(("accounts", event.account))
    return items


def _amortized_payment(principal: float, rate_pct: float, years: int) -> float:
    n = years * 12
    i = rate_pct / 1200
    if n <= 0:
        return principal
    if i == 0:
        return principal / n
    return principal * i * (1 + i) ** n / ((1 + i) ** n - 1)


def _remaining_balance(principal: float, rate_pct: float, years: int, payments_made: int) -> float:
    n = years * 12
    i = rate_pct / 1200
    if payments_made >= n:
        return 0.0
    if i == 0:
        return principal * (1 - payments_made / n)
    payment = _amortized_payment(principal, rate_pct, years)
    return principal * (1 + i) ** payments_made - payment * ((1 + i) ** payments_made - 1) / i


# --- Model validation ----------------------------------------------------------------------------


def validate_model(model) -> list[Finding]:
    """Run the household checks on an already-constructed :class:`~life_model.model.LifeModel`.

    The same rules as :func:`validate_spec`, read from agents instead of spec fields (only the
    rules that can be decided from agent state; ``not_yet_supported`` does not apply).
    """
    from ..base_classes import FinancialAccount, Investment, Loan
    from ..debt.credit_card import RevolvingDebt
    from ..housing.apartment import Apartment
    from ..lifeevents import LifeEvents
    from ..people.family import Family
    from ..people.person import Person
    from ..work.job import Job

    findings: list[Finding] = []
    config = model.config
    packs = set(config.tax.state.packs)
    min_claim = config.social_security.min_early_retirement_age
    agents = list(model.agents)
    people = [a for a in agents if isinstance(a, Person)]

    def ppath(person) -> str:
        return f"person[{person.name}]"

    def add(level, path, message, fix=None, code="invalid"):
        findings.append(Finding(level, path, message, fix, code))

    for person in people:
        path = ppath(person)
        if person.state is not None and person.state != DEFAULT_STATE_KEY and person.state not in packs:
            add(
                ERROR,
                f"{path}.state",
                f"no state tax pack for {person.state!r}: there is no fallback rate (Plan 31 D4).",
                None,
                "unknown_state",
            )
        if not person.bank_accounts:
            add(
                ERROR,
                f"{path}.bank_accounts",
                f"{person.name} has no bank account; income goes to an untracked cash bucket.",
                "create a BankAccount(owner=person, ...).",
                "no_bank_account",
            )
        if any(not job.retired for job in person.jobs) and person.retirement_age < person.age:
            add(
                ERROR,
                f"{path}.retirement_age",
                f"retirement_age {person.retirement_age:g} is below age {person.age}.",
                None,
                "retirement_before_age",
            )
        ss = person.social_security
        if ss is not None and ss.withdrawal_start_age < min_claim:
            add(
                ERROR,
                f"{path}.social_security",
                f"claim age {ss.withdrawal_start_age:g} is below {min_claim}.",
                None,
                "ss_claim_too_early",
            )
        increase = person.spending._yearly_increase_override
        if increase == 0:
            add(
                WARNING,
                f"{path}.spending",
                "spending grows 0%/yr (the core default).",
                "pass Spending(growth_pct=None) to follow inflation, or a percentage.",
                "zero_growth",
            )
        elif increase is not None and 0 < increase < 1:
            findings.append(_fraction_finding(f"{path}.spending.yearly_increase", increase))
        banks = person.bank_accounts
        for bank in banks:
            if _BOND_LIKE.search(bank.company) or _BOND_LIKE.search(bank.type):
                add(
                    WARNING,
                    f"{path}.bank_accounts[{bank.company} {bank.type}]",
                    "this bank account looks like a stand-in for bonds/CDs/Treasuries; it is spent like checking.",
                    "use a FixedIncomeHolding (or BankAccount(reserve=True) for an emergency fund).",
                    "bonds_as_bank",
                )
        for home in person.homes:
            mortgage = home.mortgage
            if mortgage is None:
                continue
            elapsed = model.start_year - int(mortgage.start_date)
            if elapsed > 0 and mortgage.principal >= mortgage.loan_amount:
                add(
                    WARNING,
                    f"{path}.homes[{home.name}].mortgage",
                    f"the mortgage from {int(mortgage.start_date)} still has its original principal; enter the current "
                    "balance as principal=.",
                    None,
                    "mortgage_inconsistent",
                )
            elif elapsed > 0 and elapsed < mortgage.length_years:
                expected = _remaining_balance(
                    mortgage.loan_amount, mortgage.yearly_interest_rate, mortgage.length_years, elapsed * 12
                )
                if expected > 0 and abs(mortgage.principal - expected) / expected > MORTGAGE_BALANCE_TOLERANCE:
                    add(
                        WARNING,
                        f"{path}.homes[{home.name}].mortgage",
                        f"principal ${mortgage.principal:,.0f} is inconsistent with the amortized ~${expected:,.0f}.",
                        None,
                        "mortgage_inconsistent",
                    )

    for agent in agents:
        if isinstance(agent, Job):
            override = agent.salary._yearly_increase_override
            path = f"{ppath(agent.owner)}.jobs[{agent.company}]"
            if override == 0:
                add(WARNING, f"{path}.salary", f"salary at {agent.company} never rises (0%/yr).", None, "zero_growth")
            elif override is not None and 0 < override < 1:
                findings.append(_fraction_finding(f"{path}.salary.yearly_increase", override))
            account = agent.retirement_account
            if account is not None and account.company_match_percent:
                pct = account.company_match_percent
                add(
                    WARNING,
                    f"{path}.retirement_account.company_match_percent",
                    f"company_match_percent={pct:g} is deprecated (a {pct:g}% match on each deferred dollar).",
                    f"pass match_tiers; a dollar-for-dollar match up to {pct:g}% of pay is match_tiers=[(100, {pct:g})].",
                    "deprecated_match",
                )
            if account is not None:
                for name in ("pretax_contrib_percent", "roth_contrib_percent", "company_match_percent"):
                    value = getattr(account, name)
                    if 0 < value < 1:
                        findings.append(_fraction_finding(f"{path}.retirement_account.{name}", value))
        elif isinstance(agent, Apartment) and agent._yearly_increase_override == 5:
            add(
                WARNING,
                f"apartment[{agent.name}]",
                "rent grows 5%/yr (the core default).",
                "pass yearly_increase explicitly (None follows inflation).",
                "default_rent_growth",
            )
        elif isinstance(agent, Loan) and agent.principal < 0:
            add(
                ERROR,
                f"loan[{type(agent).__name__}]",
                f"negative principal {agent.principal:,.2f}.",
                None,
                "negative_balance",
            )
        elif isinstance(agent, RevolvingDebt) and agent.balance < 0:
            add(
                ERROR,
                f"revolving_debt[{agent.name}]",
                f"negative balance {agent.balance:,.2f}.",
                None,
                "negative_balance",
            )
        if isinstance(agent, FinancialAccount) and not isinstance(agent, Loan) and agent.balance < 0:
            add(
                ERROR,
                f"account[{type(agent).__name__}]",
                f"negative balance {agent.balance:,.2f}.",
                None,
                "negative_balance",
            )
        if isinstance(agent, Investment):
            override = agent._growth_rate_override
            if override is not None and 0 < override < 1:
                findings.append(_fraction_finding(f"account[{type(agent).__name__}].growth_rate", override))
            if override is not None and agent.allocation is not None:
                add(
                    WARNING,
                    f"account[{type(agent).__name__}].allocation",
                    "an explicit growth rate overrides the allocation (and disconnects the account from stochastic "
                    "runs).",
                    "pass growth_pct=None to grow at the allocation's blend of the economy's returns.",
                    "allocation_ignored",
                )
        if isinstance(agent, LifeEvents):
            for life_event in agent.life_events:
                if life_event.year < model.start_year:
                    add(
                        ERROR,
                        f"life_events[{life_event.name}]",
                        f"dated {life_event.year}, before start_year {model.start_year}; it never fires.",
                        "date it at start_year or later, or apply its effect at construction.",
                        "event_before_start",
                    )
                elif life_event.year > model.end_year:
                    add(
                        WARNING,
                        f"life_events[{life_event.name}]",
                        f"dated {life_event.year}, after end_year {model.end_year}.",
                    )

    investments = [a for a in agents if isinstance(a, Investment)]
    if investments and all(a._growth_rate_override is not None for a in investments):
        add(
            WARNING,
            "accounts",
            f"all {len(investments)} investment account(s) use a fixed growth rate, so stochastic "
            "economies do not move them.",
            "pass growth_rate=None to follow the economy.",
            "fixed_growth",
        )

    for family in (a for a in agents if isinstance(a, Family)):
        single_adults = [m for m in family.members if m.age >= ADULT_AGE and m.spouse is None and not m.is_deceased]
        if len(single_adults) >= 2:
            names = ", ".join(m.name for m in single_adults)
            add(
                WARNING,
                "family",
                f"{len(single_adults)} adults in one family are not married ({names}); they file "
                "separate SINGLE returns.",
                "call get_married at construction if they are married.",
                "unmarried_adults",
            )
    return findings
