# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Build a :class:`~life_model.model.LifeModel` from a :class:`~life_model.spec.schema.HouseholdSpec`.

The builder owns construction order (Plan 25 D5). Mesa agents step in construction order within a
stage priority, and several results depend on it (``bank_accounts[0]`` receives income, the first
family member heads the tax unit, same-priority agents run in insertion order). So the builder never
uses the order the user wrote things in: :func:`canonical` sorts every list into a fixed order and
the builder then constructs, for all people at each step:

1. model (:func:`create_model`: seed, scenario, economy overrides) and the one ``Family`` (with the
   spec's household ``withdrawal_order``);
2. people (``Spending`` then ``Person``), in :func:`people_order` (marriage heads first, in
   ``relationships`` order, each followed by their spouse; then everyone else by id);
3. bank accounts (the ``primary`` one first), then jobs (``Salary``, ``Job``), then 401ks, then
   stock plans;
4. other accounts in kind order: brokerage, traditional_ira, roth_ira, hsa, inherited_pretax,
   pension, annuity, daf, trust;
5. debts (car, student, credit_card), housing (homes, then rentals), home equity lines (they need
   their home), insurance (life, then general policies);
6. children, then 529 plans (which reference children);
7. healthcare agents (medical costs, Medicare, long-term care), then Social Security;
8. giving; marriages already in effect at the start; events (a ``LifeEvents`` agent, last).

Within one step, items are ordered by ``(id, canonical JSON)``, so two items without ids still have
a deterministic order. Shuffling any list in a spec therefore yields an identical model.

Plan 27 replaced the undocumented core workarounds the builder used to rely on (brokerage opening lots via
``deposit_with_basis``; a loan in progress as ``loan_amount=original_amount, principal=balance``) with
real constructor arguments: ``BrokerageAccount(lots=)`` and the loans' statement inputs (origination,
current balance, months remaining).

Standing savings policies (``contribution_plans``, ``savings_policy``, ``roth_conversion``) are attached
after every account exists (they reference accounts by id).

Past-dated events: the builder never creates a ``LifeEvent`` dated before ``start_year`` and never
passes ``LifeEvents(allow_past=True)``. A spec event that resolves before the start year is a
validator error (``event_before_start``); with ``check=False`` the core ``LifeEvents`` raises the
same problem as a ``ValueError``. Something that already happened belongs in the starting state
instead (a marriage in ``relationships``, a balance, an owned home).
"""

import json
import warnings
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, cast

from ..config.financial_config import FinancialConfig
from ..model import LifeModel, LifeModelAgent
from ..people.family import Family
from . import schema as s


class SpecValidationError(ValueError):
    """Raised by the builder when a spec has validation errors (``findings`` lists all of them)."""

    def __init__(self, findings: list):
        self.findings = findings
        lines = "\n".join(f"  {f.path}: {f.message}" for f in findings)
        super().__init__(f"Household spec has {len(findings)} error(s):\n{lines}")


class SpecWarning(UserWarning):
    """Warning category for validator warnings emitted while building a spec."""


@dataclass
class BuiltHousehold:
    """Handles to the agents a spec was built into.

    ``people`` maps person id to :class:`~life_model.people.person.Person`; ``items`` maps every
    item key (the item's ``id`` when given, else ``"<person>.<collection>[<n>]"`` in canonical
    order, e.g. ``"alex.accounts[0]"``) to the agent built for it.
    """

    model: LifeModel
    family: Family
    spec: s.HouseholdSpec
    people: dict[str, Any] = field(default_factory=dict)
    items: dict[str, Any] = field(default_factory=dict)
    life_events: Any = None

    def item(self, key: str) -> Any:
        """The agent built for ``key`` (``KeyError`` when absent)."""
        return self.items[key]


# --- Canonical order -----------------------------------------------------------------------------

ACCOUNT_KIND_ORDER = (
    "bank",
    "fixed_income",
    "401k",
    "brokerage",
    "traditional_ira",
    "roth_ira",
    "hsa",
    "inherited_pretax",
    "pension",
    "annuity",
    "daf",
    "trust",
    "529",
)
DEBT_KIND_ORDER = ("car", "student", "credit_card", "heloc")
HOUSING_KIND_ORDER = ("home", "rental")
INSURANCE_KIND_ORDER = (
    "life",
    "health",
    "disability",
    "ltc",
    "umbrella",
    "auto",
    "home",
    "renters",
    "flood",
    "earthquake",
)
#: Accounts built in step 4 (after banks, jobs and 401ks); 529s are built after children.
LATE_ACCOUNT_KINDS = ("529",)


def _content_key(item: s.SpecModel) -> str:
    return json.dumps(item.model_dump(mode="json", exclude_defaults=True), sort_keys=True)


def _kind_rank(item: s.SpecModel, order: tuple[str, ...]) -> int:
    kind = getattr(item, "kind", None)
    return order.index(kind) if kind in order else len(order)


def _sorted(items: Iterable[s.SpecModel], order: tuple[str, ...] = ()) -> list:
    def key(item):
        primary = 0 if getattr(item, "primary", False) else 1
        return (_kind_rank(item, order) if order else 0, primary, getattr(item, "id", None) or "", _content_key(item))

    return sorted(items, key=key)


def people_order(spec: s.HouseholdSpec) -> list[str]:
    """Person ids in construction order: marriage heads (each followed by their spouse) in
    ``relationships`` order, then marry-event participants in event order, then the rest by id."""
    ordered: list[str] = []
    known = {p.id for p in spec.people}

    def add(pid: str) -> None:
        if pid in known and pid not in ordered:
            ordered.append(pid)

    for marriage in spec.relationships.marriages:
        add(marriage.spouses[0])
        add(marriage.spouses[1])
    for event in _sorted(spec.events):
        if isinstance(event, s.MarryEvent):
            add(event.person)
            add(event.spouse)
    for pid in sorted(known - set(ordered)):
        add(pid)
    return ordered


def canonical(spec: s.HouseholdSpec) -> s.HouseholdSpec:
    """A copy of ``spec`` with every list in the builder's canonical order.

    ``dump(canonical(spec))`` is what :func:`~life_model.spec.extract.spec_from_model` reproduces
    for a freshly built model, and two specs that differ only in list order canonicalize equally.
    Collections of entities are sorted; ordered values keep their order (vesting schedules, trust
    beneficiaries, marriage spouses), except brokerage lots, which are sold FIFO and so are put in
    acquisition order.
    """
    by_id = {p.id: p for p in spec.people}
    start = spec.meta.start_year

    def lots_in_acquisition_order(account):
        # Lots are sold FIFO, so their canonical order is acquisition order (the real FIFO order).
        if not isinstance(account, s.BrokerageAccount) or not account.lots:
            return account
        lots = sorted(
            account.lots,
            key=lambda lot: (lot.acquired_year if lot.acquired_year is not None else start, lot.cost_basis, lot.value),
        )
        return account.model_copy(update={"lots": lots})

    people = []
    for pid in people_order(spec):
        p = by_id[pid]
        people.append(
            p.model_copy(
                update={
                    "jobs": _sorted(p.jobs),
                    "accounts": _sorted([lots_in_acquisition_order(a) for a in p.accounts], ACCOUNT_KIND_ORDER),
                    "debts": _sorted(p.debts, DEBT_KIND_ORDER),
                    "housing": _sorted(p.housing, HOUSING_KIND_ORDER),
                    "insurance": _sorted(p.insurance, INSURANCE_KIND_ORDER),
                    "giving": _sorted(p.giving),
                    "children": _sorted(p.children),
                }
            )
        )
    return spec.model_copy(update={"people": people, "events": _sorted(spec.events)})


# --- Model creation ------------------------------------------------------------------------------

_ECONOMY_FIELDS = {
    "inflation_pct": "inflation",
    "wage_growth_pct": "wage_growth",
    "equity_return_pct": "equity_return",
    "bond_return_pct": "bond_return",
    "cash_yield_pct": "cash_yield",
    "home_appreciation_pct": "home_appreciation",
}


def economy_overrides(economy: s.Economy | None) -> dict[str, Any]:
    """Translate a spec ``economy`` block into config ``economy`` overrides (``_pct`` names dropped)."""
    if economy is None:
        return {}
    out: dict[str, Any] = {}
    if economy.mode is not None:
        out["mode"] = economy.mode
    for spec_name, config_name in _ECONOMY_FIELDS.items():
        value = getattr(economy, spec_name)
        if value is not None:
            out[config_name] = value
    if economy.paths is not None:
        out["paths"] = {_ECONOMY_FIELDS[name]: dict(years) for name, years in economy.paths.items()}
    if economy.stochastic is not None:
        stochastic = {}
        for name, value in economy.stochastic.model_dump(exclude_none=True).items():
            stochastic[name.removesuffix("_pct")] = value
        if stochastic:
            out["stochastic"] = stochastic
    return out


def create_model(
    spec: s.HouseholdSpec,
    *,
    config: FinancialConfig | None = None,
    seed: int | None = None,
    collect_data: bool = True,
    apply_economy: bool = True,
    model_cls: type[LifeModel] = LifeModel,
    collect: str = "year",
) -> LifeModel:
    """Create the (empty) :class:`LifeModel` for ``spec``: years, seed, scenario and economy.

    Args:
        spec: The household spec (only ``meta`` and ``economy`` are read here).
        config: Financial config to use (mutated when the spec sets a scenario or economy overrides
            and ``apply_economy`` is true). Defaults to a fresh copy of the packaged defaults.
        seed: Overrides ``meta.seed``.
        collect_data: Passed to ``LifeModel(collect_data=)``.
        apply_economy: When False, ``meta.scenario`` and ``economy`` are recorded but not applied:
            for callers that already applied them to ``config`` themselves (the RL environment
            applies a scenario as a stochastic overlay).
        model_cls: The ``LifeModel`` subclass to instantiate.
        collect: Passed to ``LifeModel(collect=)``: ``"month"`` also collects month-end rows
            (``RunResult.monthly_frame``).
    """
    meta = spec.meta
    if config is None:
        config = FinancialConfig()
    if apply_economy:
        # Applied to the config *before* the model exists: the EconomyModel captures the config's
        # economy section (and caches the first year's rates) at construction.
        if meta.scenario is not None:
            from ..config.scenarios import get_scenario

            config.apply_scenario(meta.scenario, get_scenario(meta.scenario))
        overrides = economy_overrides(spec.economy)
        if overrides:
            # Keep the scenario name: the economy block refines the scenario rather than replacing it.
            config.apply_scenario(cast(str, config.scenario), {"economy": overrides})
    start_month = int(meta.start.split("-")[1]) if meta.start is not None else None
    return model_cls(
        end_year=meta.end_year,
        start_year=meta.start_year,
        seed=meta.seed if seed is None else seed,
        config=config,
        collect_data=collect_data,
        start_month=start_month,
        collect=collect,
    )


def build_household(
    spec: s.HouseholdSpec,
    *,
    config: FinancialConfig | None = None,
    seed: int | None = None,
    collect_data: bool = True,
    check: bool = True,
    collect: str = "year",
) -> BuiltHousehold:
    """:func:`create_model` + :func:`populate_model`, returning the agent handles."""
    _check(spec, config, check)
    model = create_model(spec, config=config, seed=seed, collect_data=collect_data, collect=collect)
    return _populate(model, spec)


def build_model(
    spec: s.HouseholdSpec,
    *,
    config: FinancialConfig | None = None,
    seed: int | None = None,
    collect_data: bool = True,
    check: bool = True,
    collect: str = "year",
) -> LifeModel:
    """Build a ready-to-run :class:`LifeModel` from ``spec``.

    Args:
        spec: The household spec.
        config: Financial config (see :func:`create_model`).
        seed: Overrides ``meta.seed``.
        collect_data: Passed to ``LifeModel(collect_data=)``.
        check: Run the validator first: errors raise :class:`SpecValidationError`, warnings are
            emitted as :class:`SpecWarning`. When False only ``not_yet_supported`` fields are
            checked (they are always rejected, so the builder never silently drops one).
        collect: ``"year"`` (default) or ``"month"`` (also month-end rows; see :func:`create_model`).

    Returns:
        The model; ``model.household`` holds the :class:`BuiltHousehold` handles.
    """
    return build_household(
        spec, config=config, seed=seed, collect_data=collect_data, check=check, collect=collect
    ).model


def _check(spec: s.HouseholdSpec, config: FinancialConfig | None, check: bool) -> None:
    from .validate import ERROR, WARNING, not_yet_supported_findings, validate_spec

    if check:
        findings = validate_spec(spec, config=config)
    else:
        findings = not_yet_supported_findings(spec)
    errors = [f for f in findings if f.level == ERROR]
    if errors:
        raise SpecValidationError(errors)
    for finding in findings:
        if finding.level == WARNING:
            warnings.warn(f"{finding.path}: {finding.message}", SpecWarning, stacklevel=4)


# --- Population ----------------------------------------------------------------------------------


def _growth(value: float | str) -> float | None:
    """Spec growth (percent or "economy") to the core convention (None follows the economy)."""
    return None if value == "economy" else float(value)


def _fractions(pcts: list[float] | None):
    from ..work.stock import VestingSchedule

    return None if pcts is None else VestingSchedule([p / 100 for p in pcts])


class _Builder:
    """Stateful helper that builds one spec into one model (see the module docstring for the order)."""

    def __init__(self, model: LifeModel, spec: s.HouseholdSpec):
        self.model = model
        self.spec = spec
        self.family = Family(
            model, withdrawal_order=None if spec.withdrawal_order is None else tuple(spec.withdrawal_order)
        )
        self.built = BuiltHousehold(model=model, family=self.family, spec=spec)

    # --- helpers ---

    def _register(self, person_spec: s.Person, collection: str, index: int, item: Any, agent: Any) -> None:
        key = getattr(item, "id", None) or f"{person_spec.id}.{collection}[{index}]"
        self.built.items[key] = agent
        if getattr(item, "id", None) is not None:
            agent.spec_id = item.id
        if getattr(item, "primary", False):
            agent.spec_primary = True  # provenance for the extractor

    def person(self, pid: str):
        return self.built.people[pid]

    def start_spouse(self, person_spec: s.Person):
        """The person's spouse by a marriage in effect at the start (a joint account's co-owner)."""
        start = self.model.start_year
        for marriage in self.spec.relationships.marriages:
            if person_spec.id in marriage.spouses and (marriage.year is None or marriage.year <= start):
                other = next(pid for pid in marriage.spouses if pid != person_spec.id)
                return self.built.people[other]
        raise ValueError(f"{person_spec.id}: a joint account needs a marriage in effect at the start")

    def job_agent(self, person_spec: s.Person, job_id: str | None):
        if job_id is None:
            return None
        for index, job in enumerate(person_spec.jobs):
            if job.id == job_id:
                return self.built.items[job.id or f"{person_spec.id}.jobs[{index}]"]
        se = person_spec.self_employment
        if se is not None and se.id == job_id:
            return self.built.items[job_id]
        agent = self.built.items.get(job_id) if job_id is not None else None
        if agent is None:
            raise ValueError(f"{person_spec.id}: unknown job {job_id!r}")
        return agent

    # --- people ---

    def build_person(self, p: s.Person):
        from ..people.person import Person, Spending
        from ..people.types import GenderAtBirth, MortalityMode

        if p.spending is None:
            # A spouse whose partner's spending holds the household budget spends nothing of their own.
            spending = Spending(model=self.model, base_annual=0.0, growth_pct=None)
            spending.spec_omitted = True  # provenance for the extractor
        else:
            spending = Spending(
                model=self.model,
                base_annual=p.spending.amount_annual,
                growth_pct=_growth(p.spending.growth_pct),
                categories=_spending_lines(p.spending.categories),
                schedule=[tuple(step) for step in p.spending.schedule] if p.spending.schedule else None,
            )
        person = Person(
            family=self.family,
            name=p.name,
            age=p.age,
            retirement_age=p.retirement_age,
            spending=spending,
            gender=GenderAtBirth(p.gender),
            mortality_mode=MortalityMode(p.mortality),
            death_age=p.death_age,
            state=p.state if p.state is not None else self.spec.meta.default_state,
            birth=p.birth,
        )
        person.spec_id = p.id
        self.built.people[p.id] = person
        return person

    # --- jobs ---

    def build_job(self, person, job: s.Job):
        from ..work.job import Bonus, Job, Salary

        structured = job.bonus_fixed_annual is not None or job.bonus_range_pct is not None or job.signon_bonus > 0
        salary = Salary(
            self.model,
            base_annual=job.salary_annual,
            raise_pct=_growth(job.raise_pct),
            bonus_pct=0.0 if structured else job.bonus_pct,
            bonus=Bonus(
                target_pct=job.bonus_pct,
                fixed_annual=job.bonus_fixed_annual or 0.0,
                range_pct=job.bonus_range_pct,
                signon=job.signon_bonus,
            )
            if structured
            else None,
            raises=job.raises,
        )
        payroll = None
        if job.payroll is not None and any(job.payroll.model_dump().values()):
            from ..work.payroll import PayrollDeductions

            payroll = PayrollDeductions(**job.payroll.model_dump())
        return Job(
            person,
            company=job.company,
            role=job.role,
            salary=salary,
            payroll=payroll,
            start_year=job.start_year,
            end_year=job.end_year,
        )

    def build_self_employment(self, person, se: s.SelfEmployment):
        """A sole proprietorship: ``Job(kind="self_employed")`` whose salary is the gross receipts (the
        SEP account is attached once the traditional IRAs exist, :meth:`attach_sep_account`)."""
        from ..work.job import Job, Salary

        salary = Salary(self.model, base_annual=se.receipts, raise_pct=_growth(se.growth_pct))
        return Job(
            person,
            company=se.business,
            role="Owner",
            salary=salary,
            kind="self_employed",
            expenses_annual=se.expenses_annual,
            plan_contribution_percent=se.sep_ira_contrib_pct,
            sstb=se.sstb,
        )

    def attach_sep_account(self, person, person_spec: s.Person, job) -> None:
        """Give a self-employed job with a plan rate and no solo 401(k) its SEP IRA: the named
        ``sep_account``, else the person's first traditional IRA, else a new empty one."""
        from ..account.traditional_IRA import TraditionalIRA

        se = person_spec.self_employment
        if se is None or not se.sep_ira_contrib_pct or job.retirement_account is not None:
            return
        if se.sep_account is not None:
            job.sep_account = self.built.items[se.sep_account]
        elif person.traditional_iras:
            job.sep_account = person.traditional_iras[0]
        else:
            job.sep_account = TraditionalIRA(person, balance=0.0)

    def build_stock_plan(self, job_agent, plan: s.StockPlan):
        from ..work.stock import ESPP, StockGrant, StockOption, StockPlan

        espp = None
        if plan.espp_contribution_pct:
            espp = ESPP(
                contribution_pct=plan.espp_contribution_pct,
                discount_pct=plan.espp_discount_pct if plan.espp_discount_pct is not None else 15.0,
                purchase_months=tuple(plan.espp_purchase_months),
                lookback=plan.espp_lookback,
                disposition=plan.espp_disposition,
            )
        return StockPlan(
            job_agent,
            options=[
                StockOption(
                    kind=o.kind,
                    exercise_year=o.exercise_year,
                    exercise_cost=o.exercise_cost,
                    value=o.value,
                    sell_at_exercise=o.sell_at_exercise,
                )
                for o in plan.options
            ],
            signon_value=plan.signon_value,
            refresher_value=plan.refresher_value,
            refresher_start_year=plan.refresher_start_year,
            refresher_growth_pct=plan.refresher_growth_pct,
            schedule=_fractions(plan.vesting_schedule_pct),
            signon_schedule=_fractions(plan.signon_vesting_schedule_pct),
            disposition=plan.disposition,
            growth_pct=_growth(plan.growth_pct),
            existing_grants=[
                StockGrant(
                    value_at_grant=g.value,
                    grant_year=g.grant_year,
                    schedule=_fractions(g.vesting_schedule_pct),
                    unvested_value=g.unvested_value,
                )
                for g in plan.existing_grants or ()
            ],
            espp=espp,
        )

    # --- accounts ---

    def build_account(self, person, person_spec: s.Person, account: Any):
        kind = account.kind
        invest = {}
        if getattr(account, "allocation_pct", None) is not None:
            invest["allocation"] = dict(account.allocation_pct)
        if getattr(account, "expense_ratio_pct", None) is not None:
            invest["expense_ratio_pct"] = account.expense_ratio_pct
        joint_owner = self.start_spouse(person_spec) if getattr(account, "joint", False) else None
        if kind == "bank":
            from ..account.bank import BankAccount

            return BankAccount(
                person,
                company=account.company,
                type=account.type,
                balance=account.balance,
                interest_pct=_growth(account.interest_pct),
                compounding=account.compounding,
                reserve=account.reserve,
                joint_owner=joint_owner,
                joint_primary=account.primary and joint_owner is not None,
            )
        if kind == "fixed_income":
            from ..account.fixed_income import FixedIncomeHolding

            return FixedIncomeHolding(
                person,
                kind=account.instrument,
                face=account.face,
                rate_pct=account.rate_pct,
                maturity=account.maturity,
                purchased=account.purchased,
                state_tax_exempt=account.state_tax_exempt,
                tax_exempt=account.tax_exempt,
                early_withdrawal_penalty_months=account.early_withdrawal_penalty_months,
                reserve=account.reserve,
                name=account.name,
                accrued_interest=account.accrued_interest,
                cost_basis=account.cost_basis,
            )
        if kind == "401k":
            from ..account.job401k import Job401kAccount

            job = self.job_agent(person_spec, account.job)
            return Job401kAccount(
                job,
                owner=person,
                pretax_balance=account.pretax_balance,
                pretax_contrib_pct=account.pretax_contrib_pct,
                roth_balance=account.roth_balance,
                roth_contrib_pct=account.roth_contrib_pct,
                after_tax_balance=account.after_tax_balance or 0.0,
                after_tax_basis=account.after_tax_basis,
                after_tax_contrib_pct=account.after_tax_contrib_pct,
                in_plan_roth_conversion=account.in_plan_roth_conversion,
                roth_basis=account.roth_basis,
                growth_pct=_growth(account.growth_pct),
                company_match_percent=account.company_match_pct,  # deprecated; the validator warns
                match_tiers=None
                if account.match_tiers is None
                else [(tier.match_pct, tier.up_to_pay_pct) for tier in account.match_tiers],
                bonus_is_plan_pay=account.bonus_is_plan_pay,
                match_vesting_years=account.match_vesting_years,
                **invest,
            )
        if kind == "brokerage":
            from ..account.brokerage import BrokerageAccount, Lot

            lots = None
            if account.lots is not None:
                lots = [
                    Lot(
                        lot.value,
                        lot.cost_basis,
                        None
                        if lot.acquired_year is None
                        else (
                            f"{lot.acquired_year:04d}-{lot.acquired_month:02d}"
                            if lot.acquired_month is not None
                            else lot.acquired_year
                        ),
                    )
                    for lot in account.lots
                ]
            return BrokerageAccount(
                person,
                company=account.company,
                balance=account.balance or 0.0,
                lots=lots,
                growth_pct=_growth(account.growth_pct),
                dividend_yield_pct=account.dividend_yield_pct,
                reinvest_dividends=account.reinvest_dividends,
                joint_owner=joint_owner,
                **invest,
            )
        if kind == "traditional_ira":
            from ..account.traditional_IRA import TraditionalIRA

            return TraditionalIRA(
                person,
                balance=account.balance,
                growth_pct=_growth(account.growth_pct),
                contribution_limit_annual=account.contribution_limit_annual,
                nondeductible_basis=account.nondeductible_basis or 0.0,
                **invest,
            )
        if kind == "roth_ira":
            from ..account.roth_IRA import RothIRA

            return RothIRA(
                person,
                balance=account.balance,
                growth_pct=_growth(account.growth_pct),
                contribution_limit_annual=account.contribution_limit_annual,
                contribution_basis=account.contribution_basis,
                conversion_basis=account.conversion_basis or 0.0,
                **invest,
            )
        if kind == "hsa":
            from ..account.hsa import HealthSavingsAccount, HSAType

            return HealthSavingsAccount(
                person,
                hsa_type=HSAType.FAMILY if account.coverage == "family" else HSAType.INDIVIDUAL,
                balance=account.balance,
                contribution_limit_annual=account.contribution_limit_annual,
                employer_contribution_annual=account.employer_contribution_annual,
                growth_pct=_growth(account.growth_pct),
                basis=account.basis,
                **invest,
            )
        if kind == "529":
            from ..dependents.plan529 import Plan529

            beneficiary = self.built.items[account.beneficiary] if account.beneficiary is not None else None
            return Plan529(
                person,
                beneficiary=beneficiary,
                balance=account.balance,
                state=account.plan_state,
                growth_pct=_growth(account.growth_pct),
                contribution_limit_annual=account.contribution_limit_annual,
                lifetime_contribution_limit=account.lifetime_contribution_limit,
                basis=account.basis,
                **invest,
            )
        if kind == "inherited_pretax":
            from ..account.inherited import InheritedPretaxAccount

            return InheritedPretaxAccount(
                beneficiary=person, balance=account.balance, decedent_name=account.decedent_name, years=account.years
            )
        if kind == "pension":
            from ..account.pension import Pension

            pension = Pension(
                owner=person,
                company=account.company,
                vesting_years=account.vesting_years,
                benefit_annual=account.benefit_annual,
                start_age=account.start_age,
                cola_pct=account.cola_pct,
                survivor_pct=account.survivor_pct,
                years_of_service=account.years_of_service,
                benefit_multiplier_pct=account.benefit_multiplier_pct,
                final_salary_annual=account.final_salary_annual,
                job=self.job_agent(person_spec, account.job) if account.job is not None else None,
                salary_history=account.salary_history_annual,
                final_average_years=account.final_average_years,
                normal_retirement_age=account.normal_retirement_age,
                early_reduction_pct_per_year=account.early_retirement_reduction_pct or 0.0,
                survivor_reduction=account.survivor_reduction_pct,
                employee_basis=account.employee_basis,
                lump_sum=account.lump_sum_option,
                lump_sum_amount=account.lump_sum_amount,
                lump_sum_rate_pct=account.lump_sum_rate_pct,
                rollover_account=self.built.items[account.rollover_account]
                if account.rollover_account is not None
                else None,
            )
            pension.accrues_service = account.accrues_service
            return pension
        if kind == "annuity":
            from ..insurance.annuity import Annuity, AnnuityPayoutType, AnnuityType

            joint = self.person(account.joint_annuitant) if account.joint_annuitant is not None else None
            return Annuity(
                owner=person,
                annuity_type=AnnuityType[account.annuity_type.upper()],
                balance=account.balance,
                rate_pct=account.interest_pct,
                payout_type=AnnuityPayoutType[account.payout_type.upper()],
                payout_start_age=account.payout_start_age,
                payout_monthly=account.payout_monthly,
                period_certain_years=account.period_certain_years,
                surrender_charge_years=account.surrender_charge_years,
                surrender_charge_pct=account.surrender_charge_pct,
                joint_annuitant=joint,
                survivor_pct=account.survivor_pct,
                basis=account.basis,
                purchase_year=account.purchase_year,
                qualified=account.qualified,
                in_payout=account.in_payout,
                cola_pct=account.cola_pct,
            )
        if kind == "daf":
            from ..charity.daf import DonorAdvisedFund

            return DonorAdvisedFund(
                person=person,
                fund_name=account.name,
                balance=account.balance,
                growth_rate=account.growth_pct,
                management_fee=account.management_fee_pct,
                distribution_rate=account.distribution_pct,
            )
        if kind == "trust":
            from ..estate.trust import Trust, TrustType

            return Trust(
                grantor=person,
                trust_type=TrustType(account.trust_type),
                beneficiaries=[self.person(pid) for pid in account.beneficiaries],
                name=account.name,
                balance=account.balance,
                growth_rate=_growth(account.growth_pct),
                asset_class=account.asset_class,
            )
        raise NotImplementedError(f"account kind {kind!r} is not supported by the builder")

    # --- debts, housing, insurance ---

    @staticmethod
    def _loan_terms(loan: Any) -> dict[str, Any]:
        """The statement inputs every amortizing loan takes (Plan 27 D1/D7)."""
        return {
            "original_amount": loan.original_amount,
            "term_years": loan.term_years,
            "rate_pct": loan.rate_pct,
            "current_balance": loan.balance,
            "payment_monthly": loan.payment_monthly,
            "term_months": loan.term_months,
            "origination": loan.origination,
            "payments_made": loan.payments_made,
            "remaining_months": loan.remaining_months,
            "extra_principal_monthly": loan.extra_principal_monthly,
            "schedule": loan.schedule,
        }

    @staticmethod
    def _remember_loan(agent, loan: Any):
        """Provenance for the extractor: the statement fields as entered."""
        agent.spec_loan_inputs = {name: getattr(loan, name) for name in s._LoanTerms.model_fields}
        return agent

    def build_debt(self, person, debt: Any):
        if debt.kind == "car":
            from ..debt.car_loan import CarLoan

            return self._remember_loan(CarLoan(owner=person, name=debt.name, **self._loan_terms(debt)), debt)
        if debt.kind == "student":
            from ..debt.student_loan import StudentLoan, StudentLoanRepaymentPlan, StudentLoanType

            loan = StudentLoan(
                owner=person,
                loan_type=StudentLoanType[debt.loan_type.upper()],
                school_name=debt.school,
                in_deferment=debt.in_deferment,
                repayment_plan=StudentLoanRepaymentPlan[debt.repayment_plan.upper()],
                deferment_until=debt.deferment_until,
                qualifying_payments=debt.qualifying_payments,
                **self._loan_terms(debt),
            )
            return self._remember_loan(loan, debt)
        if debt.kind == "credit_card":
            from ..debt.credit_card import CreditCard, CreditCardType, PaymentStrategy

            return CreditCard(
                owner=person,
                name=debt.name,
                credit_limit=debt.credit_limit,
                balance=debt.balance,
                rate_pct=debt.rate_pct,
                minimum_payment_pct=debt.minimum_payment_pct,
                card_type=CreditCardType[debt.card_type.upper()] if debt.card_type is not None else None,
                payment_strategy=PaymentStrategy(debt.payment_strategy),
                payment_monthly=debt.payment_monthly,
                spending_charge_pct=debt.spending_charged_pct,
            )
        if debt.kind == "heloc":
            from ..debt.credit_card import PaymentStrategy
            from ..debt.heloc import HomeEquityLine

            return HomeEquityLine(
                owner=person,
                home=self.built.items[debt.home],
                credit_limit=debt.credit_limit,
                balance=debt.balance,
                rate_pct=debt.rate_pct,
                improvement_balance=debt.improvement_balance,
                payment_strategy=PaymentStrategy(debt.payment_strategy),
                payment_monthly=debt.payment_monthly,
                name=debt.name,
            )
        raise NotImplementedError(f"debt kind {debt.kind!r} is not supported by the builder")

    def build_home(self, person, home: s.Home, *, purchase: bool | None = None):
        from ..housing.home import Home, HomeExpenses, Mortgage

        mortgage = None
        if home.mortgage is not None:
            m = home.mortgage
            terms = self._loan_terms(m)
            mortgage = Mortgage(
                start_year=m.start_year if m.start_year is not None else self.model.year,
                escrow_monthly=m.escrow_monthly,
                **terms,
            )
            self._remember_loan(mortgage, m)
            mortgage.spec_start_year = m.start_year
        e = home.expenses
        expenses = HomeExpenses(
            model=self.model,
            property_tax_pct=e.property_tax_pct,
            insurance_pct=e.insurance_pct,
            maintenance_annual=e.maintenance_annual,
            maintenance_growth_pct=_growth(e.maintenance_growth_pct),
            improvement_annual=e.improvement_annual,
            improvement_growth_pct=_growth(e.improvement_growth_pct),
            hoa_annual=e.hoa_monthly * 12,
            hoa_growth_pct=_growth(e.hoa_growth_pct),
            property_tax_annual=e.property_tax_annual,
            property_tax_growth_pct=_growth(e.property_tax_growth_pct),
            assessed_value=e.assessed_value,
            assessment_growth_cap_pct=e.assessment_growth_cap_pct,
            insurance_annual=e.insurance_annual,
            insurance_growth_pct=_growth(e.insurance_growth_pct),
        )
        return Home(
            owner=person,
            name=home.name,
            purchase_price=home.purchase_price,
            value_growth_pct=_growth(home.value_growth_pct),
            down_payment=home.down_payment,
            mortgage=cast(Mortgage, mortgage),  # core accepts None (no mortgage)
            expenses=expenses,
            purchase=home.purchase if purchase is None else purchase,
            current_value=home.current_value,
            cost_basis=home.cost_basis,
            purchase_year=home.purchase_year,
            pmi=home.pmi,
            pmi_monthly=home.pmi_monthly,
            closing_cost_percent=home.closing_cost_pct,
        )

    def build_rental(self, person, rental: s.Rental):
        from ..housing.apartment import Apartment

        return Apartment(
            owner=person,
            name=rental.name,
            rent_monthly=rental.rent_monthly,
            rent_growth_pct=_growth(rental.rent_growth_pct),
        )

    def build_housing(self, person, item: Any):
        if item.kind == "home":
            return self.build_home(person, item)
        return self.build_rental(person, item)

    def build_insurance(self, person, policy: Any):
        if policy.kind == "life":
            from ..insurance.life_insurance import LifeInsurance, LifeInsuranceType, PremiumIncreaseType

            if policy.premium_schedule == "level":
                increase: float | PremiumIncreaseType | None = PremiumIncreaseType.LEVEL
            elif policy.premium_schedule == "age_banded":
                increase = PremiumIncreaseType.AGE_BANDED
            else:
                increase = policy.premium_increase_pct
            return LifeInsurance(
                owner=person,
                policy_type=LifeInsuranceType[policy.policy.upper()],
                death_benefit=policy.death_benefit,
                premium_monthly=policy.premium_monthly,
                term_years=policy.term_years,
                premium_increase_rate=increase,
                cash_value_growth_pct=policy.cash_value_growth_pct,
                loan_interest_pct=policy.loan_interest_pct,
                max_missed_payments=policy.max_missed_payments,
                beneficiary=self.person(policy.beneficiary) if policy.beneficiary is not None else None,
                issue_year=policy.issue_year,
                issue_month=policy.issue_month,
                cash_value=policy.cash_value or 0.0,
                loan_balance=policy.loan_balance or 0.0,
                premiums_paid=policy.premiums_paid,
            )
        from ..insurance.general_insurance import Insurance, InsuranceType

        kind = "LONG_TERM_CARE" if policy.kind == "ltc" else policy.kind.upper()
        return Insurance(
            owner=person,
            insurance_type=InsuranceType[kind],
            company=policy.company,
            premium_annual=policy.premium_annual,
            coverage_amount=policy.coverage_amount,
            deductible=policy.deductible,
            coverage_start_age=policy.coverage_start_age,
            coverage_end_age=policy.coverage_end_age,
            premium_increase_pct=policy.premium_increase_pct,
            max_claims_per_year=policy.max_claims_per_year,
            oop_max_annual=policy.oop_max_annual,
            coinsurance_pct=policy.coinsurance_pct,
            benefit_pct=policy.benefit_pct,
            benefit_max_monthly=policy.benefit_max_monthly,
            elimination_months=policy.elimination_months,
            benefit_end_age=policy.benefit_end_age,
            benefits_taxable=policy.benefits_taxable,
        )

    # --- SS, healthcare, giving ---

    def synthetic_earnings(self, person_spec: s.Person, career_start_age: int) -> list[tuple[int, float]]:
        """A flat real career at the first job's salary (see ``SocialSecurity.assumed_career_start_age``)."""
        from ..insurance.social_security import get_avg_wage_index

        start_year = self.model.start_year
        years_worked = max(0, int(person_spec.age) - int(career_start_age))
        salary = float(person_spec.jobs[0].salary_annual) if person_spec.jobs else 0.0
        config, economy = self.model.config, self.model.economy
        awi_now = get_avg_wage_index(start_year, config, economy=economy)
        # SSA's wage index and quarter-of-coverage tables start in 1951 / 1978; earlier working
        # years are dropped (only very old start ages reach them).
        first_year = max(start_year - years_worked, FIRST_EARNINGS_YEAR)
        history: list[tuple[int, float]] = []
        for year in range(first_year, start_year):
            wage = salary * get_avg_wage_index(year, config, economy=economy) / awi_now
            cap = self.model.config_for_year(year).tax.fica.social_security_max_income
            history.append((year, round(min(wage, cap), 2)))
        return history

    def build_social_security(self, person, person_spec: s.Person, claim_age: float | None):
        from ..insurance.social_security import SocialSecurity

        ss = person_spec.social_security
        assert ss is not None
        if ss.assumed_career_start_age is not None:
            history = self.synthetic_earnings(person_spec, ss.assumed_career_start_age)
        else:
            history = sorted((ss.earnings_history or {}).items())
        agent = SocialSecurity(
            person,
            claim_age=claim_age,
            earnings_history=history,
            pia_override_monthly=ss.pia_override_monthly,
            fra_from_birth_year=ss.fra_from_birth_year,
            spousal_benefit=ss.spousal_benefit,
            earnings_test=ss.earnings_test,
        )
        if ss.assumed_career_start_age is not None:
            # Provenance for the extractor: the record was synthesized, not entered.
            agent.spec_synthesized_history = (ss.assumed_career_start_age, len(history))
        return agent

    def build_donation(self, person, donation: s.Donation):
        from ..charity.donation import Donation, DonationType

        return Donation(
            person=person,
            charity_name=donation.charity,
            annual_amount=donation.amount_annual,
            donation_type=DonationType[donation.donation_type.upper()],
            tax_deductible=donation.tax_deductible,
            frequency_years=donation.frequency_years,
            start_year=donation.start_year,
            end_year=donation.end_year,
        )

    # --- standing savings policies (Plan 27 D4) ---

    def attach_policies(self, person, p: s.Person) -> None:
        """Attach the person's contribution plans, savings sweep and standing Roth conversion."""
        from ..policies import MAX, ContributionPlan, RothConversionPolicy, SavingsPolicy

        for plan in p.contribution_plans or ():
            account = self.built.items[plan.account]
            end = plan.end
            default_end = None
            if plan.until_age is not None:
                year, month = person.get_period_at_age(plan.until_age)
                end = (year, month - 1) if month > 1 else (year - 1, 12)
            elif end is None:
                default_end = _college_end(account)
                end = default_end
            core_plan = ContributionPlan(
                account,
                amount_annual=MAX if plan.max_out else plan.amount_annual,
                pct_of_pay=plan.pay_pct,
                source=plan.source,
                months=plan.months,
                bucket=plan.bucket,
                start=plan.start,
                end=end,
            )
            # Provenance for the extractor: the window as written (until_age, or no end for a 529's default).
            core_plan.spec_window = (plan.start, plan.end, plan.until_age)
            person.add_contribution_plan(core_plan)
        if p.savings_policy is not None:
            person.savings_policy = SavingsPolicy(
                cash_floor=p.savings_policy.cash_floor, sweep_to=self.built.items[p.savings_policy.sweep_to]
            )
        if p.roth_conversion is not None:
            rc = p.roth_conversion
            person.roth_conversion_policy = RothConversionPolicy(
                fill_bracket_pct=rc.fill_bracket_pct,
                amount_annual=rc.amount_annual,
                source=self.built.items[rc.source] if rc.source is not None else None,
                target=self.built.items[rc.target] if rc.target is not None else None,
                until_age=rc.until_age,
            )

    # --- marriages ---

    def marry(self, head, spouse, filing_status: str, *, log_event: bool = True) -> None:
        from ..tax.federal import FilingStatus

        head.get_married(spouse, log_event=log_event)
        if filing_status == "separate":
            head.filing_status = spouse.filing_status = FilingStatus.MARRIED_FILING_SEPARATELY

    # --- driver ---

    def run(self) -> BuiltHousehold:
        from ..dependents.child import Child
        from ..healthcare import LongTermCare, MedicalCosts, Medicare
        from . import events as ev

        spec = self.spec
        people = spec.people
        for p in people:
            self.build_person(p)

        def each(collection: str, select=lambda item: True):
            for p in people:
                for index, item in enumerate(getattr(p, collection)):
                    if select(item):
                        yield p, index, item

        for p, i, item in each("accounts", lambda a: a.kind == "bank"):
            self._register(p, "accounts", i, item, self.build_account(self.person(p.id), p, item))
        for p, i, job in each("jobs"):
            self._register(p, "jobs", i, job, self.build_job(self.person(p.id), job))
        for p in people:
            if p.self_employment is not None:
                self._register(
                    p,
                    "self_employment",
                    0,
                    p.self_employment,
                    self.build_self_employment(self.person(p.id), p.self_employment),
                )
        for p, i, item in each("accounts", lambda a: a.kind == "401k"):
            self._register(p, "accounts", i, item, self.build_account(self.person(p.id), p, item))
        for p, i, job in each("jobs", lambda j: j.stock_plan is not None):
            self.build_stock_plan(self.built.items[job.id or f"{p.id}.jobs[{i}]"], job.stock_plan)
        late = ("bank", "401k", *LATE_ACCOUNT_KINDS)
        for p, i, item in each("accounts", lambda a: a.kind not in late):
            self._register(p, "accounts", i, item, self.build_account(self.person(p.id), p, item))
        for p, i, item in each("debts", lambda d: d.kind != "heloc"):
            self._register(p, "debts", i, item, self.build_debt(self.person(p.id), item))
        for p, i, item in each("housing"):
            self._register(p, "housing", i, item, self.build_housing(self.person(p.id), item))
        # Home equity lines are secured by a home, so they follow housing.
        for p, i, item in each("debts", lambda d: d.kind == "heloc"):
            self._register(p, "debts", i, item, self.build_debt(self.person(p.id), item))
        for p, i, item in each("insurance"):
            self._register(p, "insurance", i, item, self.build_insurance(self.person(p.id), item))
        for p in people:
            if p.self_employment is not None:
                key = p.self_employment.id or f"{p.id}.self_employment[0]"
                self.attach_sep_account(self.person(p.id), p, self.built.items[key])
        for p, i, child in each("children"):
            self._register(
                p,
                "children",
                i,
                child,
                Child(
                    self.person(p.id),
                    child.name,
                    child.birth_year,
                    care_expenses_annual=child.care_expenses_annual,
                    interest_annual=child.interest_annual,
                    dividends_annual=child.dividends_annual,
                    cost_annual=child.cost_override_annual,
                    college_cost_annual=child.college_cost_annual,
                    birth_month=child.birth_month,
                ),
            )
        for p, i, item in each("accounts", lambda a: a.kind in LATE_ACCOUNT_KINDS):
            self._register(p, "accounts", i, item, self.build_account(self.person(p.id), p, item))
        for p in people:
            if p.healthcare is not None:
                person = self.person(p.id)
                if p.healthcare.medical_costs or p.healthcare.medical_costs_annual is not None:
                    MedicalCosts(person, annual_cost=p.healthcare.medical_costs_annual)
                if p.healthcare.medicare:
                    Medicare(person)
                if p.healthcare.long_term_care:
                    LongTermCare(person)

        # Build-time events (claiming age, fixed death age) adjust constructor inputs; resolve
        # them now that every Person exists (their ages anchor get_year_at_age).
        timing = ev.EventTiming(self)
        claim_ages = ev.apply_build_time_events(self, timing)
        for p in people:
            if p.social_security is not None:
                person = self.person(p.id)
                claim = claim_ages.get(p.id, p.social_security.claim_age)
                self._register(p, "social_security", 0, p.social_security, self.build_social_security(person, p, claim))
        for p, i, item in each("giving"):
            self._register(p, "giving", i, item, self.build_donation(self.person(p.id), item))
        for p in people:
            self.attach_policies(self.person(p.id), p)

        for marriage in spec.relationships.marriages:
            if marriage.year is None or marriage.year <= self.model.start_year:
                head, spouse = (self.person(pid) for pid in marriage.spouses)
                # A marriage before the first simulated year (or undated) is starting state, not an event of
                # the run; one dated in the start year is logged as that year's event.
                self.marry(head, spouse, marriage.filing_status, log_event=marriage.year == self.model.start_year)

        life_events = ev.compile_events(self, timing)
        if life_events:
            from ..lifeevents import LifeEvents

            self.built.life_events = LifeEvents(self.model, life_events)
        return self.built


def _spending_lines(categories: "dict[str, s.SpendingCategory] | None"):
    """The core ``SpendingLine`` of each spec spending category (Plan 27 D6)."""
    if not categories:
        return None
    from ..people.person import SpendingLine

    lines = {}
    for name, category in categories.items():
        monthly = category.amount_monthly is not None
        lines[name] = SpendingLine(
            amount=float(category.amount_monthly if monthly else category.amount_annual),
            period="monthly" if monthly else "annual",
            growth_pct=_growth(category.growth_pct),
            start_year=category.start_year,
            end_year=category.end_year,
            essential=category.essential,
        )
    return lines


def _college_end(account) -> "tuple[int, int] | None":
    """The default last contribution month of a 529 plan for a child beneficiary: the month before the
    child's college months start (``college_start_age`` birthday; January of that year without a birth
    month). None for other accounts."""
    from ..dependents.child import Child
    from ..dependents.plan529 import Plan529

    if not isinstance(account, Plan529) or not isinstance(account.beneficiary, Child):
        return None
    child = account.beneficiary
    year = child.birth_year + child.model.config.dependents.college_start_age
    month = child.birth_month or 1
    return (year, month - 1) if month > 1 else (year - 1, 12)


#: Earliest year a synthesized earnings record may start (SSA quarter-of-coverage table start).
FIRST_EARNINGS_YEAR = 1978


def populate_model(model: LifeModel, spec: s.HouseholdSpec, *, check: bool = True) -> BuiltHousehold:
    """Construct ``spec``'s household inside an existing (empty) ``model``.

    For callers that create the model themselves (a ``LifeModel`` subclass such as the dashboard's,
    or the RL environment, which installs an economy overlay between creating the model and adding
    agents). ``meta.start_year``/``end_year``/``seed``/``scenario`` and ``economy`` are *not*
    applied here (see :func:`create_model`).

    Returns:
        The agent handles; also stored as ``model.household``.
    """
    _check(spec, model.config, check)
    return _populate(model, spec)


def _populate(model: LifeModel, spec: s.HouseholdSpec) -> BuiltHousehold:
    built = _Builder(model, canonical(spec)).run()
    model.household = built
    return built


def is_spec_agent(agent: LifeModelAgent) -> bool:
    """Whether ``agent`` was built from a spec entry that carried an explicit id."""
    return getattr(agent, "spec_id", None) is not None
