# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The simulation invariant checker (Plan 29 D4).

Every invariant is a rule a correct simulated year must satisfy, written against the year's
*results* (the balance sheets around the year, the cash-flow ledger, the typed events and the tax
returns) rather than engine internals, so it holds for any engine that produces those results:

* ``conservation``: net worth changed by exactly the ledger's net external flow (``checks.py``);
* ``continuity``: between two years nothing moved money without a ledger entry (anything a driver
  does between ``step()`` calls, such as an RL action, must post what it moves);
* ``no_negative_balances``: no asset below zero, no liability with a negative balance;
* ``no_draw_above_cash_floor``: no taxable sale or pre-tax withdrawal by the payment waterfall while
  the tax unit still held cash above its floor at year end (the rule Plan 26 item 4 broke);
* ``contribution_limits``: 401(k) elective deferrals (402(g) + catch-up), 415(c) annual additions per
  plan, IRA and HSA contributions stay within the year's limits;
* ``no_income_after_job_end``: no wages, bonus or vests from an employer after the job ended;
* ``fica_wage_base``: Social Security tax is 6.2% of wages up to the year's wage base, per worker,
  and no payroll tax is charged on a member without wages;
* ``rmd_minimum``: from the start age, each pre-tax IRA/401(k) paid out at least the prior year-end
  pre-tax balance over the Uniform Lifetime Table divisor;
* ``taxes_non_negative``: no tax line is negative, and federal tax is negative only by refundable
  credits;
* ``deduction_choice``: an itemized return itemizes at least the standard deduction, and every
  return deducts the larger of the two (plus the senior deduction);
* ``return_identities``: the Form 1040 identities of each :class:`~life_model.tax.return_record.TaxReturn`.

Run them per year with ``LifeModel(checks="strict" | "warn" | "off")`` (``strict`` raises
:class:`InvariantError` at the end of the first year with a violation, ``warn`` emits an
:class:`InvariantWarning`, ``off``, the library default, skips them), or on a finished run with
:func:`check_model`. Violations are kept on ``model.invariant_violations``.
"""

import warnings
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from .checks import CONSERVATION_TOLERANCE
from .ledger import FlowKind

if TYPE_CHECKING:
    from .checks import YearBalances
    from .ledger import LedgerEntry
    from .model import LifeModel
    from .tax.return_record import TaxReturn

#: ``LifeModel(checks=...)`` modes.
CHECK_MODES = ("strict", "warn", "off")

#: Dollars of tolerance for balance and limit comparisons (float residue, cent rounding).
MONEY_TOLERANCE = 0.01
#: Dollars a tax unit may hold in its banks after a waterfall draw: the draw is rounded up to the cent
#: and the pre-tax solve converges to a tenth of a cent, so anything above a dollar is real cash.
CASH_FLOOR_TOLERANCE = 1.0
#: The household cash floor (dollars kept in the bank before anything is sold). The engine has no
#: floor yet (Plan 27 D4 adds a savings policy with one), so it is zero.
DEFAULT_CASH_FLOOR = 0.0

_WATERFALL_DRAW_KINDS = ("forced_sale", "pretax_withdrawal")
_EARNED_KINDS = frozenset(
    {FlowKind.WAGE.value, FlowKind.BONUS.value, FlowKind.VEST.value, FlowKind.BUSINESS_INCOME.value}
)


@dataclass(frozen=True)
class Violation:
    """One broken invariant in one year."""

    year: int
    invariant: str
    message: str
    amount: float | None = None
    person_id: int | None = None
    account: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def __str__(self) -> str:
        return f"{self.year} {self.invariant}: {self.message}"


class InvariantError(AssertionError):
    """Raised under ``checks="strict"`` when a simulated year breaks an invariant."""

    def __init__(self, violations: "list[Violation]"):
        self.violations = list(violations)
        lines = "\n".join(f"  {v}" for v in self.violations[:20])
        more = f"\n  ... and {len(self.violations) - 20} more" if len(self.violations) > 20 else ""
        super().__init__(f"{len(self.violations)} invariant violation(s):\n{lines}{more}")


class InvariantWarning(UserWarning):
    """Emitted under ``checks="warn"`` for each year that breaks an invariant."""


def validate_mode(mode: str) -> str:
    if mode not in CHECK_MODES:
        raise ValueError(f"checks must be one of {CHECK_MODES}, got {mode!r}")
    return mode


# --------------------------------------------------------------------------------------------------
# The year being checked
# --------------------------------------------------------------------------------------------------


@dataclass
class YearContext:
    """Everything an invariant reads about one simulated year (all results, no engine internals)."""

    model: "LifeModel"
    year: int
    balances: "YearBalances"
    entries: "list[LedgerEntry]"
    returns: "list[TaxReturn]"
    events: list
    #: The previous year's balances (None in the first simulated year).
    previous: "YearBalances | None" = None
    #: Ledger entries posted between the previous year's step and this one (outside ``step()``).
    between: "list[LedgerEntry]" = field(default_factory=list)
    #: Year-start snapshot taken before the stages ran (see :func:`year_start`), when available.
    snapshot: "dict[str, Any] | None" = None

    @property
    def config(self):
        return self.model.config_for_year(self.year)

    def agents_by_label(self) -> dict[str, Any]:
        from .ledger import account_label

        cache = getattr(self, "_agents_by_label", None)
        if cache is None:
            cache = {account_label(agent): agent for agent in self.model.agents}
            self._agents_by_label = cache
        return cache

    def people(self) -> dict[int, Any]:
        from .people.person import Person

        return {agent.unique_id: agent for agent in self.model.agents if isinstance(agent, Person)}


Invariant = Callable[[YearContext], "list[Violation]"]


# --------------------------------------------------------------------------------------------------
# Invariants
# --------------------------------------------------------------------------------------------------


def conservation(ctx: YearContext) -> list[Violation]:
    """Net worth changed by exactly the ledger's net external flow during the year."""
    net_flow = sum(e.net_worth_effect for e in ctx.entries)
    change = ctx.balances.closing.net_worth - ctx.balances.opening.net_worth
    residual = change - net_flow
    if abs(residual) <= CONSERVATION_TOLERANCE:
        return []
    from .checks import account_residuals

    accounts = ", ".join(
        f"{ctx.model.ledger.describe(label)} {value:+,.2f}"
        for label, value in list(account_residuals(ctx.model, ctx.year).items())[:6]
    )
    return [
        Violation(
            ctx.year,
            "conservation",
            f"net worth changed {change:,.2f} but the ledger's net flow is {net_flow:,.2f} "
            f"(residual {residual:,.2f}; by account: {accounts or 'n/a'})",
            amount=residual,
        )
    ]


def continuity(ctx: YearContext) -> list[Violation]:
    """Between the previous year's close and this year's open, net worth moved only by ledger entries
    posted in between (a driver acting between ``step()`` calls must post what it moves)."""
    if ctx.previous is None:
        return []
    net_flow = sum(e.net_worth_effect for e in ctx.between)
    change = ctx.balances.opening.net_worth - ctx.previous.closing.net_worth
    residual = change - net_flow
    if abs(residual) <= CONSERVATION_TOLERANCE:
        return []
    lines = []
    before, after = ctx.previous.closing.lines, ctx.balances.opening.lines
    posted: dict[str, float] = {}
    for entry in ctx.between:
        if entry.from_account is not None:
            posted[entry.from_account] = posted.get(entry.from_account, 0.0) - entry.amount
        if entry.to_account is not None:
            posted[entry.to_account] = posted.get(entry.to_account, 0.0) + entry.amount
    for label in sorted(set(before) | set(after)):
        moved = after.get(label, 0.0) - before.get(label, 0.0) - posted.get(label, 0.0)
        if abs(moved) > MONEY_TOLERANCE:
            lines.append(f"{ctx.model.ledger.describe(label)} {moved:+,.2f}")
    return [
        Violation(
            ctx.year,
            "continuity",
            f"net worth moved {change:,.2f} between {ctx.year - 1}'s close and {ctx.year}'s open but only "
            f"{net_flow:,.2f} was posted (residual {residual:,.2f}; unposted: {', '.join(lines[:6]) or 'n/a'})",
            amount=residual,
        )
    ]


def _liability_labels(ctx: YearContext) -> set[str]:
    from .base_classes import Loan
    from .debt.credit_card import RevolvingDebt
    from .ledger import account_label

    labels = {account_label(a) for a in ctx.model.agents if isinstance(a, (Loan, RevolvingDebt))}
    labels.update(label for label in ctx.balances.closing.lines if label.startswith("Debt:"))
    return labels


def no_negative_balances(ctx: YearContext) -> list[Violation]:
    """At year end no asset line is below zero and no liability line is above zero (a negative debt)."""
    liabilities = _liability_labels(ctx)
    violations = []
    for label, value in ctx.balances.closing.lines.items():
        is_liability = label in liabilities
        if (not is_liability and value < -MONEY_TOLERANCE) or (is_liability and value > MONEY_TOLERANCE):
            what = "liability below zero" if is_liability else "negative balance"
            violations.append(
                Violation(
                    ctx.year,
                    "no_negative_balances",
                    f"{ctx.model.ledger.describe(label)}: {what} ({value:,.2f})",
                    amount=value,
                    account=label,
                    person_id=ctx.balances.closing.owners.get(label),
                )
            )
    return violations


def _bank_labels(ctx: YearContext, member_ids: "set[int]") -> list[str]:
    from .account.bank import BankAccount

    agents = ctx.agents_by_label()
    closing = ctx.balances.closing
    labels = []
    for label in closing.lines:
        owner = closing.owners.get(label)
        if owner not in member_ids:
            continue
        if label.startswith("Cash:") or isinstance(agents.get(label), BankAccount):
            labels.append(label)
    return labels


def no_draw_above_cash_floor(ctx: YearContext) -> list[Violation]:
    """A tax unit whose payment waterfall sold taxable holdings or withdrew pre-tax money this year must
    end the year with no more than its cash floor in its banks: money that was sitting in a member's
    bank should have been spent before anything taxable was sold (Plan 26 item 4)."""
    floor = getattr(ctx.model, "cash_floor", DEFAULT_CASH_FLOOR)
    draws: dict[int, float] = {}
    for event in ctx.events:
        if event.kind.value in _WATERFALL_DRAW_KINDS and event.person_id is not None and event.amount:
            draws[event.person_id] = draws.get(event.person_id, 0.0) + event.amount
    if not draws:
        return []
    violations = []
    for tax_return in ctx.returns:
        members = set(tax_return.member_ids)
        drawn = sum(draws.get(member, 0.0) for member in members)
        if drawn <= MONEY_TOLERANCE:
            continue
        cash = sum(ctx.balances.closing.lines[label] for label in _bank_labels(ctx, members))
        if cash > floor + CASH_FLOOR_TOLERANCE:
            names = ", ".join(tax_return.member_names)
            violations.append(
                Violation(
                    ctx.year,
                    "no_draw_above_cash_floor",
                    f"{names}: the waterfall sold or withdrew {drawn:,.2f} of taxable money while the unit ended the "
                    f"year with {cash:,.2f} in its banks (floor {floor:,.2f})",
                    amount=cash - floor,
                    person_id=tax_return.unit_id,
                )
            )
    return violations


def _contributions_by(ctx: YearContext) -> dict[str, dict[int, float]]:
    """``{account label: {person_id: dollars}}`` of contributions (employee and employer) this year."""
    from .work.job import SELF_EMPLOYED_EMPLOYER_CAUSE

    out: dict[str, dict[int, float]] = {}
    for entry in ctx.entries:
        if entry.kind != FlowKind.CONTRIBUTION.value or entry.to_account is None:
            continue
        if entry.cause == SELF_EMPLOYED_EMPLOYER_CAUSE:
            continue  # employer money (SEP / profit sharing): 415(c) only, checked separately
        by_person = out.setdefault(entry.to_account, {})
        by_person[entry.agent_id] = by_person.get(entry.agent_id, 0.0) + entry.amount
    return out


def contribution_limits(ctx: YearContext) -> list[Violation]:
    """Contributions stay within the year's limits: 402(g) elective deferrals (plus the age-50
    catch-up) across a person's 401(k)s, 415(c) annual additions per plan, the shared IRA limit (plus
    the age-50 catch-up) and the HSA limit for the coverage (plus the age-55 catch-up)."""
    from .account.hsa import HealthSavingsAccount, HSAType
    from .account.job401k import Job401kAccount
    from .account.roth_IRA import RothIRA
    from .account.traditional_IRA import TraditionalIRA

    config = ctx.config
    params = ctx.model.config.tax_year(ctx.year)
    agents = ctx.agents_by_label()
    people = ctx.people()
    deferrals: dict[int, float] = {}
    ira: dict[int, float] = {}
    hsa: dict[int, tuple[float, float]] = {}
    additions: dict[str, float] = {}
    for label, by_person in _contributions_by(ctx).items():
        account = agents.get(label)
        total = sum(by_person.values())
        if isinstance(account, Job401kAccount):
            additions[label] = additions.get(label, 0.0) + total
            for person_id, amount in by_person.items():
                deferrals[person_id] = deferrals.get(person_id, 0.0) + amount
        elif isinstance(account, (TraditionalIRA, RothIRA)):
            owner = account.person.unique_id
            ira[owner] = ira.get(owner, 0.0) + total
        elif isinstance(account, HealthSavingsAccount):
            owner = account.person.unique_id
            base = config.accounts.hsa.contribution_limit_family
            if account.hsa_type != HSAType.FAMILY:
                base = config.accounts.hsa.contribution_limit
            paid, limit = hsa.get(owner, (0.0, 0.0))
            hsa[owner] = (paid + total, max(limit, base))
    from .work.job import SELF_EMPLOYED_EMPLOYER_CAUSE

    for entry in ctx.entries:
        employer = entry.kind == FlowKind.MATCH.value or (
            entry.kind == FlowKind.CONTRIBUTION.value and entry.cause == SELF_EMPLOYED_EMPLOYER_CAUSE
        )
        if employer and entry.to_account is not None:
            additions[entry.to_account] = additions.get(entry.to_account, 0.0) + entry.amount

    violations = []

    def age_of(person_id: int) -> int | None:
        person = people.get(person_id)
        return None if person is None else person.age_in(ctx.year)

    def over(person_id, paid, limit, what, account=None):
        if paid > limit + MONEY_TOLERANCE:
            violations.append(
                Violation(
                    ctx.year,
                    "contribution_limits",
                    f"{what}: {paid:,.2f} contributed, limit {limit:,.2f}",
                    amount=paid - limit,
                    person_id=person_id,
                    account=account,
                )
            )

    limit_401k = config.retirement.job_401k_contrib_limit
    for person_id, paid in deferrals.items():
        age = age_of(person_id)
        limit = limit_401k.base + (
            limit_401k.catch_up_amount if age is not None and age >= limit_401k.catch_up_age else 0
        )
        over(person_id, paid, limit, "401(k) elective deferrals (402(g))")
    annual_additions = config.get_job_401k_annual_additions_limit()
    for label, paid in additions.items():
        account = agents.get(label)
        owner = getattr(getattr(account, "person", None), "unique_id", None)
        over(owner, paid, annual_additions, f"{ctx.model.ledger.describe(label)} annual additions (415(c))", label)
    for person_id, paid in ira.items():
        age = age_of(person_id)
        limit = config.retirement.ira.contribution_limit + (params.limit_ira_catch_up if age and age >= 50 else 0)
        over(person_id, paid, limit, "IRA contributions")
    hsa_config = config.accounts.hsa
    for person_id, (paid, base) in hsa.items():
        age = age_of(person_id)
        limit = base + (hsa_config.catch_up_amount if age is not None and age >= hsa_config.catch_up_age else 0)
        over(person_id, paid, limit, "HSA contributions")
    return violations


def no_income_after_job_end(ctx: YearContext) -> list[Violation]:
    """No wages, bonus or stock vests arrive from an employer in a year after the person's job there
    ended (unless they hold another, active job at the same employer)."""
    from .work.job import Job

    ended: dict[tuple[int, str], int] = {}
    for event in ctx.model.event_log.of_kind("retired"):
        if event.person_id is None or event.cause is None or event.year is None:
            continue
        key = (event.person_id, event.cause)
        ended[key] = min(event.year, ended.get(key, event.year))
    if not ended:
        return []
    active = {
        (job.owner.unique_id, job.company) for job in ctx.model.agents if isinstance(job, Job) and not job.retired
    }
    violations = []
    for entry in ctx.entries:
        if entry.kind not in _EARNED_KINDS or entry.agent_id is None or entry.amount <= 0:
            continue
        key = (entry.agent_id, entry.source)
        end_year = ended.get(key)
        if end_year is not None and ctx.year > end_year and key not in active:
            violations.append(
                Violation(
                    ctx.year,
                    "no_income_after_job_end",
                    f"{entry.kind} of {entry.amount:,.2f} from {entry.source} after the job ended in {end_year}",
                    amount=entry.amount,
                    person_id=entry.agent_id,
                )
            )
    return violations


def fica_wage_base(ctx: YearContext) -> list[Violation]:
    """Per worker: Social Security tax = rate x min(wages, wage base); Medicare tax at least the base
    rate on all wages; no payroll tax on a member without wages."""
    fica = ctx.config.tax.fica
    violations = []
    for tax_return in ctx.returns:
        for line in tax_return.fica:
            expected_ss = min(max(line.wages, 0.0), fica.social_security_max_income) * fica.social_security_rate / 100
            if abs(line.social_security - expected_ss) > MONEY_TOLERANCE:
                violations.append(
                    Violation(
                        ctx.year,
                        "fica_wage_base",
                        f"{line.name}: Social Security tax {line.social_security:,.2f} on wages {line.wages:,.2f}; "
                        f"expected {expected_ss:,.2f} (wage base {fica.social_security_max_income:,})",
                        amount=line.social_security - expected_ss,
                        person_id=line.person_id,
                    )
                )
            base_medicare = max(line.wages, 0.0) * fica.medicare_rate / 100
            if line.medicare < base_medicare - MONEY_TOLERANCE or (line.wages <= 0 and line.medicare > MONEY_TOLERANCE):
                violations.append(
                    Violation(
                        ctx.year,
                        "fica_wage_base",
                        f"{line.name}: Medicare tax {line.medicare:,.2f} on wages {line.wages:,.2f}",
                        amount=line.medicare - base_medicare,
                        person_id=line.person_id,
                    )
                )
    return violations


def rmd_minimum(ctx: YearContext) -> list[Violation]:
    """From the RMD start age, each pre-tax IRA / 401(k) paid out at least its prior year-end pre-tax
    balance divided by the Uniform Lifetime Table period for the owner's age this year (needs the
    year-start snapshot; skipped on a finished run without one)."""
    if not ctx.snapshot:
        return []
    from .limits import required_min_distrib, rmd_start_age

    paid: dict[str, float] = {}
    for entry in ctx.entries:
        # A qualified charitable distribution (a gift straight from the IRA) counts toward the RMD.
        if entry.from_account is not None and entry.kind in (
            FlowKind.RMD.value,
            FlowKind.WITHDRAWAL.value,
            FlowKind.GIFT.value,
        ):
            paid[entry.from_account] = paid.get(entry.from_account, 0.0) + entry.amount
    people = ctx.people()
    violations = []
    for label, (owner_id, pretax_balance) in ctx.snapshot.get("pretax", {}).items():
        person = people.get(owner_id)
        if person is None or person.is_deceased or pretax_balance <= 0:
            continue
        age = person.age_in(ctx.year)
        start = rmd_start_age(ctx.year - age, config=ctx.model.config, year=ctx.year)
        required = required_min_distrib(age, pretax_balance, config=ctx.model.config, start_age=start)
        taken = paid.get(label, 0.0)
        if required > 0 and taken < required - MONEY_TOLERANCE:
            violations.append(
                Violation(
                    ctx.year,
                    "rmd_minimum",
                    f"{ctx.model.ledger.describe(label)}: distributed {taken:,.2f}, required {required:,.2f} "
                    f"(prior year-end pre-tax balance {pretax_balance:,.2f}, age {age})",
                    amount=required - taken,
                    person_id=owner_id,
                    account=label,
                )
            )
    return violations


def taxes_non_negative(ctx: YearContext) -> list[Violation]:
    """No tax line is negative; federal tax is negative only by refundable credits; nonrefundable
    credits never exceed the income tax they offset."""
    violations = []
    for r in ctx.returns:
        names = ", ".join(r.member_names)
        for name in (
            "ordinary_tax",
            "preferential_tax",
            "niit",
            "amt",
            "state_tax",
            "social_security_tax",
            "medicare_tax",
            "total_penalties",
        ):
            value = getattr(r, name)
            if value < -MONEY_TOLERANCE:
                violations.append(Violation(ctx.year, "taxes_non_negative", f"{names}: {name} {value:,.2f}", value))
        if r.federal_tax < -r.refundable_credits - MONEY_TOLERANCE:
            violations.append(
                Violation(
                    ctx.year,
                    "taxes_non_negative",
                    f"{names}: federal tax {r.federal_tax:,.2f} is below minus the refundable credits "
                    f"({r.refundable_credits:,.2f})",
                    r.federal_tax,
                )
            )
        liability = r.ordinary_tax + r.preferential_tax + r.kiddie_tax + r.amt
        if r.nonrefundable_credits > liability + MONEY_TOLERANCE:
            violations.append(
                Violation(
                    ctx.year,
                    "taxes_non_negative",
                    f"{names}: nonrefundable credits {r.nonrefundable_credits:,.2f} exceed the income tax {liability:,.2f}",
                    r.nonrefundable_credits - liability,
                )
            )
    return violations


def deduction_choice(ctx: YearContext) -> list[Violation]:
    """An itemizing return's itemized deductions are at least its standard deduction, and every return
    deducts ``max(standard, itemized) + senior``."""
    violations = []
    for r in ctx.returns:
        names = ", ".join(r.member_names)
        if r.deduction_taken == "itemized" and r.itemized_deductions < r.standard_deduction - MONEY_TOLERANCE:
            violations.append(
                Violation(
                    ctx.year,
                    "deduction_choice",
                    f"{names}: itemized {r.itemized_deductions:,.2f} below the standard deduction "
                    f"{r.standard_deduction:,.2f}",
                    r.itemized_deductions - r.standard_deduction,
                )
            )
        standard = r.standard_deduction + r.charitable_deduction_non_itemizer
        base = r.itemized_deductions if r.deduction_taken == "itemized" else standard
        if base < max(standard, r.itemized_deductions) - MONEY_TOLERANCE:
            violations.append(
                Violation(
                    ctx.year,
                    "deduction_choice",
                    f"{names}: took the smaller deduction ({r.deduction_taken} {base:,.2f})",
                    base - max(standard, r.itemized_deductions),
                )
            )
        expected = base + r.senior_deduction + r.qbi_deduction
        if abs(r.deduction - expected) > MONEY_TOLERANCE:
            violations.append(
                Violation(
                    ctx.year,
                    "deduction_choice",
                    f"{names}: deducted {r.deduction:,.2f}, expected the larger of standard (+ non-itemizer charity) "
                    f"and itemized, + senior + QBI = {expected:,.2f}",
                    r.deduction - expected,
                )
            )
    return violations


def return_identities(ctx: YearContext) -> list[Violation]:
    """The Form 1040 identities of each return (see :mod:`life_model.tax.return_record`)."""
    violations = []
    for r in ctx.returns:
        names = ", ".join(r.member_names)
        checks = {
            "agi = max(total income - adjustments, 0)": (r.agi, max(r.total_income - r.total_adjustments, 0.0)),
            "taxable income = max(agi - deduction, 0)": (r.taxable_income, max(r.agi - r.deduction, 0.0)),
            "federal tax = taxes - credits + penalties": (
                r.federal_tax,
                r.ordinary_tax
                + r.preferential_tax
                + r.kiddie_tax
                + r.niit
                + r.amt
                - r.total_credits
                + r.total_penalties,
            ),
            "total tax = federal + state + payroll + self-employment": (
                r.total_tax,
                r.federal_tax + r.state_tax + r.social_security_tax + r.medicare_tax + r.self_employment_tax,
            ),
            "credits = nonrefundable + refundable": (
                r.total_credits,
                r.nonrefundable_credits + r.refundable_credits,
            ),
        }
        for what, (value, expected) in checks.items():
            if abs(value - expected) > MONEY_TOLERANCE:
                violations.append(
                    Violation(
                        ctx.year,
                        "return_identities",
                        f"{names}: {what}: {value:,.2f} vs {expected:,.2f}",
                        value - expected,
                    )
                )
    return violations


#: Every invariant, in report order. Add a rule by appending ``name: function(YearContext)``.
INVARIANTS: dict[str, Invariant] = {
    "conservation": conservation,
    "continuity": continuity,
    "no_negative_balances": no_negative_balances,
    "no_draw_above_cash_floor": no_draw_above_cash_floor,
    "contribution_limits": contribution_limits,
    "no_income_after_job_end": no_income_after_job_end,
    "fica_wage_base": fica_wage_base,
    "rmd_minimum": rmd_minimum,
    "taxes_non_negative": taxes_non_negative,
    "deduction_choice": deduction_choice,
    "return_identities": return_identities,
}


# --------------------------------------------------------------------------------------------------
# Running them
# --------------------------------------------------------------------------------------------------


def year_start(model: "LifeModel") -> None:
    """Snapshot what the year-end checks need from before the stages run (the prior year-end pre-tax
    balances of RMD-eligible accounts). Called by ``LifeModel.step`` when checks are on."""
    from .account.job401k import Job401kAccount
    from .account.traditional_IRA import TraditionalIRA
    from .ledger import account_label

    pretax = {}
    for agent in model.agents:
        if isinstance(agent, Job401kAccount):
            balance = agent.pretax_balance
        elif isinstance(agent, TraditionalIRA):
            balance = agent.balance
        else:
            continue
        person = getattr(agent, "person", None)
        if person is not None and not person.is_deceased:
            pretax[account_label(agent)] = (person.unique_id, balance)
    model._invariant_snapshots[model.year] = {"pretax": pretax}


def _context(model: "LifeModel", year: int) -> YearContext:
    balances = model.balance_sheets[year]
    previous = model.balance_sheets.get(year - 1)
    between = model.ledger.between(previous.ledger_end, balances.ledger_start) if previous is not None else []
    return YearContext(
        model=model,
        year=year,
        balances=balances,
        entries=model.ledger.between(balances.ledger_start, balances.ledger_end),
        returns=model.tax_returns.for_year(year),
        events=model.event_log.for_year(year),
        previous=previous,
        between=between,
        snapshot=getattr(model, "_invariant_snapshots", {}).get(year),
    )


def check_year(model: "LifeModel", year: int, *, only: "list[str] | None" = None) -> list[Violation]:
    """Every invariant's violations for one simulated ``year`` (needs its balance sheets)."""
    if year not in model.balance_sheets:
        raise ValueError(f"No balance sheets were recorded for {year} (run with collect_data=True or checks on)")
    ctx = _context(model, year)
    violations: list[Violation] = []
    for name, invariant in INVARIANTS.items():
        if only is None or name in only:
            violations.extend(invariant(ctx))
    return violations


def check_model(model: "LifeModel", *, only: "list[str] | None" = None) -> list[Violation]:
    """Every invariant over every simulated year of a run (``rmd_minimum`` needs the year-start
    snapshots a model built with checks on records)."""
    violations: list[Violation] = []
    for year in sorted(model.balance_sheets):
        violations.extend(check_year(model, year, only=only))
    return violations


def assert_invariants(model: "LifeModel", *, only: "list[str] | None" = None) -> None:
    """Raise :class:`InvariantError` listing every violation of a finished run."""
    violations = check_model(model, only=only)
    if violations:
        raise InvariantError(violations)


def run_year_checks(model: "LifeModel", year: int) -> list[Violation]:
    """Run the year's invariants under ``model.checks`` (called by ``LifeModel.step``)."""
    mode = model.checks
    if mode == "off":
        return []
    violations = check_year(model, year)
    model.invariant_violations.extend(violations)
    if violations:
        if mode == "strict":
            raise InvariantError(violations)
        for violation in violations:
            warnings.warn(str(violation), InvariantWarning, stacklevel=3)
    return violations
