# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html
from typing import TYPE_CHECKING, Optional

from ..model import LifeModelAgent

if TYPE_CHECKING:
    from ..people.person import Person, Spending


class Child(LifeModelAgent):
    def __init__(self, person: "Person", name: str, birth_year: int):
        """Models a child dependent for a person

        Args:
            person: The person to which this child belongs
            name: The name of the child
            birth_year: The year the child was born
        """
        super().__init__(person.model)
        self.person = person
        self.name = name
        self.birth_year = birth_year
        self.stat_dependent_costs = 0.0
        # Register so the child is visible to the person (Person.children) and to death-time
        # ownership reassignment (registries.iter_registries drives estate transfer).
        self.model.registries.children.register(person, self)

    @property
    def age(self) -> int:
        """Calculate child's current age based on model year"""
        return self.model.year - self.birth_year

    def grow_up(self, *, retirement_age: float = 65, spending: "Optional[Spending]" = None) -> "Person":
        """Promote this child to an independent ``Person`` in the same family and stop modeling
        them as a dependent.

        v1 has no automatic promotion; call this manually or schedule it via a ``LifeEvent``. The
        new person joins the child's parent's family; the ``Child`` is unregistered and removed so
        it no longer incurs costs.

        Args:
            retirement_age: Retirement age for the new adult (keyword-only, default 65).
            spending: Spending habits for the new adult. Defaults to zero-base spending.

        Returns:
            The newly created ``Person``.
        """
        from ..people.person import Person, Spending

        if spending is None:
            spending = Spending(self.model, 0)
        adult = Person(self.person.family, self.name, self.age, retirement_age, spending)
        self.model.registries.children.unregister(self.person, self)
        self.remove()
        return adult

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Name: {html.escape(self.name)}</li>"
        desc += f"<li>Birth Year: {self.birth_year}</li>"
        desc += f"<li>Age: {self.age}</li>"
        desc += "</ul>"
        return desc
