# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Compile spec ``events[]`` (data) into :class:`~life_model.lifeevents.LifeEvent` callables.

**Timing.** Every ``at`` resolves to a calendar year and month, with an optional day:

* ``{year: Y}`` is ``Y``;
* ``{age: A}`` is ``person.get_year_at_age(A)``, the engine's own age arithmetic (the year the
  person turns ``A``), in the month they turn ``A`` (their birth month; January when ``birth`` is
  not given);
* ``{relative: {after: E, years: n}}`` is the resolved year of event ``E`` plus ``n``, in ``E``'s
  month.

``at.month`` sets the month explicitly; otherwise a year-dated event fires in the first simulated
month of its year (January, or ``meta.start``'s month in the first year).
``at.day`` requires an explicit year and month. A relative event in its anchor's year and month
inherits its day, so it can follow an anchor that fires after day 1.

**Firing.** Compiled events are ordinary ``LifeEvent`` objects owned by one ``LifeEvents`` agent
(built last). They fire in the engine's ``events`` stage of their month, after the month's income
and before its bills are paid, so an event's cash, salary, state and marriage effects apply from
the month it is dated (and to that year's return). Events in the same month fire by day (default
day 1), then anchors before their dependents, then in canonical order.
The builder never creates a past-dated ``LifeEvent`` (see
:mod:`life_model.spec.builder`).

Two actions are compiled into constructor inputs instead of ``LifeEvent`` callables, because the
engine decides them inside ``pre_step`` by comparing the person's age with a threshold:
``claim_social_security`` sets ``SocialSecurity.withdrawal_start_age`` and ``die`` sets fixed-age
mortality (``Person.death_age``). ``at: {age: A}`` is that threshold directly; a ``year`` or
``relative`` time becomes the person's age in that year (the inverse of ``get_year_at_age``). Either
way the effect lands in the same year as an ordinary event with the same ``at``.

Every compiled ``LifeEvent`` carries ``spec_source`` (the event or marriage it came from), which
:func:`~life_model.spec.extract.spec_from_model` reads back.
"""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from ..lifeevents import LifeEvent
from ..model import Event
from . import schema as s

if TYPE_CHECKING:
    from .builder import _Builder

#: Event actions applied at build time (constructor inputs) rather than as LifeEvent callables.
BUILD_TIME_ACTIONS = ("claim_social_security", "die")
#: Actions compiled to a stage other than ``events`` (a prepayment waits for the month's bills).
ACTION_STAGES = {"prepay_mortgage": "post_step"}


def scheduled_date(event: s.EventBase, *, day_required: bool = True) -> date:
    """The calendar date of an event dated with an explicit year and month (day 1 when the day is optional).

    The validator guarantees these dates for the actions that call this; a ValueError reports a spec
    that bypassed it.
    """
    at = event.at
    if at.year is None or at.month is None or (day_required and at.day is None):
        needed = "a full calendar date" if day_required else "an explicit year and month"
        raise ValueError(f"'{event.action}' needs {needed}, got {at!r}")
    return date(at.year, at.month, at.day or 1)


class EventTiming:
    """Resolves ``At`` values to years (and ages) for one build."""

    def __init__(self, builder: "_Builder"):
        self.builder = builder
        self.by_id: dict[str, Any] = {e.id: e for e in builder.spec.events if e.id is not None}
        self._years: dict[int, int] = {}

    def depth(self, event, stack: tuple = ()) -> int:
        """How many relative anchors precede ``event`` (anchors fire first within a year)."""
        rel = event.at.relative
        if rel is None or id(event) in stack:
            return 0
        anchor = self.by_id.get(rel.after)
        return 0 if anchor is None else 1 + self.depth(anchor, (*stack, id(event)))

    def year_of(self, event, stack: tuple = ()) -> int:
        """The resolved year of a spec event."""
        key = id(event)
        if key not in self._years:
            if key in stack:
                raise ValueError(f"relative event timing has a cycle through {event.id!r}")
            self._years[key] = self.resolve(event.at, event.person, (*stack, key))
        return self._years[key]

    def resolve(self, at: s.At, default_person: str | None, stack: tuple = ()) -> int:
        """The calendar year of ``at`` (see the module docstring for the age semantics)."""
        if at.year is not None:
            return at.year
        if at.age is not None:
            person = self.builder.person(cast(str, at.person or default_person))
            return person.get_year_at_age(at.age)
        relative = cast(s.Relative, at.relative)
        anchor = self.by_id.get(relative.after)
        if anchor is None:
            raise ValueError(f"relative event anchor {relative.after!r} does not exist")
        return self.year_of(anchor, stack) + relative.years

    def month_of(self, event, stack: tuple = ()) -> int | None:
        """The month a spec event fires in (None: the first simulated month of its year)."""
        return self.resolve_month(event.at, event.person, stack)

    def day_of(self, event) -> int | None:
        """An explicit day or the day of a relative anchor in the same year and month."""
        at = event.at
        if at.day is not None:
            return at.day
        if at.relative is not None and at.relative.years == 0:
            anchor = self.by_id[at.relative.after]
            if self.month_of(anchor) == self.month_of(event):
                return self.day_of(anchor)
        return None

    def resolve_month(self, at: s.At, default_person: str | None, stack: tuple = ()) -> int | None:
        """``at.month``, else the birth month for ``age`` timing, else the anchor's month."""
        if at.month is not None:
            return at.month
        if at.age is not None:
            person = self.builder.person(cast(str, at.person or default_person))
            return None if getattr(person, "birth_month_assumed", True) else person.birth_month
        if at.relative is not None:
            anchor = self.by_id.get(at.relative.after)
            if anchor is not None and id(anchor) not in stack:
                return self.month_of(anchor, (*stack, id(anchor)))
        return None

    def age_of(self, at: s.At, person_id: str) -> int:
        """The person's age at ``at``: ``at.age`` itself, or the inverse of ``get_year_at_age``."""
        if at.age is not None and (at.person is None or at.person == person_id):
            return at.age
        year = self.resolve(at, person_id)
        person = self.builder.person(person_id)
        # get_year_at_age is linear with slope 1, so this inverts it.
        return person.age + (year - person.get_year_at_age(person.age))


def apply_build_time_events(builder: "_Builder", timing: EventTiming) -> dict[str, float]:
    """Apply ``die`` (fixed-age mortality) and collect ``claim_social_security`` claiming ages.

    Returns the claiming age per person id (passed to ``SocialSecurity``). Each applied event is
    recorded in ``model.household_build_time_events`` with the values it replaced, so the extractor
    can reproduce the spec.
    """
    from ..people.types import MortalityMode

    records = []
    claims: dict[str, float] = {}
    for event in builder.spec.events:
        if event.action not in BUILD_TIME_ACTIONS:
            continue
        person = builder.person(event.person)
        age = timing.age_of(event.at, event.person)
        if event.action == "die":
            records.append(
                {"event": event, "previous": {"mortality": person.mortality_mode, "death_age": person.death_age}}
            )
            person.mortality_mode = MortalityMode.FIXED_AGE
            person.death_age = age
        else:
            ss = builder.spec.person(event.person).social_security
            records.append({"event": event, "previous": {"claim_age": ss.claim_age if ss is not None else None}})
            claims[event.person] = age
    builder.model.household_build_time_events = records
    return claims


def _life_event(
    year: int, name: str, source: Any, fn, *args, month: int | None = None, stage: str = "events"
) -> LifeEvent:
    life_event = LifeEvent(year, name, fn, *args, month=month, stage=stage)
    setattr(life_event, "spec_source", source)  # read back by spec_from_model  # noqa: B010
    return life_event


def compile_events(builder: "_Builder", timing: EventTiming) -> list[LifeEvent]:
    """Compile future marriages and ``events[]`` into ``LifeEvent`` objects, in firing order."""
    spec = builder.spec
    compiled: list[tuple[tuple, LifeEvent]] = []
    start = builder.model.start_year

    for index, marriage in enumerate(spec.relationships.marriages):
        if marriage.year is not None and marriage.year > start:
            head, spouse = (builder.person(pid) for pid in marriage.spouses)
            name = f"{head.name} and {spouse.name} marry"
            le = _life_event(marriage.year, name, marriage, builder.marry, head, spouse, marriage.filing_status)
            compiled.append(((marriage.year, 0, 1, 0, -1, index), le))

    for index, event in enumerate(spec.events):
        if event.action in BUILD_TIME_ACTIONS:
            continue
        year = timing.year_of(event)
        month = timing.month_of(event)
        day = timing.day_of(event)
        depth = timing.depth(event)
        for offset, life_event in enumerate(_compile_one(builder, timing, event, year)):
            fixed_month = getattr(life_event, "fixed_month", None)
            life_event.set_date(fixed_month or month, day if fixed_month in (None, month) else None)
            compiled.append(
                ((life_event.year, life_event.month or 0, life_event.day or 1, depth, index, offset), life_event)
            )

    compiled.sort(key=lambda pair: pair[0])
    return [life_event for _, life_event in compiled]


def _name(event, default: str) -> str:
    return event.name if event.name is not None else default


def _compile_one(builder: "_Builder", timing: EventTiming, event, year: int) -> list[LifeEvent]:
    person = builder.person(event.person)
    action = event.action

    if action == "marry":
        spouse = builder.person(event.spouse)
        name = _name(event, f"{person.name} and {spouse.name} marry")
        return [_life_event(year, name, event, builder.marry, person, spouse, event.filing_status)]

    if action == "retire":
        return [_life_event(year, _name(event, f"{person.name} retires"), event, _retire, person)]

    if action == "change_job":
        return [
            _life_event(year, _name(event, f"{person.name} changes jobs"), event, _change_job, builder, person, event)
        ]

    if action == "move":
        return [
            _life_event(
                year, _name(event, f"{person.name} moves"), event, _move, builder, person, event, timing.day_of(event)
            )
        ]

    if action == "buy_home":
        name = _name(event, f"{person.name} buys {event.home.name}")
        return [_life_event(year, name, event, _buy_home, builder, person, event.home, event.cash_funding)]

    if action == "sell_home":
        name = _name(event, f"{person.name} sells a home")
        return [
            _life_event(
                year, name, event, _sell_home, builder, event.home, event.selling_cost_pct, timing.day_of(event)
            )
        ]

    if action == "one_time_expense":
        name = _name(event, f"{person.name}: one-time expense ${event.amount:,.0f}")
        return [_life_event(year, name, event, person.spending.add_expense, event.amount)]

    if action == "recurring_expense":
        last = builder.model.end_year if event.until is None else timing.resolve(event.until, event.person)
        name = _name(event, f"{person.name}: recurring expense ${event.amount_annual:,.0f}/yr")
        return [
            _life_event(y, name, event, person.spending.add_expense, event.amount_annual)
            for y in range(year, min(last, builder.model.end_year) + 1)
        ]

    if action == "change_spending":
        name = _name(event, f"{person.name} changes spending")
        return [_life_event(year, name, event, _change_spending, person, event.amount_annual, event.change_pct)]

    if action == "add_account":
        name = _name(event, f"{person.name} opens a {event.account.kind} account")
        return [_life_event(year, name, event, _add_account, builder, event)]

    if action == "reserve_cash":
        name = _name(event, "Earmarked cash")
        return [_life_event(year, name, event, _reserve_cash, builder, person, event, name)]

    if action == "contribute":
        name = _name(event, f"{person.name} contributes ${event.amount:,.0f}")
        return [_life_event(year, name, event, _contribute, builder, person, event.account, event.amount)]

    if action == "stop_contribution":
        name = _name(event, f"{person.name} stops contributing to {event.account}")
        return [_life_event(year, name, event, _stop_contribution, builder, person, event)]

    if action == "change_contribution":
        name = _name(event, f"{person.name} changes the contribution to {event.account}")
        return [_life_event(year, name, event, _change_contribution, builder, person, event)]

    if action == "disability":
        name = _name(event, f"{person.name} becomes disabled")
        return [_life_event(year, name, event, _disability, person)]

    if action == "refinance":
        name = _name(event, f"{person.name} refinances at {event.rate_pct:g}%")
        return [_life_event(year, name, event, _refinance, builder, event)]

    if action == "renew_mortgage":
        name = _name(event, f"{person.name} renews the mortgage at {event.rate_pct:g}%")
        return [_life_event(year, name, event, _renew_mortgage, builder, event)]

    if action == "pay_mortgage_at_maturity":
        name = _name(event, f"{person.name} pays off the mortgage at maturity")
        return [_life_event(year, name, event, _pay_mortgage_at_maturity, builder, event)]

    if action == "prepay_mortgage":
        name = _name(event, f"{person.name} prepays the mortgage")
        return [_life_event(year, name, event, _prepay_mortgage, builder, person, event, stage=ACTION_STAGES[action])]

    if action == "heloc_draw":
        name = _name(event, f"{person.name} draws ${event.amount:,.0f} on a home equity line")
        return [_life_event(year, name, event, _heloc_draw, builder, event)]

    if action in ("draw_bridge", "repay_bridge"):
        name = _name(event, f"{person.name}: {action.replace('_', ' ')}")
        return [_life_event(year, name, event, _bridge_transaction, builder, event)]

    if action == "convert_to_roth":
        what = (
            f"${event.amount:,.0f}"
            if event.amount is not None
            else f"to the top of the {event.fill_bracket_pct:g}% bracket"
        )
        name = _name(event, f"{person.name} converts {what} to Roth")
        life_event = _life_event(year, name, event, _convert_to_roth, builder, person, event)
        if event.fill_bracket_pct is not None:
            life_event.fixed_month = 12  # it needs the year's income: December, before the year's taxes
        return [life_event]

    raise NotImplementedError(f"event action {action!r} is not supported by the builder")


# --- Event effects (called when the LifeEvent fires) ---------------------------------------------


def _retire(person) -> None:
    person.retirement_age = min(person.retirement_age, person.age)
    for job in person.jobs:
        if not job.retired:
            job.retire()
    person.retirement_triggered = True


def _change_job(builder: "_Builder", person, event: s.ChangeJobEvent) -> None:
    if event.job is not None:
        job = builder.built.items[event.job]
        if event.salary_annual is not None:
            job.salary.base = event.salary_annual
        if event.stop and not job.retired:
            # Leaving is retiring from the job: unvested match forfeited, the end of its income logged.
            job.retire(message=f"{person.name} left {job.company}")
            if event.severance > 0:
                # Severance is wages: income tax and FICA.
                person.income.add_wages(ordinary_amount=event.severance, fica_wages=event.severance)
                person.receive_cash(event.severance, source="severance")
    if event.new_job is not None:
        agent = builder.build_job(person, event.new_job)
        if event.new_job.id is not None:
            builder.built.items[event.new_job.id] = agent
            agent.spec_id = event.new_job.id
        if event.new_job.stock_plan is not None:
            builder.build_stock_plan(agent, event.new_job.stock_plan)


def _move(builder: "_Builder", person, event: s.MoveEvent, day: int | None) -> None:
    if event.state is not None:
        person.state = event.state
        if person.spouse is not None:
            person.spouse.state = event.state
    if event.end_rental is not None:
        _end_rental(builder, person, event.end_rental)
    if event.sell_home is not None:
        _sell_home(builder, event.sell_home, None, day)
    if event.buy_home is not None:
        _buy_home(builder, person, event.buy_home)
    if event.new_rental is not None:
        rental = builder.build_rental(person, event.new_rental)
        if event.new_rental.id is not None:
            builder.built.items[event.new_rental.id] = rental
            rental.spec_id = event.new_rental.id


def _end_rental(builder: "_Builder", person, rental_id: str) -> None:
    rental = builder.built.items[rental_id]
    builder.model.registries.apartments.unregister(person, rental)
    rental.remove()


def _buy_home(builder: "_Builder", person, home: s.Home, cash_funding: s.HomeCashFunding | None = None) -> None:
    if cash_funding is not None:
        from ..housing.closing import cash_funded_down_payment

        price = Decimal(str(home.purchase_price))
        down = cash_funded_down_payment(
            person,
            price=price,
            closing_costs=cash_funding.closing_costs,
            cash_floor=cash_funding.cash_floor,
            minimum_down_payment=cash_funding.minimum_down_payment,
            mortgage_limit=cash_funding.mortgage_limit,
            down_payment_fraction=cash_funding.down_payment_fraction,
            extra_down_payment=cash_funding.extra_down_payment,
        )
        principal = price - down
        mortgage = (
            s.Mortgage(
                original_amount=float(principal), rate_pct=cash_funding.rate_pct, term_years=cash_funding.term_years
            )
            if principal
            else None
        )
        home = home.model_copy(
            update={
                "down_payment": float(down),
                "mortgage": mortgage,
                "closing_cost_pct": float(100 * Decimal(str(cash_funding.closing_costs)) / price),
            }
        )
    agent = builder.build_home(person, home, purchase=True, cash_only=cash_funding is not None)
    if home.id is not None:
        builder.built.items[home.id] = agent
        agent.spec_id = home.id


def _sell_home(builder: "_Builder", home_id: str, selling_cost_pct: float | None, day: int | None) -> None:
    when = date(builder.model.year, builder.model.month, day or 1)
    builder.built.items[home_id].sell(selling_cost_pct, when=when)


def _change_spending(person, amount_annual: float | None, change_pct: float | None) -> None:
    if amount_annual is not None:
        person.spending.base = amount_annual
    else:
        person.spending.base *= 1 + cast(float, change_pct) / 100


def _add_account(builder: "_Builder", event: s.AddAccountEvent) -> None:
    person = builder.person(event.person)
    agent = builder.build_account(person, builder.spec.person(event.person), event.account)
    if event.account.id is not None:
        builder.built.items[event.account.id] = agent
        agent.spec_id = event.account.id


def _reserve_cash(builder: "_Builder", person, event: s.ReserveCashEvent, name: str) -> None:
    from ..account.bank import BankAccount
    from ..account.cash_reserve import CashReserve

    bank = builder.built.items.get(event.bank)
    if not isinstance(bank, BankAccount) or bank.owner is not person:
        raise ValueError(f"Funding bank {event.bank!r} must be open and owned by {person.name}")
    reserve = CashReserve(
        person,
        name=name,
        amount=event.amount,
        bank=bank,
        schedule=builder.event_schedule(),
        release_on=event.release_on,
    )
    if event.id is not None:
        builder.built.items[event.id] = reserve
        reserve.spec_id = event.id


def _contribute(builder: "_Builder", person, account_id: str, amount: float) -> None:
    from ..charity.daf import DonorAdvisedFund
    from ..policies import move_from_bank

    account = builder.built.items[account_id]
    if isinstance(account, DonorAdvisedFund):
        available = min(amount, sum(a.balance for a in person.usable_bank_accounts))
        if available > 0:
            account.contribute(available)  # debits the bank itself
        return
    # Every other target goes through the policies' move: a contribution within a tax-advantaged
    # account's or 529's room, a brokerage lot, a fixed-income purchase or a bank transfer, each part
    # posted as a move between the household's own accounts rather than new money from outside.
    move_from_bank(person, account, amount, cause=f"contribution to {account_id}")


def _stop_contribution(builder: "_Builder", person, event: s.StopContributionEvent) -> None:
    from ..account.job401k import Job401kAccount

    account = builder.built.items[event.account]
    person.remove_contribution_plan(account, bucket=event.bucket)
    if isinstance(account, Job401kAccount):
        for bucket in (event.bucket,) if event.bucket is not None else ("pretax", "roth", "after_tax"):
            setattr(account, f"{bucket}_contrib_percent", 0.0)
    builder.model.event_log.add(Event(f"{person.name} stopped contributing to {event.account}"))


def _change_contribution(builder: "_Builder", person, event: s.ChangeContributionEvent) -> None:
    from ..account.job401k import Job401kAccount
    from ..policies import MAX, ContributionPlan

    account = builder.built.items[event.account]
    is_401k = isinstance(account, Job401kAccount)
    bucket = (event.bucket or "pretax") if is_401k else None
    amount = MAX if event.max_out else event.amount_annual
    plan = next(
        (p for p in person.contribution_plans if p.account is account and (not is_401k or p.bucket == bucket)), None
    )
    if plan is None:
        plan = ContributionPlan(
            account,
            amount_annual=amount,
            pct_of_pay=event.pay_pct,
            source="payroll" if is_401k else "bank",
            bucket=bucket,
        )
        person.add_contribution_plan(plan)
    elif event.pay_pct is not None:
        plan.set_rate(event.pay_pct)
    else:
        plan.set_amount(amount)
    builder.model.event_log.add(Event(f"{person.name} changed the contribution to {event.account}"))


def _refinance(builder: "_Builder", event: s.RefinanceEvent) -> None:
    from ..housing.home import Home

    target = builder.built.items[event.debt]
    loan = target.mortgage if isinstance(target, Home) else target
    if loan is None or loan.principal <= 0:
        builder.model.event_log.add(Event(f"refinance skipped: {event.debt} has no balance"))
        return
    kwargs: dict[str, Any] = {
        "term_months": event.term_months,
        "term_years": event.term_years,
        "costs": event.costs,
        "finance_costs": event.finance_costs,
        "cash_out": event.cash_out,
    }
    if isinstance(target, Home):
        kwargs["cash_out_for_improvements"] = event.cash_out_for_improvements
    loan.refinance(event.rate_pct, **kwargs)


def _renew_mortgage(builder: "_Builder", event: s.MortgageRenewalEvent) -> None:
    home = builder.built.items.get(event.home)
    if home is None:
        raise ValueError(f"Home {event.home!r} must exist before its mortgage can be renewed")
    if home.sold or home.mortgage is None or home.mortgage.principal <= 0:
        builder.model.event_log.add(Event(f"mortgage renewal skipped: {event.home} has no outstanding mortgage"))
        return
    from .builder import prepayment_privilege

    new_terms = event.prepayment_privilege
    privilege = (
        prepayment_privilege(
            new_terms, as_of=scheduled_date(event, day_required=False), default_basis=home.mortgage.principal
        )
        if isinstance(new_terms, s.MortgagePrepaymentPrivilege)
        else new_terms
    )
    home.mortgage.renew(
        rate_pct=event.rate_pct,
        rate_compounding=event.rate_compounding,
        amortization_months=event.amortization_months,
        prepayment_privilege=privilege,
    )


def _pay_mortgage_at_maturity(builder: "_Builder", event: s.MortgageMaturityEvent) -> None:
    from ..housing.home import Home

    home = builder.built.items.get(event.home)
    if not isinstance(home, Home) or home.sold or home.person.is_deceased or home.mortgage is None:
        builder.model.event_log.add(Event(f"mortgage payoff skipped: {event.home} has no active homeowner mortgage"))
        return
    when = scheduled_date(event)
    bridge = _owned_bridge(builder, home.person, event.bridge) if event.bridge is not None else None
    home.mortgage.pay_at_maturity(when, interest_due=event.interest_due, cash_floor=event.cash_floor, bridge=bridge)


def _prepay_mortgage(builder: "_Builder", person, event: s.MortgagePrepaymentEvent) -> None:
    from ..housing.home import Home

    home = builder.built.items.get(event.home)
    if not isinstance(home, Home) or home.person is not person or home.mortgage is None:
        raise ValueError("A mortgage prepayment needs an existing mortgage on the borrower's home")
    when = scheduled_date(event)
    home.mortgage.prepay_surplus(when, cash_fraction=event.cash_fraction, cash_floor=event.cash_floor)


def _heloc_draw(builder: "_Builder", event: s.HelocDrawEvent) -> None:
    builder.built.items[event.heloc].draw(event.amount, for_improvements=event.for_improvements)


def _owned_bridge(builder: "_Builder", person, bridge_id: str):
    from ..debt.bridge import DatedBridgeLine

    line = builder.built.items.get(bridge_id)
    if not isinstance(line, DatedBridgeLine) or line.person is not person:
        raise ValueError("The borrower must own the approved bridge line")
    return line


def _bridge_transaction(builder: "_Builder", event: s.DrawBridgeEvent | s.RepayBridgeEvent) -> None:
    from ..debt.bridge import DatedBridgeLine

    line = builder.built.items.get(event.bridge)
    if not isinstance(line, DatedBridgeLine) or line.home.sold or line.person.is_deceased:
        builder.model.event_log.add(Event(f"bridge transaction skipped: {event.bridge} has no active borrower"))
        return
    when = scheduled_date(event)
    if isinstance(event, s.DrawBridgeEvent):
        line.draw(event.amount, when=when)
    else:
        line.repay(when, cash_floor=event.cash_floor)


def _disability(person) -> None:
    from ..insurance.general_insurance import InsuranceType

    policies = [
        policy
        for policy in person.model.registries.general_insurance_policies.get_items(person)
        if policy.insurance_type == InsuranceType.DISABILITY
    ]
    monthly_pay = sum(job.salary.base for job in person.jobs if not job.retired) / 12
    for policy in policies:
        policy.start_disability_claim(monthly_pay)
    for job in person.jobs:
        if not job.retired:
            job.retire()
    person.model.event_log.add(Event(f"{person.name} became disabled and stopped working"))


def _convert_to_roth(builder: "_Builder", person, event: s.ConvertToRothEvent) -> None:
    from ..policies import convert_to_roth

    items = builder.built.items
    convert_to_roth(
        person,
        event.amount,
        fill_bracket_pct=event.fill_bracket_pct,
        source=items[event.source] if event.source is not None else None,
        target=items[event.target] if event.target is not None else None,
    )
