# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING
from .model import LifeModelAgent
from .limits import federal_retirement_age

if TYPE_CHECKING:
    from .people.person import Person


class FinancialAccount(LifeModelAgent, ABC):
    """Abstract base class for all financial accounts with balances"""

    def __init__(self, person: 'Person', balance: float = 0):
        super().__init__(person.model)
        self.person = person
        self.balance = balance
        self.stat_balance_history = []

    @abstractmethod
    def get_balance(self) -> float:
        """Get current account balance"""
        pass

    @abstractmethod
    def deposit(self, amount: float) -> bool:
        """Deposit amount into account. Returns success status"""
        pass

    @abstractmethod
    def withdraw(self, amount: float) -> float:
        """Withdraw amount from account. Returns actual amount withdrawn"""
        pass

    def step(self):
        """Track balance history each step"""
        self.stat_balance_history.append(self.balance)


class Loan(LifeModelAgent, ABC):
    """Abstract base class for all loans with payment calculations"""

    def __init__(self, person: 'Person', loan_amount: float, yearly_interest_rate: float,
                 length_years: int, principal: Optional[float] = None,
                 monthly_payment: Optional[float] = None):
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
    """Abstract base class for investment accounts with growth"""

    def __init__(self, person: 'Person', balance: float = 0, growth_rate: float = 0):
        super().__init__(person, balance)
        self.growth_rate = growth_rate
        self.stat_growth_history = []

    @abstractmethod
    def calculate_growth(self) -> float:
        """Calculate investment growth for the period"""
        pass

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


class RetirementAccount(FinancialAccount, ABC):
    """Abstract base class for retirement accounts (401k, IRA, etc.)"""

    def __init__(self, person: 'Person', balance: float = 0):
        super().__init__(person, balance)
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

    def __init__(self, person: 'Person', company: str):
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
