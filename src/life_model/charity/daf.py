# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from ..person import Person
from ..model import LifeModelAgent


class DonorAdvisedFund(LifeModelAgent):
    def __init__(self, person: Person, fund_name: str, balance: float):
        """ Models a donor advised fund for a person

        Args:
            person: The person to which this fund belongs
            fund_name: Name of the donor advised fund
            balance: Current balance in the fund
        """
        super().__init__(person.model)
        self.person = person
        self.fund_name = fund_name
        self.balance = balance

    def _repr_html_(self):
        desc = '<ul>'
        desc += f'<li>Fund Name: {self.fund_name}</li>'
        desc += f'<li>Balance: ${self.balance:,.2f}</li>'
        desc += '</ul>'
        return desc
