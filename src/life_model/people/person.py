# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from enum import Enum
from typing import List, Optional, TYPE_CHECKING
from ..model import LifeModelAgent, LifeModel, Event, ModelSetupException
from .family import Family
from ..limits import federal_retirement_age
from ..tax.federal import FilingStatus, federal_standard_deduction
from ..tax.tax import get_income_taxes_due, TaxesDue
from ..account.job401k import Job401kAccount
from ..services.tax_calculation_service import TaxCalculationService
from ..services.payment_service import PaymentService

if TYPE_CHECKING:
    from ..insurance.social_security import SocialSecurity


class GenderAtBirth(Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class Person(LifeModelAgent):
    def __init__(self, family: Family, name: str, age: int, retirement_age: float, spending: 'Spending'):
        """Person

        Args:
            family (Family): Family of which the person is a part.
            name (str): Person's name.
            age (int): Person's age.
            retirement_age (float): Person's retirement age.
            spending (Spending): Person's spending habits.
        """
        super().__init__(family.model)
        self.family = family
        self.name = name
        self.age = age
        self.retirement_age = retirement_age
        self.spending = spending
        self.debt = 0
        self.taxable_income: float = 0
        self.spouse = None
        self.filing_status = FilingStatus.SINGLE
        self.social_security: Optional[SocialSecurity] = None

        self.stat_money_spent = 0.0
        self.stat_taxes_paid = 0.0
        self.stat_bank_balance = 0.0
        self.stat_housing_costs = 0.0
        self.stat_interest_paid = 0.0
        self.stat_ss_income = 0.0

        # Initialize services for business logic
        self.tax_service = TaxCalculationService(self)
        self.payment_service = PaymentService(self)

        self.family.members.append(self)

    @property
    def jobs(self):
        """Get all jobs for this person from the registry"""
        return self.model.registries.jobs.get_items(self)

    @property
    def bank_accounts(self):
        """Get all bank accounts for this person from the registry"""
        return self.model.registries.bank_accounts.get_items(self)

    @property
    def homes(self):
        """Get all homes for this person from the registry"""
        return self.model.registries.homes.get_items(self)

    @property
    def apartments(self):
        """Get all apartments for this person from the registry"""
        return self.model.registries.apartments.get_items(self)

    @property
    def life_insurance_policies(self):
        """Get all life insurance policies for this person from the registry"""
        return self.model.registries.life_insurance_policies.get_items(self)

    @property
    def plan_529s(self):
        """Get all 529 plans for this person from the registry"""
        return self.model.registries.plan_529s.get_items(self)

    @property
    def donations(self):
        """Get all donations for this person from the registry"""
        return self.model.registries.donations.get_items(self)

    @property
    def donor_advised_funds(self):
        """Get all donor advised funds for this person from the registry"""
        return self.model.registries.donor_advised_funds.get_items(self)

    @property
    def charitable_deductions(self) -> float:
        """Calculate total charitable deductions for the year

        Includes:
        - Direct donations (deductible at time of donation)
        - DAF contributions (deductible at time of contribution, not distribution)
        """
        # Sum deductions from direct donations
        donation_deductions = sum(d.get_tax_deduction_amount() for d in self.donations)

        # Sum deductions from DAF contributions (tracked in stat_contributions_this_year)
        # DAF contributions are deductible when contributed, not when distributed
        daf_contribution_deductions = sum(
            daf.stat_contributions_this_year for daf in self.donor_advised_funds
        )

        return donation_deductions + daf_contribution_deductions

    @property
    def total_itemized_deductions(self) -> float:
        """Calculate total itemized deductions

        Currently includes:
        - Charitable contributions
        - Mortgage interest (if applicable)

        TODO: Add other itemized deductions (state taxes, medical expenses, etc.)
        """
        itemized = self.charitable_deductions

        # Add mortgage interest deductions
        for home in self.homes:
            if hasattr(home, 'mortgage') and home.mortgage:
                itemized += home.mortgage.get_interest_for_year()

        return itemized

    @property
    def federal_deductions(self) -> float:
        """Get federal deductions - use greater of standard or itemized"""
        standard_deduction = federal_standard_deduction[self.filing_status]
        itemized_deductions = self.total_itemized_deductions
        return max(standard_deduction, itemized_deductions)

    @property
    def all_retirement_accounts(self) -> List[Job401kAccount]:
        return [x.retirement_account for x in self.jobs if x.retirement_account is not None]

    @property
    def is_retired(self) -> bool:
        """Check if person is retired"""
        return self.age >= self.retirement_age

    def _repr_html_(self):
        desc = self.name
        desc += '<ul>'
        desc += f'<li>Age: {self.age}</li>'
        desc += f'<li>Retirement Age: {self.retirement_age}</li>'
        desc += ''.join(f"<li>{x._repr_html_()}</li>" for x in self.jobs)
        desc += ''.join(f"<li>{x._repr_html_()}</li>" for x in self.bank_accounts)
        desc += ''.join(f"<li>{x._repr_html_()}</li>" for x in self.homes)
        desc += ''.join(f"<li>{x._repr_html_()}</li>" for x in self.apartments)
        desc += f'<li>Debt: {self.debt}</li>'
        desc += '</ul>'
        return desc

    @property
    def bank_account_balance(self) -> float:
        return sum(x.balance for x in self.bank_accounts)

    def deduct_from_bank_accounts(self, amount: float) -> float:
        """Deducts money from bank accounts.

        Args:
            amount (float): Amount to deduct.

        Returns:
            float: Amount that could not be deducted.
        """
        spending_balance = amount
        for bank_account in self.bank_accounts:
            if (spending_balance == 0):
                break
            spending_balance -= bank_account.withdraw(spending_balance)
        return spending_balance

    def deduct_from_pretax_401ks(self, amount: float) -> float:
        """Deducts money from pre-tax 401ks.

        Args:
            amount (float): Amount to deduct.

        Returns:
            float: Amount that could not be deducted.
        """
        spending_balance = amount
        for retirement_account in self.all_retirement_accounts:
            if (spending_balance == 0):
                break
            spending_balance -= retirement_account.deduct_pretax(spending_balance)
        return spending_balance

    def deduct_from_roth_401ks(self, amount: float) -> float:
        """Deducts money from roth 401ks.

        Args:
            amount (float): Amount to deduct.

        Returns:
            float: Amount that could not be deducted.
        """
        spending_balance = amount
        for retirement_account in self.all_retirement_accounts:
            if (spending_balance == 0):
                break
            spending_balance -= retirement_account.deduct_roth(spending_balance)
        return spending_balance

    def withdraw_from_pretax_401ks(self, amount: float) -> float:
        """Withdraws money from pre-tax 401ks.

        Args:
            amount (float): Amount to withdraw.

        Returns:
            float: Amount that could not be withdrawn.
        """
        amount -= self.deduct_from_pretax_401ks(amount)
        self.taxable_income += amount
        self.deposit_into_bank_account(amount)
        return amount

    def deposit_into_bank_account(self, amount: float):
        """Deposits money into bank account.

        Args:
            amount (float): Amount to deposit.
        """
        if len(self.bank_accounts) == 0:
            raise ModelSetupException('No Bank Account. Create a bank account before making deposits.')
        self.bank_accounts[0].balance += amount

    def pay_bills(self, spending_balance: float) -> float:
        """Pays bills using payment service for optimal prioritization.

        Args:
            spending_balance (float): Amount of money spent.

        Returns:
            float: Amount that could not be paid.
        """
        return self.payment_service.pay_bills_with_prioritization(spending_balance)

    def get_income_taxes_due(self, additional_income: float = 0) -> TaxesDue:
        """Gets income taxes due for the year.

        Args:
            additional_income (float, optional): Additional income to include, not present in taxable_income.

        Raises:
            NotImplementedError: Unsupported filing status.

        Returns:
            float: Federal taxes due.
        """

        income_amount = self.taxable_income + additional_income
        if self.filing_status == FilingStatus.SINGLE:
            return get_income_taxes_due(income_amount, self.federal_deductions, self.filing_status)
        else:
            raise NotImplementedError(f"Unsupported filing status: {self.filing_status}")

    def get_married(self, spouse: 'Person', link_spouse: bool = True):
        """Get  married.

        Args:
            spouse (Person): Spouse to get married to.
            link_spouse (bool, optional): Whether to call get_married on the spouse object as well. Defaults to True.
        """
        self.spouse = spouse
        self.filing_status = FilingStatus.MARRIED_FILING_JOINTLY
        if link_spouse:
            spouse.get_married(self, False)
            event_str = f"{self.name} and {spouse.name} got married at age {self.age} and {spouse.age}"
            self.model.event_log.add(Event(event_str))

    def get_year_at_age(self, age: int) -> int:
        """Gets the year at a given age.

        Args:
            age (int): Age of the person.

        Returns:
            int: Year at the given age.
        """
        return self.model.year + (age - self.age)

    def pre_step(self):
        self.age += 1

    def step(self):
        discretionary_spending = self.spending.get_yearly_spending()
        home_spending = sum(x.make_yearly_payment() for x in self.homes)
        home_interest_paid = sum(x.mortgage.get_interest_for_year() for x in self.homes)
        apartment_rent = sum(x.yearly_rent for x in self.apartments)
        all_bills_except_taxes = discretionary_spending + home_spending + apartment_rent

        # Retire from all jobs at retirement age
        if self.age == self.retirement_age:
            for job in self.jobs:
                job.retire()

        # Pay off spending, taxes, and debts for the year
        # - People filing single is handled individually here, MFJ is handled in family
        if self.filing_status == FilingStatus.SINGLE:
            # Use tax service to handle complex 401k withdrawal and tax calculations
            withdrawal_amount, yearly_taxes = self.tax_service.calculate_total_401k_withdrawal(all_bills_except_taxes)

            # Pay bills and handle any remaining debt
            self.debt += self.pay_bills(all_bills_except_taxes + yearly_taxes.total)
            self.debt = self.pay_bills(self.debt)
        else:
            yearly_taxes = TaxesDue()

        if (self.age == int(federal_retirement_age())):
            self.model.event_log.add(Event(f"{self.name} reached retirement age (age {federal_retirement_age()})"))

        self.stat_money_spent = discretionary_spending
        self.stat_taxes_paid = yearly_taxes.total
        self.stat_bank_balance = self.bank_account_balance
        self.stat_housing_costs = home_spending + apartment_rent
        self.stat_interest_paid = home_interest_paid

        # Additional tax stats
        self.stat_taxes_paid_federal = yearly_taxes.federal
        self.stat_taxes_paid_state = yearly_taxes.state
        self.stat_taxes_paid_ss = yearly_taxes.ss
        self.stat_taxes_paid_medicare = yearly_taxes.medicare

    def post_step(self):
        self.taxable_income = 0


class Spending(LifeModelAgent):
    def __init__(self, model: LifeModel, base: float = 0, yearly_increase: float = 0):
        """Spending

        Args:
            model (LifeModel): LifeModel instance.
            base (float): Base spending amount.
            yearly_increase (float): Yearly percentage increase in spending. 10 = 10%.
        """
        super().__init__(model)
        self.base = base
        self.yearly_increase = yearly_increase
        self.one_time_expenses = 0

    def add_expense(self, amount: float):
        """Adds a one-time expense.

        Args:
            amount (float): Amount of expense to add.
        """
        self.one_time_expenses += amount

    def get_yearly_spending(self) -> float:
        """Gets yearly spending."""
        return self.base + self.one_time_expenses

    def adjust_base(self, base_percent: float):
        """Adjusts base spending.

        Args:
            percent_increase (float): Percentage increase in spending. 50 = 50%.
        """
        self.base = self.base * (base_percent / 100)

    def step(self):
        self.base += (self.base * (self.yearly_increase / 100))
        self.one_time_expenses = 0
