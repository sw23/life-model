# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Whole-household scenarios shared by the explainable-output tests (Plan 28).

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
        person=owner,
        name=f"{owner.name}'s house",
        purchase_price=price,
        value_yearly_increase=None,
        down_payment=price - principal,
        mortgage=Mortgage(loan_amount=principal, start_date=model.year, length_years=30, yearly_interest_rate=6.0),
        expenses=HomeExpenses(
            model,
            property_tax_percent=1.1,
            home_insurance_percent=0.4,
            maintenance_amount=2500,
            maintenance_increase=3,
            improvement_amount=1000,
            improvement_increase=3,
            hoa_amount=600,
            hoa_increase=2,
        ),
        purchase=purchase,
    )


def married_homeowners(start_year: int = 2026, years: int = 45, *, seed: int | None = 1) -> LifeModel:
    """A married couple with two kids, two jobs with 401k matches, a mortgage, a brokerage account,
    IRAs, an HSA, Social Security, and a car loan; one retires early and draws on savings."""
    model = LifeModel(start_year=start_year, end_year=start_year + years - 1, seed=seed)
    family = Family(model)
    john = Person(family, "John", 42, 58, Spending(model, base=52000, yearly_increase=None), state="CA")
    jane = Person(family, "Jane", 40, 62, Spending(model, base=30000, yearly_increase=None), state="CA")
    john.get_married(jane)
    BankAccount(john, "Chase", balance=40000, interest_rate=2.0)
    BankAccount(jane, "Ally", balance=25000, interest_rate=3.5)
    BrokerageAccount(john, "Vanguard", balance=150000)
    acme = Job(john, "Acme", "Engineer", Salary(model, base=165000, yearly_increase=None, yearly_bonus=8))
    Job401kAccount(
        acme,
        pretax_balance=220000,
        pretax_contrib_percent=10,
        roth_balance=30000,
        roth_contrib_percent=4,
        match_tiers=[(100, 3), (50, 2)],
    )
    clinic = Job(jane, "Clinic", "Nurse", Salary(model, base=92000, yearly_increase=None))
    Job401kAccount(clinic, pretax_balance=90000, pretax_contrib_percent=6, match_tiers=[(50, 6)])
    TraditionalIRA(jane, balance=45000)
    RothIRA(john, balance=38000)
    HealthSavingsAccount(jane, HSAType.FAMILY, balance=12000)
    _home(model, john, price=780000, principal=520000)
    CarLoan(john, loan_amount=32000, length_years=5, yearly_interest_rate=6.5, name="SUV")
    ava = john.add_child("Ava", birth_year=start_year - 8)
    Plan529(john, beneficiary=ava, balance=40000)
    jane.add_child("Ben", birth_year=start_year - 5)
    SocialSecurity(john, withdrawal_start_age=67, income_history=EARNINGS_HISTORY)
    SocialSecurity(jane, withdrawal_start_age=67, income_history=EARNINGS_HISTORY[5:])
    LifeEvents(model, [LifeEvent(start_year + 6, "Kitchen remodel", john.spending.add_expense, 45000)])
    return model


def stochastic_retiree(seed: int, start_year: int = 2026, years: int = 40) -> LifeModel:
    """A single retiree under the stochastic economy: Social Security, RMDs from a 401k and IRA,
    a brokerage account sold to fund spending, healthcare costs, Medicare and long-term care."""
    model = LifeModel(start_year=start_year, end_year=start_year + years - 1, seed=seed, config=_stochastic_config())
    family = Family(model)
    ann = Person(family, "Ann", 66, 65, Spending(model, base=58000, yearly_increase=None), gender=GenderAtBirth.FEMALE)
    BankAccount(ann, "Bank", balance=60000)
    BrokerageAccount(ann, "Brokerage", balance=650000)
    job = Job(ann, "Former employer", "Retired", Salary(model, base=0))
    job.retired = True
    ann.retirement_triggered = True
    Job401kAccount(job, pretax_balance=480000)
    TraditionalIRA(ann, balance=150000)
    RothIRA(ann, balance=90000)
    HealthSavingsAccount(ann, HSAType.INDIVIDUAL, balance=30000, employer_contribution=0)
    SocialSecurity(ann, withdrawal_start_age=67, income_history=EARNINGS_HISTORY)
    MedicalCosts(ann)
    Medicare(ann)
    LongTermCare(ann)
    Insurance(ann, InsuranceType.LONG_TERM_CARE, "LTC Co", annual_premium=3200, coverage_amount=90000)
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
        Spending(model, base=70000, yearly_increase=None),
        mortality_mode=MortalityMode.FIXED_AGE,
        death_age=78,
        gender=GenderAtBirth.MALE,
    )
    sue = Person(
        family,
        "Sue",
        68,
        65,
        Spending(model, base=20000, yearly_increase=None),
        mortality_mode=MortalityMode.FIXED_AGE,
        death_age=90,
        gender=GenderAtBirth.FEMALE,
    )
    kid = Person(family, "Kim", 40, 65, Spending(model, base=45000, yearly_increase=None))
    bob.get_married(sue)
    for person, balance in ((bob, 80000), (sue, 40000), (kid, 30000)):
        BankAccount(person, "Bank", balance=balance)
    BrokerageAccount(bob, "Brokerage", balance=2_500_000)
    BrokerageAccount(kid, "Kid brokerage", balance=50000)
    old_job = Job(bob, "Utility", "Retired", Salary(model, base=0))
    old_job.retired = True
    Job401kAccount(old_job, pretax_balance=900000, roth_balance=100000)
    TraditionalIRA(sue, balance=300000)
    kid_job = Job(kid, "Studio", "Designer", Salary(model, base=110000, yearly_increase=None))
    Job401kAccount(kid_job, pretax_contrib_percent=8, match_tiers=[(100, 4)])
    Pension(bob, "Utility", vesting_years=5, benefit_amount=24000, cola_percent=2, survivor_percent=50)
    SocialSecurity(bob, withdrawal_start_age=70, income_history=EARNINGS_HISTORY)
    SocialSecurity(sue, withdrawal_start_age=67, income_history=EARNINGS_HISTORY[8:])
    LifeInsurance(bob, LifeInsuranceType.WHOLE, death_benefit=400000, monthly_premium=450)
    LifeInsurance(sue, LifeInsuranceType.TERM, death_benefit=250000, monthly_premium=90, term_years=15)
    Annuity(
        bob,
        AnnuityType.IMMEDIATE,
        initial_balance=300000,
        payout_type=AnnuityPayoutType.JOINT_AND_SURVIVOR,
        survivor_percent=50,
    )
    Annuity(
        sue,
        AnnuityType.DEFERRED,
        initial_balance=150000,
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
    max_ = Person(family, "Max", 29, 63, Spending(model, base=38000, yearly_increase=None))
    BankAccount(max_, "Credit union", balance=22000, interest_rate=1.0)
    BrokerageAccount(max_, "Robinhood", balance=60000)
    job = Job(max_, "Startup", "Developer", Salary(model, base=125000, yearly_increase=None, yearly_bonus=5))
    Job401kAccount(job, pretax_contrib_percent=6, roth_contrib_percent=4, match_tiers=[(100, 4)], match_vesting_years=3)
    StockPlan(job, signon_value=80000, refresher_value=30000, disposition="hold")
    Apartment(max_, "Downtown flat", monthly_rent=2200, yearly_increase=None)
    StudentLoan(
        max_,
        StudentLoanType.FEDERAL_UNSUBSIDIZED,
        loan_amount=55000,
        yearly_interest_rate=5.5,
        length_years=10,
        school_name="State U",
    )
    CreditCard(max_, "Visa", credit_limit=20000, current_balance=6000)
    SocialSecurity(max_, withdrawal_start_age=67, income_history=EARNINGS_HISTORY[22:])

    def buy_home():
        for apartment in list(max_.apartments):
            model.registries.apartments.unregister(max_, apartment)
        _home(model, max_, price=520000, principal=416000, purchase=True)

    def sell_home():
        for home in list(max_.homes):
            home.sell()
        Apartment(max_, "Retirement condo", monthly_rent=2600, yearly_increase=None)

    LifeEvents(
        model,
        [
            LifeEvent(start_year + 4, "Buy a house", buy_home),
            LifeEvent(start_year + 5, "Baby", max_.add_child, "Leo"),
            LifeEvent(start_year + 7, "New car", lambda: CarLoan(max_, 35000, 6, 7.0, "Sedan")),
            LifeEvent(start_year + 12, "Lose job", job.retire),
            LifeEvent(start_year + 13, "New job", lambda: Job(max_, "BigCo", "Lead", Salary(model, base=150000))),
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
        Spending(model, base=48000, yearly_increase=None),
        mortality_mode=MortalityMode.STOCHASTIC,
        gender=GenderAtBirth.FEMALE,
    )
    raj = Person(
        family,
        "Raj",
        55,
        64,
        Spending(model, base=36000, yearly_increase=None),
        mortality_mode=MortalityMode.STOCHASTIC,
        gender=GenderAtBirth.MALE,
    )
    ana.get_married(raj)
    teen = ana.add_child("Teo", birth_year=start_year - 15)
    Plan529(ana, beneficiary=teen, balance=60000)
    BankAccount(ana, "Bank", balance=50000)
    BankAccount(raj, "Bank", balance=20000)
    BrokerageAccount(raj, "Brokerage", balance=300000)
    job = Job(ana, "Hospital", "Doctor", Salary(model, base=210000, yearly_increase=None, yearly_bonus=5))
    Job401kAccount(job, pretax_balance=400000, pretax_contrib_percent=10, match_tiers=[(100, 4)])
    StockPlan(job, signon_value=40000, refresher_value=20000, disposition="sell")
    raj_job = Job(raj, "School", "Teacher", Salary(model, base=70000, yearly_increase=None))
    Job401kAccount(raj_job, pretax_balance=150000, roth_contrib_percent=5)
    TraditionalIRA(raj, balance=80000)
    HealthSavingsAccount(ana, HSAType.FAMILY, balance=20000)
    SocialSecurity(ana, withdrawal_start_age=67, income_history=EARNINGS_HISTORY)
    SocialSecurity(raj, withdrawal_start_age=65, income_history=EARNINGS_HISTORY[3:])
    _home(model, raj, price=650000, principal=300000)
    policy = LifeInsurance(raj, LifeInsuranceType.WHOLE, death_benefit=300000, monthly_premium=350)
    annuity = Annuity(ana, AnnuityType.FIXED, initial_balance=100000)
    card = CreditCard(ana, "Amex", credit_limit=30000, current_balance=2000)
    from ..debt.student_loan import StudentLoanRepaymentPlan

    StudentLoan(
        raj,
        StudentLoanType.FEDERAL_UNSUBSIDIZED,
        loan_amount=40000,
        yearly_interest_rate=6.0,
        length_years=10,
        school_name="Night school",
        repayment_plan=StudentLoanRepaymentPlan.REPAYMENT_ASSISTANCE_PLAN,
    )
    car_insurance = Insurance(
        ana, InsuranceType.AUTO, "AutoCo", annual_premium=1800, coverage_amount=40000, deductible=1000
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
        Spending(model, base=30000, yearly_increase=None),
        mortality_mode=MortalityMode.FIXED_AGE,
        death_age=80,
    )
    BankAccount(loner, "Bank", balance=40000)
    BrokerageAccount(loner, "Brokerage", balance=250000)
    old_job = Job(loner, "Mill", "Retired", Salary(model, base=0))
    old_job.retired = True
    Job401kAccount(old_job, pretax_balance=200000)
    _home(model, loner, price=300000, principal=60000)
    CarLoan(loner, loan_amount=15000, length_years=5, yearly_interest_rate=7, name="Truck")
    SocialSecurity(loner, withdrawal_start_age=70, income_history=EARNINGS_HISTORY)

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
