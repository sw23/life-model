# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from .basemodel import BaseModel, Event
from .limits import federal_retirement_age
from .tax.federal import FilingStatus, federal_income_tax, max_tax_rate


class Person(BaseModel):
    def __init__(self, family, name, age, retirement_age, spending):
        """Person

        Args:
            family (Family): Family of which the person is a part.
            name (str): Person's name.
            age (int): Person's age.
            retirement_age (float): Person's retirement age.
            spending (Spending): Person's spending habits.
        """
        self.simulation = family.simulation
        self.family = family
        self.name = name
        self.age = age
        self.retirement_age = retirement_age
        self.spending = spending
        self.jobs = []
        self.debt = 0
        self.bank_accounts = []
        self.legacy_retirement_accounts = []
        self.taxable_income = 0
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
    def all_retirement_accounts(self):
        accounts = [x.retirement_account for x in self.jobs if x.retirement_account is not None]
        accounts.extend(self.legacy_retirement_accounts)
        return accounts

    def _repr_html_(self):
        desc = self.name
        desc += '<ul>'
        desc += f'<li>Age: {self.age}</li>'
        desc += f'<li>Retirement Age: {self.retirement_age}</li>'
        desc += ''.join(f"<li>{x._repr_html_()}</li>" for x in self.jobs)
        desc += ''.join(f"<li>{x._repr_html_()}</li>" for x in self.bank_accounts)
        desc += ''.join(f"<li>{x._repr_html_()}</li>" for x in self.legacy_retirement_accounts)
        desc += ''.join(f"<li>{x._repr_html_()}</li>" for x in self.homes)
        desc += ''.join(f"<li>{x._repr_html_()}</li>" for x in self.apartments)
        desc += f'<li>Debt: {self.debt}</li>'
        desc += '</ul>'
        return desc

    @property
    def bank_account_balance(self):
        return sum(x.balance for x in self.bank_accounts)

    def deduct_from_bank_accounts(self, amount):
        spending_balance = amount
        for bank_account in self.bank_accounts:
            if (spending_balance == 0):
                break
            spending_balance -= bank_account.deduct(spending_balance)
        return spending_balance

    def deduct_from_pretax_401ks(self, amount):
        spending_balance = amount
        for retirement_account in self.all_retirement_accounts:
            if (spending_balance == 0):
                break
            spending_balance -= retirement_account.deduct_pretax(spending_balance)
        return spending_balance

    def deduct_from_roth_401ks(self, amount):
        spending_balance = amount
        for retirement_account in self.all_retirement_accounts:
            if (spending_balance == 0):
                break
            spending_balance -= retirement_account.deduct_roth(spending_balance)
        return spending_balance

    def withdraw_from_pretax_401ks(self, amount):
        amount -= self.deduct_from_pretax_401ks(amount)
        self.taxable_income += amount
        self.bank_accounts[0].balance += amount
        return amount

    def pay_bills(self, spending_balance):

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

    def get_federal_taxes_due(self, additional_income=0):
        income_amount = self.taxable_income + additional_income
        if self.filing_status == FilingStatus.SINGLE:
            return federal_income_tax(income_amount, self.filing_status)
        else:
            raise NotImplementedError(f"Unsupported filing status: {self.filing_status}")

    def get_married(self, spouse, link_spouse=True):
        self.spouse = spouse
        self.filing_status = FilingStatus.MARRIED_FILING_JOINTLY
        if link_spouse:
            spouse.get_married(self, False)
            self.event_log.add(Event(f"{self.name} and {spouse.name} got married at age {self.age} and {spouse.age}"))

    def get_year_at_age(self, age):
        return self.year + (age - self.age)

    def advance_year(self, objects=None):
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
            while self.jobs:
                self.jobs.pop(0).retire()

        # Advance the year for all sub-objects
        super().advance_year(objects)

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
            self.event_log.add(Event(f"{self.name} reached retirement age (age {federal_retirement_age()})"))

        self.stat_money_spent = discretionary_spending
        self.stat_taxes_paid = yearly_taxes
        self.stat_bank_balance = self.bank_account_balance
        self.stat_home_expenses_paid = home_spending
        self.stat_interest_paid = home_interest_paid
        self.stat_rent_paid = apartment_rent


class Spending(BaseModel):
    def __init__(self, base, yearly_increase):
        """Spending

        Args:
            base (float): Base spending amount.
            yearly_increase (float): Yearly percentage increase in spending.
        """
        self.base = base
        self.yearly_increase = yearly_increase
        self.one_time_expenses = 0

    def add_expense(self, amount):
        self.one_time_expenses += amount

    def get_yearly_spending(self):
        return self.base + self.one_time_expenses

    def advance_year(self, objects=None):
        super().advance_year(objects)
        self.base += (self.base * (self.yearly_increase / 100))
        self.one_time_expenses = 0
