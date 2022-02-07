from .basemodel import BaseModel
from .limits import job_401k_contrib_limit


class Job(BaseModel):
    def __init__(self, owner, company, role, salary):
        self.owner = owner
        self.company = company
        self.role = role
        self.salary = salary
        self.retirement_account = None

        self.stat_gross_income = 0

        self.owner.jobs.append(self)

    def _repr_html_(self):
        return f"{self.role} at {self.company}"

    def advance_year(self, objects=None):
        super().advance_year(objects)

        remaining_401k_contrib = min(self.salary.base, job_401k_contrib_limit(self.owner.age))
        # Deduct pre-tax contribution from income
        if self.retirement_account is not None:
            yearly_pretax_contrib = min(remaining_401k_contrib,
                                        self.retirement_account.pretax_contrib(self.salary.base))
            remaining_401k_contrib -= yearly_pretax_contrib

        if self.retirement_account is not None:
            yearly_roth_contrib = min(remaining_401k_contrib, self.retirement_account.roth_contrib(self.salary.base))
            remaining_401k_contrib -= yearly_roth_contrib

        # Note: Contributions are handled here, after 401k growth is calculated
        # This isn't 100% accurate since contributions aren't included in the
        # growth, which is a little pessimistic but that should be fine
        if self.retirement_account is not None:
            self.retirement_account.pretax_balance += yearly_pretax_contrib
            self.retirement_account.roth_balance += yearly_roth_contrib
            yearly_401k_contrib = yearly_pretax_contrib + yearly_roth_contrib
            self.retirement_account.pretax_balance += self.retirement_account.company_match(yearly_401k_contrib)

        gross_income = self.salary.base + self.salary.bonus

        # Deposit take-home pay into bank account
        self.owner.bank_accounts[0].balance += gross_income - yearly_401k_contrib

        # Add to taxable income for the person
        # - Taxes are dedudcted in the person class
        self.owner.taxable_income += gross_income - yearly_pretax_contrib

        self.stat_gross_income = gross_income

    def retire(self):
        # Turn over control of the retirement account to the user
        if self.retirement_account is not None:
            self.owner.legacy_retirement_accounts.append(self.retirement_account)
        # Remove the job associated with the acount
        self.retirement_account.job = None


class Salary(BaseModel):
    def __init__(self, base, yearly_increase, yearly_bonus):
        self.base = base
        self.yearly_increase = yearly_increase
        self.yearly_bonus = yearly_bonus

    @property
    def bonus(self):
        return self.base * (self.yearly_bonus / 100)

    def advance_year(self, objects=None):
        super().advance_year(objects)
        self.base += self.base * (self.yearly_increase / 100)
