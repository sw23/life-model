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

1. model (:func:`create_model`: seed, scenario, economy overrides) and the one ``Family``;
2. people (``Spending`` then ``Person``), in :func:`people_order` (marriage heads first, in
   ``relationships`` order, each followed by their spouse; then everyone else by id);
3. bank accounts (the ``primary`` one first), then jobs (``Salary``, ``Job``), then 401ks, then
   stock plans;
4. other accounts in kind order: brokerage, traditional_ira, roth_ira, hsa, inherited_pretax,
   pension, annuity, daf, trust;
5. debts (car, student, credit_card), housing (homes, then rentals), insurance (life, then general
   policies);
6. children, then 529 plans (which reference children);
7. healthcare agents (medical costs, Medicare, long-term care), then Social Security;
8. giving; marriages already in effect at the start; events (a ``LifeEvents`` agent, last).

Within one step, items are ordered by ``(id, canonical JSON)``, so two items without ids still have
a deterministic order. Shuffling any list in a spec therefore yields an identical model.

Undocumented core workarounds the builder relies on (each documented on its schema field; Plan 27
turns them into real constructor arguments, and this module switches over then):

* brokerage opening lots: ``BrokerageAccount(balance=0)`` + one ``deposit_with_basis`` per lot;
* a loan in progress: ``loan_amount=original_amount, principal=balance``;
* a level term-life premium: ``premium_increase_rate={}`` (no age multipliers).
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
DEBT_KIND_ORDER = ("car", "student", "credit_card")
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
    """
    meta = spec.meta
    if config is None:
        config = FinancialConfig()
    scenario = meta.scenario if apply_economy else None
    model = model_cls(
        end_year=meta.end_year,
        start_year=meta.start_year,
        seed=meta.seed if seed is None else seed,
        config=config,
        scenario=scenario,
        collect_data=collect_data,
    )
    overrides = economy_overrides(spec.economy) if apply_economy else {}
    if overrides:
        # Keep the scenario name: the economy block refines the scenario rather than replacing it.
        model.config.apply_scenario(cast(str, model.config.scenario), {"economy": overrides})
    return model


def build_household(
    spec: s.HouseholdSpec,
    *,
    config: FinancialConfig | None = None,
    seed: int | None = None,
    collect_data: bool = True,
    check: bool = True,
) -> BuiltHousehold:
    """:func:`create_model` + :func:`populate_model`, returning the agent handles."""
    _check(spec, config, check)
    model = create_model(spec, config=config, seed=seed, collect_data=collect_data)
    return _populate(model, spec)


def build_model(
    spec: s.HouseholdSpec,
    *,
    config: FinancialConfig | None = None,
    seed: int | None = None,
    collect_data: bool = True,
    check: bool = True,
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

    Returns:
        The model; ``model.household`` holds the :class:`BuiltHousehold` handles.
    """
    return build_household(spec, config=config, seed=seed, collect_data=collect_data, check=check).model


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
        self.family = Family(model)
        self.built = BuiltHousehold(model=model, family=self.family, spec=spec)

    # --- helpers ---

    def _register(self, person_spec: s.Person, collection: str, index: int, item: Any, agent: Any) -> None:
        key = getattr(item, "id", None) or f"{person_spec.id}.{collection}[{index}]"
        self.built.items[key] = agent
        if getattr(item, "id", None) is not None:
            agent.spec_id = item.id

    def person(self, pid: str):
        return self.built.people[pid]

    def job_agent(self, person_spec: s.Person, job_id: str | None):
        for index, job in enumerate(person_spec.jobs):
            if job.id == job_id:
                return self.built.items[job.id or f"{person_spec.id}.jobs[{index}]"]
        agent = self.built.items.get(job_id) if job_id is not None else None
        if agent is None:
            raise ValueError(f"{person_spec.id}: unknown job {job_id!r}")
        return agent

    # --- people ---

    def build_person(self, p: s.Person):
        from ..people.person import Person, Spending
        from ..people.types import GenderAtBirth, MortalityMode

        spending = Spending(
            model=self.model, base=p.spending.amount_annual, yearly_increase=_growth(p.spending.growth_pct)
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
        )
        person.spec_id = p.id
        self.built.people[p.id] = person
        return person

    # --- jobs ---

    def build_job(self, person, job: s.Job):
        from ..work.job import Job, Salary

        salary = Salary(
            model=self.model,
            base=job.salary_annual,
            yearly_increase=_growth(job.raise_pct),
            yearly_bonus=job.bonus_pct,
        )
        return Job(owner=person, company=job.company, role=job.role, salary=salary)

    def build_stock_plan(self, job_agent, plan: s.StockPlan):
        from ..work.stock import StockPlan

        return StockPlan(
            job_agent,
            signon_value=plan.signon_value,
            refresher_value=plan.refresher_value,
            refresher_start_year=plan.refresher_start_year,
            refresher_growth_percent=plan.refresher_growth_pct,
            schedule=_fractions(plan.vesting_schedule_pct),
            signon_schedule=_fractions(plan.signon_vesting_schedule_pct),
            disposition=plan.disposition,
            growth_rate=_growth(plan.growth_pct),
        )

    # --- accounts ---

    def build_account(self, person, person_spec: s.Person, account: Any):
        kind = account.kind
        if kind == "bank":
            from ..account.bank import BankAccount

            return BankAccount(
                owner=person,
                company=account.company,
                type=account.type,
                balance=account.balance,
                interest_rate=_growth(account.interest_pct),
            )
        if kind == "401k":
            from ..account.job401k import Job401kAccount

            return Job401kAccount(
                job=self.job_agent(person_spec, account.job),
                pretax_balance=account.pretax_balance,
                pretax_contrib_percent=account.pretax_contrib_pct,
                roth_balance=account.roth_balance,
                roth_contrib_percent=account.roth_contrib_pct,
                average_growth=_growth(account.growth_pct),
                company_match_percent=account.company_match_pct,
            )
        if kind == "brokerage":
            from ..account.brokerage import BrokerageAccount

            if account.lots is None:
                return BrokerageAccount(
                    person=person,
                    company=account.company,
                    balance=account.balance or 0.0,
                    growth_rate=_growth(account.growth_pct),
                    dividend_yield=account.dividend_yield_pct,
                )
            # Workaround (Plan 27 D1 adds lots=): open empty, then one deposit_with_basis per lot.
            brokerage = BrokerageAccount(
                person=person,
                company=account.company,
                balance=0.0,
                growth_rate=_growth(account.growth_pct),
                dividend_yield=account.dividend_yield_pct,
            )
            for lot in account.lots:
                brokerage.deposit_with_basis(lot.value, lot.cost_basis, lot.acquired_year)
            return brokerage
        if kind == "traditional_ira":
            from ..account.traditional_IRA import TraditionalIRA

            return TraditionalIRA(
                person=person,
                balance=account.balance,
                growth_rate=_growth(account.growth_pct),
                contribution_limit=account.contribution_limit_annual,
            )
        if kind == "roth_ira":
            from ..account.roth_IRA import RothIRA

            return RothIRA(
                person=person,
                balance=account.balance,
                growth_rate=_growth(account.growth_pct),
                contribution_limit=account.contribution_limit_annual,
            )
        if kind == "hsa":
            from ..account.hsa import HealthSavingsAccount, HSAType

            return HealthSavingsAccount(
                person=person,
                hsa_type=HSAType.FAMILY if account.coverage == "family" else HSAType.INDIVIDUAL,
                balance=account.balance,
                contribution_limit=account.contribution_limit_annual,
                employer_contribution=account.employer_contribution_annual,
                growth_rate=_growth(account.growth_pct),
            )
        if kind == "529":
            from ..dependents.plan529 import Plan529

            beneficiary = self.built.items[account.beneficiary] if account.beneficiary is not None else None
            return Plan529(
                owner=person,
                beneficiary=beneficiary,
                balance=account.balance,
                state=account.plan_state,
                growth_rate=_growth(account.growth_pct),
                annual_contribution_limit=account.contribution_limit_annual,
                lifetime_contribution_limit=account.lifetime_contribution_limit,
            )
        if kind == "inherited_pretax":
            from ..account.inherited import InheritedPretaxAccount

            return InheritedPretaxAccount(
                beneficiary=person, balance=account.balance, decedent_name=account.decedent_name, years=account.years
            )
        if kind == "pension":
            from ..account.pension import Pension

            return Pension(
                person=person,
                company=account.company,
                vesting_years=account.vesting_years,
                benefit_amount=account.benefit_annual,
                start_age=account.start_age,
                cola_percent=account.cola_pct,
                survivor_percent=account.survivor_pct,
                years_of_service=account.years_of_service,
                benefit_multiplier=account.benefit_multiplier_pct,
                final_salary=account.final_salary_annual,
            )
        if kind == "annuity":
            from ..insurance.annuity import Annuity, AnnuityPayoutType, AnnuityType

            joint = self.person(account.joint_annuitant) if account.joint_annuitant is not None else None
            return Annuity(
                person=person,
                annuity_type=AnnuityType[account.annuity_type.upper()],
                initial_balance=account.balance,
                interest_rate=account.interest_pct,
                payout_type=AnnuityPayoutType[account.payout_type.upper()],
                payout_start_age=account.payout_start_age,
                monthly_payout=account.payout_monthly,
                period_certain_years=account.period_certain_years,
                surrender_charge_years=account.surrender_charge_years,
                surrender_charge_rate=account.surrender_charge_pct,
                joint_annuitant=joint,
                survivor_percent=account.survivor_pct,
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

    def build_debt(self, person, debt: Any):
        if debt.kind == "car":
            from ..debt.car_loan import CarLoan

            # Workaround: loan_amount=original, principal=current (Plan 27 D1/D7).
            return CarLoan(
                person=person,
                loan_amount=debt.original_amount,
                length_years=debt.term_years,
                yearly_interest_rate=debt.rate_pct,
                name=debt.name,
                principal=debt.balance,
                monthly_payment=debt.payment_monthly,
            )
        if debt.kind == "student":
            from ..debt.student_loan import StudentLoan, StudentLoanRepaymentPlan, StudentLoanType

            return StudentLoan(
                person=person,
                loan_type=StudentLoanType[debt.loan_type.upper()],
                loan_amount=debt.original_amount,
                yearly_interest_rate=debt.rate_pct,
                length_years=debt.term_years,
                school_name=debt.school,
                principal=debt.balance,
                monthly_payment=debt.payment_monthly,
                in_deferment=debt.in_deferment,
                repayment_plan=StudentLoanRepaymentPlan[debt.repayment_plan.upper()],
            )
        if debt.kind == "credit_card":
            from ..debt.credit_card import CreditCard, CreditCardType, PaymentStrategy

            return CreditCard(
                person=person,
                card_name=debt.name,
                credit_limit=debt.credit_limit,
                current_balance=debt.balance,
                yearly_interest_rate=debt.rate_pct,
                minimum_payment_percent=debt.minimum_payment_pct,
                card_type=CreditCardType[debt.card_type.upper()] if debt.card_type is not None else None,
                payment_strategy=PaymentStrategy(debt.payment_strategy),
                fixed_payment=debt.payment_monthly,
            )
        raise NotImplementedError(f"debt kind {debt.kind!r} is not supported by the builder")

    def build_home(self, person, home: s.Home, *, purchase: bool | None = None):
        from ..housing.home import Home, HomeExpenses, Mortgage

        mortgage = None
        if home.mortgage is not None:
            m = home.mortgage
            mortgage = Mortgage(
                loan_amount=m.original_amount,
                start_date=m.start_year if m.start_year is not None else self.model.start_year,
                length_years=m.term_years,
                yearly_interest_rate=m.rate_pct,
                principal=m.balance,
                monthly_payment=m.payment_monthly,
            )
        e = home.expenses
        expenses = HomeExpenses(
            model=self.model,
            property_tax_percent=e.property_tax_pct,
            home_insurance_percent=e.insurance_pct,
            maintenance_amount=e.maintenance_annual,
            maintenance_increase=e.maintenance_growth_pct,
            improvement_amount=e.improvement_annual,
            improvement_increase=e.improvement_growth_pct,
            hoa_amount=e.hoa_monthly * 12,
            hoa_increase=e.hoa_growth_pct,
        )
        return Home(
            person=person,
            name=home.name,
            purchase_price=home.purchase_price,
            value_yearly_increase=_growth(home.value_growth_pct),
            down_payment=home.down_payment,
            mortgage=cast(Mortgage, mortgage),  # core accepts None (no mortgage)
            expenses=expenses,
            purchase=home.purchase if purchase is None else purchase,
        )

    def build_rental(self, person, rental: s.Rental):
        from ..housing.apartment import Apartment

        return Apartment(
            person=person,
            name=rental.name,
            monthly_rent=rental.rent_monthly,
            yearly_increase=_growth(rental.rent_growth_pct),
        )

    def build_housing(self, person, item: Any):
        if item.kind == "home":
            return self.build_home(person, item)
        return self.build_rental(person, item)

    def build_insurance(self, person, policy: Any):
        if policy.kind == "life":
            from ..insurance.life_insurance import LifeInsurance, LifeInsuranceType

            if policy.premium_schedule == "level":
                increase: float | dict | None = {}  # workaround: no age multipliers = level premium
            elif policy.premium_schedule == "age_banded":
                increase = None
            else:
                increase = policy.premium_increase_pct
            return LifeInsurance(
                person=person,
                policy_type=LifeInsuranceType[policy.policy.upper()],
                death_benefit=policy.death_benefit,
                monthly_premium=policy.premium_monthly,
                term_years=policy.term_years,
                premium_increase_rate=increase,
                cash_value_growth_rate=policy.cash_value_growth_pct,
                loan_interest_rate=policy.loan_interest_pct,
                max_missed_payments=policy.max_missed_payments,
                beneficiary=self.person(policy.beneficiary) if policy.beneficiary is not None else None,
            )
        from ..insurance.general_insurance import Insurance, InsuranceType

        kind = "LONG_TERM_CARE" if policy.kind == "ltc" else policy.kind.upper()
        return Insurance(
            person=person,
            insurance_type=InsuranceType[kind],
            company=policy.company,
            annual_premium=policy.premium_annual,
            coverage_amount=policy.coverage_amount,
            deductible=policy.deductible,
            coverage_start_age=policy.coverage_start_age,
            coverage_end_age=policy.coverage_end_age,
            premium_increase_rate=policy.premium_increase_pct,
            max_claims_per_year=policy.max_claims_per_year,
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
        agent = SocialSecurity(person, withdrawal_start_age=claim_age, income_history=history)
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

    # --- marriages ---

    def marry(self, head, spouse, filing_status: str) -> None:
        from ..tax.federal import FilingStatus

        head.get_married(spouse)
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
        for p, i, item in each("accounts", lambda a: a.kind == "401k"):
            self._register(p, "accounts", i, item, self.build_account(self.person(p.id), p, item))
        for p, i, job in each("jobs", lambda j: j.stock_plan is not None):
            self.build_stock_plan(self.built.items[job.id or f"{p.id}.jobs[{i}]"], job.stock_plan)
        late = ("bank", "401k", *LATE_ACCOUNT_KINDS)
        for p, i, item in each("accounts", lambda a: a.kind not in late):
            self._register(p, "accounts", i, item, self.build_account(self.person(p.id), p, item))
        for p, i, item in each("debts"):
            self._register(p, "debts", i, item, self.build_debt(self.person(p.id), item))
        for p, i, item in each("housing"):
            self._register(p, "housing", i, item, self.build_housing(self.person(p.id), item))
        for p, i, item in each("insurance"):
            self._register(p, "insurance", i, item, self.build_insurance(self.person(p.id), item))
        for p, i, child in each("children"):
            self._register(p, "children", i, child, Child(self.person(p.id), child.name, child.birth_year))
        for p, i, item in each("accounts", lambda a: a.kind in LATE_ACCOUNT_KINDS):
            self._register(p, "accounts", i, item, self.build_account(self.person(p.id), p, item))
        for p in people:
            if p.healthcare is not None:
                person = self.person(p.id)
                if p.healthcare.medical_costs:
                    MedicalCosts(person)
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

        for marriage in spec.relationships.marriages:
            if marriage.year is None or marriage.year <= self.model.start_year:
                head, spouse = (self.person(pid) for pid in marriage.spouses)
                self.marry(head, spouse, marriage.filing_status)

        life_events = ev.compile_events(self, timing)
        if life_events:
            from ..lifeevents import LifeEvents

            self.built.life_events = LifeEvents(self.model, life_events)
        return self.built


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
