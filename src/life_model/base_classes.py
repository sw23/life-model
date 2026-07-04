# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, Optional

from .limits import federal_retirement_age
from .model import LifeModelAgent

if TYPE_CHECKING:
    from .people.person import Person


class TaxTreatment(Enum):
    """How a tax-advantaged account's contributions and withdrawals are taxed."""

    PRETAX = "pretax"  # Traditional 401k/IRA: deduct on contribute, ordinary income on withdraw.
    ROTH = "roth"  # Roth 401k/IRA: no deduction; qualified withdrawals tax/penalty-free.
    HSA = "hsa"  # HSA: deduct on contribute; tax-free for medical, taxed + penalty otherwise.


class FinancialAccount(LifeModelAgent, ABC):
    """Abstract base class for all financial accounts with balances.

    Provides uniform balance storage, deposit/withdraw validation, and balance-history tracking so
    subclasses don't reimplement these. Subclasses with a *derived* balance (e.g. the 401k, whose
    balance is pretax + roth) override the ``balance`` property; the setter must either work or
    raise — it must never silently discard a write.

    ``beneficiary`` is an optional per-account designation: at the owner's death the account is
    routed to that (surviving) beneficiary instead of the residual estate — the way real
    retirement accounts and payable-on-death accounts pass by designation, not by will. A
    predeceased beneficiary falls back to the residual-estate path. Designation changes *who*
    receives the account, not the estate-tax base (see ``Person._transfer_estate``). Subclasses
    that don't expose the keyword can have ``account.beneficiary`` assigned directly.
    """

    def __init__(self, person: "Person", balance: float = 0, *, beneficiary: Optional["Person"] = None):
        super().__init__(person.model)
        self.person = person
        self._balance = float(balance)
        self.beneficiary = beneficiary
        self.stat_balance_history = []

    @property
    def balance(self) -> float:
        """Current account balance."""
        return self._balance

    @balance.setter
    def balance(self, value: float) -> None:
        self._balance = value

    def get_balance(self) -> float:
        """Get current account balance"""
        return self.balance

    def deposit(self, amount: float) -> bool:
        """Deposit amount into account. Returns success status.

        Negative amounts raise ``ValueError``; zero is a no-op that succeeds.
        """
        if amount < 0:
            raise ValueError("Deposit amount cannot be negative")
        self.balance += amount
        return True

    def withdraw(self, amount: float) -> float:
        """Withdraw amount from account. Returns actual amount withdrawn.

        Non-positive amounts withdraw nothing; a request larger than the balance withdraws the
        whole balance.
        """
        if amount <= 0:
            return 0.0
        amount_withdrawn = min(self.balance, amount)
        self.balance -= amount_withdrawn
        return amount_withdrawn

    def step(self):
        """Track balance history each step"""
        self.stat_balance_history.append(self.balance)


class Loan(LifeModelAgent, ABC):
    """Abstract base class for amortizing loans.

    The ABC owns amortization: :meth:`make_payment` applies a single **monthly** payment (loans
    compound and amortize monthly) with all the clamps — interest is charged on the current
    principal, principal never goes negative, and extra principal that exceeds the balance simply
    pays the loan off. :meth:`make_yearly_payment` runs the twelve monthly periods that make up
    one simulated year, so annual results match a real amortization schedule. Concrete subclasses
    supply only rate/term/identification and register themselves; they do not re-implement payment
    math.
    """

    def __init__(
        self,
        person: "Person",
        loan_amount: float,
        yearly_interest_rate: float,
        length_years: int,
        principal: float | None = None,
        monthly_payment: float | None = None,
    ):
        super().__init__(person.model)
        self.person = person
        self.loan_amount = loan_amount
        self.yearly_interest_rate = yearly_interest_rate
        self.length_years = length_years
        self.principal = loan_amount if principal is None else principal
        self.monthly_payment = self.calculate_monthly_payment() if monthly_payment is None else monthly_payment

        # Interest actually charged over the current year, captured as the year is amortized so the
        # itemized deduction / interest stats aren't understated by reading the post-payment principal.
        self.interest_paid_this_year = 0.0

        # Statistics tracking. The per-payment histories record one entry per *monthly* period; the
        # yearly histories record one aggregated entry per simulated year (convenient for plotting
        # against the yearly simulation timeline).
        self.stat_principal_payment_history = []
        self.stat_interest_payment_history = []
        self.stat_balance_history = []
        self.stat_yearly_principal_payment_history = []
        self.stat_yearly_interest_payment_history = []

    @property
    def monthly_interest_rate(self) -> float:
        """Per-month interest rate as a fraction (e.g. 6% APR -> 0.005)."""
        return self.yearly_interest_rate / (100 * 12)

    def calculate_monthly_payment(self) -> float:
        """Fully-amortizing monthly payment using the standard loan formula.

        Guards the zero-interest case (avoids division by zero) and a zero-length term.
        """
        p = self.loan_amount
        i = self.monthly_interest_rate
        n = self.length_years * 12
        if n == 0:
            return p
        if i == 0:
            return p / n
        return p * (i * ((1 + i) ** n)) / (((1 + i) ** n) - 1)

    def get_interest_amount(self, period: str = "month") -> float:
        """Interest accrued on the current principal for one period.

        Args:
            period: ``"month"`` (default) for a single month's interest — the period the loan
                actually amortizes over — or ``"year"`` for a full year's simple interest.
        """
        annual = self.principal * (self.yearly_interest_rate / 100)
        if period == "year":
            return annual
        if period == "month":
            return annual / 12
        raise ValueError(f"Unknown period {period!r}; expected 'month' or 'year'")

    def make_payment(self, payment_amount: float, extra_to_principal: float = 0) -> float:
        """Apply a single monthly payment.

        Interest is charged on the current principal first; the remainder plus any
        ``extra_to_principal`` reduces the principal. The principal is clamped at zero (paying
        more than the balance simply pays the loan off), and if a payment doesn't cover the
        month's interest the shortfall is added to the principal (negative amortization).

        Returns:
            float: The total cash actually paid this month (interest + principal).
        """
        if payment_amount < 0:
            raise ValueError("Payment amount cannot be negative")
        if extra_to_principal < 0:
            raise ValueError("Extra principal payment cannot be negative")

        monthly_interest = self.get_interest_amount("month")
        actual_interest_payment = min(payment_amount, monthly_interest)
        available_for_principal = payment_amount - actual_interest_payment
        total_principal_payment = available_for_principal + extra_to_principal
        principal_payment = min(total_principal_payment, self.principal)

        unpaid_interest = monthly_interest - actual_interest_payment
        self.principal = max(0.0, self.principal - principal_payment + unpaid_interest)

        self.stat_principal_payment_history.append(principal_payment)
        self.stat_interest_payment_history.append(actual_interest_payment)

        return actual_interest_payment + principal_payment

    def make_yearly_payment(self, monthly_payment: float | None = None, extra_to_principal: float = 0) -> float:
        """Amortize one simulated year as twelve monthly payments.

        ``extra_to_principal`` is applied once (in the first month). Payments stop early once the
        loan is paid off. ``interest_paid_this_year`` is updated to the interest charged across the
        year.

        Returns:
            float: Total cash paid across the year.
        """
        if monthly_payment is None:
            monthly_payment = self.monthly_payment
        total_paid = 0.0
        interest_this_year = 0.0
        principal_this_year = 0.0
        for month in range(12):
            if self.principal <= 0:
                break
            extra = extra_to_principal if month == 0 else 0.0
            total_paid += self.make_payment(monthly_payment, extra)
            interest_this_year += self.stat_interest_payment_history[-1]
            principal_this_year += self.stat_principal_payment_history[-1]
        self.interest_paid_this_year = interest_this_year
        self.stat_yearly_principal_payment_history.append(principal_this_year)
        self.stat_yearly_interest_payment_history.append(interest_this_year)
        return total_paid

    def service_year(self) -> float:
        """Service this loan for one simulated year at its scheduled payment.

        Called by the debt-servicing pipeline during tax-unit settlement. Returns the total cash
        paid this year (which is collected through the unit's bills).
        """
        return self.make_yearly_payment(self.monthly_payment)

    def step(self):
        """Track loan balance history"""
        self.stat_balance_history.append(self.principal)


class Investment(FinancialAccount, ABC):
    """Abstract base class for investment accounts with growth.

    Growth is applied with **annual compounding** (APY) as the model-wide default so that every
    ``Investment`` subclass grows identically given the same nominal rate. Subclasses that need a
    different growth model override :meth:`calculate_growth`.
    """

    # Apply growth before tax-unit settlement so withdrawals see the grown balance.
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"step": -10}

    # Maps an account's asset class to the economy rate that drives its return.
    _ASSET_CLASS_RATES: ClassVar[dict[str, str]] = {
        "equity": "equity_return",
        "bond": "bond_return",
        "cash": "cash_yield",
    }

    def __init__(
        self,
        person: "Person",
        balance: float = 0,
        growth_rate: float | None = None,
        asset_class: str = "equity",
        *,
        beneficiary: Optional["Person"] = None,
    ):
        super().__init__(person, balance, beneficiary=beneficiary)
        # An explicit growth_rate overrides the economy; None defers to the economy's
        # return for this account's asset class, re-read each year so path/stochastic economies flow
        # through to account growth.
        self._growth_rate_override = growth_rate
        if asset_class not in self._ASSET_CLASS_RATES:
            raise ValueError(f"Unknown asset_class {asset_class!r}; expected one of {list(self._ASSET_CLASS_RATES)}")
        self.asset_class = asset_class
        self.stat_growth_history = []

    @property
    def growth_rate(self) -> float:
        """Annual growth rate (percent): the explicit override if set, else the economy's return."""
        if self._growth_rate_override is not None:
            return self._growth_rate_override
        rate_name = self._ASSET_CLASS_RATES[self.asset_class]
        return self.model.economy.rate(rate_name, self.model.year)

    @growth_rate.setter
    def growth_rate(self, value: float | None) -> None:
        self._growth_rate_override = value

    def calculate_growth(self) -> float:
        """Calculate investment growth for the period (annual compounding, APY).

        One year at an APY is ``balance * rate``; written as a product rather than via
        ``compound_interest`` so it is exact in floating point.
        """
        return self.balance * (self.growth_rate / 100)

    def apply_growth(self):
        """Apply calculated growth to balance"""
        growth = self.calculate_growth()
        self.balance += growth
        self.stat_growth_history.append(growth)
        return growth

    def step(self):
        """Apply growth and track statistics"""
        self.apply_growth()
        super().step()


class TaxAdvantagedAccount(Investment, ABC):
    """Base class for tax-advantaged accounts (IRAs, HSA).

    Adds a year-indexed contribution limit hook, year-to-date contribution tracking (reset in
    post_step), contribution-vs-earnings basis tracking (for Roth withdrawal ordering and HSA/529
    penalty math), a :class:`TaxTreatment`, an early-withdrawal usability gate, and an RMD
    participation flag.
    """

    #: How this account is taxed. Subclasses set this.
    tax_treatment: TaxTreatment = TaxTreatment.ROTH
    #: Whether the account participates in required minimum distributions.
    is_rmd_eligible: bool = False
    #: Accounts of the same owner with the same non-None group share one annual contribution limit
    #: (e.g. "ira": Roth and Traditional IRAs share the single IRA limit).
    limit_group: ClassVar[str | None] = None

    def __init__(
        self,
        person: "Person",
        balance: float = 0,
        growth_rate: float | None = None,
        asset_class: str = "equity",
        *,
        beneficiary: Optional["Person"] = None,
    ):
        super().__init__(person, balance, growth_rate, asset_class, beneficiary=beneficiary)
        # Contributions made this year (reset in post_step).
        self.contributions_ytd = 0.0
        # Cumulative contribution basis still in the account. Any opening balance is treated as
        # basis (contributions) rather than earnings; growth accrues to earnings, not basis.
        self.contribution_basis = float(balance)

    @abstractmethod
    def annual_contribution_limit(self) -> float:
        """The contribution limit for the owner this year (year- and age-indexed)."""

    def remaining_contribution_room(self) -> float:
        """Contribution room left this year (net of any contributions to sibling accounts that
        share the same limit, e.g. Roth + Traditional IRA)."""
        used = self.contributions_ytd + self.sibling_contributions_ytd()
        return max(0.0, self.annual_contribution_limit() - used)

    def sibling_contributions_ytd(self) -> float:
        """Contributions made this year to the owner's other accounts in the same ``limit_group``.

        Zero when the account's limit is not shared (``limit_group`` is None).
        """
        if self.limit_group is None:
            return 0.0
        return sum(
            account.contributions_ytd
            for account in self.person.all_tax_advantaged_accounts
            if account is not self and account.limit_group == self.limit_group
        )

    def contribute(self, amount: float) -> float:
        """Contribute up to the remaining annual limit. Returns the amount actually contributed."""
        if amount <= 0:
            return 0.0
        actual = min(amount, self.remaining_contribution_room())
        if actual > 0:
            self.balance += actual
            self.contributions_ytd += actual
            self.contribution_basis += actual
        return actual

    @property
    def earnings(self) -> float:
        """Portion of the balance that is investment earnings (balance minus basis)."""
        return max(0.0, self.balance - self.contribution_basis)

    def withdraw(self, amount: float) -> float:
        """Withdraw, drawing down contribution basis before earnings (Roth ordering)."""
        withdrawn = super().withdraw(amount)
        self.contribution_basis -= min(self.contribution_basis, withdrawn)
        return withdrawn

    def reset_annual_contributions(self):
        """Reset annual contribution tracking (called at year end)."""
        self.contributions_ytd = 0.0

    @property
    def is_useable(self) -> bool:
        """Whether funds can be withdrawn without an early-withdrawal penalty (age-based)."""
        return self.person.age >= federal_retirement_age(self.model.config)

    def post_step(self):
        """Reset the annual contribution counter at year end."""
        self.reset_annual_contributions()


class RetirementAccount(Investment, ABC):
    """Abstract base class for retirement accounts (401k)."""

    def __init__(
        self,
        person: "Person",
        balance: float = 0,
        growth_rate: float | None = None,
        asset_class: str = "equity",
        *,
        beneficiary: Optional["Person"] = None,
    ):
        super().__init__(person, balance, growth_rate, asset_class, beneficiary=beneficiary)
        self.stat_useable_balance = 0

    @property
    def is_useable(self) -> bool:
        """Check if funds can be withdrawn without penalty based on age"""
        return self.person.age >= federal_retirement_age(self.model.config)

    def step(self):
        """Update useable balance and track statistics"""
        if self.is_useable:
            self.stat_useable_balance = self.balance
        super().step()


class Benefit(LifeModelAgent, ABC):
    """Abstract base class for benefits that provide periodic payments"""

    def __init__(self, person: "Person", company: str):
        super().__init__(person.model)
        self.person = person
        self.company = company

    @abstractmethod
    def get_annual_benefit(self) -> float:
        """Calculate annual benefit amount"""

    @abstractmethod
    def is_eligible(self) -> bool:
        """Check if person is eligible to receive benefits"""
