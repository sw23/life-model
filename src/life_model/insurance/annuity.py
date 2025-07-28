# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from enum import Enum
from typing import Optional, cast
from ..people.person import Person, GenderAtBirth
from ..people.mortality import mortality_rates, get_chance_of_mortality
from ..model import LifeModel, LifeModelAgent, Event, compound_interest


class AnnuityType(Enum):
    """ Enum for annuity types """
    FIXED = "Fixed"
    VARIABLE = "Variable"
    IMMEDIATE = "Immediate"
    DEFERRED = "Deferred"


class AnnuityPayoutType(Enum):
    """ Enum for annuity payout types """
    LIFE_ONLY = "Life Only"
    LIFE_WITH_PERIOD_CERTAIN = "Life with Period Certain"
    JOINT_AND_SURVIVOR = "Joint and Survivor"
    LUMP_SUM = "Lump Sum"


def calculate_life_expectancy(age: int, gender: Optional[GenderAtBirth] = None) -> float:
    """Calculate life expectancy using actuarial mortality tables

    Args:
        age: Current age of the person
        gender: Gender for more accurate calculation (optional)

    Returns:
        Expected remaining years of life
    """
    if age >= 119:
        return 0.5  # Minimum life expectancy

    remaining_years = 0.0
    survival_probability = 1.0

    # Calculate expected remaining life using mortality tables
    for future_age in range(age, 120):
        if gender is not None:
            mortality_rate = get_chance_of_mortality(future_age, gender)
        else:
            # Use average of male and female rates if gender not specified
            male_rate = get_chance_of_mortality(future_age, GenderAtBirth.MALE)
            female_rate = get_chance_of_mortality(future_age, GenderAtBirth.FEMALE)
            mortality_rate = (male_rate + female_rate) / 2

        # Calculate probability of surviving this year
        year_survival_prob = 1 - mortality_rate

        # Add expected fraction of year lived
        remaining_years += survival_probability * year_survival_prob

        # Update survival probability for next year
        survival_probability *= year_survival_prob

        # Stop if survival probability becomes negligible
        if survival_probability < 0.001:
            break

    return max(remaining_years, 0.5)  # Minimum 6 months


def calculate_annuity_factor(age: int, interest_rate: float, payout_type: AnnuityPayoutType,
                           period_certain_years: int = 0, gender: Optional[GenderAtBirth] = None) -> float:
    """Calculate annuity factor using actuarial principles

    Args:
        age: Current age of annuitant
        interest_rate: Annual interest rate (as percentage)
        payout_type: Type of annuity payout
        period_certain_years: Years of guaranteed payments for period certain
        gender: Gender for mortality calculations

    Returns:
        Annuity factor (present value of $1 annuity)
    """
    monthly_rate = interest_rate / 100 / 12
    annuity_factor = 0.0

    if payout_type == AnnuityPayoutType.LIFE_ONLY:
        # Pure life annuity - payments until death
        survival_probability = 1.0
        for month in range(12 * 80):  # Up to age 120
            current_age = age + month / 12
            if current_age >= 120:
                break

            # Get mortality rate for this age
            age_int = int(current_age)
            if gender is not None:
                annual_mortality = get_chance_of_mortality(age_int, gender)
            else:
                male_rate = get_chance_of_mortality(age_int, GenderAtBirth.MALE)
                female_rate = get_chance_of_mortality(age_int, GenderAtBirth.FEMALE)
                annual_mortality = (male_rate + female_rate) / 2

            monthly_mortality = annual_mortality / 12
            monthly_survival = 1 - monthly_mortality

            # Present value of payment if alive
            discount_factor = (1 + monthly_rate) ** (-month)
            annuity_factor += survival_probability * discount_factor

            # Update survival probability
            survival_probability *= monthly_survival

            if survival_probability < 0.001:
                break

    elif payout_type == AnnuityPayoutType.LIFE_WITH_PERIOD_CERTAIN:
        # Life annuity with guaranteed period
        guaranteed_months = period_certain_years * 12
        survival_probability = 1.0

        for month in range(12 * 80):
            current_age = age + month / 12
            if current_age >= 120 and month >= guaranteed_months:
                break

            discount_factor = (1 + monthly_rate) ** (-month)

            if month < guaranteed_months:
                # Guaranteed payment regardless of survival
                annuity_factor += discount_factor
            else:
                # Payment only if alive after guaranteed period
                age_int = int(current_age)
                if gender is not None:
                    annual_mortality = get_chance_of_mortality(age_int, gender)
                else:
                    male_rate = get_chance_of_mortality(age_int, GenderAtBirth.MALE)
                    female_rate = get_chance_of_mortality(age_int, GenderAtBirth.FEMALE)
                    annual_mortality = (male_rate + female_rate) / 2

                monthly_mortality = annual_mortality / 12
                monthly_survival = 1 - monthly_mortality

                annuity_factor += survival_probability * discount_factor
                survival_probability *= monthly_survival

                if survival_probability < 0.001:
                    break

    else:
        # For other types, use simplified calculation
        life_expectancy = calculate_life_expectancy(age, gender)
        total_months = life_expectancy * 12

        if monthly_rate > 0:
            annuity_factor = (1 - (1 + monthly_rate) ** (-total_months)) / monthly_rate
        else:
            annuity_factor = total_months

    return annuity_factor


class Annuity(LifeModelAgent):
    def __init__(self, person: Person, annuity_type: AnnuityType,
                 initial_balance: float = 0.0, interest_rate: float = 3.0,
                 payout_type: AnnuityPayoutType = AnnuityPayoutType.LIFE_ONLY,
                 payout_start_age: Optional[int] = None,
                 monthly_payout: Optional[float] = None,
                 period_certain_years: int = 10,
                 surrender_charge_years: int = 7,
                 surrender_charge_rate: float = 7.0):
        """ Models an annuity for a person

        Args:
            person: The person to which this annuity belongs
            annuity_type: The type of annuity
            initial_balance: Starting balance in the annuity
            interest_rate: Annual interest rate percentage
            payout_type: How the annuity pays out
            payout_start_age: Age when payouts begin (None for immediate)
            monthly_payout: Fixed monthly payout amount (calculated if None)
            period_certain_years: Years of guaranteed payments for period certain
            surrender_charge_years: Years during which surrender charges apply
            surrender_charge_rate: Annual surrender charge rate percentage
        """
        super().__init__(cast(LifeModel, person.model))
        self.model: 'LifeModel' = cast('LifeModel', self.model)
        self.person = person
        self.annuity_type = annuity_type
        self.balance = initial_balance
        self.interest_rate = interest_rate
        self.payout_type = payout_type
        self.payout_start_age = payout_start_age or (65 if annuity_type == AnnuityType.DEFERRED else person.age)
        self.monthly_payout = monthly_payout
        self.period_certain_years = period_certain_years
        self.surrender_charge_years = surrender_charge_years
        self.surrender_charge_rate = surrender_charge_rate

        # State tracking
        self.is_active = True
        self.is_annuitized = False
        self.annuitization_year = None
        self.purchase_year = self.model.year
        self.remaining_period_certain_payments = 0

        # Statistics tracking
        self.stat_balance = initial_balance
        self.stat_interest_earned = 0.0
        self.stat_payouts_received = 0.0
        self.stat_surrender_charges_paid = 0.0

        # Register with model
        self.model.registries.annuities.register(person, self)

    @property
    def years_since_purchase(self) -> int:
        """Years since the annuity was purchased"""
        return self.model.year - self.purchase_year

    @property
    def is_in_surrender_period(self) -> bool:
        """Whether surrender charges apply"""
        return self.years_since_purchase < self.surrender_charge_years

    @property
    def is_payout_eligible(self) -> bool:
        """Whether the person is eligible to start receiving payouts"""
        return self.person.age >= self.payout_start_age

    @property
    def surrender_charge_amount(self) -> float:
        """Calculate current surrender charge if annuity is surrendered"""
        if not self.is_in_surrender_period:
            return 0.0

        # Surrender charge typically decreases each year
        years_remaining = self.surrender_charge_years - self.years_since_purchase
        charge_rate = (years_remaining / self.surrender_charge_years) * self.surrender_charge_rate
        return self.balance * (charge_rate / 100)

    def deposit(self, amount: float) -> bool:
        """Deposit additional funds into the annuity (if not annuitized)"""
        if self.is_annuitized or not self.is_active:
            return False

        # Try to deduct from bank accounts
        remaining_balance = self.person.deduct_from_bank_accounts(amount)
        amount_deposited = amount - remaining_balance

        if amount_deposited > 0:
            self.balance += amount_deposited
            self.model.event_log.add(Event(f"{self.person.name} deposited ${amount_deposited:,.0f} into annuity"))
            return True
        return False

    def withdraw(self, amount: float) -> float:
        """Withdraw funds from the annuity (with potential surrender charges)"""
        if self.is_annuitized or not self.is_active or amount <= 0:
            return 0.0

        # Calculate available amount after surrender charges
        withdrawal_amount = min(amount, self.balance)
        surrender_charge = 0.0

        if self.is_in_surrender_period:
            surrender_charge = withdrawal_amount * (self.surrender_charge_rate / 100)
            surrender_charge *= (self.surrender_charge_years - self.years_since_purchase) / self.surrender_charge_years
            self.stat_surrender_charges_paid += surrender_charge

        net_withdrawal = withdrawal_amount - surrender_charge
        self.balance -= withdrawal_amount

        # Add to person's bank account
        if hasattr(self.person, 'bank_accounts') and self.person.bank_accounts:
            self.person.bank_accounts[0].deposit(net_withdrawal)

        if surrender_charge > 0:
            self.model.event_log.add(Event(f"{self.person.name} withdrew ${net_withdrawal:,.0f} from annuity (${surrender_charge:,.0f} surrender charge)"))
        else:
            self.model.event_log.add(Event(f"{self.person.name} withdrew ${net_withdrawal:,.0f} from annuity"))

        return net_withdrawal

    def annuitize(self) -> bool:
        """Convert the annuity to income payments"""
        if self.is_annuitized or not self.is_active or self.balance <= 0:
            return False

        if not self.is_payout_eligible:
            return False

        self.is_annuitized = True
        self.annuitization_year = self.model.year

        # Calculate monthly payout if not specified
        if self.monthly_payout is None:
            # Use actuarial tables to calculate proper annuity payment
            # Determine gender if available (default to None for average calculation)
            gender = getattr(self.person, 'gender', None)

            # Calculate annuity factor using mortality tables
            annuity_factor = calculate_annuity_factor(
                age=self.person.age,
                interest_rate=self.interest_rate,
                payout_type=self.payout_type,
                period_certain_years=self.period_certain_years,
                gender=gender
            )

            # Set remaining period certain payments if applicable
            if self.payout_type == AnnuityPayoutType.LIFE_WITH_PERIOD_CERTAIN:
                self.remaining_period_certain_payments = self.period_certain_years * 12

            # Calculate monthly payment: balance divided by annuity factor
            if annuity_factor > 0:
                self.monthly_payout = self.balance / annuity_factor
            else:
                # Fallback to simple calculation if factor is zero
                life_expectancy = calculate_life_expectancy(self.person.age, gender)
                self.monthly_payout = self.balance / (life_expectancy * 12)

        self.model.event_log.add(Event(f"{self.person.name} annuitized with ${self.monthly_payout:,.0f}/month payments"))
        return True

    def make_payout(self) -> float:
        """Make monthly annuity payment if eligible"""
        if not self.is_annuitized or not self.is_active:
            return 0.0

        # Check if person is still alive (simplified - in practice would check death status)
        person_deceased = False  # Placeholder for actual death checking logic

        if person_deceased:
            # Handle period certain payments to beneficiaries
            if self.payout_type == AnnuityPayoutType.LIFE_WITH_PERIOD_CERTAIN and self.remaining_period_certain_payments > 0:
                payout = self.monthly_payout or 0.0
                self.remaining_period_certain_payments -= 1
                self.stat_payouts_received += payout

                # Add to family income or first surviving family member
                if hasattr(self.person, 'family') and self.person.family.members:
                    for family_member in self.person.family.members:
                        if family_member != self.person:  # Simplified survivor check
                            if family_member.bank_accounts:
                                family_member.bank_accounts[0].deposit(payout)
                            break

                return payout
            else:
                # No more payments
                self.is_active = False
                return 0.0

        # Person is alive, make normal payment
        payout = self.monthly_payout or 0.0
        self.stat_payouts_received += payout

        # Add to person's bank account
        if self.person.bank_accounts:
            self.person.bank_accounts[0].deposit(payout)

        # Reduce period certain payments if applicable
        if self.payout_type == AnnuityPayoutType.LIFE_WITH_PERIOD_CERTAIN and self.remaining_period_certain_payments > 0:
            self.remaining_period_certain_payments -= 1

        return payout

    def surrender(self) -> float:
        """Surrender the annuity for cash value"""
        if not self.is_active or self.balance <= 0:
            return 0.0

        surrender_charge = self.surrender_charge_amount
        net_value = self.balance - surrender_charge

        self.stat_surrender_charges_paid += surrender_charge

        # Add to person's bank account
        if self.person.bank_accounts:
            self.person.bank_accounts[0].deposit(net_value)

        self.model.event_log.add(Event(f"{self.person.name} surrendered annuity for ${net_value:,.0f} (${surrender_charge:,.0f} charge)"))

        self.balance = 0.0
        self.is_active = False

        return net_value

    def step(self):
        """Process annuity for the current year"""
        if not self.is_active:
            return

        # Apply interest growth to non-annuitized balance
        if not self.is_annuitized and self.balance > 0:
            interest_earned = self.balance * (self.interest_rate / 100)
            self.balance += interest_earned
            self.stat_interest_earned += interest_earned

        # Make monthly payments if annuitized
        if self.is_annuitized:
            monthly_income = 0.0
            for month in range(12):
                monthly_income += self.make_payout()

        # Update statistics
        self.stat_balance = self.balance

    def pre_step(self):
        """Pre-step processing"""
        # Auto-annuitize immediate annuities or when payout age is reached
        if (self.annuity_type == AnnuityType.IMMEDIATE or
            (self.annuity_type == AnnuityType.DEFERRED and self.is_payout_eligible)) and not self.is_annuitized:
            self.annuitize()

    def _repr_html_(self):
        desc = '<ul>'
        desc += f'<li>Type: {self.annuity_type.value}</li>'
        desc += f'<li>Balance: ${self.balance:,.2f}</li>'
        desc += f'<li>Interest Rate: {self.interest_rate}%</li>'
        desc += f'<li>Payout Type: {self.payout_type.value}</li>'
        if self.is_annuitized:
            desc += f'<li>Monthly Payout: ${self.monthly_payout:,.2f}</li>'
        else:
            desc += f'<li>Payout Start Age: {self.payout_start_age}</li>'
        if self.is_in_surrender_period:
            desc += f'<li>Surrender Charge: ${self.surrender_charge_amount:,.2f}</li>'
        desc += f'<li>Status: {"Annuitized" if self.is_annuitized else "Accumulation Phase"}</li>'
        desc += '</ul>'
        return desc
