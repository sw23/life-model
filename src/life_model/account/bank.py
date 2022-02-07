from ..basemodel import BaseModel, compound_interest


class BankAccount(BaseModel):
    def __init__(self, owner, company, type='Bank', balance=0, interest_rate=0):
        self.owner = owner
        self.company = company
        self.type = type
        self.balance = balance
        self.interest_rate = interest_rate
        self.compound_rate = 12  # Monthly - TODO - make configurable

        self.stat_total_interest = 0
        self.stat_balance_history = []
        self.stat_useable_balance = 0

        owner.bank_accounts.append(self)

    def _repr_html_(self):
        return f"{self.type} account at {self.company} balance: ${self.balance:,}"

    def advance_year(self, objects=None):
        super().advance_year(objects)
        interest = compound_interest(self.balance, self.interest_rate, self.compound_rate)
        self.balance += interest

        self.stat_total_interest += interest
        self.stat_balance_history.append(self.balance)
        self.stat_useable_balance = self.balance

    def deduct(self, amount):
        amount_deducted = min(self.balance, amount)
        self.balance -= amount_deducted
        return amount_deducted
