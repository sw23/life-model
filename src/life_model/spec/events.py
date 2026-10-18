# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Compile spec ``events[]`` (data) into :class:`~life_model.lifeevents.LifeEvent` callables.

**Timing.** Every ``at`` resolves to a calendar year:

* ``{year: Y}`` is ``Y``;
* ``{age: A}`` is ``person.get_year_at_age(A)``, the engine's own age arithmetic. This module adds
  no off-by-one compensation of its own. Today ``get_year_at_age`` is evaluated at construction
  with the constructor age, which is "age last year" (Plan 26 item 1: an event "at 42" fires when
  the simulated age is 43). Plan 26 fixes that inside ``get_year_at_age``; because the builder
  routes every age through it, age-dated events become correct automatically when Plan 26 lands;
* ``{relative: {after: E, years: n}}`` is the resolved year of event ``E`` plus ``n``.

**Firing.** Compiled events are ordinary ``LifeEvent`` objects owned by one ``LifeEvents`` agent
(built last). Today that agent steps after tax-unit settlement, so an event's cash effects land a
year late (Plan 26 item 2); Plan 26 adds an ``events`` stage before settlement, and these
``LifeEvent`` objects use it automatically. Events in the same year fire anchors first, then in
canonical order.

Two actions are compiled into constructor inputs instead of ``LifeEvent`` callables, because the
engine decides them inside ``pre_step`` from an age: ``claim_social_security`` sets the claiming
age (``SocialSecurity.withdrawal_start_age``) and ``die`` sets fixed-age mortality
(``Person.death_age``). Their ``at`` resolves to an age through the inverse of
``get_year_at_age``, so they share its semantics too.

Every compiled ``LifeEvent`` carries ``spec_source`` (the event or marriage it came from), which
:func:`~life_model.spec.extract.spec_from_model` reads back.
"""

from typing import TYPE_CHECKING, Any, cast

from ..lifeevents import LifeEvent
from ..model import Event
from . import schema as s

if TYPE_CHECKING:
    from .builder import _Builder

#: Event actions applied at build time (constructor inputs) rather than as LifeEvent callables.
BUILD_TIME_ACTIONS = ("claim_social_security", "die")


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
            # No compensation here on purpose: Plan 26 fixes get_year_at_age itself.
            return person.get_year_at_age(at.age)
        relative = cast(s.Relative, at.relative)
        anchor = self.by_id.get(relative.after)
        if anchor is None:
            raise ValueError(f"relative event anchor {relative.after!r} does not exist")
        return self.year_of(anchor, stack) + relative.years

    def age_of(self, at: s.At, person_id: str) -> int:
        """The person's age at ``at``: ``at.age`` itself, or the inverse of ``get_year_at_age``."""
        if at.age is not None and (at.person is None or at.person == person_id):
            return at.age
        year = self.resolve(at, person_id)
        person = self.builder.person(person_id)
        # get_year_at_age is linear with slope 1, so this inverts it whatever its offset.
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


def _life_event(year: int, name: str, source: Any, fn, *args) -> LifeEvent:
    life_event = LifeEvent(year, name, fn, *args)
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
            compiled.append(((marriage.year, 0, -1, index), le))

    for index, event in enumerate(spec.events):
        if event.action in BUILD_TIME_ACTIONS:
            continue
        year = timing.year_of(event)
        depth = timing.depth(event)
        for offset, life_event in enumerate(_compile_one(builder, timing, event, year)):
            compiled.append(((life_event.year, depth, index, offset), life_event))

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
        return [_life_event(year, _name(event, f"{person.name} moves"), event, _move, builder, person, event)]

    if action == "buy_home":
        name = _name(event, f"{person.name} buys {event.home.name}")
        return [_life_event(year, name, event, _buy_home, builder, person, event.home)]

    if action == "sell_home":
        name = _name(event, f"{person.name} sells a home")
        return [_life_event(year, name, event, _sell_home, builder, event.home, event.selling_cost_pct)]

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

    if action == "contribute":
        name = _name(event, f"{person.name} contributes ${event.amount:,.0f}")
        return [_life_event(year, name, event, _contribute, builder, person, event.account, event.amount)]

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
            job.retired = True
            builder.model.event_log.add(Event(f"{person.name} left {job.company}"))
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


def _move(builder: "_Builder", person, event: s.MoveEvent) -> None:
    if event.state is not None:
        person.state = event.state
        if person.spouse is not None:
            person.spouse.state = event.state
    if event.end_rental is not None:
        _end_rental(builder, person, event.end_rental)
    if event.sell_home is not None:
        _sell_home(builder, event.sell_home, None)
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


def _buy_home(builder: "_Builder", person, home: s.Home) -> None:
    agent = builder.build_home(person, home, purchase=True)
    if home.id is not None:
        builder.built.items[home.id] = agent
        agent.spec_id = home.id


def _sell_home(builder: "_Builder", home_id: str, selling_cost_pct: float | None) -> None:
    builder.built.items[home_id].sell(selling_cost_pct)


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


def _contribute(builder: "_Builder", person, account_id: str, amount: float) -> None:
    from ..charity.daf import DonorAdvisedFund

    account = builder.built.items[account_id]
    available = min(amount, person.bank_account_balance)
    if available <= 0:
        return
    if isinstance(account, DonorAdvisedFund):
        account.contribute(available)  # debits the bank itself
    elif hasattr(account, "contribute"):
        # Tax-advantaged / 529: the account accepts at most its remaining room; debit what it took.
        accepted = account.contribute(available)
        person.deduct_from_bank_accounts(accepted)
    else:
        person.deduct_from_bank_accounts(available)
        account.deposit(available)
