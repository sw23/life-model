# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html
from typing import TYPE_CHECKING

from ..model import LifeModelAgent, snap_money

if TYPE_CHECKING:
    from ..people.person import Person, Spending


class Child(LifeModelAgent):
    """A child dependent: the age band's yearly cost is charged a twelfth each month (college months
    drawn from the child's 529 plans first)."""

    STATS_OWNED = frozenset({"stat_dependent_costs"})

    def __init__(
        self,
        person: "Person",
        name: str,
        birth_year: int,
        *,
        care_expenses_annual: float = 0.0,
        interest_annual: float = 0.0,
        dividends_annual: float = 0.0,
        cost_annual: float | None = None,
        college_cost_annual: float | None = None,
    ):
        """Models a child dependent for a person

        Args:
            person: The person to which this child belongs
            name: The name of the child
            birth_year: The year the child was born
            care_expenses_annual: Dependent care (after-school care, day camp, ...) paid for the child
                while under 13, on top of the age-band cost, in start-year dollars (grown by inflation like
                the bands). The childcare band's cost (under 6) already counts as care expenses for the
                child and dependent care credit and a dependent-care FSA.
            interest_annual: The child's own interest income (e.g. a custodial account outside the
                household's balances) each year, for the kiddie tax (the parents report it on Form 8814).
            dividends_annual: The child's own qualified dividends each year (same).
            cost_annual: This child's yearly cost while a dependent (birth to ``adult_age``), in
                start-year dollars, instead of the configured childcare and school-age bands (Plan 27 D6).
                Unlike the childcare band it is not counted as dependent care for the credit: enter care
                in ``care_expenses_annual``.
            college_cost_annual: This child's yearly college cost, in start-year dollars, instead of the
                configured college band.
        """
        super().__init__(person.model)
        self.person = person
        self.name = name
        self.birth_year = birth_year
        self.care_expenses_annual = care_expenses_annual
        self.interest_annual = interest_annual
        self.dividends_annual = dividends_annual
        self.cost_annual = cost_annual
        self.college_cost_annual = college_cost_annual
        self.stat_dependent_costs = 0.0
        #: This year's dependent care expenses (Form 2441), education expenses and the part of them paid
        #: with tax-free 529 withdrawals (Form 8863 / Pub. 970), set in ``pre_step``.
        self.care_expenses_this_year = 0.0
        self.education_expenses_this_year = 0.0
        self.education_paid_by_529 = 0.0
        #: Years the American opportunity credit was claimed for this child (at most four).
        self.aotc_years_claimed = 0
        self._aotc_reserved_this_year = 0.0
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
        if age < cfg.adult_age and self.cost_annual is not None:
            return self.cost_annual
        if age < self.CHILDCARE_END_AGE:
            return cfg.childcare_annual_cost
        if age < cfg.adult_age:
            return cfg.school_age_annual_cost
        if cfg.college_start_age <= age < cfg.college_start_age + cfg.college_years:
            return cfg.college_annual_cost if self.college_cost_annual is None else self.college_cost_annual
        return 0.0

    def yearly_cost(self) -> float:
        """This year's child cost in current (nominal) dollars.

        The nominal band cost is grown by cumulative inflation from the start year so a child born
        later costs later-year dollars.
        """
        nominal = self.nominal_cost_for_age(self.age)
        if nominal <= 0:
            return 0.0
        return nominal * self.model.economy.cumulative_inflation(self.model.year)

    def grow_up(self, *, retirement_age: float = 65, spending: "Spending | None" = None) -> "Person":
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
        """Charge this month's child cost (a twelfth of the year's) to the owning person's spending.

        Runs in the pre_step stage so the expense is pending when the tax unit pays the month's bills
        in the step stage. Costs flow through ``Spending.add_expense`` (one-time expenses), never
        ``base`` — ``base`` is compounded by inflation at year end and would otherwise double-count.
        """
        if self.model.is_year_start:
            # The year's Form 2441 / 8863 figures accumulate month by month from the year's first month.
            self.care_expenses_this_year = 0.0
            self.education_expenses_this_year = 0.0
            self.education_paid_by_529 = 0.0
            self._aotc_reserved_this_year = 0.0
        if self.person.is_deceased:
            return
        cost = self.yearly_cost() / 12
        if 0 <= self.age < self.CARE_CREDIT_AGE and self.care_expenses_annual > 0:
            extra = self.care_expenses_annual * self.model.economy.cumulative_inflation(self.model.year) / 12
            self.person.spending.add_expense(extra, category="dependent_care")
            self.care_expenses_this_year += extra
            self.stat_dependent_costs = snap_money(self.stat_dependent_costs + extra)
        if 0 <= self.age < self.CHILDCARE_END_AGE and self.cost_annual is None:
            # The childcare band is the cost of care while the parents work (Form 2441 expenses). An
            # entered cost_annual is the child's whole cost: its care part goes in care_expenses_annual.
            self.care_expenses_this_year += cost
        if cost <= 0:
            return
        if self.in_college_band:
            # Draw self-beneficiary 529 plans first: withdraw_qualified deposits the tuition cash
            # into the owner's bank tax-free, so college is funded from the 529 before other
            # assets. The full tuition is then charged to spending; because the qualified
            # withdrawal already sits in the bank, only the shortfall the 529 could not cover
            # actually reduces other assets. This keeps bank+529 conservation intact while
            # making the 529 machinery load-bearing.
            #
            # Expenses paid with tax-free 529 money cannot also earn the American opportunity credit
            # (Pub. 970 ch. 7), so while AOTC years remain and the parents' last AGI was not past the
            # phase-out, the first $4,000 of the year's expenses is left for other money.
            reserve = self._aotc_reserve(cost)
            shortfall = self._draw_college_from_529s(cost - reserve)
            self.education_expenses_this_year += cost
            self.education_paid_by_529 += cost - reserve - shortfall
        self.person.spending.add_expense(cost, category="dependents")
        self.stat_dependent_costs = snap_money(self.stat_dependent_costs + cost)

    #: Dependent care qualifies for the child and dependent care credit until the child turns 13.
    CARE_CREDIT_AGE = 13

    def _aotc_reserve(self, cost: float) -> float:
        """This month's expenses kept out of the 529 draw so they can earn the AOTC: the year's first
        $4,000 (0 once its years are used, when the parents' prior-year AGI was past the phase-out, or
        without a 529 to draw)."""
        if not any(plan.beneficiary is self for plan in self.person.plan_529s):
            return 0.0
        federal = self.model.year_config.tax.federal
        edu = federal.credits.education
        if edu is None or self.aotc_years_claimed >= edu.aotc_max_years:
            return 0.0
        last_agi = self.person.agi_history.get(self.model.year - 1)
        joint = getattr(self.person.filing_status, "name", "") == "MARRIED_FILING_JOINTLY"
        phaseout = edu.phaseout_joint if joint else edu.phaseout_single
        if last_agi is not None and last_agi >= phaseout.end:
            return 0.0
        room = edu.aotc_full_expenses + edu.aotc_partial_expenses - self._aotc_reserved_this_year
        reserve = max(0.0, min(cost, room))
        self._aotc_reserved_this_year += reserve
        return reserve

    def _draw_college_from_529s(self, amount: float) -> float:
        """Draw ``amount`` of qualified education expenses from the owner's 529 plans whose
        beneficiary is this child. Returns the shortfall the 529 balances could not cover."""
        remaining = amount
        for plan in self.person.plan_529s:
            if remaining <= 0:
                break
            if plan.beneficiary is self:
                remaining -= plan.withdraw_qualified(remaining)
        return remaining

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Name: {html.escape(self.name)}</li>"
        desc += f"<li>Birth Year: {self.birth_year}</li>"
        desc += f"<li>Age: {self.age}</li>"
        desc += "</ul>"
        return desc
