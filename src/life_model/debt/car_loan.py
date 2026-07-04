# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html
from typing import Optional

from ..base_classes import Loan
from ..people.person import Person


class CarLoan(Loan):
    def __init__(
        self,
        person: Person,
        loan_amount: float,
        length_years: int,
        yearly_interest_rate: float,
        name: str,
        principal: Optional[float] = None,
        monthly_payment: Optional[float] = None,
    ):
        """Models a car loan for a person

        Args:
            person: The person to which this loan belongs
            loan_amount: Amount of the loan
            length_years: Length of loan in years
            yearly_interest_rate: Annual interest rate percentage
            name: Name of this vehicle (Make/Model)
            principal: Current principal balance (defaults to loan_amount)
            monthly_payment: Monthly payment amount (calculated if not provided)
        """
        super().__init__(person, loan_amount, yearly_interest_rate, length_years, principal, monthly_payment)
        self.name = name
        self.model.registries.car_loans.register(person, self)

    def get_monthly_payment(self) -> float:
        """Calculate monthly payment using standard loan formula"""
        return self.calculate_monthly_payment()

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Vehicle: {html.escape(self.name)}</li>"
        desc += f"<li>Loan Amount: ${self.loan_amount:,.2f}</li>"
        desc += f"<li>Principal Balance: ${self.principal:,.2f}</li>"
        desc += f"<li>Monthly Payment: ${self.monthly_payment:,.2f}</li>"
        desc += f"<li>Interest Rate: {self.yearly_interest_rate}%</li>"
        desc += "</ul>"
        return desc
