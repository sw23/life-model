# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import Optional, TYPE_CHECKING
from ..basemodel import BaseModel, continous_interest
from ..limits import federal_retirement_age, required_min_distrib

if TYPE_CHECKING:
    from ..job import Job


class Job401kAccount(BaseModel):
    def __init__(self, job: 'Job',
                 pretax_balance: float = 0, pretax_contrib_percent: float = 0,
                 roth_balance: float = 0, roth_contrib_percent: float = 0,
                 average_growth: float = 0, company_match_percent: float = 0):
        """401k Account

        Args:
            job (Job): Job offering the 401k plan.
            pretax_balance (float, optional): Initial pre-tax balance of account. Defaults to 0.
            pretax_contrib_percent (float, optional): Pre-tax contribution percentage. Defaults to 0.
            roth_balance (float, optional): Initial roth balance of account. Defaults to 0.
            roth_contrib_percent (float, optional): Roth contribution percentage. Defaults to 0.
            average_growth (float, optional): Average account growth every year. Defaults to 0.
            company_match_percent (float, optional): Percentage that company matches contributions. Defaults to 0.
        """
        self.simulation = job.simulation
        self.job: Optional['Job'] = job
        self.owner = job.owner
        self.pretax_balance = pretax_balance
        self.pretax_contrib_percent = pretax_contrib_percent
        self.roth_balance = roth_balance
        self.roth_contrib_percent = roth_contrib_percent
        self.average_growth = average_growth
        self.company_match_percent = company_match_percent

        self.stat_balance_history = []
        self.stat_useable_balance = 0
        self.stat_required_min_distrib = 0
        self.stat_401k_balance = 0

        job.retirement_account = self

    def pretax_contrib(self, salary: float):
        return salary * (self.pretax_contrib_percent / 100)

    def roth_contrib(self, salary: float):
        return salary * (self.roth_contrib_percent / 100)

    def company_match(self, contribution: float):
        return contribution * (self.company_match_percent / 100)

    @property
    def balance(self):
        return self.pretax_balance + self.roth_balance

    def _repr_html_(self):
        company = self.job.company if self.job is not None else "<None>"
        return f"401k at {company} balance: ${self.balance:,}"

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
        required_min_dist_amount = self.deduct_pretax(required_min_distrib(self.owner.age, self.pretax_balance))
        self.owner.bank_accounts[0].balance += required_min_dist_amount
        self.owner.taxable_income += required_min_dist_amount

        self.stat_required_min_distrib = required_min_dist_amount
        self.stat_401k_balance = self.balance

    def deduct_pretax(self, amount: float):
        """Deduct from pre-tax balance

        Args:
            amount (float): Amount to deduct.

        Returns:
            float: Amount deducted. Will not be less than the account balance.
        """
        # TODO - Need to figure out where early penalties and limits are applied
        amount_deducted = min(self.pretax_balance, amount)
        self.pretax_balance -= amount_deducted
        return amount_deducted

    def deduct_roth(self, amount: float) -> float:
        """Deduct from roth balance

        Args:
            amount (float): Amount to deduct.

        Returns:
            float: Amount deducted. Will not be less than the account balance.
        """
        # TODO - Need to figure out where early penalties and limits are applied
        amount_deducted = min(self.roth_balance, amount)
        self.roth_balance -= amount_deducted
        return amount_deducted
