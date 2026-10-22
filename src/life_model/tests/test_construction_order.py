# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Construction order does not change the simulation.

Each household below is described as a list of construction steps (each step builds one agent, or
a group that must be built together, such as a job and its 401k). The same household is built in
the declared order and in five seeded random permutations of the steps (people first, in a
shuffled order too), and the collected model frames must match. Agent execution order follows
``STEP_PRIORITY`` then construction order, so a failure here means two agents in the same stage
and priority depend on each other's effects.
"""

import random
import unittest
from typing import Any

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount
from ..account.hsa import HealthSavingsAccount, HSAType
from ..account.job401k import Job401kAccount
from ..account.pension import Pension
from ..account.roth_IRA import RothIRA
from ..account.traditional_IRA import TraditionalIRA
from ..charity.donation import Donation
from ..debt.car_loan import CarLoan
from ..dependents.child import Child
from ..healthcare.medical_costs import MedicalCosts
from ..healthcare.medicare import Medicare
from ..housing.apartment import Apartment
from ..housing.home import Home, HomeExpenses, Mortgage
from ..insurance.annuity import Annuity, AnnuityType
from ..insurance.life_insurance import LifeInsurance, LifeInsuranceType
from ..insurance.social_security import SocialSecurity
from ..lifeevents import LifeEvent, LifeEvents
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..work.job import Job, Salary
from ..work.stock import StockPlan

SHUFFLE_SEEDS = (1, 2, 3, 4, 5)
_HISTORY = [(year, 70000) for year in range(1985, 2025)]


def _home(person, price=500000, loan=400000):
    model = person.model
    mortgage = Mortgage(original_amount=loan, start_year=2022, term_years=30, rate_pct=6.0)
    expenses = HomeExpenses(model, 1.1, 0.4, 3000, 3.0, 1000, 3.0, 0, 0.0)
    Home(person, "Home", price, None, price - loan, mortgage, expenses)


def single_saver(model):
    """A single renter in their thirties: wages, 401k with a tiered match, RSUs, brokerage,
    Roth IRA, HSA, term life, a car loan, a donation and a scheduled car purchase."""
    family = Family(model)
    people = {}

    def person():
        people["a"] = Person(family, "Sam", age=34, retirement_age=62, spending=Spending(model, base_annual=45000))

    def job():
        job = Job(
            people["a"], company="Co", role="Eng", salary=Salary(model, base_annual=140000, raise_pct=3, bonus_pct=10)
        )
        Job401kAccount(job=job, pretax_contrib_pct=10, match_tiers=[(100, 3), (50, 2)], pretax_balance=60000)
        StockPlan(job, signon_value=40000, refresher_value=20000)

    steps = [
        lambda: BankAccount(people["a"], company="Bank", balance=25000, interest_pct=3.5),
        job,
        lambda: BrokerageAccount(people["a"], company="Broker", balance=80000),
        lambda: RothIRA(people["a"], balance=30000),
        lambda: HealthSavingsAccount(people["a"], hsa_type=HSAType.INDIVIDUAL, balance=5000),
        lambda: Apartment(people["a"], "Flat", rent_monthly=2200, rent_growth_pct=4),
        lambda: LifeInsurance(people["a"], LifeInsuranceType.TERM, 500000, 40, term_years=20),
        lambda: CarLoan(people["a"], original_amount=30000, term_years=5, rate_pct=6.5, name="Car"),
        lambda: Donation(people["a"], "Food bank", 2000),
        lambda: LifeEvents(model, [LifeEvent(2029, "New car", people["a"].spending.add_expense, 35000)]),
    ]
    return [person], steps


def married_homeowners(model):
    """A married couple with a mortgage, two jobs, a 401k, brokerage, a child and life insurance."""
    family = Family(model)
    people = {}

    def build(key, name, age, salary, bank):
        def _person():
            people[key] = Person(family, name, age=age, retirement_age=65, spending=Spending(model, base_annual=40000))

        def _accounts():
            BankAccount(people[key], company="Bank", balance=bank, interest_pct=1.0)
            job = Job(
                people[key], company=f"{name} Co", role="Role", salary=Salary(model, base_annual=salary, raise_pct=2.5)
            )
            Job401kAccount(job=job, pretax_contrib_pct=8, match_tiers=[(50, 6)], pretax_balance=bank * 3)

        return _person, _accounts

    a_person, a_accounts = build("a", "Alex", 41, 165000, 40000)
    b_person, b_accounts = build("b", "Blair", 39, 95000, 15000)

    def marry():
        people["a"].get_married(people["b"])

    steps = [
        a_accounts,
        b_accounts,
        marry,
        lambda: _home(people["a"]),
        lambda: BrokerageAccount(people["b"], company="Broker", balance=150000),
        lambda: Child(people["a"], "Kid", birth_year=2019),
        lambda: LifeInsurance(people["a"], LifeInsuranceType.TERM, 1_000_000, 70, term_years=20),
        lambda: LifeInsurance(people["b"], LifeInsuranceType.WHOLE, 250000, 150),
        lambda: MedicalCosts(people["a"]),
    ]
    return [a_person, b_person], steps


def retired_couple(model):
    """A retired couple: Social Security for both, a pension, an immediate annuity, RMD-age IRA and
    401k money, Medicare and medical costs, and a taxable account with embedded gains."""
    family = Family(model)
    people = {}

    def build(key, name, age, retirement_age=62):
        def _person():
            people[key] = Person(
                family, name, age=age, retirement_age=retirement_age, spending=Spending(model, base_annual=45000)
            )

        return _person

    def marry():
        people["a"].get_married(people["b"])

    def old_401k():
        job = Job(people["a"], company="Former", role="Retired", salary=Salary(model, base_annual=0))
        job.retire()
        Job401kAccount(job=job, pretax_balance=600000, roth_balance=50000)

    steps = [
        marry,
        lambda: BankAccount(people["a"], company="Bank", balance=60000, interest_pct=2.0),
        lambda: BankAccount(people["b"], company="Bank", balance=20000, interest_pct=2.0),
        lambda: SocialSecurity(people["a"], claim_age=67, earnings_history=_HISTORY),
        lambda: SocialSecurity(people["b"], claim_age=67, earnings_history=[(y, 40000) for y in range(1990, 2025)]),
        lambda: Pension(people["a"], company="State", vesting_years=5, benefit_annual=18000, cola_pct=2.0),
        lambda: Annuity(people["b"], annuity_type=AnnuityType.IMMEDIATE, balance=150000, rate_pct=4.0),
        lambda: TraditionalIRA(people["b"], balance=250000),
        old_401k,
        lambda: BrokerageAccount(people["a"], company="Broker", balance=300000),
        lambda: Medicare(people["a"]),
        lambda: Medicare(people["b"]),
        lambda: MedicalCosts(people["b"]),
        lambda: Donation(people["b"], "Church", 5000),
        # Part-time wages alongside benefits: provisional income must not depend on whether the job
        # or Social Security books first.
        lambda: Job(people["b"], company="Shop", role="Clerk", salary=Salary(model, base_annual=30000)),
        lambda: LifeInsurance(people["b"], LifeInsuranceType.WHOLE, 100000, 300),
    ]
    return [build("a", "Pat", 74), build("b", "Lee", 71, retirement_age=76)], steps


def early_retiree(model):
    """A 52-year-old early retiree living off brokerage, Roth basis and pre-tax money."""
    family = Family(model)
    people = {}

    def person():
        people["a"] = Person(family, "Jo", age=52, retirement_age=50, spending=Spending(model, base_annual=70000))

    def old_401k():
        job = Job(people["a"], company="Former", role="Retired", salary=Salary(model, base_annual=0))
        job.retire()
        Job401kAccount(job=job, pretax_balance=900000, roth_balance=80000)

    steps = [
        lambda: BankAccount(people["a"], company="Bank", balance=30000, interest_pct=3.0),
        lambda: BrokerageAccount(people["a"], company="Broker", balance=250000),
        lambda: RothIRA(people["a"], balance=120000),
        old_401k,
        lambda: _home(people["a"], price=400000, loan=150000),
        lambda: MedicalCosts(people["a"]),
        lambda: Annuity(people["a"], annuity_type=AnnuityType.FIXED, balance=50000, rate_pct=4.0),
    ]
    return [person], steps


HOUSEHOLDS = {
    "single_saver": single_saver,
    "married_homeowners": married_homeowners,
    "retired_couple": retired_couple,
    "early_retiree": early_retiree,
}


def run_household(builder, seed=None, years=25):
    """Build ``builder``'s household (steps shuffled by ``seed``; None keeps the declared order)."""
    model = LifeModel(start_year=2026, end_year=2026 + years - 1)
    people, steps = builder(model)
    if seed is not None:
        rng = random.Random(seed)
        people = rng.sample(people, len(people))
        # Steps that need another step's agent (marriage needs both people) are declared after the
        # people; everything else is free to move.
        steps = rng.sample(steps, len(steps))
    for step in people:
        step()
    for step in steps:
        step()
    model.run()
    return model.datacollector.get_model_vars_dataframe()


class TestConstructionOrderProperty(unittest.TestCase):
    """Five shuffled constructions of each household give identical frames."""

    def assert_frames_match(self, expected, actual, label):
        self.assertEqual(list(expected.columns), list(actual.columns))
        for column in expected.columns:
            for year, (x, y) in enumerate(zip(expected[column], actual[column])):
                # Summation order differs with construction order, so allow float round-off only.
                self.assertAlmostEqual(
                    float(x), float(y), delta=1e-6 * max(1.0, abs(float(x))), msg=f"{label}: {column} row {year}"
                )

    def test_households_are_construction_order_independent(self):
        for name, builder in HOUSEHOLDS.items():
            baseline = run_household(builder)
            for seed in SHUFFLE_SEEDS:
                with self.subTest(household=name, seed=seed):
                    self.assert_frames_match(baseline, run_household(builder, seed), f"{name} seed {seed}")


# --- The same property over the household-spec examples ------------------------------------


def _spec_example(name: str, years: int = 25):
    from ..spec import canonical, load_example

    spec = canonical(load_example(name))
    meta = spec.meta.model_copy(update={"end_year": spec.meta.start_year + years - 1})
    return spec.model_copy(update={"meta": meta})


def run_spec_shuffled_lists(name: str, seed: int | None):
    """Build an example spec through the builder after shuffling every list in it."""
    import json
    import warnings

    from ..spec import HouseholdSpec, build_model, dumps
    from .test_spec_builder import _shuffled

    data = json.loads(dumps(_spec_example(name), "json"))
    if seed is not None:
        data = _shuffled(data, random.Random(seed))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # SpecWarning too: events past the shortened end year
        model = build_model(HouseholdSpec.model_validate(data))
    model.run()
    assert model.datacollector is not None
    return model.datacollector.get_model_vars_dataframe()


def run_spec_shuffled_construction(name: str, seed: int | None):
    """Construct an example spec's agents directly (the builder's per-item core calls) in shuffled order.

    Steps are grouped only where core needs one agent before another: a job with its 401k, stock plan
    and sponsored pensions; a child with the 529s naming it; a person's bank accounts in their
    primary-first order (``bank_accounts[0]`` receives income by definition, not by accident).
    """
    import warnings

    from ..dependents.child import Child
    from ..healthcare import LongTermCare, MedicalCosts, Medicare
    from ..lifeevents import LifeEvents as _LifeEvents
    from ..spec import create_model
    from ..spec import events as ev
    from ..spec.builder import _Builder

    spec = _spec_example(name)
    model = create_model(spec)
    builder = _Builder(model, spec)
    people_steps: list[Any] = [lambda p=p: builder.build_person(p) for p in spec.people]
    steps: list[Any] = []
    for p in spec.people:

        def person(p=p):
            return builder.person(p.id)

        def register(collection, index, item, agent, p=p):
            builder._register(p, collection, index, item, agent)

        banks = [(i, a) for i, a in enumerate(p.accounts) if a.kind == "bank"]
        steps.append(
            lambda p=p, banks=banks: [
                register("accounts", i, a, builder.build_account(person(p), p, a)) for i, a in banks
            ]
        )
        for j, job in enumerate(p.jobs):

            def job_group(p=p, j=j, job=job):
                agent = builder.build_job(person(p), job)
                register("jobs", j, job, agent)
                for i, a in enumerate(p.accounts):
                    if (a.kind == "401k" and a.job == job.id) or (a.kind == "pension" and a.job == job.id and job.id):
                        register("accounts", i, a, builder.build_account(person(p), p, a))
                if job.stock_plan is not None:
                    builder.build_stock_plan(agent, job.stock_plan)

            steps.append(job_group)
        for i, a in enumerate(p.accounts):
            if a.kind in ("bank", "401k", "529") or (a.kind == "pension" and a.job is not None):
                continue
            steps.append(lambda p=p, i=i, a=a: register("accounts", i, a, builder.build_account(person(p), p, a)))
        for collection, build in (
            ("debts", builder.build_debt),
            ("housing", builder.build_housing),
            ("insurance", builder.build_insurance),
            ("giving", builder.build_donation),
        ):
            for i, item in enumerate(getattr(p, collection)):
                steps.append(
                    lambda p=p, i=i, item=item, c=collection, b=build: register(c, i, item, b(person(p), item))
                )
        for i, child in enumerate(p.children):

            def child_group(p=p, i=i, child=child):
                register("children", i, child, Child(person(p), child.name, child.birth_year))
                for k, a in enumerate(p.accounts):
                    if a.kind == "529" and a.beneficiary == child.id:
                        register("accounts", k, a, builder.build_account(person(p), p, a))

            steps.append(child_group)
        if p.healthcare is not None:
            hc = p.healthcare
            for flag, cls in (
                (hc.medical_costs, MedicalCosts),
                (hc.medicare, Medicare),
                (hc.long_term_care, LongTermCare),
            ):
                if flag:
                    steps.append(lambda p=p, cls=cls: cls(person(p)))
    for marriage in spec.relationships.marriages:
        if marriage.year is None or marriage.year <= model.start_year:
            head, spouse = marriage.spouses
            steps.append(
                lambda m=marriage, h=head, w=spouse: builder.marry(
                    builder.person(h), builder.person(w), m.filing_status
                )
            )

    def social_security_and_events():
        timing = ev.EventTiming(builder)
        claims = ev.apply_build_time_events(builder, timing)
        for p in spec.people:
            if p.social_security is not None:
                claim = claims.get(p.id, p.social_security.claim_age)
                builder.build_social_security(builder.person(p.id), p, claim)
        return timing

    if seed is not None:
        # People keep the spec's order here because stochastic mortality draws follow it (RNG
        # consumption order). Which spouse heads the unit does not matter for the money: see
        # TestHeadOfUnitIndependence.
        steps = random.Random(seed).sample(steps, len(steps))
    for step in people_steps:
        step()
    for step in steps:
        step()
    # Social Security needs the build-time claim/death events (resolved from every person's age) and
    # the event schedule references built items, so these two come last, as in the builder.
    timing = social_security_and_events()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        life_events = ev.compile_events(builder, timing)
        if life_events:
            _LifeEvents(model, life_events)
    model.run()
    assert model.datacollector is not None
    return model.datacollector.get_model_vars_dataframe()


SPEC_EXAMPLES = ("married_homeowners", "single_renter", "retiree_couple")


class TestSpecExampleConstructionOrder(unittest.TestCase):
    """The construction-order property over every buildable household-spec example."""

    assert_frames_match = TestConstructionOrderProperty.assert_frames_match

    def test_shuffled_spec_lists(self):
        for name in SPEC_EXAMPLES:
            baseline = run_spec_shuffled_lists(name, None)
            for seed in SHUFFLE_SEEDS:
                with self.subTest(example=name, seed=seed):
                    self.assert_frames_match(baseline, run_spec_shuffled_lists(name, seed), f"{name} seed {seed}")

    def test_shuffled_direct_construction(self):
        for name in SPEC_EXAMPLES:
            baseline = run_spec_shuffled_lists(name, None)
            self.assert_frames_match(baseline, run_spec_shuffled_construction(name, None), f"{name} declared")
            for seed in SHUFFLE_SEEDS:
                with self.subTest(example=name, seed=seed):
                    self.assert_frames_match(
                        baseline, run_spec_shuffled_construction(name, seed), f"{name} seed {seed}"
                    )


def _head_swap_spec(name: str, swap: bool, years: int = 50):
    """An example spec (deaths made deterministic, so no RNG draw depends on people order) with the
    spouses of every marriage, and the people list, in declared or reversed order."""
    spec = _spec_example(name, years)
    people = [
        p.model_copy(update={"mortality": "fixed_age", "death_age": 84 + 3 * i}) if p.mortality == "stochastic" else p
        for i, p in enumerate(spec.people)
    ]
    marriages = spec.relationships.marriages
    if swap:
        people = list(reversed(people))
        marriages = [m.model_copy(update={"spouses": list(reversed(m.spouses))}) for m in marriages]
    relationships = spec.relationships.model_copy(update={"marriages": marriages})
    return spec.model_copy(update={"people": people, "relationships": relationships})


class TestHeadOfUnitIndependence(unittest.TestCase):
    """Which spouse is listed first (and so heads the joint tax unit) does not change the money.

    The household waterfall draws the unit's bank accounts lowest-yield first and its other sources
    in a canonical member order, refunds land in the highest-yield bank, and the return is the
    unit's; so with same-state spouses and different bank rates the model totals are identical.
    """

    assert_frames_match = TestConstructionOrderProperty.assert_frames_match

    def test_swapping_the_head_spouse(self):
        import warnings

        from ..spec import build_model

        for name in ("married_homeowners", "retiree_couple"):
            with self.subTest(example=name):
                frames = []
                for swap in (False, True):
                    spec = _head_swap_spec(name, swap)
                    states = {p.state for p in spec.people}
                    self.assertEqual(len(states), 1, "the unit files in the head's state: keep spouses in one state")
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", UserWarning)
                        model = build_model(spec)
                    model.run()
                    frames.append(model.datacollector.get_model_vars_dataframe())
                self.assert_frames_match(frames[0], frames[1], f"{name} head swapped")

    def test_banks_with_different_rates_are_drawn_lowest_yield_first(self):
        from ..spec import build_model, load_example

        model = build_model(load_example("married_homeowners"))
        from ..people.tax_unit import TaxUnit

        (family,) = [a for a in model.agents if type(a).__name__ == "Family"]
        (unit,) = TaxUnit.build_units(family)
        rates = [account.interest_rate for account in unit._bank_accounts_in_draw_order()]
        self.assertEqual(rates, sorted(rates))
        self.assertGreater(len(set(rates)), 1)


if __name__ == "__main__":
    unittest.main()
