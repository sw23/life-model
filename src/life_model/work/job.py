# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import html
from typing import TYPE_CHECKING, Optional

from ..limits import job_401k_annual_additions_limit
from ..model import Event, LifeModel, LifeModelAgent
from ..people.person import Person

if TYPE_CHECKING:
    from ..account.job401k import Job401kAccount


class Job(LifeModelAgent):
    def __init__(self, owner: Person, company: str, role: str, salary: "Salary"):
        """Job

        Args:
            owner (Person): Person who owns the job.
            company (str): Company name.
            role (str): Job title.
            salary (Salary): Salary of the job.
        """
        super().__init__(owner.model)
        self.owner = owner
        self.company = company
        self.role = role
        self.salary = salary
        self.retirement_account: Optional["Job401kAccount"] = None
        self.retired = False

        self.stat_gross_income = 0
        self.stat_retirement_contrib = 0
        self.stat_retirement_match = 0

        # Register with the model registry
        self.model.registries.jobs.register(self.owner, self)

    def _repr_html_(self):
        return f"{html.escape(self.role)} at {html.escape(self.company)}"

    # Using pre_step() so taxable_income will be set before person's step() is called
    def pre_step(self):
        # If retired, don't do anything
        if self.retired:
            self.stat_gross_income = 0
            self.stat_retirement_contrib = 0
            self.stat_retirement_match = 0
            return

        salary = self.salary.base
        yearly_pretax_contrib = 0.0
        yearly_roth_contrib = 0.0
        company_match = 0.0

        if self.retirement_account is not None:
            account = self.retirement_account
            # Elective deferrals share one 402(g) limit across all of the person's jobs, so two
            # jobs can no longer each defer the full limit.
            room = self.owner.remaining_401k_elective_room()
            yearly_pretax_contrib = min(account.pretax_contrib(salary), room)
            room -= yearly_pretax_contrib
            yearly_roth_contrib = min(account.roth_contrib(salary), room)
            elective = yearly_pretax_contrib + yearly_roth_contrib
            self.owner.record_401k_elective_deferral(elective)

            # Employer match: the configured percentage of the deferral, capped both by
            # match_percent x salary and by the 415(c) overall annual-additions limit (employee +
            # employer money per plan) so the match can't run away.
            salary_cap = (account.company_match_percent / 100) * salary
            company_match = min(account.company_match(elective), salary_cap)
            additions_limit = job_401k_annual_additions_limit(self.owner.model.config)
            company_match = max(0.0, min(company_match, additions_limit - elective))

            account.pretax_balance += yearly_pretax_contrib
            account.roth_balance += yearly_roth_contrib
            account.pretax_balance += company_match

        yearly_401k_contrib = yearly_pretax_contrib + yearly_roth_contrib
        gross_income = self.salary.base + self.salary.bonus

        # Deposit take-home pay into bank account
        self.owner.deposit_into_bank_account(gross_income - yearly_401k_contrib)

        # Add to taxable income for the person
        # - Income tax is settled by the tax unit in Family.step
        # - Elective pre-tax 401k deferrals reduce ordinary income but are still FICA wages, so
        #   the full gross is recorded as the FICA base (fixes the understated-FICA bug).
        self.owner.income.add_wages(ordinary_amount=gross_income - yearly_pretax_contrib, fica_wages=gross_income)
        if self.owner.social_security is not None:
            self.owner.social_security.add_income_for_year(gross_income)

        self.stat_gross_income = gross_income
        self.stat_retirement_contrib = yearly_401k_contrib
        self.stat_retirement_match = company_match

    def retire(self):
        """Retire from the job"""
        self.retired = True
        self.model.event_log.add(Event(f"{self.owner.name} retired from {self.company}"))


class Salary(LifeModelAgent):
    def __init__(self, model: LifeModel, base: float, yearly_increase: float = 0, yearly_bonus: float = 0):
        """Salary

        Args:
            base (float): Base salary.
            yearly_increase (float): Yearly percentage increase.
            yearly_bonus (float): Yearly percentage bonus.
        """
        super().__init__(model)
        self.base = base
        self.yearly_increase = yearly_increase
        self.yearly_bonus = yearly_bonus

    @property
    def bonus(self) -> float:
        return self.base * (self.yearly_bonus / 100)

    def post_step(self):
        # Escalator runs after the year's income has been earned/deposited (consume-then-advance).
        self.base += self.base * (self.yearly_increase / 100)
