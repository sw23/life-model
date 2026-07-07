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

    # Boundary between the childcare band (0 to CHILDCARE_END_AGE-1, ~0-5) and the school-age band
    # (CHILDCARE_END_AGE to adult_age-1, ~6-17). Kept as a constant rather than a config knob to
    # match the DependentsConfig field list.
    CHILDCARE_END_AGE = 6

    @property
    def age(self) -> int:
        """Calculate child's current age based on model year"""
        return self.model.year - self.birth_year

    @property
    def in_college_band(self) -> bool:
        """Whether the child is in the college-cost band this year."""
        cfg = self.model.config.dependents
        return cfg.college_start_age <= self.age < cfg.college_start_age + cfg.college_years

    def nominal_cost_for_age(self, age: int) -> float:
        """Start-year-dollar cost of the child at ``age`` (before inflation indexing).

        Age bands (from config): childcare (0 .. CHILDCARE_END_AGE-1), school-age
        (CHILDCARE_END_AGE .. adult_age-1), and college (college_start_age .. +college_years).
        Costs are zero for a not-yet-born child (negative age) and for an adult past the college
        band.
        """
        cfg = self.model.config.dependents
        if age < 0:
            return 0.0
        if age < self.CHILDCARE_END_AGE:
            return cfg.childcare_annual_cost
        if age < cfg.adult_age:
            return cfg.school_age_annual_cost
        if cfg.college_start_age <= age < cfg.college_start_age + cfg.college_years:
            return cfg.college_annual_cost
        return 0.0

    def yearly_cost(self) -> float:
        """This year's child cost in current (nominal) dollars.

        The nominal band cost is grown by cumulative inflation from the start year so a child born
        later costs later-year dollars (D2).
        """
        nominal = self.nominal_cost_for_age(self.age)
        if nominal <= 0:
            return 0.0
        return nominal * self.model.economy.cumulative_inflation(self.model.year)

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

    def pre_step(self):
        """Charge this year's child cost to the owning person's spending.

        Runs in the pre_step stage so the expense is present when the tax unit reads
        ``get_yearly_spending()`` during the step stage (cross-stage ordering, safe under
        construction-order execution). Costs flow through ``Spending.add_expense`` (one-time
        expenses), never ``base`` — ``base`` is compounded by inflation in ``Spending.post_step``
        and would otherwise double-count.
        """
        self.stat_dependent_costs = 0.0
        if self.person.is_deceased:
            return
        cost = self.yearly_cost()
        if cost <= 0:
            return
        self.person.spending.add_expense(cost)
        self.stat_dependent_costs = cost

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Name: {html.escape(self.name)}</li>"
        desc += f"<li>Birth Year: {self.birth_year}</li>"
        desc += f"<li>Age: {self.age}</li>"
        desc += "</ul>"
        return desc
