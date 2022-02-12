from ..basemodel import BaseModel, continous_interest
from ..limits import federal_retirement_age, required_min_distrib


class Job401kAccount(BaseModel):
    def __init__(self, job,
                 pretax_balance=0, pretax_contrib_percent=0,
                 roth_balance=0, roth_contrib_percent=0,
                 average_growth=0, company_match_percent=0):
        self.job = job
        self.owner = job.owner
        self.pretax_balance = pretax_balance
        self.pretax_contrib_percent = pretax_contrib_percent
        self.roth_balance = roth_balance
        self.roth_contrib_percent = roth_contrib_percent
        self.average_growth = average_growth
        self.company_match_percent = company_match_percent

        self.stat_contributions = 0
        self.stat_balance_history = []
        self.stat_useable_balance = 0

        job.retirement_account = self

    def pretax_contrib(self, salary):
        return salary * (self.pretax_contrib_percent / 100)

    def roth_contrib(self, salary):
        return salary * (self.roth_contrib_percent / 100)

    def company_match(self, contribution):
        return contribution * (self.company_match_percent / 100)

    @property
    def balance(self):
        return self.pretax_balance + self.roth_balance

    def _repr_html_(self):
        return f"401k at {self.job.company} balance: ${self.balance:,}"

    def advance_year(self, objects=None):
        super().advance_year(objects)
        # Note: Contributions are handled by job, after this is called
        # This isn't 100% accurate since contributions aren't included in the
        # growth, which is a little pessimistic but that should be fine
        self.pretax_balance += continous_interest(self.pretax_balance, self.average_growth)
        self.roth_balance += continous_interest(self.roth_balance, self.average_growth)

        self.stat_balance_history.append(self.balance)
        if (self.owner.age > federal_retirement_age()):
            self.stat_useable_balance = self.balance

        # Required minimum distributions
        # - Based on the owner's age, force withdraw the required minium
        required_min_dist_amount = min(required_min_distrib(self.owner.age, self.pretax_balance), self.pretax_balance)
        self.pretax_balance -= required_min_dist_amount
        self.owner.bank_accounts[0].balance += required_min_dist_amount
        self.owner.taxable_income += required_min_dist_amount

    def deduct(self, amount):
        # TODO - Need to figure out where early penalties and limits are applied
        pretax_amount_deducted = min(self.pretax_balance, amount)
        self.pretax_balance -= pretax_amount_deducted
        amount -= pretax_amount_deducted
        roth_amount_deducted = min(self.roth_balance, amount)
        self.roth_balance -= roth_amount_deducted
        amount -= roth_amount_deducted
        return pretax_amount_deducted + roth_amount_deducted
