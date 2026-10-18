# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html

from ..base_classes import LOAN_RENAMES, Loan
from ..deprecated_names import deprecated_arguments
from ..people.person import Person


class CarLoan(Loan):
    @deprecated_arguments(
        LOAN_RENAMES,
        positional=("original_amount", "term_years", "rate_pct", "name", "current_balance", "payment_monthly"),
    )
    def __init__(
        self,
        owner: Person,
        *,
        original_amount: float | None = None,
        term_years: float | None = None,
        rate_pct: float | None = None,
        name: str = "Car",
        current_balance: float | None = None,
        payment_monthly: float | None = None,
        term_months: int | None = None,
        origination=None,
        payments_made: int | None = None,
        remaining_months: int | None = None,
        extra_principal_monthly: float = 0.0,
    ):
        """Models a car loan for a person

        Args:
            owner: The person to which this loan belongs (``person=`` is a deprecated alias)
            original_amount: Amount originally borrowed (may be omitted with ``current_balance`` and
                ``remaining_months``; ``loan_amount=`` is a deprecated alias)
            term_years: Original term in years (or ``term_months``; ``length_years=`` is deprecated)
            rate_pct: APR, percent (``yearly_interest_rate=`` is deprecated)
            name: Name of this vehicle (Make/Model)
            current_balance: Current principal (defaults to the schedule's: the original amount for a
                new loan; ``principal=`` is deprecated)
            payment_monthly: Monthly payment (calculated if not provided; ``monthly_payment=`` is deprecated)
            term_months: Term in months (66, 75, ...).
            origination: Origination month ``"YYYY-MM"``.
            payments_made: Payments made before the run (instead of ``origination``).
            remaining_months: Payments left on the statement.
            extra_principal_monthly: Extra principal paid every month.

        Every argument after the owner is keyword-only (positional use is deprecated).

        Raises:
            LoanTermsError: When the statement inputs disagree (see :mod:`life_model.debt.terms`).
        """
        super().__init__(
            owner,
            original_amount=original_amount,
            rate_pct=rate_pct,
            term_years=term_years,
            current_balance=current_balance,
            payment_monthly=payment_monthly,
            term_months=term_months,
            origination=origination,
            payments_made=payments_made,
            remaining_months=remaining_months,
            extra_principal_monthly=extra_principal_monthly,
        )
        self.name = name
        self.model.registries.car_loans.register(owner, self)

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
