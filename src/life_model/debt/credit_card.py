# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html
from enum import Enum
from typing import Optional

from ..model import LifeModelAgent
from ..people.person import Person


class CreditCardType(Enum):
    """Types of credit cards"""

    VISA = "Visa"
    MASTERCARD = "MasterCard"
    AMERICAN_EXPRESS = "American Express"
    DISCOVER = "Discover"
    STORE_CARD = "Store Card"


class PaymentStrategy(Enum):
    """How a revolving-debt balance is paid down each month."""

    MINIMUM = "minimum"  # Pay only the required minimum (max of a % of balance and a dollar floor).
    FULL_BALANCE = "full_balance"  # Pay the whole balance every month (carries no interest after month 1).
    FIXED = "fixed"  # Pay a fixed dollar amount each month.


class RevolvingDebt(LifeModelAgent):
    """Open-ended revolving debt (e.g. a credit card).

    Unlike an amortizing :class:`~life_model.base_classes.Loan`, revolving debt has no fixed term:
    it carries a ``balance`` that compounds monthly and is paid down according to a
    :class:`PaymentStrategy`. The minimum payment is recomputed from the current balance every
    month (a percentage of balance, floored at a dollar amount), so it tracks the balance instead
    of being frozen at construction.
    """

    def __init__(
        self,
        person: Person,
        name: str,
        credit_limit: float,
        balance: float = 0,
        yearly_interest_rate: Optional[float] = None,
        minimum_payment_percent: Optional[float] = None,
        minimum_payment_floor: Optional[float] = None,
        payment_strategy: "PaymentStrategy" = PaymentStrategy.MINIMUM,
        fixed_payment: float = 0.0,
    ):
        """Revolving debt.

        Args:
            person: The person who owns this debt.
            name: Name of the account / issuer.
            credit_limit: Credit limit.
            balance: Current balance owed.
            yearly_interest_rate: Annual interest rate percentage (defaults from config).
            minimum_payment_percent: Minimum payment as a percentage of balance (defaults from config).
            minimum_payment_floor: Dollar floor on the minimum payment (defaults from config).
            payment_strategy: How the balance is paid down each month.
            fixed_payment: Monthly payment when ``payment_strategy`` is ``FIXED``.
        """
        super().__init__(person.model)
        config = person.model.config.debt.credit_card
        if yearly_interest_rate is None:
            yearly_interest_rate = config.default_interest_rate
        if minimum_payment_percent is None:
            minimum_payment_percent = config.default_minimum_payment_percent
        if minimum_payment_floor is None:
            minimum_payment_floor = config.default_minimum_payment_floor

        self.person = person
        self.name = name
        self.credit_limit = credit_limit
        self.balance = balance
        self.yearly_interest_rate = yearly_interest_rate
        self.minimum_payment_percent = minimum_payment_percent
        self.minimum_payment_floor = minimum_payment_floor
        self.payment_strategy = payment_strategy
        self.fixed_payment = fixed_payment

        # Interest charged over the current year, captured as the year is serviced.
        self.interest_paid_this_year = 0.0

        self.stat_principal_payment_history = []
        self.stat_interest_payment_history = []
        self.stat_balance_history = []

        self.model.registries.credit_cards.register(person, self)

    # ``principal`` mirrors ``balance`` so revolving debt reads uniformly with amortizing loans
    # (net-worth aggregation, payment code, and tests can use either name).
    @property
    def principal(self) -> float:
        return self.balance

    @principal.setter
    def principal(self, value: float) -> None:
        self.balance = value

    @property
    def monthly_interest_rate(self) -> float:
        """Per-month interest rate as a fraction (credit cards compound monthly)."""
        return self.yearly_interest_rate / (100 * 12)

    @property
    def monthly_payment(self) -> float:
        """The payment that would be made this month under the current strategy."""
        return self._scheduled_payment()

    def get_available_credit(self) -> float:
        """Get available credit remaining"""
        return max(0, self.credit_limit - self.balance)

    def charge(self, amount: float) -> bool:
        """Charge amount to the card. Returns success status."""
        if amount < 0:
            raise ValueError("Cannot charge negative amounts")
        if amount == 0:
            return True  # No-op for zero charges
        if amount <= self.get_available_credit():
            self.balance += amount
            return True
        return False

    def get_interest_amount(self, period: str = "month") -> float:
        """Interest accrued on the current balance for one period (monthly default)."""
        annual = self.balance * (self.yearly_interest_rate / 100)
        if period == "year":
            return annual
        if period == "month":
            return annual / 12
        raise ValueError(f"Unknown period {period!r}; expected 'month' or 'year'")

    def get_minimum_payment(self) -> float:
        """Minimum payment required this month, recomputed from the current balance."""
        if self.balance <= 0:
            return 0.0
        calculated_minimum = self.balance * (self.minimum_payment_percent / 100)
        return max(self.minimum_payment_floor, calculated_minimum)

    def _scheduled_payment(self) -> float:
        """The payment amount for the current month under the active strategy."""
        if self.balance <= 0:
            return 0.0
        if self.payment_strategy is PaymentStrategy.FULL_BALANCE:
            # Enough to clear the balance plus this month's interest.
            return self.balance + self.get_interest_amount("month")
        if self.payment_strategy is PaymentStrategy.FIXED:
            return self.fixed_payment
        return self.get_minimum_payment()

    def make_payment(self, payment_amount: float, extra_to_principal: float = 0) -> float:
        """Apply a single monthly payment (interest first, then balance).

        The balance is clamped at zero; a payment that doesn't cover interest grows the balance
        (negative amortization).
        """
        if payment_amount < 0:
            raise ValueError("Payment amount cannot be negative")
        if extra_to_principal < 0:
            raise ValueError("Extra principal payment cannot be negative")

        monthly_interest = self.get_interest_amount("month")
        actual_interest_payment = min(payment_amount, monthly_interest)
        available_for_principal = payment_amount - actual_interest_payment
        total_principal_payment = available_for_principal + extra_to_principal
        principal_payment = min(total_principal_payment, self.balance)

        unpaid_interest = monthly_interest - actual_interest_payment
        self.balance = max(0.0, self.balance - principal_payment + unpaid_interest)

        self.stat_principal_payment_history.append(principal_payment)
        self.stat_interest_payment_history.append(actual_interest_payment)

        return actual_interest_payment + principal_payment

    def service_year(self) -> float:
        """Service this debt for one simulated year (twelve monthly payments by strategy).

        Returns the total cash paid this year; ``interest_paid_this_year`` is updated.
        """
        total_paid = 0.0
        interest_this_year = 0.0
        for _ in range(12):
            if self.balance <= 0:
                break
            total_paid += self.make_payment(self._scheduled_payment())
            interest_this_year += self.stat_interest_payment_history[-1]
        self.interest_paid_this_year = interest_this_year
        return total_paid

    def step(self):
        """Track balance history."""
        self.stat_balance_history.append(self.balance)

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Card: {html.escape(self.name)}</li>"
        desc += f"<li>Credit Limit: ${self.credit_limit:,.2f}</li>"
        desc += f"<li>Current Balance: ${self.balance:,.2f}</li>"
        desc += f"<li>Available Credit: ${self.get_available_credit():,.2f}</li>"
        desc += f"<li>Interest Rate: {self.yearly_interest_rate}%</li>"
        desc += f"<li>Minimum Payment: ${self.get_minimum_payment():,.2f}</li>"
        desc += "</ul>"
        return desc


class CreditCard(RevolvingDebt):
    """A credit card: revolving debt with a card name and (optional) network type."""

    def __init__(
        self,
        person: Person,
        card_name: str,
        credit_limit: float,
        current_balance: float = 0,
        yearly_interest_rate: Optional[float] = None,
        minimum_payment_percent: Optional[float] = None,
        card_type: Optional[CreditCardType] = None,
        payment_strategy: "PaymentStrategy" = PaymentStrategy.MINIMUM,
        fixed_payment: float = 0.0,
    ):
        """Models a credit card for a person.

        Args:
            person: The person who owns this credit card.
            card_name: Card issuing company.
            credit_limit: Credit limit on the card.
            current_balance: Current balance owed.
            yearly_interest_rate: Annual interest rate percentage.
            minimum_payment_percent: Minimum payment as percentage of balance.
            card_type: Card network (Visa, MasterCard, ...).
            payment_strategy: How the balance is paid down each month.
            fixed_payment: Monthly payment when ``payment_strategy`` is ``FIXED``.
        """
        super().__init__(
            person,
            card_name,
            credit_limit,
            balance=current_balance,
            yearly_interest_rate=yearly_interest_rate,
            minimum_payment_percent=minimum_payment_percent,
            payment_strategy=payment_strategy,
            fixed_payment=fixed_payment,
        )
        self.card_name = card_name
        self.card_type = card_type
