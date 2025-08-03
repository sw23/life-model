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
        p = self.loan_amount
        i = self.yearly_interest_rate / (100 * 12)
        n = self.length_years * 12
        if i == 0:
            return p / n
        return p * (i * ((1 + i) ** n)) / (((1 + i) ** n) - 1)

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
