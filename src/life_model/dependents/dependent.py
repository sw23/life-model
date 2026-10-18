# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""A dependent other than a child: a qualifying relative (IRC §152(d)) such as a parent (Plan 31 D5)."""

import html
from typing import TYPE_CHECKING

from ..model import LifeModelAgent, snap_money

if TYPE_CHECKING:
    from ..people.person import Person

#: Relationships a qualifying relative may have to the taxpayer (IRC §152(d)(2)); ``member_of_household``
#: is any other person who lives with the taxpayer all year.
RELATIONSHIPS = ("parent", "grandparent", "sibling", "adult_child", "other_relative", "member_of_household")


class Dependent(LifeModelAgent):
    """A qualifying relative the person supports (IRC §152(d)): e.g. a parent.

    Tax effects (each year the dependent qualifies: gross income below the year's §152(d)(1)(B) exemption
    amount, ``tax_years.<year>.qualifying_relative_income_limit``):

    * the credit for other dependents ($500, IRC §24(h)(4)) on the supporter's return;
    * head of household for an unmarried supporter (IRC §2(b)): a parent qualifies without living with the
      supporter (the supporter pays more than half the cost of the parent's home), any other relative only
      when ``lives_with`` the supporter;
    * a state dependent exemption or credit where the state has one.

    ``support_annual`` (start-year dollars, grown by inflation) is charged a twelfth a month to the
    supporter's spending, like a child's cost. Support itself is not deductible; medical costs paid for a
    dependent are not modeled separately.
    """

    STATS_OWNED = frozenset({"stat_dependent_costs"})

    def __init__(
        self,
        person: "Person",
        name: str,
        *,
        relationship: str = "parent",
        birth_year: int | None = None,
        gross_income_annual: float = 0.0,
        support_annual: float = 0.0,
        lives_with: bool = False,
    ):
        """Dependent

        Args:
            person: The person who supports (and claims) the dependent.
            name: The dependent's name.
            relationship: One of :data:`RELATIONSHIPS` (default ``"parent"``).
            birth_year: The dependent's birth year (informational).
            gross_income_annual: The dependent's own gross income a year (Social Security benefits do not
                count), in start-year dollars; at or above the year's limit the dependent does not qualify.
            support_annual: What the supporter spends on the dependent a year (start-year dollars, grown by
                inflation), paid a twelfth a month.
            lives_with: Whether the dependent lives with the supporter (needed for head of household unless
                the dependent is a parent).
        """
        if relationship not in RELATIONSHIPS:
            raise ValueError(f"Unknown relationship {relationship!r}; expected one of {RELATIONSHIPS}")
        if gross_income_annual < 0 or support_annual < 0:
            raise ValueError("Dependent amounts must be non-negative")
        super().__init__(person.model)
        self.person = person
        self.name = name
        self.relationship = relationship
        self.birth_year = birth_year
        self.gross_income_annual = gross_income_annual
        self.support_annual = support_annual
        self.lives_with = lives_with
        self.stat_dependent_costs = 0.0
        self.model.registries.qualifying_relatives.register(person, self)

    def gross_income(self, year: int) -> float:
        """The dependent's gross income in ``year`` (nominal: start-year dollars grown by inflation)."""
        return self.gross_income_annual * self.model.economy.cumulative_inflation(year)

    def qualifies(self, year: int) -> bool:
        """Whether the dependent is a qualifying relative in ``year``: gross income below the year's
        §152(d)(1)(B) limit (no limit configured: always)."""
        limit = self.model.tax_params_for_year(year).qualifying_relative_income_limit
        return limit is None or self.gross_income(year) < limit

    @property
    def qualifies_for_head_of_household(self) -> bool:
        """A head-of-household qualifying person (IRC §2(b)(1)): a parent wherever they live, anyone else
        only when living with the supporter."""
        return self.qualifies(self.model.year) and (self.relationship == "parent" or self.lives_with)

    def pre_step(self):
        """Charge this month's support to the supporter's spending."""
        if self.person.is_deceased or self.support_annual <= 0:
            return
        cost = self.support_annual * self.model.economy.cumulative_inflation(self.model.year) / 12
        self.person.spending.add_expense(cost, category="dependents")
        self.stat_dependent_costs = snap_money(self.stat_dependent_costs + cost)

    def _repr_html_(self):
        return f"<ul><li>Name: {html.escape(self.name)}</li><li>Relationship: {self.relationship}</li></ul>"
