# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html
from enum import Enum

from ..base_classes import LOAN_RENAMES, Loan
from ..deprecated_names import deprecated_arguments
from ..model import Event
from ..people.person import Person
from ..tax.income import IncomeType


class StudentLoanType(Enum):
    """Enum for student loan types"""

    FEDERAL_SUBSIDIZED = "Federal Subsidized"
    FEDERAL_UNSUBSIDIZED = "Federal Unsubsidized"
    PRIVATE = "Private"
    PLUS = "PLUS"
    #: The statement does not say whether the loan is federal or private. Repaid like any loan on the
    #: standard plan; interest accrues and capitalizes during deferment (no subsidy); not eligible for the
    #: Repayment Assistance Plan (federal only). The interest deduction applies as to any qualified loan.
    UNKNOWN = "Unknown"


class StudentLoanRepaymentPlan(Enum):
    """How a student loan is repaid."""

    STANDARD = "Standard"  # Fixed amortizing payment over the loan term.
    # Income-driven Repayment Assistance Plan (federal loans only); see RepaymentAssistancePlanConfig.
    REPAYMENT_ASSISTANCE_PLAN = "Repayment Assistance Plan"


class StudentLoan(Loan):
    @deprecated_arguments(
        LOAN_RENAMES,
        positional=(
            "loan_type",
            "original_amount",
            "rate_pct",
            "term_years",
            "school_name",
            "current_balance",
            "payment_monthly",
            "in_deferment",
        ),
    )
    def __init__(
        self,
        owner: Person,
        *,
        loan_type: StudentLoanType,
        original_amount: float | None = None,
        rate_pct: float | None = None,
        term_years: float | None = None,
        school_name: str = "School",
        current_balance: float | None = None,
        payment_monthly: float | None = None,
        in_deferment: bool = False,
        repayment_plan: StudentLoanRepaymentPlan = StudentLoanRepaymentPlan.STANDARD,
        term_months: int | None = None,
        origination=None,
        payments_made: int | None = None,
        remaining_months: int | None = None,
        extra_principal_monthly: float = 0.0,
        schedule: str = "contract",
        deferment_until: int | None = None,
        qualifying_payments: int = 0,
    ):
        """Models a student loan for a person

        Args:
            owner: The person to which this loan belongs (``person=`` is a deprecated alias)
            loan_type: Type of student loan (``UNKNOWN`` when the statement does not say: no deferment
                subsidy and no Repayment Assistance Plan)
            original_amount: Original amount of the loan (``loan_amount=`` is deprecated)
            rate_pct: Annual interest rate percentage (``yearly_interest_rate=`` is deprecated)
            term_years: Length of loan in years, or ``term_months`` (``length_years=`` is deprecated)
            school_name: Name of the educational institution
            current_balance: Current principal balance (defaults to the schedule's; ``principal=`` is
                deprecated)
            payment_monthly: Monthly payment amount (calculated if not provided; ``monthly_payment=``
                is deprecated)
            in_deferment: Whether the loan is currently in deferment (no scheduled payments).
                For ``FEDERAL_SUBSIDIZED`` loans the government pays the interest during deferment
                (the balance does not grow); for other types interest accrues and capitalizes.
            repayment_plan: ``STANDARD`` amortization, or the income-driven Repayment Assistance
                Plan (federal loans only), whose payment follows the borrower's AGI.
            term_months, origination, payments_made, remaining_months, extra_principal_monthly, schedule: The
                loan from its statement, as for every :class:`~life_model.base_classes.Loan`.
            deferment_until: Last year of deferment (inclusive): the loan is in deferment through that
                December and repays from the January after. Implies ``in_deferment``.
            qualifying_payments: Forgiveness-qualifying payments already made under an income-driven
                plan (counts toward the RAP forgiveness horizon).

        Every argument after the owner is keyword-only (positional use is deprecated).

        Raises:
            ValueError: If a private loan is put on the Repayment Assistance Plan.
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
            schedule=schedule,
        )
        self.loan_type = loan_type
        self.school_name = school_name
        self.deferment_until = deferment_until
        if deferment_until is not None:
            in_deferment = deferment_until >= self.model.year
        self.in_deferment = in_deferment
        if repayment_plan is StudentLoanRepaymentPlan.REPAYMENT_ASSISTANCE_PLAN and loan_type in (
            StudentLoanType.PRIVATE,
            StudentLoanType.UNKNOWN,
        ):
            raise ValueError(
                "Only federal student loans are eligible for the Repayment Assistance Plan (an UNKNOWN loan type "
                "is not known to be federal)"
            )
        self.repayment_plan = repayment_plan
        # Monthly payments made under an income-driven plan (counts toward forgiveness).
        if qualifying_payments < 0:
            raise ValueError("qualifying_payments must not be negative")
        self.qualifying_payments = int(qualifying_payments)
        self.forgiven_amount = 0.0
        # Unsubsidized interest accrued during deferment this year (capitalized at year end).
        self.deferred_interest = 0.0
        # This year's Repayment Assistance Plan payment (set at the year start from the last AGI).
        self._rap_annual: float | None = None
        self.model.registries.student_loans.register(owner, self)

    def service_year(self) -> float:
        """Service the loan for one year (twelve :meth:`service_month` payments, then the year-end
        capitalization of deferred interest). For direct callers; the engine services it monthly."""
        self.on_year_start()
        paid = sum(self.service_month() for _ in range(12))
        self.on_year_end()
        return paid

    def service_month(self) -> float:
        """Make this month's payment, honoring deferment and the Repayment Assistance Plan.

        In deferment no borrower payment is made (no interest is *paid*); unsubsidized interest
        accrues (simple, on the principal) and capitalizes at year end, and the government pays a
        ``FEDERAL_SUBSIDIZED`` loan's interest.
        """
        if self.in_deferment:
            if self.loan_type is not StudentLoanType.FEDERAL_SUBSIDIZED:
                self.deferred_interest += self.get_interest_amount("month")
            return 0.0
        if self.repayment_plan is StudentLoanRepaymentPlan.REPAYMENT_ASSISTANCE_PLAN:
            return self._service_month_rap()
        return super().service_month()

    def on_year_start(self):
        super().on_year_start()
        self._rap_annual = None

    def on_year_end(self):
        if self.deferred_interest:
            # Unsubsidized interest accrued during deferment capitalizes onto the principal.
            self.principal += self.deferred_interest
            self.deferred_interest = 0.0
        if self.in_deferment and self.deferment_until is not None and self.model.year >= self.deferment_until:
            # Deferment ends: repayment starts in January, the payment re-amortizing the (capitalized)
            # balance over the months left.
            self.in_deferment = False
            self.monthly_payment = self.get_monthly_payment_for_remaining()
        super().on_year_end()

    def get_monthly_payment_for_remaining(self) -> float:
        """The level payment that retires today's balance over the remaining term (at least a month)."""
        from .terms import amortizing_payment

        return amortizing_payment(self.principal, self.yearly_interest_rate, max(1, self.remaining_months))

    def _service_month_rap(self) -> float:
        """One income-driven monthly payment, then forgiveness once the horizon is reached.

        Interest the payment doesn't cover is waived (never capitalized); the principal match tops
        up a month in which principal fell by less than the match amount (government money, not the
        borrower's). Returns the cash the borrower paid.
        """
        if self.principal <= 0:
            return 0.0
        cfg = self._rap_config()
        if self._rap_annual is None:
            self._rap_annual = self.rap_annual_payment()
        interest = self.principal * self.monthly_interest_rate
        payment = min(self._rap_annual / 12, self.principal + interest)
        to_interest = min(payment, interest)
        to_principal = payment - to_interest
        match = max(0.0, min(cfg.principal_match_monthly, payment) - to_principal)
        reduction = min(self.principal, to_principal + match)
        self.principal -= reduction
        self.stat_principal_payment_history.append(to_principal)
        self.stat_interest_payment_history.append(to_interest)
        self._record_month(reduction, to_interest)
        self.qualifying_payments += 1
        if self.principal > 0 and self.qualifying_payments >= 12 * cfg.forgiveness_years:
            self.forgiven_amount = self.principal
            self.principal = 0.0
            if cfg.forgiveness_taxable:
                self.person.income.add(IncomeType.ORDINARY, self.forgiven_amount, source="debt_forgiveness")
            self.model.event_log.add(
                Event(f"{self.person.name}'s student loan forgiven: ${self.forgiven_amount:,.0f} after RAP payments")
            )
        return payment

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
