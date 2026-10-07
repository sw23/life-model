# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html
from enum import Enum

from ..base_classes import Loan
from ..model import Event
from ..people.person import Person
from ..tax.income import IncomeType


class StudentLoanType(Enum):
    """Enum for student loan types"""

    FEDERAL_SUBSIDIZED = "Federal Subsidized"
    FEDERAL_UNSUBSIDIZED = "Federal Unsubsidized"
    PRIVATE = "Private"
    PLUS = "PLUS"


class StudentLoanRepaymentPlan(Enum):
    """How a student loan is repaid."""

    STANDARD = "Standard"  # Fixed amortizing payment over the loan term.
    # Income-driven Repayment Assistance Plan (federal loans only); see RepaymentAssistancePlanConfig.
    REPAYMENT_ASSISTANCE_PLAN = "Repayment Assistance Plan"


class StudentLoan(Loan):
    def __init__(
        self,
        person: Person,
        loan_type: StudentLoanType,
        loan_amount: float,
        yearly_interest_rate: float,
        length_years: int,
        school_name: str,
        principal: float | None = None,
        monthly_payment: float | None = None,
        in_deferment: bool = False,
        *,
        repayment_plan: StudentLoanRepaymentPlan = StudentLoanRepaymentPlan.STANDARD,
    ):
        """Models a student loan for a person

        Args:
            person: The person to which this loan belongs
            loan_type: Type of student loan
            loan_amount: Original amount of the loan
            yearly_interest_rate: Annual interest rate percentage
            length_years: Length of loan in years
            school_name: Name of the educational institution
            principal: Current principal balance (defaults to loan_amount)
            monthly_payment: Monthly payment amount (calculated if not provided)
            in_deferment: Whether the loan is currently in deferment (no scheduled payments).
                For ``FEDERAL_SUBSIDIZED`` loans the government pays the interest during deferment
                (the balance does not grow); for other types interest accrues and capitalizes.
            repayment_plan: ``STANDARD`` amortization, or the income-driven Repayment Assistance
                Plan (federal loans only), whose payment follows the borrower's AGI.

        Raises:
            ValueError: If a private loan is put on the Repayment Assistance Plan.
        """
        super().__init__(person, loan_amount, yearly_interest_rate, length_years, principal, monthly_payment)
        self.loan_type = loan_type
        self.school_name = school_name
        self.in_deferment = in_deferment
        if (
            repayment_plan is StudentLoanRepaymentPlan.REPAYMENT_ASSISTANCE_PLAN
            and loan_type is StudentLoanType.PRIVATE
        ):
            raise ValueError("Only federal student loans are eligible for the Repayment Assistance Plan")
        self.repayment_plan = repayment_plan
        # Monthly payments made under an income-driven plan (counts toward forgiveness).
        self.qualifying_payments = 0
        self.forgiven_amount = 0.0
        self.model.registries.student_loans.register(person, self)

    def service_year(self) -> float:
        """Service the loan for one year, honoring deferment and the subsidized-interest benefit.

        In deferment no borrower payment is made, so no interest is *paid* (the interest deduction
        sees nothing). For ``FEDERAL_SUBSIDIZED`` the government covers the interest and the balance
        is unchanged; for other types the year's interest capitalizes onto the principal.
        """
        if self.in_deferment:
            self.interest_paid_this_year = 0.0
            if self.loan_type is not StudentLoanType.FEDERAL_SUBSIDIZED:
                # Unsubsidized interest accrues and capitalizes during deferment.
                self.principal += self.get_interest_amount("year")
            return 0.0
        if self.repayment_plan is StudentLoanRepaymentPlan.REPAYMENT_ASSISTANCE_PLAN:
            return self._service_year_rap()
        return super().service_year()

    def _rap_config(self):
        return self.model.config.debt.student_loan.repayment_assistance_plan

    def _borrower_agi(self) -> float:
        """AGI from the borrower's most recent filed return, else this year's AGI so far."""
        history = {year: agi for year, agi in self.person.agi_history.items() if year < self.model.year}
        if history:
            return history[max(history)]
        return self.person.agi()

    def rap_annual_payment(self, agi: float | None = None) -> float:
        """Required yearly payment under the Repayment Assistance Plan."""
        cfg = self._rap_config()
        agi = self._borrower_agi() if agi is None else agi
        if agi <= cfg.income_step:
            base = cfg.minimum_annual
        else:
            steps = int((agi - 1) // cfg.income_step)
            rate = min(steps * cfg.rate_step_percent, cfg.max_rate_percent)
            base = agi * rate / 100
        adult_age = self.model.config.dependents.adult_age
        dependents = sum(1 for child in self.person.children if 0 <= child.age < adult_age)
        return max(base - 12 * cfg.dependent_credit_monthly * dependents, 12 * cfg.minimum_monthly)

    def _service_year_rap(self) -> float:
        """Twelve income-driven monthly payments, then forgiveness once the horizon is reached.

        Interest the payment doesn't cover is waived (never capitalized); the principal match tops
        up any month in which principal fell by less than the match amount (government money, not the
        borrower's). Returns the cash the borrower paid.
        """
        cfg = self._rap_config()
        monthly_payment = self.rap_annual_payment() / 12
        monthly_rate = self.monthly_interest_rate
        paid = interest_paid = principal_paid_year = 0.0
        for _month in range(12):
            if self.principal <= 0:
                break
            interest = self.principal * monthly_rate
            payment = min(monthly_payment, self.principal + interest)
            to_interest = min(payment, interest)
            to_principal = payment - to_interest
            match = max(0.0, min(cfg.principal_match_monthly, payment) - to_principal)
            reduction = min(self.principal, to_principal + match)
            self.principal -= reduction
            self.stat_principal_payment_history.append(to_principal)
            self.stat_interest_payment_history.append(to_interest)
            paid += payment
            interest_paid += to_interest
            principal_paid_year += reduction
            self.qualifying_payments += 1
        self.interest_paid_this_year = interest_paid
        self.stat_yearly_principal_payment_history.append(principal_paid_year)
        self.stat_yearly_interest_payment_history.append(interest_paid)

        if self.principal > 0 and self.qualifying_payments >= 12 * cfg.forgiveness_years:
            self.forgiven_amount = self.principal
            self.principal = 0.0
            if cfg.forgiveness_taxable:
                self.person.income.add(IncomeType.ORDINARY, self.forgiven_amount)
            self.model.event_log.add(
                Event(f"{self.person.name}'s student loan forgiven: ${self.forgiven_amount:,.0f} after RAP payments")
            )
        return paid

    def get_monthly_payment(self) -> float:
        """Calculate monthly payment using standard loan formula"""
        return self.calculate_monthly_payment()

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Loan Type: {self.loan_type.value}</li>"
        desc += f"<li>School: {html.escape(self.school_name)}</li>"
        desc += f"<li>Loan Amount: ${self.loan_amount:,.2f}</li>"
        desc += f"<li>Principal Balance: ${self.principal:,.2f}</li>"
        desc += f"<li>Monthly Payment: ${self.monthly_payment:,.2f}</li>"
        desc += f"<li>Interest Rate: {self.yearly_interest_rate}%</li>"
        desc += "</ul>"
        return desc
