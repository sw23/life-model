# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

from ..config.financial_config import resolve_financial_config as _fin
from ..deprecated_names import deprecated_arguments
from ..economy import annual_to_monthly
from ..ledger import FlowKind
from ..model import Event, EventKind, LifeModel, LifeModelAgent
from ..people.mortality import get_chance_of_mortality
from ..people.person import GenderAtBirth, Person
from ..tax.income import IncomeType

if TYPE_CHECKING:
    from ..config.financial_config import FinancialConfig


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


def calculate_life_expectancy(
    age: int, gender: GenderAtBirth | None = None, config: "FinancialConfig | None" = None
) -> float:
    """Calculate life expectancy using actuarial mortality tables

    Args:
        age: Current age of the person
        gender: Gender for more accurate calculation (optional)
        config: Per-model config. Defaults to the packaged defaults.

    Returns:
        Expected remaining years of life
    """
    annuity_config = _fin(config).insurance.annuity
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
    gender: GenderAtBirth | None = None,
    config: "FinancialConfig | None" = None,
    *,
    joint_age: int | None = None,
    joint_gender: GenderAtBirth | None = None,
    survivor_percent: float = 100.0,
) -> float:
    """Calculate annuity factor using actuarial principles

    Args:
        age: Current age of annuitant
        interest_rate: Annual interest rate (as percentage)
        payout_type: Type of annuity payout
        period_certain_years: Years of guaranteed payments for period certain
        gender: Gender for mortality calculations
        config: Per-model config. Defaults to the packaged defaults.
        joint_age: JOINT_AND_SURVIVOR only: the joint annuitant's age.
        joint_gender: JOINT_AND_SURVIVOR only: the joint annuitant's gender.
        survivor_percent: JOINT_AND_SURVIVOR only: share of the payment continued to the joint
            annuitant after the primary annuitant's death (contingent form).

    Returns:
        Annuity factor (present value of $1 annuity). With ``interest_rate=0`` it is the expected
        number of full monthly payments.
    """
    annuity_config = _fin(config).insurance.annuity
    max_age = annuity_config.max_projection_age
    survival_cutoff = annuity_config.survival_probability_cutoff
    max_months = (max_age - age) * 12

    monthly_rate = interest_rate / 100 / 12
    annuity_factor = 0.0

    def _monthly_survival(current_age: float, who: GenderAtBirth | None = gender) -> float:
        age_int = int(current_age)
        if who is not None:
            annual_mortality = get_chance_of_mortality(age_int, who)
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

    elif payout_type == AnnuityPayoutType.JOINT_AND_SURVIVOR:
        # Contingent joint-and-survivor: the full payment while the primary annuitant lives, then
        # ``survivor_percent`` of it while the joint annuitant survives them. With independent
        # lives, month m is worth p1 + s x (1 - p1) x p2 payments.
        if joint_age is None:
            raise ValueError("A joint-and-survivor annuity factor needs the joint annuitant's age")
        share = survivor_percent / 100
        p1 = p2 = 1.0
        months = (max_age - min(age, joint_age)) * 12
        for month in range(months):
            age1 = age + month / 12
            age2 = joint_age + month / 12
            expected = p1 + share * (1 - p1) * p2
            annuity_factor += expected * (1 + monthly_rate) ** (-month)
            p1 = p1 * _monthly_survival(age1) if age1 < max_age else 0.0
            p2 = p2 * _monthly_survival(age2, joint_gender) if age2 < max_age else 0.0
            if p1 + share * (1 - p1) * p2 < survival_cutoff:
                break

    else:
        # For other types, use simplified calculation
        life_expectancy = calculate_life_expectancy(age, gender, config)
        total_months = life_expectancy * 12

        if monthly_rate > 0:
            annuity_factor = (1 - (1 + monthly_rate) ** (-total_months)) / monthly_rate
        else:
            annuity_factor = total_months

    return annuity_factor


class Annuity(LifeModelAgent):
    """An annuity: an accumulation balance credited interest monthly, then (once annuitized) a
    reserve paying one monthly payout per month and credited interest monthly."""

    STATS_OWNED = frozenset({"stat_annuity_balance"})

    @deprecated_arguments(
        {
            "person": "owner",
            "initial_balance": "balance",
            "interest_rate": "rate_pct",
            "monthly_payout": "payout_monthly",
            "surrender_charge_rate": "surrender_charge_pct",
            "survivor_percent": "survivor_pct",
            "cola_percent": "cola_pct",
        },
        positional=(
            "annuity_type",
            "balance",
            "rate_pct",
            "payout_type",
            "payout_start_age",
            "payout_monthly",
            "period_certain_years",
            "surrender_charge_years",
            "surrender_charge_pct",
        ),
    )
    def __init__(
        self,
        owner: Person,
        *,
        annuity_type: AnnuityType,
        balance: float = 0.0,
        rate_pct: float | None = None,
        payout_type: AnnuityPayoutType = AnnuityPayoutType.LIFE_ONLY,
        payout_start_age: int | None = None,
        payout_monthly: float | None = None,
        period_certain_years: int | None = None,
        surrender_charge_years: int | None = None,
        surrender_charge_pct: float | None = None,
        joint_annuitant: Person | None = None,
        survivor_pct: float = 100.0,
        basis: float | None = None,
        purchase_year: int | None = None,
        qualified: bool = False,
        in_payout: bool = False,
        cola_pct: float = 0.0,
    ):
        """Models an annuity for a person

        Every argument after the owner is keyword-only. Deprecated (one release): positional arguments,
        and the names ``person`` (owner), ``initial_balance`` (balance), ``interest_rate`` (rate_pct),
        ``monthly_payout`` (payout_monthly), ``surrender_charge_rate`` (surrender_charge_pct),
        ``survivor_percent`` (survivor_pct) and ``cola_percent`` (cola_pct).

        Args:
            owner: The person to which this annuity belongs
            annuity_type: The type of annuity
            balance: Starting balance in the annuity
            rate_pct: Annual interest rate percentage (the credited rate in accumulation, and
                the pricing rate at annuitization). If None: the configured default, except that a
                VARIABLE annuity's accumulation balance then tracks the economy's equity return.
            payout_type: How the annuity pays out
            payout_start_age: Age at which the contract annuitizes automatically. If None: an
                IMMEDIATE annuity annuitizes at once, a DEFERRED one at the configured
                ``insurance.annuity.default_payout_start_age``, and a FIXED or VARIABLE one stays in
                accumulation (it can still be annuitized explicitly with :meth:`annuitize`).
            payout_monthly: Fixed monthly payout amount (calculated if None)
            period_certain_years: Years of guaranteed payments for period certain. Configured default if None.
            surrender_charge_years: Years during which surrender charges apply. Configured default if None.
            surrender_charge_pct: Annual surrender charge rate percentage. Configured default if None.
            joint_annuitant: JOINT_AND_SURVIVOR only: the second life. Defaults to the owner's spouse
                at annuitization; annuitizing without one raises ``ValueError``.
            survivor_pct: JOINT_AND_SURVIVOR only: share of the payment continued to the joint
                annuitant after the owner dies (e.g. 50.0 for joint-and-50%-survivor).
            basis: An existing contract's cost basis (after-tax money paid in; keyword-only, Plan 27
                D1). Defaults to ``balance`` (no gain) for a non-qualified contract.
            purchase_year: Year the contract was bought (the surrender-charge clock and the
                period-certain guarantee count from it). Defaults to the current year.
            qualified: Held in a qualified plan or IRA (bought with pre-tax money): no basis, every
                payout and withdrawal is taxable as a pension/annuity distribution (a 10% additional
                tax before 59.5).
            in_payout: An annuity already paying (an existing SPIA): ``monthly_payout`` is paid for
                life (and to the joint annuitant / for the rest of the period certain under the payout
                type) by the insurer; there is no reserve on the balance sheet (an income stream,
                like a pension). Needs ``payout_monthly``.
            cola_pct: Yearly increase of the payout once in payout (a COLA rider).

        Note:
            Payout taxation uses a simplified exclusion-ratio model (basis / expected total
            payout). Real rules differ for qualified vs non-qualified annuities; this is an
            approximation.
        """
        person, initial_balance, interest_rate, monthly_payout = owner, balance, rate_pct, payout_monthly
        surrender_charge_rate, survivor_percent, cola_percent = surrender_charge_pct, survivor_pct, cola_pct
        super().__init__(cast(LifeModel, person.model))
        self.model: LifeModel = cast("LifeModel", self.model)
        annuity_config = self.model.config.insurance.annuity
        # A VARIABLE contract with no stated rate is invested in the market: its accumulation
        # balance follows the economy's equity return (the configured rate still prices payouts).
        self.tracks_equity = annuity_type == AnnuityType.VARIABLE and interest_rate is None
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
        if payout_start_age is None:
            if annuity_type == AnnuityType.IMMEDIATE:
                payout_start_age = person.age
            elif annuity_type == AnnuityType.DEFERRED:
                payout_start_age = annuity_config.default_payout_start_age
            # FIXED / VARIABLE: None = stay in accumulation (no automatic annuitization).
        self.payout_start_age: float | None = payout_start_age
        self.monthly_payout = monthly_payout
        self.period_certain_years = period_certain_years
        self.surrender_charge_years = surrender_charge_years
        self.surrender_charge_rate = surrender_charge_rate

        # Cost basis (after-tax investment in the contract) used for exclusion-ratio taxation.
        self.qualified = qualified
        if qualified:
            if basis:
                raise ValueError("a qualified annuity has no after-tax basis")
            basis = 0.0
        self.basis = initial_balance if basis is None else float(basis)
        self.cola_percent = cola_percent

        self.joint_annuitant = joint_annuitant
        self.survivor_percent = survivor_percent
        # Set when the owner dies and payments continue: period-certain payments run out the
        # guarantee; a joint-and-survivor contract pays the survivor share.
        self.annuitant_deceased = False
        self.survivor_phase = False

        # State tracking
        self.is_active = True
        self.is_annuitized = False
        self.annuitization_year: int | None = None
        self.purchase_year = self.model.year if purchase_year is None else int(purchase_year)
        if self.purchase_year > self.model.year:
            raise ValueError(f"purchase_year {purchase_year} is after the current year {self.model.year}")
        self.remaining_period_certain_payments = 0
        #: An existing contract in payout: the insurer pays ``monthly_payout`` (no reserve modeled).
        self.insurer_funded = in_payout

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
        self.model.ledger.post_opening(self, initial_balance)
        if in_payout:
            self._start_existing_payout()

    def _start_existing_payout(self) -> None:
        """An annuity already in payout: annuitized at purchase, paying the stated monthly payout."""
        if self.monthly_payout is None or self.monthly_payout <= 0:
            raise ValueError("an annuity in payout (in_payout=True) needs its monthly_payout")
        if self.balance:
            raise ValueError("an annuity in payout has no accumulation balance (initial_balance must be 0)")
        self.is_annuitized = True
        self.annuitization_year = self.purchase_year
        if self.payout_type == AnnuityPayoutType.JOINT_AND_SURVIVOR:
            self.joint_annuitant = self._joint_life()
        if self.payout_type == AnnuityPayoutType.LIFE_WITH_PERIOD_CERTAIN:
            elapsed = 12 * (self.model.year - self.purchase_year)
            self.remaining_period_certain_payments = max(0, self.period_certain_years * 12 - elapsed)
        gender = getattr(self.person, "gender", None)
        joint_kwargs: dict[str, Any] = {}
        if self.payout_type == AnnuityPayoutType.JOINT_AND_SURVIVOR:
            joint = self.joint_annuitant
            joint_kwargs = {
                "joint_age": joint.age,
                "joint_gender": getattr(joint, "gender", None),
                "survivor_percent": self.survivor_percent,
            }
        # The exclusion ratio over the payments still expected (Pub. 939 would use the expected return
        # at the annuity starting date; the remaining basis over today's expectation is equivalent for
        # a contract whose basis is not yet recovered).
        expected_total = self.monthly_payout * self._expected_payout_months(gender, **joint_kwargs)
        self.exclusion_ratio = min(1.0, self.basis / expected_total) if expected_total > 0 else 0.0

    def collect_stats(self):
        """Year-end value: the accumulation balance plus the annuitized reserve, while in force."""
        self.stat_annuity_balance = self.balance + self.annuitized_reserve if self.is_active else 0.0

    def _close(self, cause: str) -> None:
        """End the contract; whatever value it still holds goes to the insurer (posted as forfeited)."""
        remaining = self.balance + self.annuitized_reserve
        if self.is_active and remaining:
            self.model.ledger.post(
                remaining, FlowKind.FORFEIT, from_account=self, sink="insurer", cause=cause, agent=self.person
            )
        self.is_active = False

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
        """Whether the contract has reached its automatic annuitization age (never, when it has none)."""
        return self.payout_start_age is not None and self.person.age_years_fractional >= self.payout_start_age

    @property
    def accumulation_rate(self) -> float:
        """This year's credited rate (percent) on the accumulation balance."""
        if self.tracks_equity:
            return self.model.economy.equity_return(self.model.year)
        return self.interest_rate

    @property
    def monthly_accumulation_rate(self) -> float:
        """This month's credited rate (percent) on the accumulation balance."""
        if self.tracks_equity:
            return self.model.economy.monthly_rate("equity_return")
        return annual_to_monthly(self.interest_rate)

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
        remaining_balance = self.person.deduct_from_bank_accounts(
            amount, kind=FlowKind.CONTRIBUTION, to_account=self, cause="annuity deposit"
        )
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
        # Before annuitization gains come out first (IRC §72(e)): the amount received is ordinary
        # income up to the contract's gain, and only the rest returns basis.
        taxable = min(net_withdrawal, max(0.0, self.balance - self.basis))
        self.basis = max(0.0, self.basis - (net_withdrawal - taxable))
        self.balance -= withdrawal_amount
        self._tax_distribution(taxable)

        self.person.receive_cash(
            net_withdrawal, source="annuity withdrawal", kind=FlowKind.WITHDRAWAL, from_account=self
        )
        self.model.ledger.post(
            surrender_charge,
            FlowKind.FORFEIT,
            from_account=self,
            sink="insurer: surrender charge",
            cause="annuity withdrawal surrender charge",
            agent=self.person,
        )

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

    def _tax_distribution(self, taxable: float) -> None:
        """Record a pre-annuitization distribution's gain: ordinary income, plus the 10% additional
        tax before the federal retirement age (IRC §72(q), same rate as §72(t))."""
        if taxable <= 0:
            return
        income_type = IncomeType.PENSION if self.qualified else IncomeType.ORDINARY
        self.person.income.add(income_type, taxable, source="annuity")
        self.stat_taxable_payouts += taxable
        self.person.income.add_penalty(
            self.person.early_withdrawal_penalty(taxable), source="annuity_early_distribution"
        )

    def _joint_life(self) -> Person:
        """The joint annuitant for a JOINT_AND_SURVIVOR contract (defaults to the living spouse)."""
        joint = self.joint_annuitant or self.person.spouse
        if joint is None or joint.is_deceased:
            raise ValueError(
                f"{self.person.name}'s joint-and-survivor annuity needs a living joint annuitant (e.g. a spouse)"
            )
        return joint

    def annuitize(self) -> bool:
        """Convert the annuity to income payments"""
        if self.is_annuitized or not self.is_active or self.balance <= 0:
            return False

        if self.payout_start_age is None:
            # An accumulation-only contract annuitizes when the owner elects to, at today's age.
            self.payout_start_age = self.person.age
        elif not self.is_payout_eligible:
            return False

        self.is_annuitized = True
        self.annuitization_year = self.model.year

        gender = getattr(self.person, "gender", None)
        joint_kwargs: dict[str, Any] = {}
        if self.payout_type == AnnuityPayoutType.JOINT_AND_SURVIVOR:
            joint = self._joint_life()
            self.joint_annuitant = joint
            joint_kwargs = {
                "joint_age": joint.age,
                "joint_gender": getattr(joint, "gender", None),
                "survivor_percent": self.survivor_percent,
            }

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
                config=self.model.config,
                **joint_kwargs,
            )

            # Calculate monthly payment: balance divided by annuity factor
            if annuity_factor > 0:
                self.monthly_payout = self.balance / annuity_factor
            else:
                # Fallback to simple calculation if factor is zero
                life_expectancy = calculate_life_expectancy(self.person.age, gender, self.model.config)
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
        expected_months = self._expected_payout_months(gender, **joint_kwargs)
        expected_total_payout = (self.monthly_payout or 0.0) * expected_months
        if expected_total_payout > 0:
            self.exclusion_ratio = min(1.0, self.basis / expected_total_payout)
        else:
            self.exclusion_ratio = 1.0

        self.model.event_log.add(
            Event(
                EventKind.ANNUITIZED,
                person=self.person,
                amount=self.annuitized_reserve,
                account=self,
                message=f"{self.person.name} annuitized with ${self.monthly_payout:,.0f}/month payments",
                monthly_payout=self.monthly_payout,
            )
        )
        return True

    def _expected_payout_months(self, gender: GenderAtBirth | None, **joint_kwargs) -> float:
        """Expected number of (full) monthly payouts, used for the exclusion ratio."""
        if self.payout_type == AnnuityPayoutType.JOINT_AND_SURVIVOR:
            # The undiscounted factor is the expected number of full payments over both lives.
            return calculate_annuity_factor(
                self.person.age, 0.0, self.payout_type, gender=gender, config=self.model.config, **joint_kwargs
            )
        life_months = calculate_life_expectancy(self.person.age, gender, self.model.config) * 12
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

        if self.annuitized_reserve <= 0 and not self.insurer_funded:
            # Reserve exhausted: guaranteed payments already accounted for; stop paying.
            self._close("annuity reserve exhausted")
            return 0.0

        if (
            self.annuitant_deceased
            and self.payout_type == AnnuityPayoutType.LIFE_WITH_PERIOD_CERTAIN
            and self.remaining_period_certain_payments <= 0
        ):
            # The annuitant died and the guaranteed period has run out: the contract is complete.
            self._close("period-certain guarantee ended after the annuitant's death")
            return 0.0

        scheduled = self.monthly_payout or 0.0
        if self.survivor_phase:
            scheduled *= self.survivor_percent / 100
        payout = scheduled if self.insurer_funded else min(scheduled, self.annuitized_reserve)
        if payout <= 0:
            return 0.0

        if not self.insurer_funded:
            self.annuitized_reserve -= payout
        self.stat_payouts_received += payout

        # Tax the gains portion as ordinary income (exclusion ratio covers return of basis); once the
        # basis is recovered every payment is taxable (IRC §72(b)(2)).
        excluded = min(payout * self.exclusion_ratio, self.basis)
        self.basis -= excluded
        taxable_portion = payout - excluded
        if taxable_portion > 0:
            income_type = IncomeType.PENSION if self.qualified else IncomeType.ORDINARY
            self.person.income.add(income_type, taxable_portion, source="annuity")
            self.stat_taxable_payouts += taxable_portion

        # Deposit the payout into the person's bank account.
        if self.insurer_funded:
            self.person.receive_cash(
                payout, source="insurer: annuity payout", kind=FlowKind.BENEFIT, cause="annuity payout"
            )
        else:
            self.person.receive_cash(
                payout, source="annuity payout", kind=FlowKind.WITHDRAWAL, from_account=self, cause="annuity payout"
            )

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

        # The gain over basis is ordinary income (a loss is not deducted).
        self._tax_distribution(max(0.0, net_value - self.basis))
        self.basis = 0.0
        self.person.receive_cash(net_value, source="annuity surrender", kind=FlowKind.WITHDRAWAL, from_account=self)
        self.model.ledger.post(
            surrender_charge,
            FlowKind.FORFEIT,
            from_account=self,
            sink="insurer: surrender charge",
            cause="annuity surrender charge",
            agent=self.person,
        )

        self.model.event_log.add(
            Event(f"{self.person.name} surrendered annuity for ${net_value:,.0f} (${surrender_charge:,.0f} charge)")
        )

        self.balance = 0.0
        self.is_active = False

        return net_value

    def step(self):
        """Credit the month's interest to the reserve (annuitized) or the accumulation balance."""
        if not self.is_active:
            return

        # Apply interest growth to the reserve (annuitized) or the accumulation balance.
        interest_earned = 0.0
        if self.is_annuitized:
            if self.annuitized_reserve > 0:
                interest_earned = self.annuitized_reserve * (annual_to_monthly(self.interest_rate) / 100)
                self.annuitized_reserve += interest_earned
                self.stat_interest_earned += interest_earned
        elif self.balance > 0:
            interest_earned = self.balance * (self.monthly_accumulation_rate / 100)
            self.balance += interest_earned
            self.stat_interest_earned += interest_earned
        self.model.ledger.post(
            interest_earned, FlowKind.GROWTH, to_account=self, source="insurer: credited interest", agent=self.person
        )

        self.stat_balance = self.balance
        self.stat_annuitized_reserve = self.annuitized_reserve

    def pre_step(self):
        """Auto-annuitize when eligible, then make the month's payout (its taxable portion lands on
        the income ledger for the year's return)."""
        # Auto-annuitize once the contract's payout age is reached (immediately for IMMEDIATE).
        if not self.is_annuitized and self.is_active and self.is_payout_eligible:
            self.annuitize()

        if self.is_annuitized and self.is_active:
            self.make_payout()

    def on_year_end(self):
        """A COLA rider raises the payout once a year while in payout."""
        if self.cola_percent and self.is_annuitized and self.is_active and self.monthly_payout:
            self.monthly_payout *= 1 + self.cola_percent / 100

    def settle_owner_death(self, inheritor: Person | None) -> None:
        """Apply the contract's death terms when its current owner dies.

        - Accumulation phase: the contract value is paid to the inheritor as a death benefit, its
          gain taxed to them as ordinary income (it would otherwise vanish with the owner).
        - Life only: payments stop.
        - Life with period certain: the rest of the guarantee is paid to the inheritor, then stops.
        - Joint and survivor: the joint annuitant receives ``survivor_percent`` of the payment for
          life; at the survivor's own death the contract ends.
        """
        owner = self.person
        if not self.is_active:
            return
        registry = self.model.registries.annuities
        if not self.is_annuitized:
            if inheritor is not None and self.balance > 0:
                gain = max(0.0, self.balance - self.basis)
                if gain > 0:
                    inheritor.income.add(IncomeType.ORDINARY, gain, source="annuity_death_benefit")
                inheritor.receive_cash(
                    self.balance,
                    source=f"{owner.name}'s annuity death benefit",
                    kind=FlowKind.INHERITANCE,
                    from_account=self,
                    cause=f"{owner.name}'s annuity death benefit",
                )
                self.balance = 0.0
            self._close(f"{owner.name}'s annuity ended at death with no heir")
            registry.unregister(owner, self)
            return
        if self.payout_type == AnnuityPayoutType.JOINT_AND_SURVIVOR:
            joint = self.joint_annuitant
            if self.survivor_phase or joint is None or joint is owner or joint.is_deceased:
                self._close(f"joint-and-survivor annuity ended at {owner.name}'s death")
                registry.unregister(owner, self)
                return
            # Continue to the joint annuitant (not the residual inheritor) at the survivor share.
            registry.unregister(owner, self)
            registry.register(joint, self)
            self.person = joint
            self.annuitant_deceased = True
            self.survivor_phase = True
            return
        if (
            self.payout_type == AnnuityPayoutType.LIFE_WITH_PERIOD_CERTAIN
            and self.remaining_period_certain_payments > 0
            and inheritor is not None
        ):
            self.annuitant_deceased = True  # the estate transfer moves it to the inheritor
            return
        self._close(f"life annuity ended at {owner.name}'s death")
        registry.unregister(owner, self)

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
