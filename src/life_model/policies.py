# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Standing savings policies (Plan 27 D4): recurring contributions, a surplus sweep, Roth conversions.

Each policy is a plain object attached to a person; the engine carries it out every period until it is
changed or removed, so a running model can change it between months (the RL environment's standing
policies, Plan 32 D8, are these objects):

* :class:`ContributionPlan` (``person.add_contribution_plan(plan)``, ``person.contribution_plans``):
  money into an account every month. ``source="payroll"`` into a 401(k) sets the plan's deferral percent
  (``bucket`` pre-tax, Roth or after-tax); into an HSA it is a §125 payroll deferral (excluded from wages
  and FICA). Otherwise (``source="bank"``) it moves money from the owner's bank after the month's bills,
  never more than the bank holds (in December, less the year's estimated tax), and a tax-advantaged
  account takes at most its remaining room. ``amount_annual`` (dollars a year, or ``"max"``: the account's
  limit) is spread evenly over the plan's ``months``; ``pct_of_pay`` takes that percent of the month's
  gross W-2 pay. ``start`` / ``end`` bound the months a plan contributes in. Change it with :meth:`ContributionPlan.set_rate` / :meth:`ContributionPlan.set_amount`, or
  replace it (``person.add_contribution_plan`` replaces the plan for the same account and bucket).
* :class:`SavingsPolicy` (``person.savings_policy = SavingsPolicy(cash_floor=, sweep_to=)``; None holds
  cash): once a year, after the year's taxes are paid, cash in the owner's banks above ``cash_floor``
  moves to ``sweep_to`` (a brokerage account, a fixed-income holding, a savings account or a
  tax-advantaged account within its room).
* :class:`RothConversionPolicy` (``person.roth_conversion_policy = RothConversionPolicy(
  fill_bracket_pct=12)``): every December before the year's taxes, convert traditional IRA money to a Roth
  IRA, either a fixed ``amount_annual`` or enough to fill the return's ordinary income to the top of the
  ``fill_bracket_pct`` bracket. :func:`convert_to_roth` is the one-off conversion it (and the spec's
  ``convert_to_roth`` event) uses.
"""

import math
from typing import TYPE_CHECKING, ClassVar

from .ledger import FlowKind
from .model import Event, LifeModelAgent

if TYPE_CHECKING:
    from .people.person import Person
    from .work.job import Job

#: ``ContributionPlan`` sources.
CONTRIBUTION_SOURCES = ("bank", "payroll")
#: 401(k) buckets a payroll ``ContributionPlan`` can set.
BUCKETS_401K = ("pretax", "roth", "after_tax")
#: ``ContributionPlan(amount_annual=MAX)``: the account's annual limit.
MAX = "max"


def _period(value, *, end: bool) -> "tuple[int, int] | None":
    """A plan window bound as ``(year, month)``: ``"YYYY-MM"``, ``(year, month)``, or a year (January for a
    start, December for an end); None passes through."""
    if value is None:
        return None
    if isinstance(value, tuple):
        year, month = int(value[0]), int(value[1])
    elif isinstance(value, int) and not isinstance(value, bool):
        year, month = value, 12 if end else 1
    else:
        from .model import parse_year_month

        text = str(value)
        if text.isdigit():
            year, month = int(text), 12 if end else 1
        else:
            year, month = parse_year_month(text)
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1-12, got {month}")
    return year, month


def _months(months: "int | list[int] | tuple[int, ...]") -> tuple[int, ...]:
    if isinstance(months, int):
        if not 1 <= months <= 12:
            raise ValueError("months must be 1-12 (the first n months) or a list of months")
        return tuple(range(1, months + 1))
    chosen = tuple(sorted({int(m) for m in months}))
    if not chosen or any(not 1 <= m <= 12 for m in chosen):
        raise ValueError(f"months must be months 1-12, got {months}")
    return chosen


class ContributionPlan:
    """A recurring contribution into ``account`` (see the module docstring)."""

    def __init__(
        self,
        account,
        *,
        amount_annual: "float | str | None" = None,
        pct_of_pay: float | None = None,
        source: str = "bank",
        months: "int | list[int]" = 12,
        bucket: str | None = None,
        start=None,
        end=None,
    ):
        """A recurring contribution.

        Args:
            account: The account receiving the money (a 401(k), IRA, HSA, brokerage, 529, fixed-income
                holding or bank account).
            amount_annual: Dollars a year, or ``"max"`` (the account's annual limit; 401(k): the 402(g)
                limit). Give this or ``pct_of_pay``.
            pct_of_pay: Percent of gross pay (a 401(k)'s deferral percent; for other accounts, of each
                month's gross W-2 pay).
            source: ``"bank"`` (moved from the owner's bank after the month's bills) or ``"payroll"`` (a
                401(k) deferral, or a pre-tax HSA deferral through the owner's first W-2 job).
            months: Contribute in the first ``n`` months of each year (12: monthly), or in the listed months.
            bucket: For a 401(k): ``"pretax"`` (default), ``"roth"`` or ``"after_tax"``.
            start: First month the plan contributes: ``"YYYY-MM"``, ``(year, month)`` or a year (its January).
                None: from now.
            end: Last month the plan contributes (inclusive): ``"YYYY-MM"``, ``(year, month)`` or a year (its
                December). None: until changed or removed. A 401(k) plan with a window sets the deferral
                percent to 0 outside it.
        """
        from .account.hsa import HealthSavingsAccount
        from .account.job401k import Job401kAccount
        from .base_classes import TaxAdvantagedAccount

        if source not in CONTRIBUTION_SOURCES:
            raise ValueError(f"source must be one of {CONTRIBUTION_SOURCES}, got {source!r}")
        if (amount_annual is None) == (pct_of_pay is None):
            raise ValueError("give exactly one of amount_annual or pct_of_pay")
        if isinstance(amount_annual, str) and amount_annual != MAX:
            raise ValueError(f"amount_annual must be dollars or {MAX!r}")
        if isinstance(amount_annual, (int, float)) and amount_annual < 0:
            raise ValueError("amount_annual must be non-negative")
        if pct_of_pay is not None and not 0 <= pct_of_pay <= 100:
            raise ValueError("pct_of_pay must be 0-100")
        is_401k = isinstance(account, Job401kAccount)
        if is_401k:
            if source != "payroll":
                raise ValueError("401(k) contributions come from payroll (source='payroll')")
            bucket = bucket or "pretax"
            if bucket not in BUCKETS_401K:
                raise ValueError(f"bucket must be one of {BUCKETS_401K}")
            if account.job is None:
                raise ValueError("a standalone (old-employer) 401(k) takes no contributions")
        elif bucket is not None:
            raise ValueError("bucket is for 401(k) plans")
        if source == "payroll" and not is_401k and not isinstance(account, HealthSavingsAccount):
            raise ValueError("payroll contributions go to a 401(k) or an HSA; use source='bank' for other accounts")
        if amount_annual == MAX and not (is_401k or isinstance(account, TaxAdvantagedAccount) or _is_529(account)):
            raise ValueError("amount_annual='max' needs an account with an annual limit")
        self.account = account
        self.amount_annual = amount_annual
        self.pct_of_pay = pct_of_pay
        self.source = source
        self.months = _months(months)
        self.bucket = bucket
        self.start = _period(start, end=False)
        self.end = _period(end, end=True)
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError(f"end {self.end} is before start {self.start}")
        #: Contributed by this plan so far this year (``(year, dollars)``).
        self._ytd: tuple[int, float] = (0, 0.0)
        self.person: Person | None = None

    def __repr__(self) -> str:
        amount = (
            f"pct_of_pay={self.pct_of_pay:g}"
            if self.pct_of_pay is not None
            else f"amount_annual={self.amount_annual!r}"
        )
        bucket = f", bucket={self.bucket!r}" if self.bucket else ""
        window = "".join(
            f", {name}='{value[0]:04d}-{value[1]:02d}'"
            for name, value in (("start", self.start), ("end", self.end))
            if value is not None
        )
        return f"ContributionPlan({type(self.account).__name__}, {amount}, source={self.source!r}{bucket}{window})"

    @property
    def has_window(self) -> bool:
        """Whether the plan has a start or an end month."""
        return self.start is not None or self.end is not None

    def active(self, year: int, month: int) -> bool:
        """Whether the plan contributes in ``(year, month)`` (inside its start/end window)."""
        if self.start is not None and (year, month) < self.start:
            return False
        return self.end is None or (year, month) <= self.end

    # --- changing it ---

    @property
    def is_401k(self) -> bool:
        from .account.job401k import Job401kAccount

        return isinstance(self.account, Job401kAccount)

    def set_rate(self, pct_of_pay: float) -> None:
        """Contribute ``pct_of_pay`` percent of pay from now on."""
        if not 0 <= pct_of_pay <= 100:
            raise ValueError("pct_of_pay must be 0-100")
        self.pct_of_pay, self.amount_annual = pct_of_pay, None
        self.apply_401k_election()

    def set_amount(self, amount_annual: "float | str") -> None:
        """Contribute ``amount_annual`` dollars a year (or ``"max"``) from now on."""
        if isinstance(amount_annual, str) and amount_annual != MAX:
            raise ValueError(f"amount_annual must be dollars or {MAX!r}")
        self.amount_annual, self.pct_of_pay = amount_annual, None
        self.apply_401k_election()

    def apply_401k_election(self) -> None:
        """Write a 401(k) plan's percent onto the account (``"max"``/dollars become the percent of this
        year's plan pay that reaches them; the job's 402(g) room check stops the deferral at the limit)."""
        if not self.is_401k:
            return
        account = self.account
        if self.pct_of_pay is not None:
            pct = self.pct_of_pay
        else:
            job = account.job
            pay = account.plan_compensation(job.salary.base, job.salary.bonus) if job is not None else 0.0
            if self.amount_annual == MAX:
                owner = account.person
                target = owner.model.year_config.get_job_401k_contrib_limit(owner.age_in(owner.model.year))
                if self.bucket == "after_tax":
                    target = owner.model.year_config.get_job_401k_annual_additions_limit()
            else:
                target = float(self.amount_annual or 0.0)
            pct = min(100.0, math.ceil(target / pay * 10000) / 100) if pay > 0 else 0.0
        setattr(account, f"{self.bucket}_contrib_percent", pct)

    # --- amounts ---

    def contributed_ytd(self, year: int) -> float:
        return self._ytd[1] if self._ytd[0] == year else 0.0

    def _record(self, year: int, amount: float) -> None:
        self._ytd = (year, self.contributed_ytd(year) + amount)

    def annual_target(self, year: int | None = None) -> float:
        """This year's dollar target (``"max"``: the account's annual limit). With ``year``, a dollar amount
        is prorated to the plan's months inside its start/end window that year."""
        if self.amount_annual == MAX:
            if _is_529(self.account):
                return self.account.annual_contribution_limit
            return self.account.annual_contribution_limit()
        amount = float(self.amount_annual or 0.0)
        if year is not None and self.has_window:
            amount *= sum(1 for m in self.months if self.active(year, m)) / len(self.months)
        return amount

    def _remaining_months(self, year: int, month: int) -> int:
        """Contribution months left this year, from ``month`` (inside the window)."""
        return sum(1 for m in self.months if m >= month and self.active(year, m))

    def month_amount(self, year: int, month: int, gross_pay: float) -> float:
        """What the plan wants to put in this month (before limits and cash). A dollar plan spreads what
        the year's target leaves over the plan's remaining months this year (inside its window)."""
        if month not in self.months or not self.active(year, month):
            return 0.0
        if self.pct_of_pay is not None:
            return gross_pay * self.pct_of_pay / 100
        remaining_months = self._remaining_months(year, month)
        return max(0.0, self.annual_target(year) - self.contributed_ytd(year)) / max(1, remaining_months)

    def payroll_amount(self, job: "Job", booked: float) -> float:
        """This month's payroll HSA deferral through ``job``. ``booked`` is the HSA money (employee and
        employer) this month's paycheck already booked, so a true-up recomputes the same amount. A
        ``"max"`` plan spreads what the year's limit leaves, after the employer's remaining payroll
        contributions, over the plan's remaining months."""
        model = job.model
        month = model.month
        if month not in self.months or not self.active(model.year, month):
            return 0.0
        if self.pct_of_pay is not None:
            gross = job.salary.base / 12 + (job.salary.bonus if month == job.salary.bonus_month else 0.0)
            return gross * self.pct_of_pay / 100
        remaining_months = self._remaining_months(model.year, month)
        if self.amount_annual != MAX:
            return float(self.amount_annual or 0.0) / len(self.months)
        account = self.account
        employer = job.payroll.hsa_employer_annual / 12 if job.payroll is not None else 0.0
        employer_left = employer * (13 - month)
        room = account.annual_contribution_limit() - (account.contributions_ytd - booked) - employer_left
        return max(0.0, room) / max(1, remaining_months)


def _is_529(account) -> bool:
    from .dependents.plan529 import Plan529

    return isinstance(account, Plan529)


class SavingsPolicy:
    """Invest cash above ``cash_floor`` in ``sweep_to`` once a year, after the year's taxes are paid."""

    def __init__(self, *, cash_floor: float, sweep_to=None):
        """A surplus sweep.

        Args:
            cash_floor: Dollars kept in the owner's (non-reserve) bank accounts.
            sweep_to: Where the surplus goes: a brokerage account, fixed-income holding, bank account or
                tax-advantaged account (within its room). None keeps the cash (no sweep).
        """
        if cash_floor < 0:
            raise ValueError("cash_floor must be non-negative")
        self.cash_floor = float(cash_floor)
        self.sweep_to = sweep_to

    def __repr__(self) -> str:
        target = type(self.sweep_to).__name__ if self.sweep_to is not None else None
        return f"SavingsPolicy(cash_floor={self.cash_floor:g}, sweep_to={target})"


class RothConversionPolicy:
    """Convert traditional IRA money to a Roth IRA every December before the year's taxes."""

    def __init__(
        self,
        *,
        fill_bracket_pct: float | None = None,
        amount_annual: float | None = None,
        source=None,
        target=None,
        until_age: int | None = None,
    ):
        """A standing Roth conversion.

        Args:
            fill_bracket_pct: Convert enough to fill the return's ordinary taxable income to the top of the
                bracket with this rate (12, 22, ...).
            amount_annual: Or convert this many dollars a year.
            source: The account converted from (a traditional IRA or a 401(k)'s pre-tax money, in plan);
                default every traditional IRA of the owner.
            target: The Roth IRA receiving it (default the owner's first, opened if needed).
            until_age: Stop once the owner reaches this age (by the end of the year); None: every year.
        """
        if (fill_bracket_pct is None) == (amount_annual is None):
            raise ValueError("give exactly one of fill_bracket_pct or amount_annual")
        self.fill_bracket_pct = fill_bracket_pct
        self.amount_annual = amount_annual
        self.source = source
        self.target = target
        self.until_age = until_age

    def __repr__(self) -> str:
        what = (
            f"fill_bracket_pct={self.fill_bracket_pct:g}"
            if self.fill_bracket_pct is not None
            else f"amount_annual={self.amount_annual:g}"
        )
        return f"RothConversionPolicy({what})"


# ----------------------------------------------------------------------
# Roth conversions
# ----------------------------------------------------------------------


def bracket_top(person: "Person", rate_pct: float) -> float:
    """The top of the ordinary bracket taxed at ``rate_pct`` for ``person``'s return this year (taxable
    income dollars)."""
    from .people.tax_unit import TaxUnit
    from .tax.federal import get_federal_tax_brackets

    unit = TaxUnit.for_member(person)
    for low, high, rate in get_federal_tax_brackets(unit.filing_status, unit.config):
        if abs(rate - rate_pct) < 1e-9:
            return float(high)
    raise ValueError(f"no {rate_pct:g}% bracket for this return")


def conversion_room(person: "Person", rate_pct: float) -> float:
    """Taxable conversion income that brings the return's ordinary taxable income to the top of the
    ``rate_pct`` bracket (0 when it is already there). Uses the year's income booked so far."""
    from .people.tax_unit import TaxUnit

    unit = TaxUnit.for_member(person)
    top = bracket_top(person, rate_pct)

    def ordinary(extra: float) -> float:
        return unit.get_income_taxes_due(extra).taxable_ordinary

    if ordinary(0.0) >= top:
        return 0.0
    low, high = 0.0, max(top, 1.0) * 2 + unit.agi()
    for _ in range(60):
        mid = (low + high) / 2
        if ordinary(mid) > top:
            high = mid
        else:
            low = mid
        if high - low < 0.5:
            break
    # Re-post the taxable Social Security share for the year's income without the prospective amount.
    unit.get_income_taxes_due()
    return low


def convert_to_roth(
    person: "Person",
    amount: float | None = None,
    *,
    fill_bracket_pct: float | None = None,
    source=None,
    target=None,
) -> float:
    """Convert pre-tax money to Roth now (IRC §408A(d)(3)); returns the amount converted.

    From a traditional IRA (``source``, default all of the owner's) the conversion is pro rata to Form 8606
    basis: the basis share is tax-free and the rest is ordinary income this year (no 10% additional tax);
    it lands in ``target`` (default the owner's first Roth IRA, opened if needed) as conversion basis. From a
    :class:`~life_model.account.job401k.Job401kAccount` it is an in-plan Roth rollover of pre-tax money.
    Give ``amount`` (dollars) or ``fill_bracket_pct`` (convert enough to fill the return's ordinary income to
    the top of that bracket, from the year's income so far: call it in December for the whole year).
    """
    from .account.job401k import Job401kAccount
    from .account.roth_IRA import RothIRA
    from .account.traditional_IRA import _reduce_ira_basis, ira_basis_ratio

    if (amount is None) == (fill_bracket_pct is None):
        raise ValueError("give exactly one of amount or fill_bracket_pct")
    model = person.model
    if isinstance(source, Job401kAccount):
        taxable_fraction = 1.0
        available = source.pretax_balance
    else:
        sources = [source] if source is not None else [ira for ira in person.traditional_iras if ira.balance > 0]
        available = sum(ira.balance for ira in sources)
        taxable_fraction = 1.0 - ira_basis_ratio(person)
    if available <= 0:
        return 0.0
    if fill_bracket_pct is not None:
        room = conversion_room(person, fill_bracket_pct)
        gross = room / taxable_fraction if taxable_fraction > 0 else available
    else:
        gross = float(amount or 0.0)
    gross = min(gross, available)
    if gross < 0.005:
        return 0.0
    cause = f"{model.year} Roth conversion"
    if isinstance(source, Job401kAccount):
        # Pre-tax to Roth inside the same account: no ledger entry (no money moves between accounts).
        converted = source.convert_pretax_to_roth(gross)
    else:
        if target is None:
            target = person.roth_iras[0] if person.roth_iras else RothIRA(person)
        converted = 0.0
        for ira in sources:
            if converted >= gross:
                break
            taken = ira.withdraw(gross - converted)
            if taken > 0:
                model.ledger.post(
                    taken, FlowKind.TRANSFER, from_account=ira, to_account=target, cause=cause, agent=person
                )
            converted += taken
        nontaxable = converted * (1 - taxable_fraction)
        if nontaxable > 0:
            _reduce_ira_basis(person, nontaxable)
        taxable = converted - nontaxable
        if taxable > 0:
            from .tax.income import IncomeType

            person.income.add(IncomeType.PRETAX_DISTRIBUTION, taxable, source="roth_conversion")
        target.receive_conversion(converted, taxable)
    person.roth_conversions_ytd = getattr(person, "roth_conversions_ytd", 0.0) + converted
    model.event_log.add(Event(f"{person.name} converted ${converted:,.0f} to Roth"))
    return converted


# ----------------------------------------------------------------------
# The engine
# ----------------------------------------------------------------------


class PolicyRunner(LifeModelAgent):
    """Carries out the people's standing policies (one per model, created when the first is attached).

    * ``on_year_start`` (5): re-derive 401(k) percents of dollar / ``"max"`` plans from the year's limits.
    * ``pre_step`` (-50): a windowed 401(k) plan's percent (0 outside its start/end months), before payroll.
    * ``post_step`` (5): bank-sourced contributions, after the month's bills.
    * ``on_year_end`` (-5): Roth conversions, before the year's taxes (0).
    * ``on_year_end`` (15, via :class:`SweepRunner`): the surplus sweep, after the taxes and escalators.
    """

    STEP_PRIORITY: ClassVar[dict[str, int]] = {
        "on_year_start": 5,
        "pre_step": -50,
        "post_step": 5,
        "on_year_end": -5,
    }

    def __init__(self, model):
        super().__init__(model)
        self.people: list[Person] = []
        self.sweeper = SweepRunner(model, self)

    @classmethod
    def for_model(cls, model) -> "PolicyRunner":
        runner = getattr(model, "_policy_runner", None)
        if runner is None or runner.model is not model:
            runner = cls(model)
            model._policy_runner = runner
        return runner

    def watch(self, person: "Person") -> None:
        if person not in self.people:
            self.people.append(person)

    def _living(self) -> "list[Person]":
        return [p for p in self.people if not p.is_deceased]

    def on_year_start(self):
        for person in self._living():
            for plan in person.contribution_plans:
                if plan.is_401k and plan.pct_of_pay is None:
                    plan.apply_401k_election()

    def pre_step(self):
        """A 401(k) plan with a start/end window defers only inside it: before the month's paycheck, set the
        deferral percent (0 outside the window)."""
        year, month = self.model.year, self.model.month
        for person in self._living():
            for plan in person.contribution_plans:
                if not (plan.is_401k and plan.has_window):
                    continue
                if plan.active(year, month):
                    plan.apply_401k_election()
                else:
                    setattr(plan.account, f"{plan.bucket}_contrib_percent", 0.0)

    def post_step(self):
        for person in self._living():
            for plan in person.contribution_plans:
                if plan.source == "bank":
                    _contribute_from_bank(person, plan)

    def on_year_end(self):
        for person in self._living():
            policy = person.roth_conversion_policy
            if policy is None:
                continue
            if policy.until_age is not None and person.age_in(self.model.year) >= policy.until_age:
                continue
            convert_to_roth(
                person,
                policy.amount_annual,
                fill_bracket_pct=policy.fill_bracket_pct,
                source=policy.source,
                target=policy.target,
            )


class SweepRunner(LifeModelAgent):
    """The surplus sweep of :class:`SavingsPolicy` (year end, after the taxes)."""

    STEP_PRIORITY: ClassVar[dict[str, int]] = {"on_year_end": 15}

    def __init__(self, model, runner: PolicyRunner):
        super().__init__(model)
        self.runner = runner

    def on_year_end(self):
        for person in self.runner._living():
            policy = person.savings_policy
            if policy is not None and policy.sweep_to is not None:
                sweep(person, policy)


def _gross_pay_this_month(person: "Person") -> float:
    total = 0.0
    for job in person.jobs:
        booked = job._booked_this_month() if job.kind == "w2" else None
        if booked is not None:
            total += booked.gross
    return total


def _available_cash(person: "Person") -> float:
    """Cash a bank-sourced contribution may use: the owner's spendable bank balance (their own and the joint
    accounts they hold with a spouse) less their share of the tax the unit still owes. That is the balance
    due on last year's return until April, plus the month's share of this year's tax not yet paid: the
    projected year's tax times the share of the year elapsed, less the withholding and estimated payments so
    far (:meth:`TaxUnit.expected_unpaid_tax`). Holding it back month by month means a contribution is never
    sold back to pay the same year's taxes (Plan 31 D3)."""
    from .people.tax_unit import TaxUnit

    cash = person.usable_bank_balance
    unit = TaxUnit.for_member(person)
    owed = sum(getattr(m, "taxes_owed", 0.0) for m in unit.living_members)
    reserve = owed + unit.expected_unpaid_tax()
    if reserve > 0:
        bank = unit.bank_account_balance
        share = cash / bank if bank > 0 else 1.0
        cash -= reserve * share
    return max(0.0, cash)


def _contribute_from_bank(person: "Person", plan: ContributionPlan) -> float:
    model = person.model
    wanted = plan.month_amount(model.year, model.month, _gross_pay_this_month(person))
    amount = min(wanted, _available_cash(person))
    if amount < 0.005:
        return 0.0
    moved = move_from_bank(person, plan.account, amount, cause="contribution plan")
    plan._record(model.year, moved)
    return moved


def move_from_bank(person: "Person", account, amount: float, *, cause: str) -> float:
    """Move up to ``amount`` from ``person``'s non-reserve banks into ``account``, posting it: a
    contribution to a tax-advantaged account or 529 (within its room, with its tax treatment), a deposit
    to a brokerage (a new lot), a purchase of a fixed-income holding, or a transfer to a bank account.
    Returns the amount moved."""
    with person.model.ledger.caused_by(cause):
        return _move_from_bank(person, account, amount, cause=cause)


def _move_from_bank(person: "Person", account, amount: float, *, cause: str) -> float:
    from .account.bank import BankAccount
    from .account.brokerage import BrokerageAccount
    from .account.fixed_income import FixedIncomeHolding
    from .base_classes import TaxAdvantagedAccount

    moved = 0.0
    banks = [b for b in person.usable_bank_accounts if not b.reserve and b is not account and b.balance > 0]
    for bank in banks:
        want = min(amount - moved, bank.balance)
        if want <= 0.005:
            break
        if isinstance(account, TaxAdvantagedAccount) or _is_529(account):
            accepted = account.contribute(want, from_account=bank)
            if accepted <= 0:
                break
            bank.withdraw(accepted)
            moved += accepted
            continue
        bank.withdraw(want)
        if isinstance(account, BrokerageAccount):
            account.deposit(want)
            kind = FlowKind.CONTRIBUTION
        elif isinstance(account, FixedIncomeHolding):
            account.buy(want)
            kind = FlowKind.TRANSFER
        elif isinstance(account, BankAccount):
            account.deposit(want)
            kind = FlowKind.TRANSFER
        else:
            account.deposit(want)
            kind = FlowKind.TRANSFER
        person.model.ledger.post(want, kind, from_account=bank, to_account=account, cause=cause, agent=person)
        moved += want
    return moved


def sweep(person: "Person", policy: SavingsPolicy) -> float:
    """Move ``person``'s cash above ``policy.cash_floor`` to ``policy.sweep_to``. Returns the amount moved."""
    surplus = person.usable_bank_balance - policy.cash_floor
    if surplus < 1.0:
        return 0.0
    moved = move_from_bank(person, policy.sweep_to, surplus, cause="savings sweep")
    if moved > 0:
        person.model.event_log.add(Event(f"{person.name} swept ${moved:,.0f} of surplus cash"))
    return moved
