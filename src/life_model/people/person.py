# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import TYPE_CHECKING, List, Optional

from ..account.job401k import Job401kAccount
from ..limits import federal_retirement_age
from ..model import Event, LifeModel, LifeModelAgent
from ..services.payment_service import PaymentService
from ..services.tax_calculation_service import TaxCalculationService
from ..tax.federal import FilingStatus, federal_standard_deduction
from ..tax.tax import TaxesDue, get_income_taxes_due
from .family import Family
from .types import GenderAtBirth  # re-exported for backward compatibility

if TYPE_CHECKING:
    from ..insurance.social_security import SocialSecurity

__all__ = ["GenderAtBirth", "Person", "Spending"]


class Person(LifeModelAgent):
    # Age first in pre_step so income/RMD calculations see the current-year age.
    STEP_PRIORITY = {"pre_step": -20}

    def __init__(self, family: Family, name: str, age: int, retirement_age: float, spending: "Spending"):
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
        self.retirement_triggered = False
        self._retirement_age_event_logged = False
        # Cash held when the person has no bank account (see receive_cash).
        self.cash = 0.0
        self._warned_no_bank_account = False

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
        daf_contribution_deductions = sum(daf.stat_contributions_this_year for daf in self.donor_advised_funds)

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
            if hasattr(home, "mortgage") and home.mortgage:
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
        desc += "<ul>"
        desc += f"<li>Age: {self.age}</li>"
        desc += f"<li>Retirement Age: {self.retirement_age}</li>"
        desc += "".join(f"<li>{x._repr_html_()}</li>" for x in self.jobs)
        desc += "".join(f"<li>{x._repr_html_()}</li>" for x in self.bank_accounts)
        desc += "".join(f"<li>{x._repr_html_()}</li>" for x in self.homes)
        desc += "".join(f"<li>{x._repr_html_()}</li>" for x in self.apartments)
        desc += f"<li>Debt: {self.debt}</li>"
        desc += "</ul>"
        return desc

    @property
    def bank_account_balance(self) -> float:
        return sum(x.balance for x in self.bank_accounts)

    @staticmethod
    def _withdraw_sequence(withdrawers, amount: float) -> float:
        """Withdraw ``amount`` from a sequence of withdraw callables, in order.

        Each callable takes the remaining amount and returns how much it withdrew.

        Returns:
            float: The shortfall (amount that could not be withdrawn).
        """
        remaining = amount
        for withdraw in withdrawers:
            if remaining <= 0:
                break
            remaining -= withdraw(remaining)
        return remaining

    def deduct_from_bank_accounts(self, amount: float) -> float:
        """Deducts money from bank accounts.

        Args:
            amount (float): Amount to deduct.

        Returns:
            float: Amount that could not be deducted.
        """
        return self._withdraw_sequence((account.withdraw for account in self.bank_accounts), amount)

    def deduct_from_pretax_401ks(self, amount: float) -> float:
        """Deducts money from pre-tax 401ks.

        Args:
            amount (float): Amount to deduct.

        Returns:
            float: Amount that could not be deducted.
        """
        return self._withdraw_sequence((account.deduct_pretax for account in self.all_retirement_accounts), amount)

    def deduct_from_roth_401ks(self, amount: float) -> float:
        """Deducts money from roth 401ks.

        Args:
            amount (float): Amount to deduct.

        Returns:
            float: Amount that could not be deducted.
        """
        return self._withdraw_sequence((account.deduct_roth for account in self.all_retirement_accounts), amount)

    def withdraw_from_pretax_401ks(self, amount: float) -> float:
        """Withdraws money from pre-tax 401ks into the bank account.

        The amount actually withdrawn is added to taxable income and deposited into the bank.

        Args:
            amount (float): Amount to withdraw.

        Returns:
            float: Amount actually withdrawn (may be less than requested if funds are short).
        """
        withdrawn = amount - self.deduct_from_pretax_401ks(amount)
        self.taxable_income += withdrawn
        self.receive_cash(withdrawn)
        return withdrawn

    def receive_cash(self, amount: float, source: str = "income"):
        """Receive cash into the person's primary bank account.

        If the person has no bank account, the cash is held in an untracked ``cash`` bucket and a
        warning event is logged once, rather than raising mid-simulation.

        Args:
            amount (float): Amount of cash received.
            source (str, optional): Description of where the cash came from (for the warning event).
        """
        if amount <= 0:
            return
        if self.bank_accounts:
            self.bank_accounts[0].balance += amount
        else:
            self.cash += amount
            if not self._warned_no_bank_account:
                self.model.event_log.add(
                    Event(f"{self.name} received ${amount:,.0f} from {source} but has no bank account; holding as cash")
                )
                self._warned_no_bank_account = True

    def deposit_into_bank_account(self, amount: float):
        """Deposits money into the primary bank account (see receive_cash).

        Args:
            amount (float): Amount to deposit.
        """
        self.receive_cash(amount)

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

    def get_married(self, spouse: "Person", link_spouse: bool = True):
        """Get married.

        Args:
            spouse (Person): Spouse to get married to.
            link_spouse (bool, optional): Whether to call get_married on the spouse object as well. Defaults to True.
        """
        self.spouse = spouse
        self.filing_status = FilingStatus.MARRIED_FILING_JOINTLY
        if link_spouse:
            # Merge the spouse's family into this person's family so the couple settles as a
            # single joint tax unit (previously each spouse could sit in a separate family and
            # each compute a full MFJ tax on half the income).
            if spouse.family is not self.family:
                vacated_family = spouse.family
                for member in list(vacated_family.members):
                    member.family = self.family
                    if member not in self.family.members:
                        self.family.members.append(member)
                vacated_family.members = []
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
        # Year-end settlement (taxes, spending, housing, one-time expenses, debt) is performed
        # at the tax-unit level in Family.step. Here the person only handles retirement.
        #
        # Retirement uses crossing detection (>=, fired once) so that a non-integer retirement
        # age still triggers and a person can't draw a full salary while "retired".
        if not self.retirement_triggered and self.age >= self.retirement_age:
            for job in self.jobs:
                job.retire()
            self.retirement_triggered = True

        if not self._retirement_age_event_logged and self.age >= int(federal_retirement_age()):
            self.model.event_log.add(Event(f"{self.name} reached retirement age (age {federal_retirement_age()})"))
            self._retirement_age_event_logged = True

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
            base_percent (float): Percentage increase in spending. 50 = 50%.
        """
        self.base = self.base * (base_percent / 100)

    def post_step(self):
        # Consume-then-advance: the year's spending is read during the step stage; only after
        # it has been spent do we clear one-time expenses and apply the yearly increase.
        self.base += self.base * (self.yearly_increase / 100)
        self.one_time_expenses = 0
