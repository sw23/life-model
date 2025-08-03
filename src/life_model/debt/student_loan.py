# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html
from enum import Enum
from typing import Optional
from ..people.person import Person
from ..base_classes import Loan


class StudentLoanType(Enum):
    """ Enum for student loan types """
    FEDERAL_SUBSIDIZED = "Federal Subsidized"
    FEDERAL_UNSUBSIDIZED = "Federal Unsubsidized"
    PRIVATE = "Private"
    PLUS = "PLUS"


class StudentLoan(Loan):
    def __init__(self, person: Person, loan_type: StudentLoanType, loan_amount: float,
                 yearly_interest_rate: float, length_years: int,
                 school_name: str, principal: Optional[float] = None,
                 monthly_payment: Optional[float] = None):
        """ Models a student loan for a person

        Args:
            person: The person to which this loan belongs
            loan_type: Type of student loan
            loan_amount: Original amount of the loan
            yearly_interest_rate: Annual interest rate percentage
            length_years: Length of loan in years
            school_name: Name of the educational institution
            principal: Current principal balance (defaults to loan_amount)
            monthly_payment: Monthly payment amount (calculated if not provided)
        """
        super().__init__(person, loan_amount, yearly_interest_rate, length_years,
                         principal, monthly_payment)
        self.loan_type = loan_type
        self.school_name = school_name

    def get_monthly_payment(self) -> float:
        """ Calculate monthly payment using standard loan formula """
        return self.calculate_monthly_payment()

    def make_payment(self, payment_amount: float, extra_to_principal: float = 0) -> float:
        """Make student loan payment"""
        # Validate inputs
        if payment_amount < 0:
            raise ValueError("Payment amount cannot be negative")
        if extra_to_principal < 0:
            raise ValueError("Extra principal payment cannot be negative")

        if payment_amount == 0 and extra_to_principal == 0:
            # No payment made, but interest still accrues (negative amortization)
            monthly_interest = self.get_interest_amount() / 12
            self.principal += monthly_interest

            # Track statistics
            self.stat_principal_payment_history.append(0.0)
            self.stat_interest_payment_history.append(0.0)

            return 0.0

        # Calculate monthly interest
        monthly_interest = self.get_interest_amount() / 12

        # Calculate how much goes to principal from the regular payment
        available_for_principal = payment_amount - monthly_interest

        # Principal payment cannot be negative and cannot exceed current principal balance
        # Include extra principal in the total principal payment
        total_principal_payment = max(0, available_for_principal) + extra_to_principal
        principal_payment = min(total_principal_payment, self.principal)

        # Calculate actual total payment made
        # If payment_amount < monthly_interest, we only get partial interest payment
        actual_interest_payment = min(payment_amount, monthly_interest)
        total_payment = actual_interest_payment + principal_payment

        # Update principal balance
        # If payment doesn't cover interest, principal grows by unpaid interest
        unpaid_interest = monthly_interest - actual_interest_payment
        self.principal = self.principal - principal_payment + unpaid_interest

        # Ensure principal doesn't go negative
        self.principal = max(0.0, self.principal)

        # Track statistics
        self.stat_principal_payment_history.append(principal_payment)
        self.stat_interest_payment_history.append(actual_interest_payment)

        return total_payment

    def _repr_html_(self):
        desc = '<ul>'
        desc += f'<li>Loan Type: {self.loan_type.value}</li>'
        desc += f'<li>School: {html.escape(self.school_name)}</li>'
        desc += f'<li>Loan Amount: ${self.loan_amount:,.2f}</li>'
        desc += f'<li>Principal Balance: ${self.principal:,.2f}</li>'
        desc += f'<li>Monthly Payment: ${self.monthly_payment:,.2f}</li>'
        desc += f'<li>Interest Rate: {self.yearly_interest_rate}%</li>'
        desc += '</ul>'
        return desc
