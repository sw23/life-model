# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from enum import Enum
from ..person import Person
from ..base_classes import Loan


class CreditCardType(Enum):
    """Types of credit cards"""
    VISA = "Visa"
    MASTERCARD = "MasterCard"
    AMERICAN_EXPRESS = "American Express"
    DISCOVER = "Discover"
    STORE_CARD = "Store Card"


class CreditCard(Loan):
    def __init__(self, person: Person, card_name: str, credit_limit: float,
                 current_balance: float = 0, yearly_interest_rate: float = 18.0,
                 minimum_payment_percent: float = 2.0):
        """ Models a credit card for a person

        Args:
            person: The person who owns this credit card
            card_name: Card issuing company
            credit_limit: Credit limit on the card
            current_balance: Current balance owed
            yearly_interest_rate: Annual interest rate percentage
            minimum_payment_percent: Minimum payment as percentage of balance
        """
        # Credit cards don't have a fixed term, so we'll use a default
        super().__init__(person, current_balance, yearly_interest_rate,
                         length_years=0, principal=current_balance)
        self.card_name = card_name
        self.credit_limit = credit_limit
        self.minimum_payment_percent = minimum_payment_percent

    def get_available_credit(self) -> float:
        """Get available credit remaining"""
        return max(0, self.credit_limit - self.principal)

    def charge(self, amount: float) -> bool:
        """Charge amount to credit card. Returns success status"""
        if amount <= self.get_available_credit():
            self.principal += amount
            return True
        return False

    def get_minimum_payment(self) -> float:
        """Calculate minimum payment required"""
        return max(25, self.principal * (self.minimum_payment_percent / 100))

    def make_payment(self, payment_amount: float, extra_to_principal: float = 0) -> float:
        """Make credit card payment"""
        interest_amount = self.get_interest_amount() / 12  # Monthly interest
        principal_payment = payment_amount - interest_amount + extra_to_principal

        # Ensure we don't pay more than the balance
        principal_payment = min(principal_payment, self.principal)
        total_payment = principal_payment + interest_amount

        self.principal -= principal_payment

        # Track statistics
        self.stat_principal_payment_history.append(principal_payment)
        self.stat_interest_payment_history.append(interest_amount)

        return total_payment

    def _repr_html_(self):
        desc = '<ul>'
        desc += f'<li>Card: {self.card_name}</li>'
        desc += f'<li>Credit Limit: ${self.credit_limit:,.2f}</li>'
        desc += f'<li>Current Balance: ${self.principal:,.2f}</li>'
        desc += f'<li>Available Credit: ${self.get_available_credit():,.2f}</li>'
        desc += f'<li>Interest Rate: {self.yearly_interest_rate}%</li>'
        desc += f'<li>Minimum Payment: ${self.get_minimum_payment():,.2f}</li>'
        desc += '</ul>'
        return desc
