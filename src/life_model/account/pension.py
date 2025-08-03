# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html
from ..people.person import Person
from ..base_classes import Benefit


class Pension(Benefit):
    def __init__(self, person: Person, company: str, vesting_years: int, benefit_amount: float):
        """ Models a pension plan for a person

        Args:
            person: The person to which this pension belongs
            company: The company providing the pension
            vesting_years: Number of years required for vesting
            benefit_amount: Monthly or annual benefit amount
        """
        super().__init__(person, company)
        self.vesting_years = vesting_years
        self.benefit_amount = benefit_amount

    def get_annual_benefit(self) -> float:
        """Calculate annual benefit amount"""
        if self.is_eligible():
            return self.benefit_amount
        return 0.0

    def is_eligible(self) -> bool:
        """Check if person is eligible to receive benefits"""
        # This is a simplified implementation - in reality this would depend on
        # years of service, age, and other factors
        return self.person.is_retired

    def _repr_html_(self):
        desc = '<ul>'
        desc += f'<li>Company: {html.escape(self.company)}</li>'
        desc += f'<li>Vesting Years: {self.vesting_years}</li>'
        desc += f'<li>Benefit Amount: ${self.benefit_amount:,.2f}</li>'
        desc += '</ul>'
        return desc
