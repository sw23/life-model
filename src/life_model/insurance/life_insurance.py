# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from enum import Enum
from ..people.person import Person
from ..model import LifeModelAgent


class LifeInsuranceType(Enum):
    """ Enum for life insurance types """
    TERM = "Term"
    WHOLE = "Whole"


class LifeInsurance(LifeModelAgent):
    def __init__(self, person: Person, policy_type: LifeInsuranceType):
        """ Models life insurance policy for a person

        Args:
            person: The person to which this policy belongs
            policy_type: The type of life insurance policy
        """
        super().__init__(person.model)
        self.person = person
        self.policy_type = policy_type

    def _repr_html_(self):
        desc = '<ul>'
        desc += f'<li>Policy Type: {self.policy_type}</li>'
        desc += '</ul>'
        return desc
