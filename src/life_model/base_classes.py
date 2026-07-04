# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, Optional

from .limits import federal_retirement_age
from .model import LifeModelAgent, compound_interest

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
    """

    def __init__(self, person: "Person", balance: float = 0):
        super().__init__(person.model)
        self.person = person
        self._balance = float(balance)
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
    """Abstract base class for all loans with payment calculations"""

    def __init__(
        self,
        person: "Person",
        loan_amount: float,
        yearly_interest_rate: float,
        length_years: int,
        principal: Optional[float] = None,
        monthly_payment: Optional[float] = None,
    ):
        super().__init__(person.model)
        self.person = person
        self.loan_amount = loan_amount
        self.yearly_interest_rate = yearly_interest_rate
        self.length_years = length_years
        self.principal = principal or loan_amount
        self.monthly_payment = monthly_payment or self.calculate_monthly_payment()

        # Statistics tracking
        self.stat_principal_payment_history = []
        self.stat_interest_payment_history = []
        self.stat_balance_history = []

    def calculate_monthly_payment(self) -> float:
        """Calculate monthly payment using standard loan formula"""
        p = self.loan_amount
        i = self.yearly_interest_rate / (100 * 12)
        n = self.length_years * 12
        if i == 0:
            return p / n
        return p * (i * ((1 + i) ** n)) / (((1 + i) ** n) - 1)

    @abstractmethod
    def make_payment(self, payment_amount: float, extra_to_principal: float = 0) -> float:
        """Make loan payment. Returns total amount paid"""
        pass

    def get_interest_amount(self) -> float:
        """Calculate interest amount for current period"""
        return self.principal * (self.yearly_interest_rate / 100)

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
    STEP_PRIORITY = {"step": -10}

    def __init__(self, person: "Person", balance: float = 0, growth_rate: float = 0):
        super().__init__(person, balance)
        self.growth_rate = growth_rate
        self.stat_growth_history = []

    def calculate_growth(self) -> float:
        """Calculate investment growth for the period (annual compounding, APY)."""
        return compound_interest(self.balance, self.growth_rate, 1, 1)

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

    def __init__(self, person: "Person", balance: float = 0, growth_rate: float = 0):
        super().__init__(person, balance, growth_rate)
        # Contributions made this year (reset in post_step).
        self.contributions_ytd = 0.0
        # Cumulative contribution basis still in the account. Any opening balance is treated as
        # basis (contributions) rather than earnings; growth accrues to earnings, not basis.
        self.contribution_basis = float(balance)

    @abstractmethod
    def annual_contribution_limit(self) -> float:
        """The contribution limit for the owner this year (year- and age-indexed)."""
        pass

    def remaining_contribution_room(self) -> float:
        """Contribution room left this year (net of any contributions to sibling accounts that
        share the same limit, e.g. Roth + Traditional IRA)."""
        used = self.contributions_ytd + self.sibling_contributions_ytd()
        return max(0.0, self.annual_contribution_limit() - used)

    def sibling_contributions_ytd(self) -> float:
        """Contributions made this year to other accounts that share this account's limit.

        Defaults to 0 (the limit is not shared). IRAs override this to share the single IRA limit
        across the person's Roth and Traditional IRAs.
        """
        return 0.0

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
        return self.person.age >= federal_retirement_age()

    def post_step(self):
        """Reset the annual contribution counter at year end."""
        self.reset_annual_contributions()


class RetirementAccount(Investment, ABC):
    """Abstract base class for retirement accounts (401k)."""

    def __init__(self, person: "Person", balance: float = 0, growth_rate: float = 0):
        super().__init__(person, balance, growth_rate)
        self.stat_useable_balance = 0

    @property
    def is_useable(self) -> bool:
        """Check if funds can be withdrawn without penalty based on age"""
        return self.person.age >= federal_retirement_age()

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
        pass

    @abstractmethod
    def is_eligible(self) -> bool:
        """Check if person is eligible to receive benefits"""
        pass
