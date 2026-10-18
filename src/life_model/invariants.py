# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The simulation invariant checker (Plan 29 D4).

Every invariant is a rule a correct simulated year must satisfy, written against the year's
*results* (the balance sheets around the year and around each of its months, the cash-flow ledger,
the typed events and the tax returns) rather than engine internals, so it holds for any engine that
produces those results. They run once a year, at the year end (after December's taxes):

* ``conservation``: net worth changed by exactly the ledger's net external flow (``checks.py``), over
  the year and over each of its months;
* ``continuity``: between two years, and between two months of a year, nothing moved money without a
  ledger entry (anything a driver does between ``step()`` calls, such as an RL action, must post what
  it moves);
* ``no_negative_balances``: at no month end is an asset below zero or a liability negative;
* ``no_draw_above_cash_floor``: no taxable sale or pre-tax withdrawal by the payment waterfall in a
  month the tax unit ended with cash above its floor (the rule Plan 26 item 4 broke): the waterfall
  runs monthly, so a draw in a lean month is legitimate even when later months' pay refills the bank,
  and money that reached the bank after the month's last draw (a year-end insurance payout, a tax
  refund) does not count;
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
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from .checks import CONSERVATION_TOLERANCE
from .ledger import FlowKind

if TYPE_CHECKING:
    from .checks import MonthBalances, YearBalances
    from .ledger import BalanceSheet, LedgerEntry
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
_EARNED_KINDS = frozenset({FlowKind.WAGE.value, FlowKind.BONUS.value, FlowKind.VEST.value})


@dataclass(frozen=True)
class Violation:
    """One broken invariant in one year."""

    year: int
    invariant: str
    message: str
    amount: float | None = None
    person_id: int | None = None
    account: str | None = None
    #: The month (1-12) of a monthly rule's violation; None for a whole-year rule.
    month: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def __str__(self) -> str:
        when = f"{self.year}-{self.month:02d}" if self.month is not None else f"{self.year}"
        return f"{when} {self.invariant}: {self.message}"


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
    #: The year's monthly balance sheets by month (empty on a model that recorded none).
    months: "dict[int, MonthBalances]" = field(default_factory=dict)

    def month_closing(self, month: int) -> "BalanceSheet":
        """The balance sheet at the end of ``month`` (the year's closing sheet when months were not
        recorded)."""
        balances = self.months.get(month)
        return balances.closing if balances is not None else self.balances.closing

    def month_ends(self) -> "list[tuple[int | None, BalanceSheet]]":
        """``(month, closing sheet)`` for each simulated month, or ``[(None, year closing)]``."""
        if not self.months:
            return [(None, self.balances.closing)]
        return [(month, self.months[month].closing) for month in sorted(self.months)]

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


def monthly_conservation(ctx: YearContext) -> list[Violation]:
    """Each month of the year: net worth changed by exactly the ledger's net flow posted in that month
    (catches money that appears in one month and leaves in another, which the yearly check nets)."""
    from .checks import account_residuals

    violations = []
    for month, balances in sorted(ctx.months.items()):
        entries = ctx.model.ledger.between(balances.ledger_start, balances.ledger_end)
        net_flow = sum(e.net_worth_effect for e in entries)
        change = balances.closing.net_worth - balances.opening.net_worth
        residual = change - net_flow
        if abs(residual) <= CONSERVATION_TOLERANCE:
            continue
        accounts = ", ".join(
            f"{ctx.model.ledger.describe(label)} {value:+,.2f}"
            for label, value in list(account_residuals(ctx.model, ctx.year, month=month).items())[:6]
        )
        violations.append(
            Violation(
                ctx.year,
                "monthly_conservation",
                f"net worth changed {change:,.2f} in the month but the ledger's net flow is {net_flow:,.2f} "
                f"(residual {residual:,.2f}; by account: {accounts or 'n/a'})",
                amount=residual,
                month=month,
            )
        )
    return violations


def _unposted_move(ctx: YearContext, before, after, between) -> "tuple[float, float, list[str]] | None":
    """``(change, posted net flow, unposted lines)`` when net worth moved from ``before`` to ``after``
    by more than the ``between`` entries explain, else None."""
    net_flow = sum(e.net_worth_effect for e in between)
    change = after.net_worth - before.net_worth
    if abs(change - net_flow) <= CONSERVATION_TOLERANCE:
        return None
    posted: dict[str, float] = {}
    for entry in between:
        if entry.from_account is not None:
            posted[entry.from_account] = posted.get(entry.from_account, 0.0) - entry.amount
        if entry.to_account is not None:
            posted[entry.to_account] = posted.get(entry.to_account, 0.0) + entry.amount
    lines = []
    for label in sorted(set(before.lines) | set(after.lines)):
        moved = after.lines.get(label, 0.0) - before.lines.get(label, 0.0) - posted.get(label, 0.0)
        if abs(moved) > MONEY_TOLERANCE:
            lines.append(f"{ctx.model.ledger.describe(label)} {moved:+,.2f}")
    return change, net_flow, lines


def continuity(ctx: YearContext) -> list[Violation]:
    """Between the previous year's close and this year's open, and between one month's close and the
    next month's open, net worth moved only by ledger entries posted in between (a driver acting
    between ``step()`` calls must post what it moves)."""
    gaps = []
    if ctx.previous is not None:
        gaps.append((None, ctx.previous.closing, ctx.balances.opening, ctx.between, f"{ctx.year - 1}'s close"))
    months = sorted(ctx.months)
    for prior, month in pairwise(months):
        before, after = ctx.months[prior], ctx.months[month]
        between = ctx.model.ledger.between(before.ledger_end, after.ledger_start)
        gaps.append((month, before.closing, after.opening, between, f"{ctx.year}-{prior:02d}'s close"))
    violations = []
    for month, before, after, between, since in gaps:
        moved = _unposted_move(ctx, before, after, between)
        if moved is None:
            continue
        change, net_flow, lines = moved
        until = f"{ctx.year}'s open" if month is None else f"{ctx.year}-{month:02d}'s open"
        violations.append(
            Violation(
                ctx.year,
                "continuity",
                f"net worth moved {change:,.2f} between {since} and {until} but only {net_flow:,.2f} was posted "
                f"(residual {change - net_flow:,.2f}; unposted: {', '.join(lines[:6]) or 'n/a'})",
                amount=change - net_flow,
                month=month,
            )
        )
    return violations


def _liability_labels(ctx: YearContext) -> set[str]:
    from .base_classes import Loan
    from .debt.credit_card import RevolvingDebt
    from .ledger import account_label

    labels = {account_label(a) for a in ctx.model.agents if isinstance(a, (Loan, RevolvingDebt))}
    labels.update(label for label in ctx.balances.closing.lines if label.startswith("Debt:"))
    return labels


def no_negative_balances(ctx: YearContext) -> list[Violation]:
    """At no month end is an asset line below zero or a liability line above zero (a negative debt).
    Each account is reported once a year, at the first month end it is wrong."""
    liabilities = _liability_labels(ctx)
    violations = []
    seen: set[str] = set()
    for month, sheet in ctx.month_ends():
        for label, value in sheet.lines.items():
            if label in seen:
                continue
            is_liability = label in liabilities or label.startswith("Debt:")
            if (not is_liability and value < -MONEY_TOLERANCE) or (is_liability and value > MONEY_TOLERANCE):
                seen.add(label)
                what = "liability below zero" if is_liability else "negative balance"
                violations.append(
                    Violation(
                        ctx.year,
                        "no_negative_balances",
                        f"{ctx.model.ledger.describe(label)}: {what} ({value:,.2f})",
                        amount=value,
                        account=label,
                        person_id=sheet.owners.get(label),
                        month=month,
                    )
                )
    return violations


def _bank_labels(ctx: YearContext, member_ids: "set[int]", sheet: "BalanceSheet | None" = None) -> list[str]:
    from .account.bank import BankAccount

    agents = ctx.agents_by_label()
    closing = ctx.balances.closing if sheet is None else sheet
    labels = []
    for label in closing.lines:
        owner = closing.owners.get(label)
        if owner not in member_ids:
            continue
        if label.startswith("Cash:") or isinstance(agents.get(label), BankAccount):
            labels.append(label)
    return labels


#: Ledger causes of the payment waterfall's draws (``TaxUnit``: monthly bills, December's taxes, a
#: purchase raised in cash).
_WATERFALL_CAUSES = ("pay ", "fund ", "raise cash for ")


def _inflows_after_last_draw(ctx: YearContext, month: int | None, banks: "set[str]") -> float:
    """Money that reached the unit's ``banks`` in ``month`` after the waterfall's last draw (a year-end
    insurance payout, a refund of refundable credits): the draw could not have spent it, so it does not
    count against the floor."""
    balances = ctx.months.get(month) if month is not None else None
    entries = (
        ctx.model.ledger.between(balances.ledger_start, balances.ledger_end) if balances is not None else ctx.entries
    )
    last = None
    for index, entry in enumerate(entries):
        if (
            entry.kind in (FlowKind.SALE.value, FlowKind.WITHDRAWAL.value)
            and entry.to_account in banks
            and (entry.cause or "").startswith(_WATERFALL_CAUSES)
        ):
            last = index
    if last is None:
        return 0.0
    inflows = 0.0
    for entry in entries[last + 1 :]:
        if entry.to_account in banks and entry.from_account not in banks and entry.amount > 0:
            inflows += entry.amount
        elif entry.from_account in banks and entry.to_account not in banks and entry.amount < 0:
            inflows -= entry.amount  # a negative payment out of the bank: a tax refund
    return inflows


def no_draw_above_cash_floor(ctx: YearContext) -> list[Violation]:
    """A tax unit whose payment waterfall sold taxable holdings or withdrew pre-tax money in a month must
    end that month with no more than its cash floor in its banks: money sitting in a member's bank
    should have been spent before anything taxable was sold (Plan 26 item 4). The waterfall pays each
    month's bills (December's also funds the year's taxes), so the rule looks at the draw's month: a
    draw in a lean month is fine when a later month's pay refills the bank, and money that reached the
    banks after the month's last draw does not count. Reported once per unit and year, at the first
    offending month."""
    floor = getattr(ctx.model, "cash_floor", DEFAULT_CASH_FLOOR)
    draws: dict[tuple[int, int | None], float] = {}
    for event in ctx.events:
        if event.kind.value in _WATERFALL_DRAW_KINDS and event.person_id is not None and event.amount:
            key = (event.person_id, getattr(event, "month", None) if ctx.months else None)
            draws[key] = draws.get(key, 0.0) + event.amount
    if not draws:
        return []
    violations = []
    for tax_return in ctx.returns:
        members = set(tax_return.member_ids)
        months = sorted({month for person, month in draws if person in members}, key=lambda m: m or 0)
        for month in months:
            drawn = sum(amount for (person, m), amount in draws.items() if person in members and m == month)
            if drawn <= MONEY_TOLERANCE:
                continue
            sheet = ctx.balances.closing if month is None else ctx.month_closing(month)
            banks = _bank_labels(ctx, members, sheet)
            cash = sum(sheet.lines[label] for label in banks) - _inflows_after_last_draw(ctx, month, set(banks))
            if cash > floor + CASH_FLOOR_TOLERANCE:
                names = ", ".join(tax_return.member_names)
                when = "year" if month is None else f"month ({ctx.year}-{month:02d})"
                violations.append(
                    Violation(
                        ctx.year,
                        "no_draw_above_cash_floor",
                        f"{names}: the waterfall sold or withdrew {drawn:,.2f} of taxable money while the unit ended "
                        f"the {when} with {cash:,.2f} in its banks (floor {floor:,.2f})",
                        amount=cash - floor,
                        person_id=tax_return.unit_id,
                        month=month,
                    )
                )
                break
    return violations


def _contributions_by(ctx: YearContext) -> dict[str, dict[int, float]]:
    """``{account label: {person_id: dollars}}`` of contributions (employee and employer) this year."""
    out: dict[str, dict[int, float]] = {}
    for entry in ctx.entries:
        if entry.kind != FlowKind.CONTRIBUTION.value or entry.to_account is None:
            continue
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
    for entry in ctx.entries:
        if entry.kind == FlowKind.MATCH.value and entry.to_account is not None:
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
        if entry.from_account is not None and entry.kind in (FlowKind.RMD.value, FlowKind.WITHDRAWAL.value):
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
        liability = r.ordinary_tax + r.preferential_tax + r.amt
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
        expected = max(r.standard_deduction, r.itemized_deductions) + r.senior_deduction
        if abs(r.deduction - expected) > MONEY_TOLERANCE:
            violations.append(
                Violation(
                    ctx.year,
                    "deduction_choice",
                    f"{names}: deducted {r.deduction:,.2f}, expected max(standard, itemized) + senior = {expected:,.2f}",
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
                r.ordinary_tax + r.preferential_tax + r.niit + r.amt - r.total_credits + r.total_penalties,
            ),
            "total tax = federal + state + payroll": (
                r.total_tax,
                r.federal_tax + r.state_tax + r.social_security_tax + r.medicare_tax,
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
    "monthly_conservation": monthly_conservation,
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
        months={month: sheet for (y, month), sheet in model.month_balance_sheets.items() if y == year},
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
