# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from enum import Enum
from typing import ClassVar, cast

from ..ledger import FlowKind
from ..model import Event, EventKind, LifeModel, LifeModelAgent, compound_interest
from ..people.person import Person
from ..tax.income import IncomeType


class LifeInsuranceType(Enum):
    """Enum for life insurance types"""

    TERM = "Term"
    WHOLE = "Whole"


class PremiumIncreaseType(Enum):
    """How a policy's premium changes over time."""

    #: The premium never changes (the default: a level-premium term policy; whole life).
    LEVEL = "level"
    #: Re-priced every year from age-band multipliers on the base premium (annually renewable term).
    AGE_BANDED = "age_banded"
    #: Deprecated name for :attr:`AGE_BANDED` (an alias of the same member).
    AGE_BASED = "age_banded"  # noqa: PIE796 - deliberate alias of AGE_BANDED
    #: Grows by a fixed percentage each year.
    YEARLY = "yearly"


class LifeInsurance(LifeModelAgent):
    """A life insurance policy: the year's premium is charged once a year, in the first month of the
    year; at year end the premium is re-priced, whole-life cash value and policy loans accrue a year
    of growth and interest, and an over-borrowed policy lapses."""

    STATS_OWNED = frozenset({"stat_premium_payments", "stat_cash_value", "stat_death_benefit_paid"})

    # The premium's affordability check reads the household's balances, so it runs after the
    # month's income and benefits have been deposited (pre_step 0), whatever the construction order.
    # The year-end update runs before the tax settlement (0): a lapse's taxable gain is this year's.
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"pre_step": 10, "on_year_end": -5}

    def __init__(
        self,
        person: Person,
        policy_type: LifeInsuranceType,
        death_benefit: float,
        monthly_premium: float,
        term_years: int | None = None,
        premium_increase_rate: "float | dict | PremiumIncreaseType | None" = None,
        cash_value_growth_rate: float | None = None,
        loan_interest_rate: float | None = None,
        max_missed_payments: int | None = None,
        *,
        beneficiary: Person | None = None,
    ):
        """Models life insurance policy for a person

        Args:
            person: The person to which this policy belongs
            policy_type: The type of life insurance policy
            death_benefit: Amount paid out on death
            monthly_premium: Monthly premium cost
            term_years: Number of years for term life (None for whole life)
            premium_increase_rate: How the premium changes: ``None`` / ``0`` /
                ``PremiumIncreaseType.LEVEL`` keep it level (the default: a level-premium term policy,
                and an inflation-free whole-life premium); a positive number grows it that many
                percent a year; ``PremiumIncreaseType.AGE_BANDED`` re-prices a term policy every year
                from the configured age-band multipliers (``insurance.life.term_age_multipliers``);
                a dict ``{age: multiplier}`` does the same with custom bands.
            cash_value_growth_rate: Yearly growth rate for whole life cash value. Uses configured default if None.
            loan_interest_rate: Interest rate for loans against cash value. Uses configured default if None.
            max_missed_payments: Maximum consecutive missed payments before lapse. Uses configured default if None.
            beneficiary: Optional designated beneficiary for the death benefit. When set (and
                surviving), the benefit is paid to this person; otherwise it defaults to the
                surviving spouse, then the first family member with a bank account.
        """
        super().__init__(cast(LifeModel, person.model))
        self.model: LifeModel = cast("LifeModel", self.model)  # Type override for better intellisense
        life_config = self.model.config.insurance.life
        if cash_value_growth_rate is None:
            cash_value_growth_rate = life_config.default_cash_value_growth_rate
        if loan_interest_rate is None:
            loan_interest_rate = life_config.default_loan_interest_rate
        if max_missed_payments is None:
            max_missed_payments = life_config.default_max_missed_payments
        # Config-driven policy parameters.
        self.loan_to_value_ratio = life_config.loan_to_value_ratio
        self.cash_value_premium_fraction_first_year = life_config.cash_value_premium_fraction_first_year
        self.cash_value_premium_fraction_later = life_config.cash_value_premium_fraction_later
        self.surrender_percentage_early = life_config.surrender_percentages.early
        self.surrender_percentage_standard = life_config.surrender_percentages.standard
        self.person = person
        self.policy_type = policy_type
        self.beneficiary = beneficiary
        self.death_benefit = death_benefit
        self.monthly_premium = monthly_premium
        self.base_monthly_premium = monthly_premium
        self.term_years = term_years
        self.cash_value_growth_rate = cash_value_growth_rate
        self.loan_interest_rate = loan_interest_rate
        self.max_missed_payments = max_missed_payments

        # premium_increase_rate: a dict of age bands, an explicit type, a yearly percent, or None.
        self.yearly_increase_rate = 0.0
        self.age_multipliers: dict = {}
        if isinstance(premium_increase_rate, dict):
            # Custom age-band multipliers
            self.premium_increase_type = PremiumIncreaseType.AGE_BANDED
            self.age_multipliers = premium_increase_rate
        elif premium_increase_rate is PremiumIncreaseType.AGE_BANDED:
            # Configured age-band multipliers (annually renewable term pricing)
            self.premium_increase_type = PremiumIncreaseType.AGE_BANDED
            self.age_multipliers = dict(self.model.config.insurance.life.term_age_multipliers)
        elif premium_increase_rate is PremiumIncreaseType.YEARLY:
            raise ValueError("PremiumIncreaseType.YEARLY needs a rate: pass the yearly percentage instead")
        elif premium_increase_rate is None or premium_increase_rate is PremiumIncreaseType.LEVEL:
            self.premium_increase_type = PremiumIncreaseType.LEVEL
        elif isinstance(premium_increase_rate, (int, float)):
            if premium_increase_rate < 0:
                raise ValueError("premium_increase_rate must be >= 0")
            if premium_increase_rate > 0:
                self.premium_increase_type = PremiumIncreaseType.YEARLY
                self.yearly_increase_rate = float(premium_increase_rate)
            else:
                self.premium_increase_type = PremiumIncreaseType.LEVEL
        else:
            raise TypeError(f"Unsupported premium_increase_rate {premium_increase_rate!r}")

        # Policy state
        self.is_active = True
        self.is_lapsed = False
        self.policy_start_year = self.model.year
        self.consecutive_missed_payments = 0
        self.total_premiums_paid = 0.0

        # Whole life specific
        self.cash_value = 0.0
        self.outstanding_loan_balance = 0.0

        # Statistics tracking
        self.stat_premium_payments = 0.0
        self.stat_cash_value = 0.0
        self.stat_loan_balance = 0.0
        self.stat_death_benefit_paid = 0.0
        self.stat_policy_active = 1

        # Register with the model registry
        self.model.registries.life_insurance_policies.register(person, self)

    @property
    def ledger_value(self) -> float:
        """The policy's value on the household balance sheet: cash value net of policy loans, while
        the policy is in force."""
        return self.cash_value - self.outstanding_loan_balance if self.is_active else 0.0

    def close(self, cause: str) -> None:
        """Take the policy out of force; any cash value net of loans not paid out goes to the insurer
        (a negative value, a loan larger than the cash value, is extinguished). The policy then holds
        no money: its cash value and loan are settled."""
        value = self.ledger_value
        was_active = self.is_active
        self.is_active = False
        if not was_active:
            return
        if value > 0:
            self.model.ledger.post(
                value, FlowKind.FORFEIT, from_account=self, sink="insurer", cause=cause, agent=self.person
            )
        elif value < 0:
            self.model.ledger.post(
                -value,
                FlowKind.BENEFIT,
                to_account=self,
                source="insurer: policy loan extinguished",
                cause=cause,
                agent=self.person,
            )
        self.cash_value = 0.0
        self.outstanding_loan_balance = 0.0

    @property
    def yearly_premium(self) -> float:
        """Calculate yearly premium cost"""
        return self.monthly_premium * 12

    @property
    def available_cash_value(self) -> float:
        """Cash value available for loans (cash value minus outstanding loans)"""
        return max(0, self.cash_value - self.outstanding_loan_balance)

    @property
    def net_death_benefit(self) -> float:
        """Death benefit minus any outstanding loans"""
        return max(0, self.death_benefit - self.outstanding_loan_balance)

    @property
    def policy_years_active(self) -> int:
        """Number of years the policy has been active"""
        return self.model.year - self.policy_start_year

    @property
    def is_term_expired(self) -> bool:
        """Check if term life policy has expired"""
        if self.policy_type == LifeInsuranceType.TERM and self.term_years:
            return self.policy_years_active >= self.term_years
        return False

    def make_premium_payment(self) -> bool:
        """Charge the yearly premium. Returns True if the policy stays paid up.

        An affordable premium goes through the tax unit's bill path (``spending.add_expense``), so it
        is paid at year-end settlement like every other bill and can be funded by a sized
        retirement withdrawal rather than lapsing a cash-poor retiree's policy. "Affordable" means
        the household's settlement-drawable resources cover it. Otherwise a whole-life policy pays
        from cash value; failing that the premium is missed (nothing is partially paid) and the
        policy lapses after ``max_missed_payments`` misses.
        """
        if not self.is_active or self.is_lapsed or self.is_term_expired:
            return False

        yearly_cost = self.yearly_premium
        household = [self.person]
        if self.person.spouse is not None and not self.person.spouse.is_deceased:
            household.append(self.person.spouse)
        amount_paid = 0.0
        if sum(member.spendable_resources for member in household) >= yearly_cost:
            self.person.spending.add_expense(yearly_cost, category="life_insurance_premium")
            amount_paid = yearly_cost

        if amount_paid >= yearly_cost:
            self.total_premiums_paid += yearly_cost
            self.consecutive_missed_payments = 0
            self.stat_premium_payments = yearly_cost

            # For whole life, part of premium goes to cash value
            if self.policy_type == LifeInsuranceType.WHOLE:
                # A configured fraction of premium funds cash value (lower in the first year).
                fraction = (
                    self.cash_value_premium_fraction_later
                    if self.policy_years_active > 0
                    else self.cash_value_premium_fraction_first_year
                )
                cash_value_contribution = yearly_cost * fraction
                self.cash_value += cash_value_contribution
                self.model.ledger.post(
                    cash_value_contribution,
                    FlowKind.PREMIUM,
                    to_account=self,
                    source="insurer: cash value credited from the premium",
                    agent=self.person,
                )

            return True
        else:
            # For whole life, can use cash value to pay premiums
            if self.policy_type == LifeInsuranceType.WHOLE and self.available_cash_value > 0:
                remaining_premium = yearly_cost - amount_paid
                cash_value_used = min(remaining_premium, self.available_cash_value)
                self.cash_value -= cash_value_used
                self.model.ledger.post(
                    cash_value_used,
                    FlowKind.PREMIUM,
                    from_account=self,
                    sink="insurer: premium paid from cash value",
                    agent=self.person,
                )
                amount_paid += cash_value_used

                # If we used any cash value, consider the payment successful
                # (This is common in real life insurance - cash value keeps policy in force)
                if cash_value_used > 0:
                    self.consecutive_missed_payments = 0
                    self.stat_premium_payments = amount_paid
                    return True

            # Payment failed
            self.consecutive_missed_payments += 1
            self.stat_premium_payments = amount_paid

            # Check if policy should lapse
            if self.consecutive_missed_payments >= self.max_missed_payments:
                self.lapse_policy()

            return False

    def lapse_policy(self):
        """Lapse the policy due to non-payment"""
        self.is_lapsed = True
        self.close("life insurance policy lapsed")
        self.model.event_log.add(
            Event(
                EventKind.POLICY_LAPSED,
                person=self.person,
                account=self,
                cause="non-payment",
                message=f"{self.person.name}'s life insurance policy lapsed due to non-payment",
            )
        )

    def drop_policy(self):
        """Voluntarily drop the policy (e.g., when no longer needed)"""
        if not self.is_active:
            return  # already ended (death, lapse, expiry): nothing left to surrender

        # For whole life policies, person gets the cash surrender value
        if self.policy_type == LifeInsuranceType.WHOLE and self.cash_value > 0:
            # Surrender value is a configured fraction of cash value (lower for young policies).
            surrender_percentage = (
                self.surrender_percentage_standard if self.policy_years_active >= 3 else self.surrender_percentage_early
            )
            surrender_value = self.available_cash_value * surrender_percentage

            if surrender_value > 0:
                self.person.deposit_into_bank_account(
                    surrender_value, kind=FlowKind.WITHDRAWAL, from_account=self, cause="life insurance surrender"
                )
                # Gains over the premiums paid (basis) are taxable ordinary income.
                taxable_gain = max(0.0, surrender_value - self.total_premiums_paid)
                if taxable_gain > 0:
                    self.person.income.add(IncomeType.ORDINARY, taxable_gain, source="life_insurance")
                self.model.event_log.add(
                    Event(f"{self.person.name} surrendered life insurance policy for ${surrender_value:,.0f}")
                )
                self.cash_value -= surrender_value
        self.close("life insurance policy dropped (surrender charge)")
        self.cash_value = 0.0
        self.model.event_log.add(Event(f"{self.person.name} voluntarily dropped their life insurance policy"))

    def take_loan(self, loan_amount: float) -> float:
        """Take a loan against cash value (whole life only)"""
        if self.policy_type != LifeInsuranceType.WHOLE or not self.is_active:
            return 0.0

        # Calculate what portion of requested amount can actually be borrowed. The loan is
        # capped at a configured fraction of available cash value (the cap is not a per-request
        # haircut): a request within the cap is fully honored.
        loan_cap = self.available_cash_value * self.loan_to_value_ratio
        actual_loan = min(loan_amount, loan_cap)

        if actual_loan > 0:
            self.outstanding_loan_balance += actual_loan
            self.person.deposit_into_bank_account(
                actual_loan, kind=FlowKind.BORROW, from_account=self, cause="loan against life insurance cash value"
            )
            self.model.event_log.add(Event(f"{self.person.name} took ${actual_loan:,.0f} loan against life insurance"))

        return actual_loan

    def repay_loan(self, repayment_amount: float) -> float:
        """Repay loan against the policy"""
        if not self.is_active or self.outstanding_loan_balance <= 0:
            return 0.0

        actual_repayment = min(repayment_amount, self.outstanding_loan_balance)
        remaining_balance = self.person.deduct_from_bank_accounts(
            actual_repayment, kind=FlowKind.DEBT_SERVICE, to_account=self, cause="life insurance loan repayment"
        )
        amount_paid = actual_repayment - remaining_balance

        self.outstanding_loan_balance -= amount_paid
        return amount_paid

    def process_death_benefit(self):
        """Process death benefit payout"""
        if not self.is_active or self.is_lapsed:
            return 0.0

        benefit_amount = self.net_death_benefit
        if benefit_amount > 0:
            # A designated (surviving) beneficiary takes precedence; otherwise pay the surviving
            # spouse, then the first family member with a bank account.
            paid = {
                "source": "life insurer: death benefit",
                "kind": FlowKind.BENEFIT,
                "cause": f"death benefit on {self.person.name}",
            }
            if self.beneficiary is not None and not self.beneficiary.is_deceased:
                self.beneficiary.deposit_into_bank_account(benefit_amount, **paid)
                recipient = self.beneficiary.name
            elif self.person.spouse and hasattr(self.person.spouse, "deposit_into_bank_account"):
                self.person.spouse.deposit_into_bank_account(benefit_amount, **paid)
                recipient = self.person.spouse.name
            else:
                # Add to family's primary account (first family member with bank account)
                for member in self.person.family.members:
                    if member != self.person and hasattr(member, "bank_accounts") and member.bank_accounts:
                        member.deposit_into_bank_account(benefit_amount, **paid)
                        recipient = member.name
                        break
                else:
                    recipient = "estate"

            self.stat_death_benefit_paid = benefit_amount
            self.model.event_log.add(
                Event(f"Life insurance death benefit of ${benefit_amount:,.0f} paid to {recipient}")
            )

        return benefit_amount

    def pre_step(self):
        """Pay the year's premium in the first month of the year (January, or the start month)."""
        if self.model.is_year_start and self.is_active and not self.is_term_expired:
            self.make_premium_payment()

    def on_year_end(self):
        """Year end: term expiry, premium re-pricing, cash value growth, policy-loan interest, lapse."""
        if not self.is_active:
            self.stat_policy_active = 0
            return

        # Check if term policy has expired
        if self.is_term_expired:
            self.close("term life policy expired")
            self.model.event_log.add(Event(f"{self.person.name}'s term life insurance policy expired"))
            self.stat_policy_active = 0
            return

        # Update premiums based on the premium increase type (LEVEL: unchanged)
        if self.premium_increase_type == PremiumIncreaseType.YEARLY and self.yearly_increase_rate > 0:
            # Yearly percentage increase (term or whole life)
            self.monthly_premium += self.monthly_premium * (self.yearly_increase_rate / 100)
        elif (
            self.policy_type == LifeInsuranceType.TERM and self.premium_increase_type == PremiumIncreaseType.AGE_BANDED
        ):
            # Age-band re-pricing (configured or custom multipliers)
            self.update_term_life_premiums()

        # Grow cash value for whole life policies
        if self.policy_type == LifeInsuranceType.WHOLE and self.cash_value > 0:
            growth = compound_interest(self.cash_value, self.cash_value_growth_rate)
            self.cash_value += growth
            self.model.ledger.post(
                growth, FlowKind.GROWTH, to_account=self, source="insurer: cash value growth", agent=self.person
            )

        # Compound interest on outstanding loans
        if self.outstanding_loan_balance > 0:
            loan_interest = self.outstanding_loan_balance * (self.loan_interest_rate / 100)
            self.outstanding_loan_balance += loan_interest
            self.model.ledger.post(
                loan_interest,
                FlowKind.DEBT_SERVICE,
                from_account=self,
                sink="insurer: policy loan interest",
                agent=self.person,
            )

            # A policy lapses once the loan balance exceeds the cash value securing it. The loan
            # amount over the premiums paid (basis) becomes taxable ordinary income.
            if self.outstanding_loan_balance > self.cash_value:
                taxable_gain = max(0.0, self.outstanding_loan_balance - self.total_premiums_paid)
                if taxable_gain > 0:
                    self.person.income.add(IncomeType.ORDINARY, taxable_gain, source="life_insurance")
                self.model.event_log.add(
                    Event(
                        EventKind.POLICY_LAPSED,
                        person=self.person,
                        amount=self.outstanding_loan_balance,
                        account=self,
                        cause="policy loan exceeded the cash value",
                        message=f"{self.person.name}'s life insurance lapsed: loan balance "
                        f"${self.outstanding_loan_balance:,.0f} exceeded cash value ${self.cash_value:,.0f}",
                    )
                )
                self.lapse_policy()
                self.stat_cash_value = self.cash_value
                self.stat_loan_balance = self.outstanding_loan_balance
                self.stat_policy_active = 0
                return

        # Update stats
        self.stat_cash_value = self.cash_value
        self.stat_loan_balance = self.outstanding_loan_balance
        self.stat_policy_active = 1 if self.is_active else 0

    def calculate_age_based_premium_increase(self) -> float:
        """Calculate realistic age-based premium increase for term life insurance

        Returns the new monthly premium based on current age.
        Term life premiums typically increase exponentially with age.
        """
        if self.policy_type != LifeInsuranceType.TERM:
            return self.monthly_premium

        current_age = self.person.age

        # Find the appropriate multiplier for current age
        multiplier = 1.0
        for age_threshold in sorted(self.age_multipliers.keys()):
            if current_age >= age_threshold:
                multiplier = self.age_multipliers[age_threshold]
            else:
                break

        # Interpolate between age brackets for more realistic pricing
        if current_age not in self.age_multipliers:
            age_brackets = sorted(self.age_multipliers.keys())
            for i in range(len(age_brackets) - 1):
                if age_brackets[i] <= current_age < age_brackets[i + 1]:
                    lower_age = age_brackets[i]
                    upper_age = age_brackets[i + 1]
                    lower_mult = self.age_multipliers[lower_age]
                    upper_mult = self.age_multipliers[upper_age]

                    # Linear interpolation
                    age_progress = (current_age - lower_age) / (upper_age - lower_age)
                    multiplier = lower_mult + (upper_mult - lower_mult) * age_progress
                    break

        return self.base_monthly_premium * multiplier

    def update_term_life_premiums(self):
        """Update term life insurance premiums based on current age"""
        if self.policy_type == LifeInsuranceType.TERM:
            old_premium = self.monthly_premium
            self.monthly_premium = self.calculate_age_based_premium_increase()

            # Log significant premium increases (>20%)
            if self.monthly_premium > old_premium * 1.2:
                increase_pct = ((self.monthly_premium - old_premium) / old_premium) * 100
                self.model.event_log.add(
                    Event(
                        f"{self.person.name}'s term life premium increased {increase_pct:.0f}% "
                        f"(${old_premium:.0f} -> ${self.monthly_premium:.0f}/month) due to age"
                    )
                )

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Policy Type: {self.policy_type.value}</li>"
        desc += f"<li>Death Benefit: ${self.death_benefit:,}</li>"
        desc += f"<li>Monthly Premium: ${self.monthly_premium:,.2f}</li>"
        if self.policy_type == LifeInsuranceType.TERM and self.term_years:
            desc += f"<li>Term: {self.term_years} years</li>"
        if self.policy_type == LifeInsuranceType.WHOLE:
            desc += f"<li>Cash Value: ${self.cash_value:,.2f}</li>"
            if self.outstanding_loan_balance > 0:
                desc += f"<li>Outstanding Loan: ${self.outstanding_loan_balance:,.2f}</li>"
        desc += f"<li>Status: {'Active' if self.is_active else 'Lapsed'}</li>"
        desc += "</ul>"
        return desc
