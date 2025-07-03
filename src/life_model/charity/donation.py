# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from enum import Enum
from ..people.person import Person
from ..model import LifeModelAgent


class DonationType(Enum):
    """ Enum for donation types """
    CASH = "Cash"
    STOCK = "Stock"
    PROPERTY = "Property"
    OTHER = "Other"


class Donation(LifeModelAgent):
    def __init__(self, person: Person, charity_name: str, amount: float,
                 donation_type: DonationType, tax_deductible: bool = True):
        """ Models a charitable donation for a person

        Args:
            person: The person making the donation
            charity_name: Name of the charity receiving the donation
            amount: Amount of the donation
            donation_type: Type of donation (cash, stock, property, etc.)
            tax_deductible: Whether the donation is tax deductible
        """
        super().__init__(person.model)
        self.person = person
        self.charity_name = charity_name
        self.amount = amount
        self.donation_type = donation_type
        self.tax_deductible = tax_deductible

    def _repr_html_(self):
        desc = '<ul>'
        desc += f'<li>Charity: {self.charity_name}</li>'
        desc += f'<li>Amount: ${self.amount:,.2f}</li>'
        desc += f'<li>Type: {self.donation_type.value}</li>'
        desc += f'<li>Tax Deductible: {self.tax_deductible}</li>'
        desc += '</ul>'
        return desc
