# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from ..people.person import Person
from ..model import LifeModelAgent


class Child(LifeModelAgent):
    def __init__(self, person: Person, name: str, birth_year: int):
        """ Models a child dependent for a person

        Args:
            person: The person to which this child belongs
            name: The name of the child
            birth_year: The year the child was born
        """
        super().__init__(person.model)
        self.person = person
        self.name = name
        self.birth_year = birth_year

    def _repr_html_(self):
        desc = '<ul>'
        desc += f'<li>Name: {self.name}</li>'
        desc += f'<li>Birth Year: {self.birth_year}</li>'
        desc += '</ul>'
        return desc
