# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import List
from .model import LifeModelAgent, LifeModel, Event
from .family import Family
from .limits import federal_retirement_age
from .tax.federal import FilingStatus, federal_income_tax, max_tax_rate
from .account.job401k import Job401kAccount


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
        self.jobs = []
        self.debt = 0
        self.bank_accounts = []
        self.taxable_income: float = 0
        self.spouse = None
        self.filing_status = FilingStatus.SINGLE
        self.yearly_taxes_paid = False
        self.homes = []
        self.apartments = []

        self.stat_money_spent = 0
        self.stat_taxes_paid = 0
        self.stat_bank_balance = 0
        self.stat_home_expenses_paid = 0
        self.stat_interest_paid = 0
        self.stat_rent_paid = 0

        self.family.members.append(self)

    @property
    def all_retirement_accounts(self) -> List[Job401kAccount]:
        return [x.retirement_account for x in self.jobs if x.retirement_account is not None]

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
            spending_balance -= bank_account.deduct(spending_balance)
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
        self.bank_accounts[0].balance += amount
        return amount

    def pay_bills(self, spending_balance: float) -> float:
        """Pays bills.

        Args:
            spending_balance (float): Amount of money spent.

        Returns:
            float: Amount that could not be paid.
        """

        # Deduct spending from bank accounts
        # - Include yearly spending and any debts
        spending_balance = self.deduct_from_bank_accounts(spending_balance)
        if (spending_balance == 0):
            return 0

        # Deduct spending from roth retirement accounts
        # - Taking out of pre-tax 401k is handled ahead of this, so that taxes can be paid as well
        # - Pull from roth accounts last, to keep them invested as long as possible
        #   https://www.investopedia.com/retirement/how-to-manage-timing-and-sources-of-income-retirement/
        spending_balance = self.deduct_from_roth_401ks(spending_balance)
        return spending_balance

    def get_federal_taxes_due(self, additional_income: float = 0) -> float:
        """Gets federal taxes due.

        Args:
            additional_income (float, optional): Additional income to include, not present in taxable_income.

        Raises:
            NotImplementedError: Unsupported filing status.

        Returns:
            float: Federal taxes due.
        """
        income_amount = self.taxable_income + additional_income
        if self.filing_status == FilingStatus.SINGLE:
            return federal_income_tax(income_amount, self.filing_status)
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

    def step(self):
        self.yearly_taxes_paid = False
        self.taxable_income = 0
        self.age += 1

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
            # 1. See what amount needs to come from pre-tax 401k
            #    - RMDs are handled before this by moving the RMD from 401k to bank account
            # 2. Withdraw that amount plus max tax rate to cover taxes
            # 3. Deposit that amount into checking
            yearly_taxes = self.get_federal_taxes_due()
            spending_plus_pre_401k_taxes = all_bills_except_taxes + yearly_taxes
            amount_from_pretax_401k = max(0, spending_plus_pre_401k_taxes - self.bank_account_balance)
            taxes_from_pretax_401k = self.get_federal_taxes_due(amount_from_pretax_401k) - yearly_taxes
            taxes_from_pretax_401k += taxes_from_pretax_401k * (max_tax_rate(self.filing_status) / 100)
            self.withdraw_from_pretax_401ks(amount_from_pretax_401k + taxes_from_pretax_401k)

            # Now that 401k withdrawal is complete (if necessary), calculatue taxes
            if amount_from_pretax_401k:
                yearly_taxes = self.get_federal_taxes_due()

            self.debt += self.pay_bills(all_bills_except_taxes + yearly_taxes)
            self.debt = self.pay_bills(self.debt)
        else:
            yearly_taxes = 0

        if (self.age == int(federal_retirement_age())):
            self.model.event_log.add(Event(f"{self.name} reached retirement age (age {federal_retirement_age()})"))

        self.stat_money_spent = discretionary_spending
        self.stat_taxes_paid = yearly_taxes
        self.stat_bank_balance = self.bank_account_balance
        self.stat_home_expenses_paid = home_spending
        self.stat_interest_paid = home_interest_paid
        self.stat_rent_paid = apartment_rent


class Spending(LifeModelAgent):
    def __init__(self, model: LifeModel, base: float, yearly_increase: float):
        """Spending

        Args:
            base (float): Base spending amount.
            yearly_increase (float): Yearly percentage increase in spending.
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

    def step(self):
        self.base += (self.base * (self.yearly_increase / 100))
        self.one_time_expenses = 0
