from .basemodel import BaseModel, Event
from .tax.federal import FilingStatus, federal_income_tax
from .limits import federal_retirement_age


class Person(BaseModel):
    def __init__(self, family, name, age, retirement_age, spending, life_events=None):
        self.life_events = [] if life_events is None else life_events
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

        self.stat_money_spent = 0
        self.stat_taxes_paid = 0

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
        # - RMDs are handled elsewhere by moving the RMD from 401k to bank account
        # TODO - Should add more detail about prioritizing which account to pull from
        all_retirement_accounts = [x.retirement_account for x in self.jobs if x.retirement_account is not None]
        all_retirement_accounts.extend(self.legacy_retirement_accounts)
        for retirement_account in all_retirement_accounts:
            if (spending_balance == 0):
                break
            spending_balance -= retirement_account.deduct(spending_balance)
        return spending_balance

    def get_federal_taxes_due(self):
        if self.filing_status == FilingStatus.MARRIED_FILING_JOINTLY:
            combined_income = self.taxable_income + self.spouse.taxable_income
            yearly_taxes = federal_income_tax(combined_income, self.filing_status)
            # Set both taxable incomes to 0 so spouse wont pay any additional taxes
            self.taxable_income = 0
            self.spouse.taxable_income = 0
            return yearly_taxes
        elif self.filing_status == FilingStatus.SINGLE:
            return federal_income_tax(self.taxable_income, self.filing_status)
        else:
            raise NotImplementedError(f"Unsupported filing status: {self.filing_status}")

    def get_married(self, spouse, link_spouse=True):
        self.spouse = spouse
        self.filing_status = FilingStatus.MARRIED_FILING_JOINTLY
        if link_spouse:
            spouse.get_married(self, False)
            self.event_log.add(Event(f"{self.name} and {spouse.name} got married at age {self.age} and {spouse.age}"))

    def advance_year(self, objects=None):
        self.taxable_income = 0
        self.age += 1

        # Retire from all jobs at retirement age
        if self.age == self.retirement_age:
            while(self.jobs):
                self.jobs.pop(0).retire()

        # Perform life events at the new age
        self.life_events = [x for x in self.life_events if not x.eval_event(self.age)]

        # Advance the year for all sub-objects
        super().advance_year(objects)

        # Pay off spending, taxes, and debts for the year
        yearly_taxes = self.get_federal_taxes_due()
        self.debt += self.pay_bills(self.spending.base + yearly_taxes)
        self.debt = self.pay_bills(self.debt)

        if (self.age == int(federal_retirement_age())):
            self.event_log.add(Event(f"{self.name} reached retirement age (age {federal_retirement_age()})"))

        self.stat_money_spent = self.spending.base
        self.stat_taxes_paid = yearly_taxes


class Spending(BaseModel):
    def __init__(self, base, yearly_increase):
        self.base = base
        self.yearly_increase = yearly_increase

    def advance_year(self, objects=None):
        super().advance_year(objects)
        self.base += (self.base * (self.yearly_increase / 100))


class LifeEvent():
    def __init__(self, age, event, *event_args):
        self.age = age
        self.event = event
        self.event_args = event_args

    def eval_event(self, age):
        if self.age == age:
            self.event(*self.event_args)
            return True
        return False
