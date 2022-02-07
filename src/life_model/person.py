from .basemodel import BaseModel
from .tax.federal import federal_income_tax


class Person(BaseModel):
    def __init__(self, family, name, age, retirement_age, spending):
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

        self.stat_money_spent = 0

        self.family.members.append(self)

    def _repr_html_(self):
        desc = self.name
        desc += '<ul>'
        desc += f'<li>Age: {self.age}</li>'
        desc += f'<li>Retirement Age: {self.retirement_age}</li>'
        desc += ''.join(f"<li>{x._repr_html_()}</li>" for x in self.jobs)
        desc += ''.join(f"<li>{x._repr_html_()}</li>" for x in self.bank_accounts)
        desc += f'<li>Debt: {self.debt}</li>'
        desc += '</ul>'
        return desc

    def pay_bills(self, amount):
        # Deduct spending from accounts
        # - Include yearly spending and any debts
        spending_balance = amount
        for bank_account in self.bank_accounts:
            if (spending_balance == 0):
                break
            spending_balance -= bank_account.deduct(spending_balance)
        if (spending_balance == 0):
            return 0

        # Deduct spending from retirement accounts
        # TODO - Currently no penalties or RMDs are considered
        # TODO - Need to take out taxes when pulling from pre-tax 401k
        all_retirement_accounts = [x.retirement_account for x in self.jobs if x.retirement_account is not None]
        all_retirement_accounts.extend(self.legacy_retirement_accounts)
        for retirement_account in all_retirement_accounts:
            if (spending_balance == 0):
                break
            spending_balance -= retirement_account.deduct(spending_balance)
        return spending_balance

    def advance_year(self, objects=None):
        self.taxable_income = 0
        super().advance_year(objects)
        self.age += 1

        # Pay off spending, taxes, and debts for the year
        yearly_taxes = federal_income_tax(self.taxable_income, 'single')  # TODO
        self.debt += self.pay_bills(self.spending.base + yearly_taxes)
        self.debt = self.pay_bills(self.debt)

        # Retire from all jobs at retirement age
        if self.age == self.retirement_age:
            while(self.jobs):
                self.jobs.pop(0).retire()

        self.stat_money_spent = self.spending.base
        self.stat_taxes_paid = yearly_taxes


class Spending(BaseModel):
    def __init__(self, base, yearly_increase):
        self.base = base
        self.yearly_increase = yearly_increase

    def advance_year(self, objects=None):
        super().advance_year(objects)
        self.base += (self.base * (self.yearly_increase / 100))
