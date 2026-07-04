# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from enum import Enum
from typing import Optional, cast

from ..config.config_manager import config as _global_config
from ..model import Event, LifeModel, LifeModelAgent
from ..people.mortality import get_chance_of_mortality
from ..people.person import GenderAtBirth, Person
from ..tax.income import IncomeType


class AnnuityType(Enum):
    """Enum for annuity types"""

    FIXED = "Fixed"
    VARIABLE = "Variable"
    IMMEDIATE = "Immediate"
    DEFERRED = "Deferred"


class AnnuityPayoutType(Enum):
    """Enum for annuity payout types"""

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
    annuity_config = _global_config.financial.insurance.annuity
    max_age = annuity_config.max_projection_age
    survival_cutoff = annuity_config.survival_probability_cutoff

    if age >= max_age - 1:
        return 0.5  # Minimum life expectancy

    remaining_years = 0.0
    survival_probability = 1.0

    # Calculate expected remaining life using mortality tables
    for future_age in range(age, max_age):
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
        if survival_probability < survival_cutoff:
            break

    return max(remaining_years, 0.5)  # Minimum 6 months


def calculate_annuity_factor(
    age: int,
    interest_rate: float,
    payout_type: AnnuityPayoutType,
    period_certain_years: int = 0,
    gender: Optional[GenderAtBirth] = None,
) -> float:
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
    annuity_config = _global_config.financial.insurance.annuity
    max_age = annuity_config.max_projection_age
    survival_cutoff = annuity_config.survival_probability_cutoff
    max_months = (max_age - age) * 12

    monthly_rate = interest_rate / 100 / 12
    annuity_factor = 0.0

    def _monthly_survival(current_age: float) -> float:
        age_int = int(current_age)
        if gender is not None:
            annual_mortality = get_chance_of_mortality(age_int, gender)
        else:
            male_rate = get_chance_of_mortality(age_int, GenderAtBirth.MALE)
            female_rate = get_chance_of_mortality(age_int, GenderAtBirth.FEMALE)
            annual_mortality = (male_rate + female_rate) / 2
        return 1 - annual_mortality / 12

    if payout_type == AnnuityPayoutType.LIFE_ONLY:
        # Pure life annuity - payments until death
        survival_probability = 1.0
        for month in range(max_months):
            current_age = age + month / 12
            if current_age >= max_age:
                break

            # Present value of payment if alive
            discount_factor = (1 + monthly_rate) ** (-month)
            annuity_factor += survival_probability * discount_factor

            # Update survival probability
            survival_probability *= _monthly_survival(current_age)

            if survival_probability < survival_cutoff:
                break

    elif payout_type == AnnuityPayoutType.LIFE_WITH_PERIOD_CERTAIN:
        # Life annuity with guaranteed period
        guaranteed_months = period_certain_years * 12
        survival_probability = 1.0

        for month in range(max_months):
            current_age = age + month / 12
            if current_age >= max_age and month >= guaranteed_months:
                break

            discount_factor = (1 + monthly_rate) ** (-month)

            if month < guaranteed_months:
                # Guaranteed payment regardless of survival, but survival must still be
                # decremented so post-guarantee payments are not over-weighted.
                annuity_factor += discount_factor
                survival_probability *= _monthly_survival(current_age)
            else:
                # Payment only if alive after guaranteed period
                annuity_factor += survival_probability * discount_factor
                survival_probability *= _monthly_survival(current_age)

                if survival_probability < survival_cutoff:
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
    def __init__(
        self,
        person: Person,
        annuity_type: AnnuityType,
        initial_balance: float = 0.0,
        interest_rate: Optional[float] = None,
        payout_type: AnnuityPayoutType = AnnuityPayoutType.LIFE_ONLY,
        payout_start_age: Optional[int] = None,
        monthly_payout: Optional[float] = None,
        period_certain_years: Optional[int] = None,
        surrender_charge_years: Optional[int] = None,
        surrender_charge_rate: Optional[float] = None,
    ):
        """Models an annuity for a person

        Args:
            person: The person to which this annuity belongs
            annuity_type: The type of annuity
            initial_balance: Starting balance in the annuity
            interest_rate: Annual interest rate percentage. Uses configured default if None.
            payout_type: How the annuity pays out
            payout_start_age: Age when payouts begin (None for immediate)
            monthly_payout: Fixed monthly payout amount (calculated if None)
            period_certain_years: Years of guaranteed payments for period certain. Configured default if None.
            surrender_charge_years: Years during which surrender charges apply. Configured default if None.
            surrender_charge_rate: Annual surrender charge rate percentage. Configured default if None.

        Note:
            Payout taxation uses a simplified exclusion-ratio model (basis / expected total
            payout). Real rules differ for qualified vs non-qualified annuities; this is an
            approximation.
        """
        super().__init__(cast(LifeModel, person.model))
        self.model: "LifeModel" = cast("LifeModel", self.model)
        annuity_config = self.model.config.insurance.annuity
        if interest_rate is None:
            interest_rate = annuity_config.default_interest_rate
        if period_certain_years is None:
            period_certain_years = annuity_config.default_period_certain_years
        if surrender_charge_years is None:
            surrender_charge_years = annuity_config.default_surrender_charge_years
        if surrender_charge_rate is None:
            surrender_charge_rate = annuity_config.default_surrender_charge_rate
        self.person = person
        self.annuity_type = annuity_type
        self.balance = initial_balance
        self.interest_rate = interest_rate
        self.payout_type = payout_type
        default_payout_age = annuity_config.default_payout_start_age
        self.payout_start_age = payout_start_age or (
            default_payout_age if annuity_type == AnnuityType.DEFERRED else person.age
        )
        self.monthly_payout = monthly_payout
        self.period_certain_years = period_certain_years
        self.surrender_charge_years = surrender_charge_years
        self.surrender_charge_rate = surrender_charge_rate

        # Cost basis (after-tax investment in the contract) used for exclusion-ratio taxation.
        self.basis = initial_balance

        # State tracking
        self.is_active = True
        self.is_annuitized = False
        self.annuitization_year = None
        self.purchase_year = self.model.year
        self.remaining_period_certain_payments = 0

        # Annuitization converts ``balance`` into a reserve that funds payouts and is no longer
        # a withdrawable/surrenderable asset.
        self.annuitized_reserve = 0.0
        self.exclusion_ratio = 0.0

        # Statistics tracking
        self.stat_balance = initial_balance
        self.stat_annuitized_reserve = 0.0
        self.stat_interest_earned = 0.0
        self.stat_payouts_received = 0.0
        self.stat_taxable_payouts = 0.0
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
            self.basis += amount_deposited
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
        # Reduce cost basis pro-rata so remaining gains stay correctly attributed.
        if self.balance > 0:
            self.basis -= self.basis * (withdrawal_amount / self.balance)
        self.balance -= withdrawal_amount

        # Add to person's bank account
        if hasattr(self.person, "bank_accounts") and self.person.bank_accounts:
            self.person.bank_accounts[0].deposit(net_withdrawal)

        if surrender_charge > 0:
            self.model.event_log.add(
                Event(
                    f"{self.person.name} withdrew ${net_withdrawal:,.0f} from annuity "
                    f"(${surrender_charge:,.0f} surrender charge)"
                )
            )
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

        gender = getattr(self.person, "gender", None)

        # Calculate monthly payout if not specified
        if self.monthly_payout is None:
            # Use actuarial tables to calculate proper annuity payment
            # Calculate annuity factor using mortality tables
            annuity_factor = calculate_annuity_factor(
                age=self.person.age,
                interest_rate=self.interest_rate,
                payout_type=self.payout_type,
                period_certain_years=self.period_certain_years,
                gender=gender,
            )

            # Calculate monthly payment: balance divided by annuity factor
            if annuity_factor > 0:
                self.monthly_payout = self.balance / annuity_factor
            else:
                # Fallback to simple calculation if factor is zero
                life_expectancy = calculate_life_expectancy(self.person.age, gender)
                self.monthly_payout = self.balance / (life_expectancy * 12)

        # Set remaining period certain payments if applicable
        if self.payout_type == AnnuityPayoutType.LIFE_WITH_PERIOD_CERTAIN:
            self.remaining_period_certain_payments = self.period_certain_years * 12

        # Convert the accumulation balance into an annuitized reserve. It is no longer a
        # withdrawable/surrenderable asset; payouts draw it down and interest still accrues.
        self.annuitized_reserve = self.balance
        self.balance = 0.0
        self.stat_balance = 0.0

        # Exclusion ratio: the after-tax basis divided by the expected total payout. Each payout's
        # gains portion (1 - exclusion_ratio) is taxable ordinary income (simplified model).
        expected_months = self._expected_payout_months(gender)
        expected_total_payout = (self.monthly_payout or 0.0) * expected_months
        if expected_total_payout > 0:
            self.exclusion_ratio = min(1.0, self.basis / expected_total_payout)
        else:
            self.exclusion_ratio = 1.0

        self.model.event_log.add(
            Event(f"{self.person.name} annuitized with ${self.monthly_payout:,.0f}/month payments")
        )
        return True

    def _expected_payout_months(self, gender: Optional[GenderAtBirth]) -> float:
        """Expected number of monthly payouts, used for the exclusion ratio."""
        life_months = calculate_life_expectancy(self.person.age, gender) * 12
        if self.payout_type == AnnuityPayoutType.LIFE_WITH_PERIOD_CERTAIN:
            return max(life_months, self.period_certain_years * 12)
        return life_months

    def make_payout(self) -> float:
        """Make one monthly annuity payment, drawing down the annuitized reserve.

        The gains portion of each payout (per the exclusion ratio) is recorded as ordinary
        taxable income. Payments stop once the reserve is exhausted (no cash is created from
        nothing), except for any remaining guaranteed period-certain payments, which are clamped
        to whatever reserve remains.
        """
        if not self.is_annuitized or not self.is_active:
            return 0.0

        if self.annuitized_reserve <= 0:
            # Reserve exhausted: guaranteed payments already accounted for; stop paying.
            self.is_active = False
            return 0.0

        payout = min(self.monthly_payout or 0.0, self.annuitized_reserve)
        if payout <= 0:
            return 0.0

        self.annuitized_reserve -= payout
        self.stat_payouts_received += payout

        # Tax the gains portion as ordinary income (exclusion ratio covers return of basis).
        taxable_portion = payout * (1 - self.exclusion_ratio)
        if taxable_portion > 0:
            self.person.income.add(IncomeType.ORDINARY, taxable_portion)
            self.stat_taxable_payouts += taxable_portion

        # Deposit the payout into the person's bank account.
        self.person.receive_cash(payout, source="annuity payout")

        # Reduce period certain payments if applicable
        if (
            self.payout_type == AnnuityPayoutType.LIFE_WITH_PERIOD_CERTAIN
            and self.remaining_period_certain_payments > 0
        ):
            self.remaining_period_certain_payments -= 1

        return payout

    def surrender(self) -> float:
        """Surrender the annuity for cash value (invalid once annuitized)"""
        if self.is_annuitized or not self.is_active or self.balance <= 0:
            return 0.0

        surrender_charge = self.surrender_charge_amount
        net_value = self.balance - surrender_charge

        self.stat_surrender_charges_paid += surrender_charge

        # Add to person's bank account
        if self.person.bank_accounts:
            self.person.bank_accounts[0].deposit(net_value)

        self.model.event_log.add(
            Event(f"{self.person.name} surrendered annuity for ${net_value:,.0f} (${surrender_charge:,.0f} charge)")
        )

        self.balance = 0.0
        self.is_active = False

        return net_value

    def step(self):
        """Process annuity for the current year"""
        if not self.is_active:
            return

        # Apply interest growth to the reserve (annuitized) or the accumulation balance.
        if self.is_annuitized:
            if self.annuitized_reserve > 0:
                interest_earned = self.annuitized_reserve * (self.interest_rate / 100)
                self.annuitized_reserve += interest_earned
                self.stat_interest_earned += interest_earned
        elif self.balance > 0:
            interest_earned = self.balance * (self.interest_rate / 100)
            self.balance += interest_earned
            self.stat_interest_earned += interest_earned

        self.stat_balance = self.balance
        self.stat_annuitized_reserve = self.annuitized_reserve

    def pre_step(self):
        """Pre-step processing: auto-annuitize when eligible, then pay out for the year.

        Payouts are recorded here (in pre_step) so their taxable portion is in the income ledger
        before the tax unit settles taxes in the step stage.
        """
        # Auto-annuitize immediate annuities or any annuity whose payout age has been reached.
        if not self.is_annuitized and self.is_active and self.is_payout_eligible:
            self.annuitize()

        # Make the year's 12 monthly payouts.
        if self.is_annuitized and self.is_active:
            for _ in range(12):
                self.make_payout()

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Type: {self.annuity_type.value}</li>"
        desc += f"<li>Balance: ${self.balance:,.2f}</li>"
        desc += f"<li>Interest Rate: {self.interest_rate}%</li>"
        desc += f"<li>Payout Type: {self.payout_type.value}</li>"
        if self.is_annuitized:
            desc += f"<li>Monthly Payout: ${self.monthly_payout:,.2f}</li>"
        else:
            desc += f"<li>Payout Start Age: {self.payout_start_age}</li>"
        if self.is_in_surrender_period:
            desc += f"<li>Surrender Charge: ${self.surrender_charge_amount:,.2f}</li>"
        desc += f"<li>Status: {'Annuitized' if self.is_annuitized else 'Accumulation Phase'}</li>"
        desc += "</ul>"
        return desc
