# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html
from typing import TYPE_CHECKING
from ..model import LifeModelAgent

if TYPE_CHECKING:
    from ..people.person import Person


class Child(LifeModelAgent):
    def __init__(self, person: 'Person', name: str, birth_year: int):
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

    @property
    def age(self) -> int:
        """Calculate child's current age based on model year"""
        return self.model.year - self.birth_year

    def _repr_html_(self):
        desc = '<ul>'
        desc += f'<li>Name: {html.escape(self.name)}</li>'
        desc += f'<li>Birth Year: {self.birth_year}</li>'
        desc += f'<li>Age: {self.age}</li>'
        desc += '</ul>'
        return desc
