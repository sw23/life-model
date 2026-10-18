# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Money-conservation checks (Plan 28 task 3); :mod:`life_model.invariants` (Plan 29 D4) runs them with
the other yearly invariants.

**Money conservation.** For every simulated year, the change in household net worth (assets minus
liabilities, measured independently of the ledger by
:func:`~life_model.ledger.household_balance_sheet`) must equal the year's net external flow on the
cash-flow ledger (inflows minus outflows; transfers between household accounts net to zero), to
within a dollar. A residual is money the simulation created or destroyed without recording why.

The model records an opening and a closing balance sheet around each simulated year and each
simulated month (when it collects data), along with the range of ledger entries posted during it,
so the check also works on a finished run. The monthly check (``monthly=True``) is the finer guard:
every month's change in net worth must equal that month's ledger flows.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ledger import BalanceSheet
    from .model import LifeModel

#: Default tolerance of the conservation check, in dollars per year.
CONSERVATION_TOLERANCE = 1.0


@dataclass(frozen=True)
class YearBalances:
    """Balance sheets around one ``step()`` and the ledger entries posted during it."""

    year: int
    opening: "BalanceSheet"
    closing: "BalanceSheet"
    #: ``[ledger_start, ledger_end)`` is the slice of ``model.ledger`` posted during the step.
    ledger_start: int
    ledger_end: int


@dataclass(frozen=True)
class MonthBalances:
    """Balance sheets around one simulated month and the ledger entries posted during it."""

    year: int
    month: int
    opening: "BalanceSheet"
    closing: "BalanceSheet"
    ledger_start: int
    ledger_end: int


@dataclass(frozen=True)
class ConservationRecord:
    """One year (or, with ``month`` set, one month) of the conservation check."""

    year: int
    opening_net_worth: float
    closing_net_worth: float
    inflows: float
    outflows: float
    #: The month (1-12) of a monthly record; None for a year.
    month: int | None = None

    @property
    def change(self) -> float:
        """Closing minus opening net worth."""
        return self.closing_net_worth - self.opening_net_worth

    @property
    def net_flow(self) -> float:
        """Ledger inflows minus outflows."""
        return self.inflows - self.outflows

    @property
    def residual(self) -> float:
        """Net-worth change the ledger does not explain (0 when money is conserved)."""
        return self.change - self.net_flow

    def ok(self, tolerance: float = CONSERVATION_TOLERANCE) -> bool:
        return abs(self.residual) <= tolerance


class ConservationError(AssertionError):
    """Raised by :func:`assert_conservation` when a year's net worth changed by more (or less) than
    the ledger's net flow."""


def _record(model: "LifeModel", balances, month: int | None = None) -> ConservationRecord:
    entries = model.ledger.between(balances.ledger_start, balances.ledger_end)
    return ConservationRecord(
        year=balances.year,
        month=month,
        opening_net_worth=balances.opening.net_worth,
        closing_net_worth=balances.closing.net_worth,
        inflows=sum(e.amount for e in entries if e.is_inflow),
        outflows=sum(e.amount for e in entries if e.is_outflow),
    )


def conservation_records(model: "LifeModel", *, monthly: bool = False) -> list[ConservationRecord]:
    """One :class:`ConservationRecord` per simulated year, or per simulated month with ``monthly=True``
    (requires a model that collected data)."""
    if monthly:
        return [_record(model, balances, balances.month) for balances in model.month_balance_sheets.values()]
    return [_record(model, balances) for balances in model.balance_sheets.values()]


def check_conservation(
    model: "LifeModel", *, tolerance: float = CONSERVATION_TOLERANCE, monthly: bool = False
) -> list[ConservationRecord]:
    """The years (or months, with ``monthly=True``) whose residual exceeds ``tolerance`` dollars (empty
    when money is conserved)."""
    return [record for record in conservation_records(model, monthly=monthly) if not record.ok(tolerance)]


def account_residuals(
    model: "LifeModel", year: int, *, tolerance: float = 0.01, month: int | None = None
) -> dict[str, float]:
    """Per-account diagnostic for ``year`` (or one ``month`` of it): each balance-sheet line's change
    minus the ledger's net posting to that label, for lines where they differ by more than
    ``tolerance``.

    Settlement posts household bills from one payer account, so a spouse's bank can show offsetting
    residuals; a line whose residual does not cancel against another one points at the bug.
    """
    balances = model.balance_sheets[year] if month is None else model.month_balance_sheets[(year, month)]
    entries = model.ledger.between(balances.ledger_start, balances.ledger_end)
    posted: dict[str, float] = {}
    for entry in entries:
        if entry.from_account is not None:
            posted[entry.from_account] = posted.get(entry.from_account, 0.0) - entry.amount
        if entry.to_account is not None:
            posted[entry.to_account] = posted.get(entry.to_account, 0.0) + entry.amount
    labels = set(balances.opening.lines) | set(balances.closing.lines) | set(posted)
    residuals = {}
    for label in sorted(labels):
        change = balances.closing.lines.get(label, 0.0) - balances.opening.lines.get(label, 0.0)
        residual = change - posted.get(label, 0.0)
        if abs(residual) > tolerance:
            residuals[label] = residual
    return residuals


def assert_conservation(
    model: "LifeModel", *, tolerance: float = CONSERVATION_TOLERANCE, monthly: bool = False
) -> None:
    """Raise :class:`ConservationError` naming every year (every month with ``monthly=True``), and the
    accounts, where net worth moved without a matching ledger flow."""
    if not model.balance_sheets and not model.month_balance_sheets:
        raise ConservationError("No balance sheets were recorded (build the model with collect_data=True and run it)")
    failures = check_conservation(model, tolerance=tolerance, monthly=monthly)
    if not failures:
        return
    lines = []
    for record in failures[:10]:
        when = f"{record.year}-{record.month:02d}" if record.month is not None else f"{record.year}"
        lines.append(
            f"{when}: net worth changed {record.change:,.2f} but the ledger's net flow is "
            f"{record.net_flow:,.2f} (residual {record.residual:,.2f})"
        )
        for label, residual in account_residuals(model, record.year, month=record.month).items():
            name = model.ledger.describe(label)
            lines.append(f"    {name} [{label}]: {residual:,.2f}")
    raise ConservationError("Money was not conserved:\n" + "\n".join(lines))
