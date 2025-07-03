# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from ..people.person import Person
from ..model import LifeModelAgent


class Pension(LifeModelAgent):
    def __init__(self, person: Person, company: str, vesting_years: int, benefit_amount: float):
        """ Models a pension plan for a person

        Args:
            person: The person to which this pension belongs
            company: The company providing the pension
            vesting_years: Number of years required for vesting
            benefit_amount: Monthly or annual benefit amount
        """
        super().__init__(person.model)
        self.person = person
        self.company = company
        self.vesting_years = vesting_years
        self.benefit_amount = benefit_amount

    def _repr_html_(self):
        desc = '<ul>'
        desc += f'<li>Company: {self.company}</li>'
        desc += f'<li>Vesting Years: {self.vesting_years}</li>'
        desc += f'<li>Benefit Amount: ${self.benefit_amount:,.2f}</li>'
        desc += '</ul>'
        return desc
