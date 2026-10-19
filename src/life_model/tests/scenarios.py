# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Whole-household scenarios shared by the explainable-output tests (ledger, tax returns, events, exports).

Each builder returns a ready-to-run :class:`~life_model.model.LifeModel`. They are deliberately
broad (many agent types, decades long) because the tax-return reconciliation and money-conservation
checks are only as good as the code paths they exercise.
"""

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount
from ..account.hsa import HealthSavingsAccount, HSAType
from ..account.job401k import Job401kAccount
from ..account.pension import Pension
from ..account.roth_IRA import RothIRA
from ..account.traditional_IRA import TraditionalIRA
from ..charity.daf import DonorAdvisedFund
from ..charity.donation import Donation
from ..config.financial_config import FinancialConfig
from ..debt.car_loan import CarLoan
from ..debt.credit_card import CreditCard
from ..debt.student_loan import StudentLoan, StudentLoanType
from ..dependents.plan529 import Plan529
from ..estate.trust import Trust, TrustType
from ..healthcare.long_term_care import LongTermCare
from ..healthcare.medical_costs import MedicalCosts
from ..healthcare.medicare import Medicare
from ..housing.apartment import Apartment
from ..housing.home import Home, HomeExpenses, Mortgage
from ..insurance.annuity import Annuity, AnnuityPayoutType, AnnuityType
from ..insurance.general_insurance import Insurance, InsuranceType
from ..insurance.life_insurance import LifeInsurance, LifeInsuranceType
from ..insurance.social_security import SocialSecurity
from ..lifeevents import LifeEvent, LifeEvents
from ..model import LifeModel
from ..people.family import Family
from ..people.person import MortalityMode, Person, Spending
from ..people.types import GenderAtBirth
from ..work.job import Job, Salary
from ..work.stock import StockPlan

#: An earnings record long enough to qualify for benefits.
EARNINGS_HISTORY = [(year, 40000 + 1500 * (year - 1995)) for year in range(1995, 2026)]


def _stochastic_config() -> FinancialConfig:
    config = FinancialConfig()
    config.apply_scenario("stochastic", {"economy": {"mode": "stochastic"}})
    return config


def _home(model: LifeModel, owner: Person, *, price: float, principal: float, purchase: bool = False) -> Home:
    return Home(
        owner=owner,
        name=f"{owner.name}'s house",
        purchase_price=price,
        value_growth_pct=None,
        down_payment=price - principal,
        mortgage=Mortgage(original_amount=principal, start_year=model.year, term_years=30, rate_pct=6.0),
        expenses=HomeExpenses(
            model,
            property_tax_pct=1.1,
            insurance_pct=0.4,
            maintenance_annual=2500,
            maintenance_growth_pct=3,
            improvement_annual=1000,
            improvement_growth_pct=3,
            hoa_annual=600,
            hoa_growth_pct=2,
        ),
        purchase=purchase,
    )


def married_homeowners(start_year: int = 2026, years: int = 45, *, seed: int | None = 1) -> LifeModel:
    """A married couple with two kids, two jobs with 401k matches, a mortgage, a brokerage account,
    IRAs, an HSA, Social Security, and a car loan; one retires early and draws on savings."""
    model = LifeModel(start_year=start_year, end_year=start_year + years - 1, seed=seed)
    family = Family(model)
    john = Person(family, "John", 42, 58, Spending(model, base_annual=52000, growth_pct=None), state="CA")
    jane = Person(family, "Jane", 40, 62, Spending(model, base_annual=30000, growth_pct=None), state="CA")
    john.get_married(jane)
    BankAccount(john, company="Chase", balance=40000, interest_pct=2.0)
    BankAccount(jane, company="Ally", balance=25000, interest_pct=3.5)
    BrokerageAccount(john, company="Vanguard", balance=150000)
    acme = Job(
        john, company="Acme", role="Engineer", salary=Salary(model, base_annual=165000, raise_pct=None, bonus_pct=8)
    )
    Job401kAccount(
        acme,
        pretax_balance=220000,
        pretax_contrib_pct=10,
        roth_balance=30000,
        roth_contrib_pct=4,
        match_tiers=[(100, 3), (50, 2)],
    )
    clinic = Job(jane, company="Clinic", role="Nurse", salary=Salary(model, base_annual=92000, raise_pct=None))
    Job401kAccount(clinic, pretax_balance=90000, pretax_contrib_pct=6, match_tiers=[(50, 6)])
    TraditionalIRA(jane, balance=45000)
    RothIRA(john, balance=38000)
    HealthSavingsAccount(jane, hsa_type=HSAType.FAMILY, balance=12000)
    _home(model, john, price=780000, principal=520000)
    CarLoan(john, original_amount=32000, term_years=5, rate_pct=6.5, name="SUV")
    ava = john.add_child("Ava", birth_year=start_year - 8)
    Plan529(john, beneficiary=ava, balance=40000)
    jane.add_child("Ben", birth_year=start_year - 5)
    SocialSecurity(john, claim_age=67, earnings_history=EARNINGS_HISTORY)
    SocialSecurity(jane, claim_age=67, earnings_history=EARNINGS_HISTORY[5:])
    if start_year + 6 <= model.end_year:
        LifeEvents(model, [LifeEvent(start_year + 6, "Kitchen remodel", john.spending.add_expense, 45000)])
    return model


def stochastic_retiree(seed: int, start_year: int = 2026, years: int = 40) -> LifeModel:
    """A single retiree under the stochastic economy: Social Security, RMDs from a 401k and IRA,
    a brokerage account sold to fund spending, healthcare costs, Medicare and long-term care."""
    model = LifeModel(start_year=start_year, end_year=start_year + years - 1, seed=seed, config=_stochastic_config())
    family = Family(model)
    ann = Person(
        family, "Ann", 66, 65, Spending(model, base_annual=58000, growth_pct=None), gender=GenderAtBirth.FEMALE
    )
    BankAccount(ann, company="Bank", balance=60000)
    BrokerageAccount(ann, company="Brokerage", balance=650000)
    job = Job(ann, company="Former employer", role="Retired", salary=Salary(model, base_annual=0))
    job.retired = True
    ann.retirement_triggered = True
    Job401kAccount(job, pretax_balance=480000)
    TraditionalIRA(ann, balance=150000)
    RothIRA(ann, balance=90000)
    HealthSavingsAccount(ann, hsa_type=HSAType.INDIVIDUAL, balance=30000, employer_contribution_annual=0)
    SocialSecurity(ann, claim_age=67, earnings_history=EARNINGS_HISTORY)
    MedicalCosts(ann)
    Medicare(ann)
    LongTermCare(ann)
    Insurance(ann, InsuranceType.LONG_TERM_CARE, "LTC Co", premium_annual=3200, coverage_amount=90000)
    Donation(ann, "Food bank", annual_amount=2000)
    return model


def mortality_and_estate(seed: int = 7, start_year: int = 2026, years: int = 50) -> LifeModel:
    """Spouses who die (fixed ages) with an adult child inheriting: spousal rollover, then a
    non-spouse inheritance (10-year inherited IRA), estate tax, life insurance, annuities, a pension
    with a survivor benefit, trusts and end-of-life costs."""
    model = LifeModel(start_year=start_year, end_year=start_year + years - 1, seed=seed)
    family = Family(model)
    bob = Person(
        family,
        "Bob",
        70,
        65,
        Spending(model, base_annual=70000, growth_pct=None),
        mortality_mode=MortalityMode.FIXED_AGE,
        death_age=78,
        gender=GenderAtBirth.MALE,
    )
    sue = Person(
        family,
        "Sue",
        68,
        65,
        Spending(model, base_annual=20000, growth_pct=None),
        mortality_mode=MortalityMode.FIXED_AGE,
        death_age=90,
        gender=GenderAtBirth.FEMALE,
    )
    kid = Person(family, "Kim", 40, 65, Spending(model, base_annual=45000, growth_pct=None))
    bob.get_married(sue)
    for person, balance in ((bob, 80000), (sue, 40000), (kid, 30000)):
        BankAccount(person, company="Bank", balance=balance)
    BrokerageAccount(bob, company="Brokerage", balance=2_500_000)
    BrokerageAccount(kid, company="Kid brokerage", balance=50000)
    old_job = Job(bob, company="Utility", role="Retired", salary=Salary(model, base_annual=0))
    old_job.retired = True
    Job401kAccount(old_job, pretax_balance=900000, roth_balance=100000)
    TraditionalIRA(sue, balance=300000)
    kid_job = Job(kid, company="Studio", role="Designer", salary=Salary(model, base_annual=110000, raise_pct=None))
    Job401kAccount(kid_job, pretax_contrib_pct=8, match_tiers=[(100, 4)])
    Pension(bob, company="Utility", vesting_years=5, benefit_annual=24000, cola_pct=2, survivor_pct=50)
    SocialSecurity(bob, claim_age=70, earnings_history=EARNINGS_HISTORY)
    SocialSecurity(sue, claim_age=67, earnings_history=EARNINGS_HISTORY[8:])
    LifeInsurance(bob, LifeInsuranceType.WHOLE, death_benefit=400000, premium_monthly=450)
    LifeInsurance(sue, LifeInsuranceType.TERM, death_benefit=250000, premium_monthly=90, term_years=15)
    Annuity(
        bob,
        annuity_type=AnnuityType.IMMEDIATE,
        balance=300000,
        payout_type=AnnuityPayoutType.JOINT_AND_SURVIVOR,
        survivor_pct=50,
    )
    Annuity(
        sue,
        annuity_type=AnnuityType.DEFERRED,
        balance=150000,
        payout_type=AnnuityPayoutType.LIFE_WITH_PERIOD_CERTAIN,
        payout_start_age=75,
        period_certain_years=20,
    )
    Trust(bob, TrustType.REVOCABLE, [kid], name="Family trust", balance=200000)
    irrevocable = Trust(sue, TrustType.IRREVOCABLE, [kid], name="Kid trust")
    LifeEvents(
        model,
        [
            LifeEvent(start_year + 1, "Fund kid trust", irrevocable.fund, 30000),
            LifeEvent(start_year + 3, "Trust gift", irrevocable.distribute, 10000, kid),
        ],
    )
    for person in (bob, sue):
        MedicalCosts(person)
        Medicare(person)
    DonorAdvisedFund(sue, "Giving fund", balance=0, growth_rate=5)
    return model


def renter_buys_home(seed: int = 3, start_year: int = 2026, years: int = 45) -> LifeModel:
    """A renter with student loans and credit-card debt who buys a home by life event (down payment
    through the household waterfall), has a child, takes on a car loan mid-run, changes jobs, holds
    vested RSUs in a brokerage account and later sells the home."""
    model = LifeModel(start_year=start_year, end_year=start_year + years - 1, seed=seed)
    family = Family(model)
    max_ = Person(family, "Max", 29, 63, Spending(model, base_annual=38000, growth_pct=None))
    BankAccount(max_, company="Credit union", balance=22000, interest_pct=1.0)
    BrokerageAccount(max_, company="Robinhood", balance=60000)
    job = Job(
        max_, company="Startup", role="Developer", salary=Salary(model, base_annual=125000, raise_pct=None, bonus_pct=5)
    )
    Job401kAccount(job, pretax_contrib_pct=6, roth_contrib_pct=4, match_tiers=[(100, 4)], match_vesting_years=3)
    StockPlan(job, signon_value=80000, refresher_value=30000, disposition="hold")
    Apartment(max_, "Downtown flat", rent_monthly=2200, rent_growth_pct=None)
    StudentLoan(
        max_,
        loan_type=StudentLoanType.FEDERAL_UNSUBSIDIZED,
        original_amount=55000,
        rate_pct=5.5,
        term_years=10,
        school_name="State U",
    )
    CreditCard(max_, name="Visa", credit_limit=20000, balance=6000)
    SocialSecurity(max_, claim_age=67, earnings_history=EARNINGS_HISTORY[22:])

    def buy_home():
        for apartment in list(max_.apartments):
            model.registries.apartments.unregister(max_, apartment)
        _home(model, max_, price=520000, principal=416000, purchase=True)

    def sell_home():
        for home in list(max_.homes):
            home.sell()
        Apartment(max_, "Retirement condo", rent_monthly=2600, rent_growth_pct=None)

    LifeEvents(
        model,
        [
            LifeEvent(start_year + 4, "Buy a house", buy_home),
            LifeEvent(start_year + 5, "Baby", max_.add_child, "Leo"),
            LifeEvent(
                start_year + 7,
                "New car",
                lambda: CarLoan(max_, original_amount=35000, term_years=6, rate_pct=7.0, name="Sedan"),
            ),
            LifeEvent(start_year + 12, "Lose job", job.retire),
            LifeEvent(
                start_year + 13,
                "New job",
                lambda: Job(max_, company="BigCo", role="Lead", salary=Salary(model, base_annual=150000)),
            ),
            LifeEvent(start_year + 30, "Downsize", sell_home),
        ],
    )
    return model


def everything_stochastic(seed: int, start_year: int = 2026, years: int = 50) -> LifeModel:
    """Stochastic economy *and* stochastic mortality over many products: whole life with a policy
    loan, annuity deposits/withdrawals, a credit card charged mid-run, an income-driven student
    loan, a 529 paying for college, insurance claims, donations, a DAF, trusts, lump-sum inherited
    IRAs, and a loner whose estate dissolves with no heir."""
    config = _stochastic_config()
    config.apply_scenario("lump_sum_heirs", {"estate": {"inherited_pretax_mode": "lump_sum"}})
    model = LifeModel(start_year=start_year, end_year=start_year + years - 1, seed=seed, config=config)
    family = Family(model)
    ana = Person(
        family,
        "Ana",
        52,
        62,
        Spending(model, base_annual=48000, growth_pct=None),
        mortality_mode=MortalityMode.STOCHASTIC,
        gender=GenderAtBirth.FEMALE,
    )
    raj = Person(
        family,
        "Raj",
        55,
        64,
        Spending(model, base_annual=36000, growth_pct=None),
        mortality_mode=MortalityMode.STOCHASTIC,
        gender=GenderAtBirth.MALE,
    )
    ana.get_married(raj)
    teen = ana.add_child("Teo", birth_year=start_year - 15)
    Plan529(ana, beneficiary=teen, balance=60000)
    BankAccount(ana, company="Bank", balance=50000)
    BankAccount(raj, company="Bank", balance=20000)
    BrokerageAccount(raj, company="Brokerage", balance=300000)
    job = Job(
        ana, company="Hospital", role="Doctor", salary=Salary(model, base_annual=210000, raise_pct=None, bonus_pct=5)
    )
    Job401kAccount(job, pretax_balance=400000, pretax_contrib_pct=10, match_tiers=[(100, 4)])
    StockPlan(job, signon_value=40000, refresher_value=20000, disposition="sell")
    raj_job = Job(raj, company="School", role="Teacher", salary=Salary(model, base_annual=70000, raise_pct=None))
    Job401kAccount(raj_job, pretax_balance=150000, roth_contrib_pct=5)
    TraditionalIRA(raj, balance=80000)
    HealthSavingsAccount(ana, hsa_type=HSAType.FAMILY, balance=20000)
    SocialSecurity(ana, claim_age=67, earnings_history=EARNINGS_HISTORY)
    SocialSecurity(raj, claim_age=65, earnings_history=EARNINGS_HISTORY[3:])
    _home(model, raj, price=650000, principal=300000)
    policy = LifeInsurance(raj, LifeInsuranceType.WHOLE, death_benefit=300000, premium_monthly=350)
    annuity = Annuity(ana, annuity_type=AnnuityType.FIXED, balance=100000)
    card = CreditCard(ana, name="Amex", credit_limit=30000, balance=2000)
    from ..debt.student_loan import StudentLoanRepaymentPlan

    StudentLoan(
        raj,
        loan_type=StudentLoanType.FEDERAL_UNSUBSIDIZED,
        original_amount=40000,
        rate_pct=6.0,
        term_years=10,
        school_name="Night school",
        repayment_plan=StudentLoanRepaymentPlan.REPAYMENT_ASSISTANCE_PLAN,
    )
    car_insurance = Insurance(
        ana, InsuranceType.AUTO, "AutoCo", premium_annual=1800, coverage_amount=40000, deductible=1000
    )
    Donation(ana, "Shelter", annual_amount=3000)
    daf = DonorAdvisedFund(ana, "Giving fund", balance=0)
    gift_trust = Trust(raj, TrustType.IRREVOCABLE, [teen and ana], name="Gift trust")
    MedicalCosts(ana)
    MedicalCosts(raj)
    Medicare(raj)

    loner_family = Family(model)
    loner = Person(
        loner_family,
        "Lou",
        74,
        65,
        Spending(model, base_annual=30000, growth_pct=None),
        mortality_mode=MortalityMode.FIXED_AGE,
        death_age=80,
    )
    BankAccount(loner, company="Bank", balance=40000)
    BrokerageAccount(loner, company="Brokerage", balance=250000)
    old_job = Job(loner, company="Mill", role="Retired", salary=Salary(model, base_annual=0))
    old_job.retired = True
    Job401kAccount(old_job, pretax_balance=200000)
    _home(model, loner, price=300000, principal=60000)
    CarLoan(loner, original_amount=15000, term_years=5, rate_pct=7, name="Truck")
    SocialSecurity(loner, claim_age=70, earnings_history=EARNINGS_HISTORY)

    LifeEvents(
        model,
        [
            LifeEvent(start_year + 1, "Card purchase", card.charge, 8000),
            LifeEvent(start_year + 2, "Annuity top-up", annuity.deposit, 20000),
            LifeEvent(start_year + 3, "Fender bender", car_insurance.file_claim, 6000, "Collision"),
            LifeEvent(start_year + 4, "Policy loan", policy.take_loan, 5000),
            LifeEvent(start_year + 5, "DAF gift", daf.contribute, 15000),
            LifeEvent(start_year + 5, "Fund trust", gift_trust.fund, 25000),
            LifeEvent(start_year + 6, "Annuity withdrawal", annuity.withdraw, 10000),
            LifeEvent(start_year + 8, "Trust gift", gift_trust.distribute, 5000, ana),
            LifeEvent(start_year + 9, "Repay policy loan", policy.repay_loan, 2000),
            LifeEvent(start_year + 12, "Drop policy", policy.drop_policy),
            LifeEvent(start_year + 14, "Surrender annuity", annuity.surrender),
        ],
    )
    return model


SCENARIOS = {
    "married_homeowners": married_homeowners,
    "stochastic_retiree": lambda: stochastic_retiree(seed=11),
    "mortality_and_estate": mortality_and_estate,
    "renter_buys_home": renter_buys_home,
    "everything_stochastic": lambda: everything_stochastic(seed=5),
}
