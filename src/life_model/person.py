from .basemodel import BaseModel, Event
from .tax.federal import FilingStatus, federal_income_tax, max_tax_rate
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
        self.yearly_taxes_paid = False

        self.stat_money_spent = 0
        self.stat_taxes_paid = 0
        self.stat_bank_balance = 0

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

    def advance_year(self, objects=None):
        self.yearly_taxes_paid = False
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
        # - People filing single is handled individually here, MFJ is handled in family
        if self.filing_status == FilingStatus.SINGLE:
            # 1. See what amount needs to come from pre-tax 401k
            #    - RMDs are handled before this by moving the RMD from 401k to bank account
            # 2. Withdraw that amount plus max tax rate to cover taxes
            # 3. Deposit that amount into checking
            yearly_taxes = self.get_federal_taxes_due()
            spending_plus_pre_401k_taxes = self.spending.base + yearly_taxes
            amount_from_pretax_401k = max(0, spending_plus_pre_401k_taxes - self.bank_account_balance)
            taxes_from_pretax_401k = self.get_federal_taxes_due(amount_from_pretax_401k) - yearly_taxes
            taxes_from_pretax_401k += taxes_from_pretax_401k * (max_tax_rate(self.filing_status) / 100)
            self.withdraw_from_pretax_401ks(amount_from_pretax_401k + taxes_from_pretax_401k)

            # Now that 401k withdrawal is complete (if necessary), calculatue taxes
            if amount_from_pretax_401k:
                yearly_taxes = self.get_federal_taxes_due()

            self.debt += self.pay_bills(self.spending.base + yearly_taxes)
            self.debt = self.pay_bills(self.debt)
        else:
            yearly_taxes = 0

        if (self.age == int(federal_retirement_age())):
            self.event_log.add(Event(f"{self.name} reached retirement age (age {federal_retirement_age()})"))

        self.stat_money_spent = self.spending.base
        self.stat_taxes_paid = yearly_taxes
        self.stat_bank_balance = self.bank_account_balance


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
