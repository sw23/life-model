# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from enum import Enum
from ..person import Person
from ..model import LifeModelAgent


class AnnuityType(Enum):
    """ Enum for annuity types """
    FIXED = "Fixed"
    VARIABLE = "Variable"
    IMMEDIATE = "Immediate"
    DEFERRED = "Deferred"


class Annuity(LifeModelAgent):
    def __init__(self, person: Person, annuity_type: AnnuityType, balance: float, interest_rate: float):
        """ Models an annuity for a person

        Args:
            person: The person to which this annuity belongs
            annuity_type: The type of annuity
            balance: Current balance in the annuity
            interest_rate: Annual interest rate percentage
        """
        super().__init__(person.model)
        self.person = person
        self.annuity_type = annuity_type
        self.balance = balance
        self.interest_rate = interest_rate

    def _repr_html_(self):
        desc = '<ul>'
        desc += f'<li>Annuity Type: {self.annuity_type.value}</li>'
        desc += f'<li>Balance: ${self.balance:,.2f}</li>'
        desc += f'<li>Interest Rate: {self.interest_rate}%</li>'
        desc += '</ul>'
        return desc
