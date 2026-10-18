# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Best-effort reverse mapping: :func:`spec_from_model` reads a ``HouseholdSpec`` off a model.

Every field is read from agent state (balances, rates, overrides) as it is *now*, so extracting a
freshly built model reproduces its spec (``dumps(spec_from_model(build_model(x))) ==
dumps(canonical(x))`` for the shipped examples), and extracting after some steps gives the current
state as a fresh start: ``meta.start_year`` is the next year to simulate (ages and balances are the
current ones) and pending events are re-timed to their remaining years. It also works on models constructed directly in Python, which is how existing code migrates
to specs.

What cannot be read from agents comes from small provenance records the builder leaves on the
model: ``model.household.spec.meta`` (name, description, as-of date, seed, default state), the
``spec_source`` of each pending ``LifeEvent``, and ``model.household_build_time_events`` (the
``die`` / ``claim_social_security`` events and the values they replaced). Explicit item ids are
read from ``agent.spec_id``.

Lossy cases (documented, not errors): a value equal to the core/config default extracts as
"unset"; an age-banded term policy with custom multipliers extracts as ``age_banded``; a home
bought with ``purchase: true`` extracts as already owned; a fired event is gone (its effect is in
the state); retired jobs are omitted.
"""

import re
from typing import Any, Literal, cast

from ..config.financial_config import FinancialConfig
from . import schema as s
from .builder import (
    ACCOUNT_KIND_ORDER,
    DEBT_KIND_ORDER,
    HOUSING_KIND_ORDER,
    INSURANCE_KIND_ORDER,
    _sorted,
)


def _growth(override: float | None) -> float | Literal["economy"]:
    return "economy" if override is None else override


def _none_if(value: Any, default: Any) -> Any:
    return None if value == default else value


def _slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_").lower()
    return slug or "person"


def _pcts(schedule) -> list[float] | None:
    return None if schedule is None else [round(f * 100, 10) for f in schedule.fractions]


class _Extractor:
    def __init__(self, model):
        self.model = model
        self.config = model.config
        household = getattr(model, "household", None)
        self.source_meta: s.Meta | None = household.spec.meta if household is not None else None
        # After the model has stepped, the spec describes the current state as a fresh start: the
        # start year is the next year to simulate, and the build-time events are already part of the
        # people's state (fixed death age, claiming age).
        self.stepped = bool(model.simulated_years)
        self.start = model.year
        self.build_time = [] if self.stepped else list(getattr(model, "household_build_time_events", []) or [])
        self.spec_built = household is not None
        self.person_ids: dict[int, str] = {}
        self.item_ids: dict[int, str] = {}

    # --- ids ---

    def pid(self, person) -> str:
        return self.person_ids[person.unique_id]

    def assign_person_ids(self, people) -> None:
        used: set[str] = set()
        for person in people:
            pid = getattr(person, "spec_id", None) or _slug(person.name)
            base, n = pid, 2
            while pid in used:
                pid, n = f"{base}_{n}", n + 1
            used.add(pid)
            self.person_ids[person.unique_id] = pid

    def item_id(self, agent, generated: str | None = None) -> str | None:
        """The agent's explicit spec id, else ``generated`` (registered for references)."""
        explicit = getattr(agent, "spec_id", None)
        if explicit is not None:
            return explicit
        if generated is not None:
            self.item_ids[id(agent)] = generated
        return generated

    # --- people ---

    def people(self):
        from ..people.family import Family
        from ..people.person import Person

        ordered = []
        for family in (a for a in self.model.agents if isinstance(a, Family)):
            for member in family.members:
                if member not in ordered and not member.is_deceased:
                    ordered.append(member)
        for agent in self.model.agents:
            if isinstance(agent, Person) and agent not in ordered and not agent.is_deceased:
                ordered.append(agent)
        return ordered

    def run(self) -> s.HouseholdSpec:
        people = self.people()
        if not people:
            raise ValueError("the model has no living people to extract")
        self.assign_person_ids(people)
        person_specs = [self.person(p) for p in people]
        return s.HouseholdSpec(
            meta=self.meta(),
            economy=self.economy(),
            people=person_specs,
            relationships=self.relationships(people),
            events=self.events(),
        )

    def meta(self) -> s.Meta:
        src = self.source_meta
        return s.Meta(
            name=src.name if src is not None else "household",
            description=src.description if src is not None else None,
            as_of=src.as_of if src is not None else None,
            start_year=self.start,
            end_year=max(self.model.end_year, self.start),
            seed=src.seed if src is not None else None,
            scenario=self.config.scenario,
            default_state=src.default_state if src is not None else None,
        )

    def economy(self) -> s.Economy | None:
        from .builder import _ECONOMY_FIELDS

        current = self.config.economy
        baseline = FinancialConfig(scenario=self.config.scenario).economy
        values: dict[str, Any] = {}
        if current.mode != baseline.mode:
            values["mode"] = current.mode
        for spec_name, config_name in _ECONOMY_FIELDS.items():
            if getattr(current, config_name) != getattr(baseline, config_name):
                values[spec_name] = getattr(current, config_name)
        # Paths merge into the scenario's per year, so only the differing (rate, year) entries are emitted.
        names = {v: k for k, v in _ECONOMY_FIELDS.items()}
        paths: dict[str, dict[int, float]] = {}
        for rate, years in current.paths.items():
            base_years = baseline.paths.get(rate, {})
            changed = {year: value for year, value in years.items() if base_years.get(year) != value}
            if changed and rate in names:
                paths[names[rate]] = changed
        if paths:
            values["paths"] = paths
        stochastic = {}
        for name in type(current.stochastic).model_fields:
            if getattr(current.stochastic, name) != getattr(baseline.stochastic, name):
                key = name if name.endswith("correlation") else f"{name}_pct"
                stochastic[key] = getattr(current.stochastic, name)
        if stochastic:
            values["stochastic"] = s.StochasticEconomy(**stochastic)
        return s.Economy(**values) if values else None

    def person(self, person) -> s.Person:
        pid = self.pid(person)
        mortality, death_age = person.mortality_mode.value, person.death_age
        for record in self.build_time:
            event = record["event"]
            if event.action == "die" and event.person == pid:
                mortality = record["previous"]["mortality"].value
                death_age = record["previous"]["death_age"]
        default_state = self.source_meta.default_state if self.source_meta is not None else None
        jobs, job_ids = self.jobs(person)
        referenced = {id(plan.beneficiary) for plan in person.plan_529s if plan.beneficiary is not None}
        children = [
            s.Child(
                id=self.item_id(c, f"{pid}_child{i + 1}" if id(c) in referenced else None),
                name=c.name,
                birth_year=c.birth_year,
            )
            for i, c in enumerate(person.children)
        ]
        return s.Person(
            id=pid,
            name=person.name,
            age=person.age,
            gender=person.gender.value,
            retirement_age=person.retirement_age,
            state=None if person.state == default_state else person.state,
            mortality=mortality,
            death_age=death_age,
            spending=s.Spending(
                amount_annual=person.spending.base, growth_pct=_growth(person.spending._yearly_increase_override)
            ),
            jobs=jobs,
            accounts=_sorted(self.accounts(person, job_ids), ACCOUNT_KIND_ORDER),
            debts=_sorted(self.debts(person), DEBT_KIND_ORDER),
            housing=_sorted(self.housing(person), HOUSING_KIND_ORDER),
            insurance=_sorted(self.insurance(person), INSURANCE_KIND_ORDER),
            social_security=self.social_security(person, pid),
            healthcare=self.healthcare(person),
            giving=_sorted(self.giving(person)),
            children=_sorted(children),
        )

    # --- jobs ---

    def jobs(self, person) -> tuple[list[s.Job], dict[int, str]]:
        jobs, ids = [], {}
        active = [job for job in person.jobs if not job.retired]
        for index, job in enumerate(active):
            needs_id = job.retirement_account is not None
            job_id = self.item_id(job, f"{self.pid(person)}_job{index + 1}" if needs_id else None)
            if job_id is not None:
                ids[job.unique_id] = job_id
            jobs.append(
                s.Job(
                    id=job_id,
                    company=job.company,
                    role=job.role,
                    salary_annual=job.salary.base,
                    raise_pct=_growth(job.salary._yearly_increase_override),
                    bonus_pct=job.salary.yearly_bonus,
                    stock_plan=self.stock_plan(job.stock_plan) if job.stock_plan is not None else None,
                )
            )
        return _sorted(jobs), ids

    def stock_plan(self, plan) -> s.StockPlan:
        from ..work.stock import VestingSchedule

        equity = self.config.equity_comp
        default = VestingSchedule.from_name(equity.default_schedule, equity.default_vesting_years)
        schedule = _none_if(_pcts(plan.schedule), _pcts(default))
        signon_schedule = _pcts(plan.signon_schedule)
        signon = 0.0
        if self.model.year == plan.start_year and plan.grants:
            signon = plan.grants[0].value_at_grant
        return s.StockPlan(
            signon_value=signon,
            refresher_value=plan.refresher_value,
            refresher_start_year=plan.refresher_start_year,
            refresher_growth_pct=plan.refresher_growth_percent,
            vesting_schedule_pct=schedule,
            signon_vesting_schedule_pct=None if signon_schedule == _pcts(plan.schedule) else signon_schedule,
            disposition=plan.disposition,
            growth_pct=_growth(plan._growth_rate_override),
        )

    # --- accounts ---

    def accounts(self, person, job_ids: dict[int, str]) -> list:
        from ..account.inherited import InheritedPretaxAccount
        from ..insurance.annuity import AnnuityType

        cfg = self.config
        out: list = []
        banks = person.bank_accounts
        for index, bank in enumerate(banks):
            out.append(
                s.BankAccount(
                    kind="bank",
                    id=self.item_id(bank),
                    company=bank.company,
                    type=bank.type,
                    balance=bank.balance,
                    interest_pct=_growth(bank._interest_rate_override),
                    primary=getattr(bank, "spec_primary", False)
                    if self.spec_built
                    else (index == 0 and len(banks) > 1),
                )
            )
        for account in person.all_retirement_accounts:
            job = account.job
            out.append(
                s.Job401k(
                    kind="401k",
                    id=self.item_id(account),
                    job=job_ids.get(job.unique_id) if job is not None else None,
                    pretax_balance=account.pretax_balance,
                    roth_balance=account.roth_balance,
                    pretax_contrib_pct=account.pretax_contrib_percent,
                    roth_contrib_pct=account.roth_contrib_percent,
                    growth_pct=_growth(account._growth_rate_override),
                    company_match_pct=account.company_match_percent,
                )
            )
        for account in person.brokerage_accounts:
            lots = account.lots
            if not lots:
                balance, spec_lots = None, None
            elif len(lots) == 1 and lots[0].value == lots[0].cost_basis and lots[0].acquired_year == self.start:
                balance, spec_lots = lots[0].value, None
            else:
                balance = None
                spec_lots = [
                    s.TaxLot(value=lot.value, cost_basis=lot.cost_basis, acquired_year=lot.acquired_year)
                    for lot in lots
                ]
            out.append(
                s.BrokerageAccount(
                    kind="brokerage",
                    id=self.item_id(account),
                    company=account.company,
                    balance=balance,
                    lots=spec_lots,
                    growth_pct=_growth(account._growth_rate_override),
                    dividend_yield_pct=account._dividend_yield_override,
                )
            )
        for account in person.traditional_iras:
            out.append(
                s.TraditionalIRA(
                    kind="traditional_ira",
                    id=self.item_id(account),
                    balance=account.balance,
                    growth_pct=_growth(account._growth_rate_override),
                    contribution_limit_annual=account._contribution_limit_override,
                )
            )
        for account in person.roth_iras:
            out.append(
                s.RothIRA(
                    kind="roth_ira",
                    id=self.item_id(account),
                    balance=account.balance,
                    growth_pct=_growth(account._growth_rate_override),
                    contribution_limit_annual=account._contribution_limit_override,
                )
            )
        for account in person.hsas:
            out.append(
                s.HealthSavingsAccount(
                    kind="hsa",
                    id=self.item_id(account),
                    coverage="family" if account.hsa_type.name == "FAMILY" else "individual",
                    balance=account.balance,
                    growth_pct=_growth(account._growth_rate_override),
                    employer_contribution_annual=_none_if(
                        account.employer_contribution, cfg.accounts.hsa.default_employer_contribution
                    ),
                    contribution_limit_annual=account._contribution_limit_override,
                )
            )
        for agent in self.model.agents:
            if isinstance(agent, InheritedPretaxAccount) and agent.person is person:
                out.append(
                    s.InheritedPretaxAccount(
                        kind="inherited_pretax",
                        id=self.item_id(agent),
                        balance=agent.balance,
                        decedent_name=agent.decedent_name,
                        years=agent.years_remaining,
                    )
                )
        for pension in person.pensions:
            formula = pension.benefit_multiplier is not None
            out.append(
                s.Pension(
                    kind="pension",
                    id=self.item_id(pension),
                    company=pension.company,
                    vesting_years=pension.vesting_years,
                    benefit_annual=0.0 if formula else pension.benefit_amount,
                    start_age=pension.start_age,
                    cola_pct=pension.cola_percent,
                    survivor_pct=pension.survivor_percent,
                    years_of_service=_none_if(pension.years_of_service, pension.vesting_years),
                    benefit_multiplier_pct=pension.benefit_multiplier,
                    final_salary_annual=pension.final_salary,
                )
            )
        annuity_cfg = cfg.insurance.annuity
        for annuity in self.model.registries.annuities.get_items(person):
            deferred = annuity.annuity_type == AnnuityType.DEFERRED
            default_start = annuity_cfg.default_payout_start_age if deferred else person.age
            out.append(
                s.Annuity(
                    kind="annuity",
                    id=self.item_id(annuity),
                    annuity_type=annuity.annuity_type.name.lower(),
                    balance=annuity.balance,
                    interest_pct=_none_if(annuity.interest_rate, annuity_cfg.default_interest_rate),
                    payout_type=annuity.payout_type.name.lower(),
                    payout_start_age=_none_if(annuity.payout_start_age, default_start),
                    payout_monthly=annuity.monthly_payout,
                    period_certain_years=_none_if(
                        annuity.period_certain_years, annuity_cfg.default_period_certain_years
                    ),
                    surrender_charge_years=_none_if(
                        annuity.surrender_charge_years, annuity_cfg.default_surrender_charge_years
                    ),
                    surrender_charge_pct=_none_if(
                        annuity.surrender_charge_rate, annuity_cfg.default_surrender_charge_rate
                    ),
                    joint_annuitant=self.pid(annuity.joint_annuitant) if annuity.joint_annuitant is not None else None,
                    survivor_pct=annuity.survivor_percent,
                )
            )
        for daf in person.donor_advised_funds:
            out.append(
                s.DonorAdvisedFund(
                    kind="daf",
                    id=self.item_id(daf),
                    name=daf.fund_name,
                    balance=daf.balance,
                    growth_pct=daf.growth_rate,
                    management_fee_pct=daf.management_fee,
                    distribution_pct=daf.distribution_rate,
                )
            )
        for trust in person.trusts:
            out.append(
                s.Trust(
                    kind="trust",
                    id=self.item_id(trust),
                    trust_type=trust.trust_type.value,
                    beneficiaries=[self.pid(b) for b in trust.beneficiaries if b.unique_id in self.person_ids],
                    name=trust.name,
                    balance=trust.balance,
                    growth_pct=_growth(trust._growth_rate_override),
                    asset_class=trust.asset_class,
                )
            )
        plan_cfg = cfg.accounts.plan_529
        for index, plan in enumerate(person.plan_529s):
            beneficiary = None
            if plan.beneficiary is not None:
                beneficiary = getattr(plan.beneficiary, "spec_id", None) or self.item_ids.get(id(plan.beneficiary))
            out.append(
                s.Plan529(
                    kind="529",
                    id=self.item_id(plan),
                    beneficiary=beneficiary,
                    balance=plan.balance,
                    plan_state=plan.state,
                    growth_pct=_growth(plan._growth_rate_override),
                    contribution_limit_annual=_none_if(
                        plan.annual_contribution_limit, plan_cfg.annual_contribution_limit
                    ),
                    lifetime_contribution_limit=_none_if(
                        plan.lifetime_contribution_limit, plan_cfg.lifetime_contribution_limit
                    ),
                )
            )
        return out

    # --- debts, housing, insurance ---

    def debts(self, person) -> list:
        out: list = []
        for loan in person.car_loans:
            out.append(
                s.CarLoan(
                    kind="car",
                    id=self.item_id(loan),
                    name=loan.name,
                    original_amount=loan.loan_amount,
                    balance=_none_if(loan.principal, loan.loan_amount),
                    rate_pct=loan.yearly_interest_rate,
                    term_years=loan.length_years,
                    payment_monthly=_none_if(loan.monthly_payment, loan.calculate_monthly_payment()),
                )
            )
        for loan in person.student_loans:
            out.append(
                s.StudentLoan(
                    kind="student",
                    id=self.item_id(loan),
                    loan_type=loan.loan_type.name.lower(),
                    school=loan.school_name,
                    original_amount=loan.loan_amount,
                    balance=_none_if(loan.principal, loan.loan_amount),
                    rate_pct=loan.yearly_interest_rate,
                    term_years=loan.length_years,
                    payment_monthly=_none_if(loan.monthly_payment, loan.calculate_monthly_payment()),
                    in_deferment=loan.in_deferment,
                    repayment_plan=loan.repayment_plan.name.lower(),
                )
            )
        debt_cfg = self.config.debt.credit_card
        for card in person.credit_cards:
            out.append(
                s.CreditCard(
                    kind="credit_card",
                    id=self.item_id(card),
                    name=getattr(card, "card_name", card.name),
                    credit_limit=card.credit_limit,
                    balance=card.balance,
                    rate_pct=_none_if(card.yearly_interest_rate, debt_cfg.default_interest_rate),
                    minimum_payment_pct=_none_if(
                        card.minimum_payment_percent, debt_cfg.default_minimum_payment_percent
                    ),
                    card_type=card.card_type.name.lower() if getattr(card, "card_type", None) is not None else None,
                    payment_strategy=card.payment_strategy.value,
                    payment_monthly=card.fixed_payment,
                )
            )
        return out

    def housing(self, person) -> list:
        out: list = []
        start = self.start
        for home in person.homes:
            mortgage = None
            if home.mortgage is not None:
                m = home.mortgage
                mortgage = s.Mortgage(
                    original_amount=m.loan_amount,
                    balance=_none_if(m.principal, m.loan_amount),
                    rate_pct=m.yearly_interest_rate,
                    term_years=m.length_years,
                    start_year=_none_if(int(m.start_date), start),
                    payment_monthly=_none_if(m.monthly_payment, m.calculate_monthly_payment()),
                )
            e = home.expenses
            out.append(
                s.Home(
                    kind="home",
                    id=self.item_id(home),
                    name=home.name,
                    purchase_price=home.purchase_price,
                    value_growth_pct=_growth(home._value_yearly_increase_override),
                    down_payment=home.down_payment,
                    mortgage=mortgage,
                    expenses=s.HomeExpenses(
                        property_tax_pct=e.property_tax_percent,
                        insurance_pct=e.home_insurance_percent,
                        maintenance_annual=e.maintenance_amount,
                        maintenance_growth_pct=e.maintenance_increase,
                        improvement_annual=e.improvement_amount,
                        improvement_growth_pct=e.improvement_increase,
                        hoa_monthly=e.hoa_amount / 12,
                        hoa_growth_pct=e.hoa_increase,
                    ),
                )
            )
        for apartment in person.apartments:
            out.append(
                s.Rental(
                    kind="rental",
                    id=self.item_id(apartment),
                    name=apartment.name,
                    rent_monthly=apartment.monthly_rent,
                    rent_growth_pct=_growth(apartment._yearly_increase_override),
                )
            )
        return out

    def insurance(self, person) -> list:
        from ..insurance.life_insurance import LifeInsuranceType, PremiumIncreaseType

        out: list = []
        life_cfg = self.config.insurance.life
        for policy in person.life_insurance_policies:
            whole = policy.policy_type == LifeInsuranceType.WHOLE
            if policy.premium_increase_type == PremiumIncreaseType.YEARLY:
                schedule, increase = "yearly_increase", policy.yearly_increase_rate
            elif whole or not policy.age_multipliers:
                schedule, increase = "level", None
            else:
                schedule, increase = "age_banded", None
            out.append(
                s.LifeInsurance(
                    kind="life",
                    id=self.item_id(policy),
                    policy="whole" if whole else "term",
                    death_benefit=policy.death_benefit,
                    premium_monthly=policy.base_monthly_premium,
                    term_years=policy.term_years,
                    premium_schedule=cast(Any, schedule),
                    premium_increase_pct=increase,
                    cash_value_growth_pct=_none_if(
                        policy.cash_value_growth_rate, life_cfg.default_cash_value_growth_rate
                    ),
                    loan_interest_pct=_none_if(policy.loan_interest_rate, life_cfg.default_loan_interest_rate),
                    max_missed_payments=_none_if(policy.max_missed_payments, life_cfg.default_max_missed_payments),
                    beneficiary=self.pid(policy.beneficiary) if policy.beneficiary is not None else None,
                )
            )
        general_cfg = self.config.insurance.general
        for policy in self.model.registries.general_insurance_policies.get_items(person):
            kind = "ltc" if policy.insurance_type.name == "LONG_TERM_CARE" else policy.insurance_type.name.lower()
            out.append(
                s.GeneralInsurance(
                    kind=cast(Any, kind),
                    id=self.item_id(policy),
                    company=policy.company,
                    premium_annual=policy.base_annual_premium,
                    coverage_amount=policy.coverage_amount,
                    deductible=policy.deductible,
                    coverage_start_age=_none_if(policy.coverage_start_age, person.age),
                    coverage_end_age=policy.coverage_end_age,
                    premium_increase_pct=_none_if(
                        policy.premium_increase_rate, general_cfg.default_premium_increase_rate
                    ),
                    max_claims_per_year=_none_if(policy.max_claims_per_year, general_cfg.default_max_claims_per_year),
                )
            )
        return out

    # --- SS, healthcare, giving ---

    def social_security(self, person, pid: str) -> s.SocialSecurity | None:
        ss = person.social_security
        if ss is None:
            return None
        claim = ss.withdrawal_start_age
        for record in self.build_time:
            event = record["event"]
            if event.action == "claim_social_security" and event.person == pid:
                claim = record["previous"]["claim_age"]
        synthesized = getattr(ss, "spec_synthesized_history", None)
        if synthesized is not None and len(ss.income_history) == synthesized[1]:
            return s.SocialSecurity(claim_age=claim, assumed_career_start_age=synthesized[0])
        history = {income.year: income.amount for income in ss.income_history}
        return s.SocialSecurity(claim_age=claim, earnings_history=history or None)

    def healthcare(self, person) -> s.Healthcare | None:
        flags = s.Healthcare(
            medical_costs=bool(person.medical_costs),
            medicare=bool(person.medicare),
            long_term_care=bool(person.long_term_care),
        )
        return flags if (flags.medical_costs or flags.medicare or flags.long_term_care) else None

    def giving(self, person) -> list:
        return [
            s.Donation(
                kind="donation",
                id=self.item_id(d),
                charity=d.charity_name,
                amount_annual=d.annual_amount,
                donation_type=d.donation_type.name.lower(),
                tax_deductible=d.tax_deductible,
                frequency_years=d.frequency_years,
                start_year=d.start_year if d.start_year > self.start else None,
                end_year=_none_if(d.end_year, self.model.end_year),
            )
            for d in person.donations
        ]

    # --- relationships and events ---

    def relationships(self, people) -> s.Relationships:
        from ..tax.federal import FilingStatus

        marriages, seen = [], set()
        for person in people:
            spouse = person.spouse
            if (
                spouse is None
                or spouse.is_deceased
                or person.unique_id in seen
                or spouse.unique_id not in self.person_ids
            ):
                continue
            seen.update({person.unique_id, spouse.unique_id})
            separate = person.filing_status == FilingStatus.MARRIED_FILING_SEPARATELY
            marriages.append(
                s.Marriage(
                    spouses=(self.pid(person), self.pid(spouse)), filing_status="separate" if separate else "joint"
                )
            )
        for source in self.pending_sources():
            if isinstance(source, s.Marriage):
                marriages.append(source)
        return s.Relationships(marriages=marriages)

    def pending_sources(self) -> list:
        """The spec entries behind the not-yet-fired ``LifeEvent`` objects.

        Before the first step they are returned as written. Afterwards an event is re-timed to its
        remaining years (``at: {year}``, and ``until`` for a recurring expense), because its anchors
        or earlier years may already have fired.
        """
        from ..lifeevents import LifeEvents

        years: dict[int, list[int]] = {}
        sources: list = []
        for agent in self.model.agents:
            if isinstance(agent, LifeEvents):
                for life_event in agent.life_events:
                    source = getattr(life_event, "spec_source", None)
                    if source is None:
                        continue
                    if id(source) not in years:
                        years[id(source)] = []
                        sources.append(source)
                    years[id(source)].append(life_event.year)
        if not self.stepped:
            return sources
        retimed = []
        for source in sources:
            pending = years[id(source)]
            if isinstance(source, s.Marriage):
                retimed.append(source.model_copy(update={"year": min(pending)}))
                continue
            update: dict[str, Any] = {"at": s.At(year=min(pending))}
            if isinstance(source, s.RecurringExpenseEvent):
                update["until"] = s.At(year=max(pending))
            retimed.append(source.model_copy(update=update))
        return retimed

    def events(self) -> list:
        events = [source for source in self.pending_sources() if not isinstance(source, s.Marriage)]
        events += [record["event"] for record in self.build_time]
        return _sorted(events)


def spec_from_model(model) -> s.HouseholdSpec:
    """Read a :class:`~life_model.spec.schema.HouseholdSpec` off ``model`` (see the module docstring)."""
    return _Extractor(model).run()
