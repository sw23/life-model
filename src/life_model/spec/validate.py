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
end year.
"""

import re
from dataclasses import dataclass
from types import SimpleNamespace
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
    """One validation finding.

    Attributes:
        level: ``"error"`` (the household cannot be built as written) or ``"warning"``.
        path: Location in the spec, e.g. ``people[0].accounts[1].interest_pct`` (for a model:
            ``person[Alex].accounts[Checking]``).
        message: What is wrong.
        fix: How to fix it (None when obvious).
        code: Stable machine-readable code, e.g. ``not_yet_supported`` or ``fraction_percent``.
    """

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
    for p_index, person in enumerate(spec.people):
        for a_index, account in enumerate(person.accounts):
            if isinstance(account, s.Job401k) and account.job is None:
                findings.append(
                    Finding(
                        ERROR,
                        f"people[{p_index}].accounts[{a_index}].job",
                        "A 401k without a job (an old-employer plan) is not yet supported (Plan 27 D3).",
                        "Reference one of the person's jobs, or roll it into a traditional_ira for now.",
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
        self.end = spec.meta.end_year if spec.meta.end_year is not None else self.start + 50
        self.people = {p.id: p for p in spec.people}
        self.person_index = {p.id: i for i, p in enumerate(spec.people)}

    def error(self, path: str, message: str, fix: str | None = None, code: str = "invalid") -> None:
        self.findings.append(Finding(ERROR, path, message, fix, code))

    def warn(self, path: str, message: str, fix: str | None = None, code: str = "warning") -> None:
        self.findings.append(Finding(WARNING, path, message, fix, code))

    def run(self) -> list[Finding]:
        self.check_ids()
        self.check_states()
        self.check_people()
        self.check_marriages()
        self.check_events()
        self.check_unmarried_adults()
        self.check_growth()
        return self.findings

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
                    f"no state tax pack for {code!r}; core would silently tax it at the default flat rate.",
                    f"use one of {sorted(c for c in packs if c != DEFAULT_STATE_KEY)}, or leave it unset.",
                    "unknown_state",
                )

        check(self.spec.meta.default_state, "meta.default_state")
        for i, p in enumerate(self.spec.people):
            check(p.state, f"people[{i}].state")
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
                        "use kind: fixed_income once supported (Plan 27 D2); until then mark the intent in a comment.",
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
            for j, policy in enumerate(p.insurance):
                if isinstance(policy, s.LifeInsurance) and policy.beneficiary is not None:
                    self.check_person_ref(policy.beneficiary, f"{path}.insurance[{j}].beneficiary")

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

    def check_mortgage(self, m: s.Mortgage, path: str) -> None:
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
        if payment_off and payment_off > MORTGAGE_PAYMENT_TOLERANCE:
            self.warn(
                f"{path}.payment_monthly",
                f"payment ${m.payment_monthly:,.0f}/mo differs from the ${payment:,.0f}/mo principal+interest of "
                f"{m.original_amount:,.0f} at {m.rate_pct:g}% over {m.term_years}y (escrow included?).",
                "enter principal and interest only, or leave payment_monthly unset.",
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
        if m.balance is None:
            self.warn(
                f"{path}.balance",
                f"no current balance: the mortgage starts at its original ${m.original_amount:,.0f} although it was "
                f"originated {elapsed} year(s) earlier (amortized balance ~${expected:,.0f}).",
                "enter the statement's current principal as balance.",
                "mortgage_inconsistent",
            )
        elif expected > 0 and abs(m.balance - expected) / expected > MORTGAGE_BALANCE_TOLERANCE:
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
        """The year a person reaches ``age``, by the engine's own ``Person.get_year_at_age``.

        Called on a lightweight stand-in so the validator needs no model, and stays in step with
        whatever age semantics the engine implements (Plan 26 item 1).
        """
        from ..people.person import Person

        stub = SimpleNamespace(model=SimpleNamespace(year=self.start, start_year=self.start), age=person.age)
        return Person.get_year_at_age(cast(Person, stub), age)

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
            if isinstance(event, s.MoveEvent):
                if event.end_rental is not None and item_ids.get(event.end_rental, (None, None))[1] != "housing":
                    self.error(f"{path}.end_rental", f"unknown rental {event.end_rental!r}", code="unknown_reference")
                if event.sell_home is not None and item_ids.get(event.sell_home, (None, None))[1] != "housing":
                    self.error(f"{path}.sell_home", f"unknown home {event.sell_home!r}", code="unknown_reference")
            if isinstance(event, s.SellHomeEvent) and item_ids.get(event.home, (None, None))[1] != "housing":
                self.error(f"{path}.home", f"unknown home {event.home!r}", code="unknown_reference")
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
            if isinstance(event, s.RecurringExpenseEvent) and event.until is not None:
                last = self.resolve(event.until, event.person, by_id)
                if year is not None and last is not None and last < year:
                    self.error(f"{path}.until", f"'until' ({last}) is before 'at' ({year}).")
            if isinstance(event, s.ClaimSocialSecurityEvent):
                person = self.people.get(event.person)
                if person is not None and person.social_security is None:
                    self.error(path, f"{person.name} has no social_security to claim.", code="unknown_reference")
                age = event.at.age
                if age is None and year is not None and person is not None:
                    age = person.age + (year - self.year_at_age(person, person.age))
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
                f"no state tax pack for {person.state!r}; taxed at the default flat rate.",
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
        if person.jobs and person.retirement_age < person.age:
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
                "pass Spending(yearly_increase=None) to follow inflation, or a percentage.",
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
                    "use a fixed-income holding once supported (Plan 27 D2).",
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
