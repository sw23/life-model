# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html

from ..base_classes import Loan
from ..people.person import Person


class CarLoan(Loan):
    def __init__(
        self,
        person: Person,
        loan_amount: float | None = None,
        length_years: int | None = None,
        yearly_interest_rate: float | None = None,
        name: str = "Car",
        principal: float | None = None,
        monthly_payment: float | None = None,
        *,
        term_months: int | None = None,
        origination=None,
        payments_made: int | None = None,
        remaining_months: int | None = None,
        extra_principal_monthly: float = 0.0,
    ):
        """Models a car loan for a person

        Args:
            person: The person to which this loan belongs
            loan_amount: Amount of the loan (may be omitted with ``principal`` and ``remaining_months``)
            length_years: Length of loan in years (or ``term_months``)
            yearly_interest_rate: Annual interest rate percentage
            name: Name of this vehicle (Make/Model)
            principal: Current principal balance (defaults to the schedule's: ``loan_amount`` for a new loan)
            monthly_payment: Monthly payment amount (calculated if not provided)
            term_months: Term in months (66, 75, ...; keyword-only).
            origination: Origination month ``"YYYY-MM"`` (keyword-only).
            payments_made: Payments made before the run (instead of ``origination``).
            remaining_months: Payments left on the statement.
            extra_principal_monthly: Extra principal paid every month.

        Raises:
            LoanTermsError: When the statement inputs disagree (see :mod:`life_model.debt.terms`).
        """
        super().__init__(
            person,
            loan_amount,
            yearly_interest_rate,
            length_years,
            principal,
            monthly_payment,
            term_months=term_months,
            origination=origination,
            payments_made=payments_made,
            remaining_months=remaining_months,
            extra_principal_monthly=extra_principal_monthly,
        )
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
