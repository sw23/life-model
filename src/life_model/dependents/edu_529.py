# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from ..person import Person
from ..model import LifeModelAgent


class Plan529(LifeModelAgent):
    def __init__(self, person: Person, balance: float, state: str):
        """ Models a 529 education savings plan for a person

        Args:
            person: The person who owns this 529 plan
            balance: Current balance in the plan
            state: The state sponsoring the plan
        """
        super().__init__(person.model)
        self.person = person
        self.balance = balance
        self.state = state

    def _repr_html_(self):
        desc = '<ul>'
        desc += f'<li>Balance: ${self.balance:,.2f}</li>'
        desc += f'<li>State: {self.state}</li>'
        desc += '</ul>'
        return desc
