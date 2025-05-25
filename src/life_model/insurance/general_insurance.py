# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from enum import Enum
from ..person import Person
from ..model import LifeModelAgent


class InsuranceType(Enum):
    """Types of insurance coverage"""
    AUTO = "Auto"
    HOME = "Home"
    HEALTH = "Health"
    DISABILITY = "Disability"
    UMBRELLA = "Umbrella"


class Insurance(LifeModelAgent):
    def __init__(self, person: Person, insurance_type: InsuranceType,
                 company: str, annual_premium: float, coverage_amount: float,
                 deductible: float = 0):
        """ Models insurance coverage for a person

        Args:
            person: The person who owns this insurance
            insurance_type: Type of insurance
            company: Insurance company name
            annual_premium: Annual premium cost
            coverage_amount: Coverage amount/limit
            deductible: Insurance deductible amount
        """
        super().__init__(person.model)
        self.person = person
        self.insurance_type = insurance_type
        self.company = company
        self.annual_premium = annual_premium
        self.coverage_amount = coverage_amount
        self.deductible = deductible

    def _repr_html_(self):
        desc = '<ul>'
        desc += f'<li>Type: {self.insurance_type.value}</li>'
        desc += f'<li>Company: {self.company}</li>'
        desc += f'<li>Annual Premium: ${self.annual_premium:,.2f}</li>'
        desc += f'<li>Coverage: ${self.coverage_amount:,.2f}</li>'
        desc += f'<li>Deductible: ${self.deductible:,.2f}</li>'
        desc += '</ul>'
        return desc
