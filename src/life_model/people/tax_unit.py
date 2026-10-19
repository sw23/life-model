# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import math
import warnings
from dataclasses import replace
from typing import TYPE_CHECKING

from ..ledger import FlowKind, debt_label
from ..model import Event, EventKind, round_money, snap_money
from ..tax.deductions import additional_standard_deduction, charitable_deduction, salt_cap, senior_deduction
from ..tax.federal import FilingStatus, get_federal_standard_deduction
from ..tax.household import (
    dependent_counts,
    finish_federal,
    has_dependent_child,
    plan_deductions,
    post_year_end_adjustments,
    record_year_end,
    se_profits,
    ss_wages,
)
from ..tax.income import IncomeType
from ..tax.return_record import TaxReturn, build_tax_return
from ..tax.state import (
    StateHousehold,
    StateMember,
    StateTaxDetail,
    part_year_state_tax_detail,
    state_income_tax_detail,
)
from ..tax.tax import TaxesDue, compute_taxes

if TYPE_CHECKING:
    from .family import Family
    from .person import Person

#: The household payment waterfall, in draw order (D4). ``bank`` is cash already in members' bank
#: accounts (emergency-reserve accounts excluded); ``fixed_income`` redeems non-reserve CDs, Treasuries, I
#: bonds and bond funds (Plan 27 D2); ``brokerage`` sells taxable holdings (gains taxed this year);
#: ``roth_basis`` draws Roth IRA contribution (and seasoned conversion) basis of members under the federal
#: retirement age (59.5), which is tax- and penalty-free; ``pretax`` draws 401k / Traditional IRA / HSA
#: money (ordinary income, plus the early-withdrawal penalty when young); ``roth_earnings`` draws the
#: remaining Roth money (Roth 401k balances, and whole Roth IRAs from 59.5); ``reserve`` draws
#: emergency-reserve bank accounts and reserve fixed-income holdings, only once everything else is spent.
DEFAULT_WITHDRAWAL_ORDER: tuple[str, ...] = (
    "bank",
    "fixed_income",
    "brokerage",
    "roth_basis",
    "pretax",
    "roth_earnings",
    "reserve",
)

#: Sources an order may leave out (Plan 27 added them): they go to their default place.
_OPTIONAL_SOURCES = {"fixed_income": "bank", "reserve": None}


def validate_withdrawal_order(order: "tuple[str, ...] | list[str] | None") -> tuple[str, ...]:
    """Return ``order`` as a tuple, or the default when None.

    A valid order names every source of :data:`DEFAULT_WITHDRAWAL_ORDER` exactly once, ``bank``
    first (cash on hand is always spent before anything is sold or withdrawn). ``fixed_income`` and
    ``reserve`` (Plan 27) may be left out: ``fixed_income`` then follows ``bank`` and ``reserve`` comes
    last, so an order written before they existed keeps its meaning.
    """
    if order is None:
        return DEFAULT_WITHDRAWAL_ORDER
    order = tuple(order)
    if "fixed_income" not in order and order[:1] == ("bank",):
        order = ("bank", "fixed_income", *order[1:])
    if "reserve" not in order:
        order = (*order, "reserve")
    if sorted(order) != sorted(DEFAULT_WITHDRAWAL_ORDER) or order[0] != "bank":
        raise ValueError(
            f"withdrawal_order must list each of {DEFAULT_WITHDRAWAL_ORDER} exactly once (fixed_income and "
            f"reserve may be left out), starting with 'bank'; got {order}"
        )
    return order


class TaxUnit:
    """A tax-filing unit: a single person, or a married couple filing jointly.

    The tax unit pays its members' bills and settles their taxes:

      1. Each month (:meth:`settle_month`), gather the month's non-tax bills (spending, housing
         payments, apartment rent, loan payments, and personal debt carried by members) exactly once
         and pay them through one household waterfall (``withdrawal_order``, default
         :data:`DEFAULT_WITHDRAWAL_ORDER`): every member's bank, then every member's brokerage, then
         Roth basis of members under 59.5, then pre-tax money, then the remaining Roth money. Each
         step raises only what the previous ones could not cover; what a draw makes taxable is on the
         members' ledgers for the year's return. A shortfall becomes debt on the first member.
      2. In December (:meth:`settle_year`), compute income taxes on the unit's combined taxable
         income for the year and fund them through the same waterfall, the taxable steps sized
         against the tax they trigger (brokerage: the gains; pre-tax: the ordinary income and
         penalty), then pay them from the members' combined banks.

    ``Family`` is only a container/aggregator built on top of tax units; it performs no
    tax math. This single abstraction is what makes married-couple housing, family debt,
    and mixed-filing-status families settle correctly.

    **Single-state simplification:** the whole unit files in the *head's* state
    (``members[0].state``), and the head is whichever spouse was constructed first (agent order ==
    construction order). A CA-head/TX-spouse couple therefore pays CA tax on the full
    combined income — and swapping the construction order flips that to TX. Part-year and
    multi-state filing are not modeled; a ``UserWarning`` is emitted (once per head, per run) when
    unit members declare differing states so the order-dependence is visible rather than silent.
    """

    def __init__(self, members: list["Person"], *, withdrawal_order: "tuple[str, ...] | None" = None):
        if not members:
            raise ValueError("TaxUnit requires at least one member")
        self.members = members
        self.withdrawal_order = validate_withdrawal_order(withdrawal_order)
        self.filing_status = members[0].filing_status
        # The year's tax parameters (brackets, deductions, wage base) for this settlement.
        self.config = members[0].model.year_config
        # A tax unit files in a single state — the head's. No part-year/multi-state.
        self.state = members[0].state
        self._warn_if_mixed_states()

    def _warn_if_mixed_states(self) -> None:
        """Warn once (per head, per run) when members declare differing states.

        The unit taxes the whole combined income in the head's state, and which spouse is the
        head depends on construction order — make that visible instead of silently varying.
        """
        head = self.members[0]
        declared = {m.state for m in self.members if m.state is not None}
        if len(declared) > 1 and not getattr(head, "_warned_mixed_state_unit", False):
            head._warned_mixed_state_unit = True
            warnings.warn(
                f"TaxUnit members declare different states ({sorted(declared)}); the whole unit is "
                f"taxed in the head's state '{self.state}'. Which member is the head follows "
                "construction order — multi-state filing is not modeled.",
                UserWarning,
                stacklevel=3,
            )

    @classmethod
    def build_units(cls, family: "Family") -> list["TaxUnit"]:
        """Group a family's members into filing units.

        A married-filing-jointly member and their spouse (when both are in the family) form one
        joint unit; every other member is its own unit. An unmarried member files (the unit's status
        only — the person's own ``filing_status`` is untouched; Plan 31 D5):

        * QUALIFYING_SURVIVING_SPOUSE in the two years after the year their spouse died, while a dependent
          child (a qualifying child: under 19, or a student under 24) lives with them (IRC §2(a));
        * HEAD_OF_HOUSEHOLD with a dependent child or a qualifying relative who qualifies (a supported
          parent wherever they live, another relative living with them; IRC §2(b));
        * SINGLE otherwise. When the config carries no head_of_household data the deduction/brackets fall
          back to single.
        """
        units: list[TaxUnit] = []
        seen = set()
        order = getattr(family, "withdrawal_order", None)
        for member in family.members:
            if member.unique_id in seen:
                continue
            spouse = member.spouse
            if (
                member.filing_status == FilingStatus.MARRIED_FILING_JOINTLY
                and spouse is not None
                and spouse in family.members
            ):
                units.append(cls([member, spouse], withdrawal_order=order))
                seen.add(member.unique_id)
                seen.add(spouse.unique_id)
            else:
                unit = cls([member], withdrawal_order=order)
                if member.filing_status == FilingStatus.SINGLE:
                    status = cls._unmarried_status(member)
                    if status is not None:
                        unit.filing_status = status
                decedent = getattr(member, "deceased_spouse_this_year", None)
                if (
                    decedent is not None
                    and decedent.is_deceased
                    and member.filing_status == FilingStatus.MARRIED_FILING_JOINTLY
                ):
                    # A spouse who died this year is on the year's joint return (their income so far
                    # this year is taxed with the survivor's); they pay no bills.
                    unit.members.append(decedent)
                units.append(unit)
                seen.add(member.unique_id)
        return units

    @staticmethod
    def _unmarried_status(member: "Person") -> "FilingStatus | None":
        """Qualifying surviving spouse or head of household for an unmarried member, else None (single)."""
        year = member.model.year
        child = has_dependent_child(member)
        death_year = getattr(member, "spouse_death_year", None)
        if child and death_year is not None and death_year < year <= death_year + 2:
            return FilingStatus.QUALIFYING_SURVIVING_SPOUSE
        relative = any(d.qualifies_for_head_of_household for d in getattr(member, "qualifying_relatives", ()))
        if child or relative:
            return FilingStatus.HEAD_OF_HOUSEHOLD
        return None

    @classmethod
    def for_member(cls, person: "Person") -> "TaxUnit":
        """The filing unit ``person`` belongs to this year (with their spouse when filing jointly).

        Mid-year purchases and other immediate payments go through this unit's :meth:`pay_bills`, so
        they draw on the same household waterfall as the month's bills.
        """
        family = getattr(person, "family", None)
        if family is not None and person in family.members:
            for unit in cls.build_units(family):
                if person in unit.members:
                    return unit
        return cls([person], withdrawal_order=getattr(family, "withdrawal_order", None))

    @property
    def living_members(self) -> "list[Person]":
        """Members still alive (a spouse who died this year is on the return but pays no bills)."""
        return [m for m in self.members if not m.is_deceased]

    @property
    def taxable_income(self) -> float:
        return sum(m.taxable_income for m in self.members)

    @property
    def preferential_income(self) -> float:
        """Combined long-term capital gains and qualified dividends for the unit."""
        return sum(m.preferential_income for m in self.members)

    @property
    def net_investment_income(self) -> float:
        """Combined §1411 net investment income for the unit."""
        return sum(m.income.net_investment_income for m in self.members)

    @property
    def bank_account_balance(self) -> float:
        """Cash the unit's bills and taxes are paid from: every member's bank accounts except
        emergency reserves (which the waterfall's ``reserve`` step moves into a spending account)."""
        return sum(a.balance for a in self._unit_bank_accounts() if not getattr(a, "reserve", False))

    def _unit_bank_accounts(self) -> list:
        """Every member's bank accounts, with the joint accounts members hold with a spouse (on separate
        returns the spouse's unit can pay from a joint account too), each once."""
        seen: dict[int, object] = {}
        for member in self.members:
            for account in member.usable_bank_accounts:
                seen.setdefault(id(account), account)
        return list(seen.values())

    @property
    def total_itemized_deductions(self) -> float:
        return sum(m.total_itemized_deductions for m in self.members)

    @property
    def federal_deductions(self) -> float:
        """Greater of the standard deduction for the filing status or combined itemized."""
        return self.federal_deductions_combined(0.0, 0.0)

    def _prospective_withdrawal_allocation(self, amount: float) -> dict[int, float]:
        """Predict how ``withdraw_from_pretax_accounts`` would split ``amount`` across members.

        Mirrors the withdrawal order exactly (members in sequence, each up to their combined
        pre-tax 401k + Traditional IRA balance) without moving any money, so income-dependent
        deductions and early-withdrawal penalties can be evaluated during sizing against the same
        per-member amounts settlement will see.
        """
        allocation: dict[int, float] = {}
        remaining = amount
        for member in self._members_for("pretax"):
            # ``amount`` is taxable income: walk each member's taxable capacity (the balance less any
            # basis), which is the balance itself unless a source holds basis.
            available = member.pretax_taxable_capacity
            take = min(remaining, available)
            allocation[member.unique_id] = take
            remaining -= take
        return allocation

    def federal_deductions_combined(self, additional_income: float = 0.0, state_income_tax_paid: float = 0.0) -> float:
        """Federal deductions folding in BOTH plans' income-dependent itemized adjustments.

        - The 7.5%-of-income medical floor depends on ordinary income, so a prospective
          401k withdrawal (``additional_income``) changes the deduction. It is allocated across
          members exactly as ``withdraw_from_pretax_accounts`` will split it, so each member's floor
          matches what settlement will see — otherwise sizing over-estimates the medical deduction
          and the shortfall lands as phantom year-end debt.
        - The unit's state income tax (``state_income_tax_paid``) enters the head's SALT
          bucket (mirrors ``_record_stats``' head convention), capped at the SALT limit per member.

        With both arguments 0 this is the plain standard-vs-itemized comparison.
        """
        standard_deduction, itemized, senior = self._deduction_parts(additional_income, state_income_tax_paid)
        return max(standard_deduction, itemized) + senior

    def _deduction_parts(
        self, additional_income: float = 0.0, state_income_tax_paid: float = 0.0
    ) -> tuple[float, float, float]:
        """``(standard, itemized, senior)``: the deduction is ``max(standard, itemized) + senior``."""
        standard_deduction, itemized = self._deduction_choice(additional_income, state_income_tax_paid)
        agi = self.agi(additional_income)
        year = self.members[0].model.year
        senior = senior_deduction(self.members, self.filing_status, agi, year, self.config)
        return standard_deduction, itemized, senior

    def _deduction_choice(self, additional_income: float = 0.0, state_income_tax_paid: float = 0.0):
        """``(standard, itemized)`` for the return; the standard deduction includes the §63(f) amount for
        each member 65+, and itemized includes charity after its AGI limits (and the 2026+ floor)."""
        standard_deduction = get_federal_standard_deduction(self.filing_status, self.config)
        if self.filing_status == FilingStatus.MARRIED_FILING_SEPARATELY:
            standard_deduction = self.members[0].standard_deduction
        if standard_deduction > 0:
            standard_deduction += additional_standard_deduction(self.members, self.filing_status, self.config)
        allocation = self._prospective_withdrawal_allocation(additional_income) if additional_income > 0 else None
        itemized = 0.0
        for index, member in enumerate(self.members):
            member_income = allocation[member.unique_id] if allocation else 0.0
            itemized += member.itemized_deductions(0.0, member_income, include_charitable=False, include_salt=False)
        itemized += self.salt_deduction(state_income_tax_paid, additional_income)
        itemized += self.charitable(additional_income).itemized
        return standard_deduction, itemized

    def charitable(self, additional_income: float = 0.0):
        """The return's charitable deduction worksheet (:func:`~life_model.tax.deductions.charitable_deduction`)."""
        return charitable_deduction(self.members, self.agi(additional_income), self.filing_status, self.config)

    def salt_deduction(self, state_income_tax_paid: float = 0.0, additional_income: float = 0.0) -> float:
        """The return's SALT deduction: the members' property taxes plus the unit's state income tax,
        capped once per return at the year's cap (phased down by the return's MAGI from 2025)."""
        paid = sum(m.salt_paid(state_income_tax_paid if i == 0 else 0.0) for i, m in enumerate(self.members))
        return min(paid, salt_cap(self.filing_status, self.agi(additional_income), self.config))

    def itemized_components(self, state_income_tax_paid: float = 0.0) -> dict[str, float]:
        """Itemized deductions by line for the return (state income tax in the head's SALT, charity
        capped at the return's AGI limit). Reporting only: :meth:`_deduction_choice` is the value used."""
        components = {"mortgage_interest": 0.0, "salt": 0.0, "medical": 0.0}
        for member in self.members:
            for name, amount in member.itemized_deduction_components(0.0).items():
                if name != "salt":
                    components[name] += amount
        components["salt"] = self.salt_deduction(state_income_tax_paid)
        charity = self.charitable()
        # Schedule A line 11 (cash) and line 12 (appreciated property at FMV), each after the 2026+ floor.
        components["charity"] = charity.cash_allowed - charity.floor_cash
        components["charity_noncash"] = charity.property_allowed - charity.floor_property
        return components

    def agi(self, additional_income: float = 0.0) -> float:
        """The return's adjusted gross income: ordinary income (already net of above-the-line
        deductions) plus preferential income, with an optional prospective ordinary amount."""
        return max(self.taxable_income + self.preferential_income + additional_income, 0.0)

    @property
    def num_qualifying_children(self) -> int:
        """Children of unit members who qualify for the Child Tax Credit this year.

        A child qualifies when their age is between 0 and ``ctc_qualifying_age_max`` (inclusive);
        unborn children (negative age) and adult children do not. Each child is registered to
        exactly one (living) member, so no double-counting is possible.
        """
        max_age = self.config.dependents.ctc_qualifying_age_max
        return sum(1 for member in self.members for child in member.children if 0 <= child.age <= max_age)

    def _state_income_totals(self, additional_income: float) -> "dict[IncomeType, float]":
        """Combined ordinary-taxable amount per income type across members.

        ``additional_income`` (a prospective pre-tax 401k withdrawal) is ordinary income taxed as a
        pre-tax distribution, so states that exempt retirement income exempt it too.
        """
        totals: dict[IncomeType, float] = {income_type: 0.0 for income_type in IncomeType}
        for member in self.members:
            for income_type, amount in member.income.totals_by_type().items():
                totals[income_type] += amount
        totals[IncomeType.PRETAX_DISTRIBUTION] += additional_income
        return totals

    def state_income_tax_due(
        self,
        additional_income: float = 0,
        *,
        additional_preferential: float = 0.0,
        additional_short_term: float = 0.0,
    ) -> float:
        """State income tax for the unit, resolving the head's state pack.

        Computed against the property-only AGI base (``state_income_tax_paid=0``) so it does not
        depend on itself being folded into SALT (avoids circularity). The deduction base *does*
        reflect ``additional_income`` so the income-dependent medical floor is
        consistent between withdrawal sizing and settlement — otherwise the DEFAULT AGI, and
        thus the flat state tax, would differ between the two and leave phantom year-end debt.
        ``DEFAULT`` residents get the flat-rate number exactly when there is no medical deduction.

        ``additional_preferential`` and ``additional_short_term`` are previewed capital gains a
        prospective brokerage sale would realize (long- and short-term); they enter the state base
        the same way the federal one sees them, so a brokerage draw is sized against the state tax
        it triggers too.
        """
        # Gains are part of the state base as much as the federal one, so the legacy flat-rate AGI
        # includes preferential income; the pack path picks it up through totals_by_type.
        return self._state_income_tax_detail(
            additional_income,
            additional_preferential=additional_preferential,
            additional_short_term=additional_short_term,
        ).tax

    def _state_income_tax_detail(
        self,
        additional_income: float = 0,
        *,
        additional_preferential: float = 0.0,
        additional_short_term: float = 0.0,
    ) -> StateTaxDetail:
        """:meth:`state_income_tax_due` with the state computation's lines (the one computation).

        A year in which the head lived in more than one state (the residency timeline, Plan 31 D4) files
        part-year returns: each income entry belongs to the head's state in the month it was booked (wages
        by the months worked there, investment income by residence at receipt), and each state taxes its
        share by the income-ratio method (:func:`~life_model.tax.state.part_year_state_tax_detail`).
        Prospective amounts being sized (a December draw) belong to the December state.
        """
        ordinary_bump = additional_income + additional_short_term
        total_income = (
            self.taxable_income
            + self.preferential_income
            + additional_income
            + additional_preferential
            + additional_short_term
        )
        legacy_agi = max(total_income - self.federal_deductions_combined(ordinary_bump, 0.0), 0)
        totals = self._state_income_totals(additional_income)
        totals[IncomeType.LONG_TERM_CAPITAL_GAIN] += additional_preferential
        totals[IncomeType.SHORT_TERM_CAPITAL_GAIN] += additional_short_term
        counts = dependent_counts(self)
        year = self.members[0].model.year
        household = StateHousehold(
            federal_agi=self.agi(ordinary_bump + additional_preferential),
            children=counts["ctc"],
            other_dependents=counts["other"],
            members=tuple(
                StateMember(m.age_in(year), m.income.retirement_income, getattr(m, "birth_year", None))
                for m in self.members
            ),
        )
        head = self.members[0]
        states = head.states_in_year(year) if hasattr(head, "states_in_year") else [self.state]
        if len(set(states)) > 1:
            allocations = self._state_allocations(year, states, additional_income)
            allocations[self.state][IncomeType.LONG_TERM_CAPITAL_GAIN] += additional_preferential
            allocations[self.state][IncomeType.SHORT_TERM_CAPITAL_GAIN] += additional_short_term
            return part_year_state_tax_detail(
                allocations,
                self.filing_status,
                legacy_agi,
                self.config,
                household=household,
                final_state=self.config.tax.state.resolve_state_code(self.state),
            )
        return state_income_tax_detail(
            totals, self.filing_status, self.state, legacy_agi, self.config, household=household
        )

    def _state_allocations(
        self, year: int, states: "list[str | None]", additional_income: float
    ) -> "dict[str | None, dict[IncomeType, float]]":
        """The members' income by the head's state of residence in the month it was booked."""
        head = self.members[0]
        allocations: dict[str | None, dict[IncomeType, float]] = {}
        for code in states:
            allocations.setdefault(code, {income_type: 0.0 for income_type in IncomeType})
        allocations.setdefault(self.state, {income_type: 0.0 for income_type in IncomeType})
        for member in self.members:
            for month, totals in member.income.totals_by_type_and_month().items():
                code = head.state_at(year, month) if month is not None else self.state
                bucket = allocations.setdefault(code, {income_type: 0.0 for income_type in IncomeType})
                for income_type, amount in totals.items():
                    bucket[income_type] += amount
        allocations[self.state][IncomeType.PRETAX_DISTRIBUTION] += additional_income
        return allocations

    def taxable_social_security(self, additional_income: float = 0.0, additional_preferential: float = 0.0) -> float:
        """Taxable portion of the unit's Social Security benefits (IRC §86), side-effect free.

        Provisional income is the whole return's: every member's ordinary income (excluding
        Social Security itself) and preferential income, tax-exempt interest, half of every
        member's benefits, plus any prospective ordinary (``additional_income``: a pre-tax draw or
        short-term gain being sized) or preferential income. So a joint return pools the spouse's
        wages, RSU vests and the year's gains count whenever they were booked, and a withdrawal the
        solver sizes raises the taxable share it is sized against (the "tax torpedo").
        """
        from ..insurance.social_security import taxable_social_security

        benefits = sum(m.income.social_security_benefits for m in self.members)
        if benefits <= 0:
            return 0.0
        other_income = additional_income + additional_preferential
        for member in self.members:
            ledger = member.income
            other_income += (
                ledger.ordinary_taxable
                - ledger.taxable_social_security
                + ledger.preferential_income
                + ledger.tax_exempt_interest
            )
        return taxable_social_security(benefits, other_income, self.filing_status, self.config)

    def _post_taxable_social_security(self, additional_income: float = 0.0, additional_preferential: float = 0.0):
        """Record :meth:`taxable_social_security` on the members' ledgers (split by gross benefit), so
        every base that reads the ledger (federal, state, AGI, the medical floor) sees it.

        Called at the top of every tax computation with that computation's prospective income, so
        the recorded share always matches the income being taxed; the last computation of
        settlement (no prospective income) leaves the settled value.
        """
        benefits = {m.unique_id: m.income.social_security_benefits for m in self.members}
        total = sum(benefits.values())
        if total <= 0:
            return
        taxable = self.taxable_social_security(additional_income, additional_preferential)
        for member in self.members:
            member.income.set_taxable_social_security(taxable * benefits[member.unique_id] / total)

    def get_income_taxes_due(
        self,
        additional_income: float = 0,
        *,
        additional_preferential: float = 0.0,
        additional_short_term: float = 0.0,
    ) -> TaxesDue:
        # The taxable share of Social Security depends on everything else on the return, including
        # the prospective amounts being sized, so it is (re)computed first.
        self._post_taxable_social_security(additional_income + additional_short_term, additional_preferential)
        # ``additional_income`` models a prospective pre-tax 401k withdrawal: it is ordinary
        # income but not FICA wages, so it is not added to the per-member wage bases. It does
        # enter the deduction computation — the medical floor is income-dependent
        # and the state income tax it triggers enters SALT.
        #
        # ``additional_preferential`` / ``additional_short_term`` model previewed capital gains a
        # prospective brokerage sale would realize (long- and short-term). Long-term gains and
        # qualified dividends are taxed on the preferential schedule; short-term gains are ordinary
        # income. Both are net investment income for the §1411 surtax. Neither is FICA wages. This
        # lets the settlement solver size a brokerage draw against the tax the sale itself creates.
        ordinary_income = self.taxable_income + additional_income + additional_short_term
        wage_incomes = [m.fica_wages for m in self.members]
        state_detail = self._state_income_tax_detail(
            additional_income,
            additional_preferential=additional_preferential,
            additional_short_term=additional_short_term,
        )
        state_tax = state_detail.tax
        prospective = additional_income + additional_short_term
        preferential = self.preferential_income + additional_preferential
        agi = max(ordinary_income + preferential, 0.0)
        standard, itemized, senior = self._deduction_parts(prospective, state_tax)
        charity = self.charitable(prospective)
        plan = plan_deductions(
            self,
            agi,
            standard,
            itemized,
            senior,
            preferential,
            additional_standard=(
                additional_standard_deduction(self.members, self.filing_status, self.config) if standard > 0 else 0.0
            ),
            charitable=charity,
        )
        taxes = compute_taxes(
            ordinary_income,
            plan.total,
            self.filing_status,
            wage_incomes,
            self.config,
            state_tax=state_tax,
            preferential_income=preferential,
            net_investment_income=self.net_investment_income + additional_preferential + additional_short_term,
            se_incomes=se_profits(self),
            ss_wage_incomes=ss_wages(self),
        )
        taxes.state_detail = state_detail
        taxes.standard_deduction = standard
        taxes.itemized_deduction = plan.itemized
        taxes.senior_deduction = senior
        taxes.additional_standard_deduction = plan.additional_standard
        taxes.qbi_deduction = plan.qbi.deduction
        taxes.qbi_detail = plan.qbi
        taxes.charitable_non_itemizer = plan.non_itemizer_charitable
        taxes.charitable = charity
        taxes.itemized_limitation = plan.itemized_limitation
        taxes.itemize = plan.itemize
        # The Form 8814 tax, AMT and every credit (Form 1040 order; tax/credits.py). Computed here, the
        # only place with the members, filing status and AGI in scope; because the withdrawal-sizing
        # fixed point consumes this method, credits shrink sized withdrawals automatically.
        finish_federal(
            self,
            taxes,
            agi,
            plan,
            self.salt_deduction(state_tax, prospective),
            additional_preferential=additional_preferential,
            additional_short_term=additional_short_term,
        )
        # Early-withdrawal penalties are additional federal tax (added after the credit so the
        # nonrefundable CTC cannot offset them): those already on members' ledgers plus the ones a
        # prospective pre-tax draw of ``additional_income`` would trigger, split across members in
        # the order the draw will actually happen.
        taxes.federal += sum(m.income.penalties for m in self.members)
        for member in self.members:
            for source, amount in member.income.penalties_by_source.items():
                taxes.penalties_detail[source] = taxes.penalties_detail.get(source, 0.0) + amount
        if additional_income > 0:
            allocation = self._prospective_withdrawal_allocation(additional_income)
            prospective = sum(m.prospective_penalty(allocation.get(m.unique_id, 0.0)) for m in self.members)
            taxes.federal += prospective
            if prospective > 0:
                taxes.penalties_detail["early_withdrawal (prospective)"] = prospective
        return taxes

    def withdraw_from_pretax_401ks(self, amount: float) -> float:
        """Withdraw ``amount`` from members' pre-tax 401ks. Returns the amount not withdrawn."""
        for member in self._members_for("pretax"):
            if amount <= 0:
                break
            amount -= member.withdraw_from_pretax_401ks(amount)
        return amount

    def withdraw_from_pretax_accounts(self, amount: float) -> float:
        """Withdraw ``amount`` from members' pre-tax 401ks then Traditional IRAs, member by member.

        Returns the amount not withdrawn. This order (:meth:`_members_for`) is what
        ``_prospective_withdrawal_allocation`` predicts during sizing.
        """
        for member in self._members_for("pretax"):
            if amount <= 0:
                break
            amount -= member.withdraw_from_pretax_accounts(amount)
        return amount

    def pay_bills(
        self,
        amount: float,
        *,
        kind: "FlowKind | str" = FlowKind.SPENDING,
        cause: str | None = None,
        sink: str | None = None,
        to_account=None,
    ) -> float:
        """Pay ``amount`` now through the household waterfall. Returns the unpaid shortfall.

        The immediate-payment entry point (a home's down payment, an estate tax, any mid-year
        purchase): every member's bank first, then each later source of ``withdrawal_order`` raises
        only what is still unpaid. Gains, pre-tax distributions and penalties this creates are on the
        members' ledgers, so the year's settlement taxes them (and sizes any further draw for that
        tax). Year-end settlement funds its bills with the sized version of the same order.

        What is paid is posted to the ledger as ``kind`` (keyword-only), out to ``sink`` or, for a
        purchase of a household asset, into ``to_account``. The shortfall is not posted: a caller
        that carries it as debt books it with :meth:`Person.add_debt`.
        """
        cause = cause or sink or "bill payment"
        post = {"kind": kind, "cause": cause, "sink": sink, "to_account": to_account}
        with self.members[0].model.ledger.caused_by(f"raise cash for {cause}"):
            remaining = self._pay_from_banks(amount, **post)
            for source in self.withdrawal_order[1:]:
                if remaining <= 0:
                    break
                self._raise_cash(source, remaining)
                remaining = self._pay_from_banks(remaining, **post)
        return max(0.0, remaining)

    def _bank_accounts_in_draw_order(self) -> list:
        """Every member's bank accounts in the order the household draws them: lowest yield (APY)
        first, so the cash left over earns the most. Ties go by owner name, institution, account type
        and then the larger balance first, none of which depend on construction order or on which
        spouse heads the unit."""

        def key(account):
            periods = account.compound_rate or 1
            apy = (1 + account.interest_rate / 100 / periods) ** periods - 1
            return (apy, account.person.name, account.company, account.type, -account.balance)

        return sorted((a for a in self._unit_bank_accounts() if not getattr(a, "reserve", False)), key=key)

    def _members_for(self, source: str) -> "list[Person]":
        """The order members are drawn in by a non-bank waterfall step: canonical (by name), not by
        who heads the unit. Pre-tax draws take members past the early-withdrawal age first (no 10%
        additional tax)."""
        if source == "pretax":
            return sorted(self.members, key=lambda m: (m.early_withdrawal_penalty(100.0), m.name, m.age))
        return sorted(self.members, key=lambda m: (m.name, m.age))

    def _pay_from_banks(self, amount: float, *, kind=None, sink=None, to_account=None, cause=None) -> float:
        """Pay ``amount`` from the unit's bank accounts in :meth:`_bank_accounts_in_draw_order`.
        Returns the shortfall. ``kind`` (with ``sink``/``to_account``, ``cause``) posts the payment
        to the ledger."""
        for account in self._bank_accounts_in_draw_order():
            if amount <= 0:
                return 0.0
            taken = account.withdraw(amount)
            amount -= taken
            if kind is not None and taken > 0:
                account.model.ledger.post(
                    taken,
                    kind,
                    from_account=account,
                    to_account=to_account,
                    sink=None if to_account is not None else (sink or cause),
                    cause=cause,
                    agent=account.person,
                )
        return amount

    def _payer_account(self):
        """The account settlement posts the household's bills from: the first bank in draw order,
        else the head's cash pocket (the per-account split of the payment is not tracked)."""
        accounts = self._bank_accounts_in_draw_order()
        if accounts:
            return accounts[0]
        return self.members[0].cash_destination

    def _raise_cash(self, source: str, amount: float) -> float:
        """Move up to ``amount`` from ``source`` (a non-bank waterfall step) into members' banks,
        posting whatever the draw makes taxable. Unsized: the caller accounts for any tax. Returns
        the amount raised."""
        before = self._source_balances(source)
        raised = 0.0
        for member in self._members_for(source):
            if raised >= amount:
                break
            want = amount - raised
            if source == "brokerage":
                raised += member.withdraw_from_brokerage_accounts(want)
            elif source == "pretax":
                raised += member.withdraw_from_pretax_accounts(want)
            elif source == "roth_basis":
                if self._under_retirement_age(member):
                    raised += member.withdraw_tax_free_from_roth_iras(want)
            elif source == "roth_earnings":
                got = member.withdraw_from_roth_401ks(want)
                if want - got > 0:
                    got += member.withdraw_tax_free_from_roth_iras(want - got)
                raised += got
            elif source == "fixed_income":
                raised += member.redeem_fixed_income(want, reserve=False)
            elif source == "reserve":
                raised += member.draw_reserves(want)
            else:  # pragma: no cover - validated in __init__
                raise ValueError(f"Unknown withdrawal source {source!r}")
        self._log_draws(source, before)
        return raised

    @staticmethod
    def _source_balance(member: "Person", source: str) -> float:
        """What ``member`` holds in a waterfall source (to measure what a step drew)."""
        if source == "brokerage":
            return member.brokerage_balance
        if source == "pretax":
            return member.pretax_account_balance
        if source == "fixed_income":
            return member.fixed_income_balance(reserve=False)
        if source == "reserve":
            return member.reserve_bank_balance() + member.fixed_income_balance(reserve=True)
        roth_401k = sum(a.roth_balance for a in member.all_retirement_accounts)
        return roth_401k + sum(a.balance for a in member.roth_iras)

    def _source_balances(self, source: str) -> dict[int, float]:
        return {m.unique_id: self._source_balance(m, source) for m in self.members}

    def _log_draws(self, source: str, before: dict[int, float], *, target: float | None = None) -> None:
        """Log a typed event per member for what a waterfall step drew (a forced brokerage sale, a
        pre-tax withdrawal with the solver's target, or a Roth withdrawal), with the ledger's cause."""
        model = self.members[0].model
        cause = model.ledger.current_cause or "pay bills"
        for member in self.members:
            drawn = before[member.unique_id] - self._source_balance(member, source)
            if drawn < 0.005:
                continue
            details = {"target": target} if target is not None else {}
            if source == "brokerage":
                kind, accounts = EventKind.FORCED_SALE, member.brokerage_accounts
            elif source == "pretax":
                kind = EventKind.PRETAX_WITHDRAWAL
                accounts = [*member.all_retirement_accounts, *member.traditional_iras, *member.hsas]
            elif source in ("fixed_income", "reserve"):
                kind, accounts = EventKind.WITHDRAWAL, list(member.fixed_income_holdings)
            else:
                kind, accounts = EventKind.WITHDRAWAL, [*member.roth_iras, *member.all_retirement_accounts]
            account = accounts[0] if len(accounts) == 1 else None
            if source == "brokerage":
                member.stat_forced_sales += drawn
            elif source == "pretax":
                member.stat_pretax_withdrawals += drawn
            model.event_log.add(
                Event(kind, person=member, amount=drawn, account=account, cause=cause, source=source, **details)
            )

    @staticmethod
    def _under_retirement_age(member: "Person") -> bool:
        from ..limits import federal_retirement_age

        return member.age_years_fractional < federal_retirement_age(member.model.config)

    def _fund_bills(self, bills: float) -> TaxesDue:
        """Move enough money into the members' banks to pay ``bills`` + the year's taxes, walking
        ``withdrawal_order``, and return the final taxes due.

        Taxable steps are sized against the tax they trigger (brokerage: the gains; pre-tax: the
        ordinary income and early-withdrawal penalty); tax-free Roth steps move exactly the
        remaining gap. Capital gains and losses are netted once, right after the brokerage step
        (so the pre-tax solve that follows in the default order reads netted gains).
        """
        netted = False
        for source in self.withdrawal_order:
            if source == "bank":
                continue
            if source == "brokerage":
                before = self._source_balances("brokerage")
                self._draw_from_brokerage(bills)
                self._log_draws("brokerage", before)
                # Net capital gains and losses once — after the brokerage sale — so brokerage gains
                # net with RSU vests and any loss carryforward before later steps read the tax bases.
                self._apply_capital_loss_netting()
                netted = True
            elif source == "pretax":
                # Size and perform any pre-tax withdrawal against the tax and penalty it triggers.
                gross = self._size_gross_withdrawal(bills)
                if gross > 0:
                    before = self._source_balances("pretax")
                    self.withdraw_from_pretax_accounts(gross)
                    self._log_draws("pretax", before, target=gross)
            else:
                # Unsized steps move the remaining gap; a draw that is itself taxable (a fund sale, an I
                # bond's deferred interest, non-qualified Roth 401(k) earnings) raises the tax, so repeat
                # until the gap closes or the source is exhausted.
                for _ in range(20):
                    gap = bills + self.get_income_taxes_due().total - self.bank_account_balance
                    # Sub-cent gaps are fixed-point residue from the sized steps, not a real shortfall.
                    if gap < 0.005 or self._raise_cash(source, gap) < 0.005:
                        break
        if not netted:
            self._apply_capital_loss_netting()
        return self.get_income_taxes_due()

    @property
    def brokerage_balance(self) -> float:
        """Combined taxable brokerage balance across the unit's members."""
        return sum(m.brokerage_balance for m in self.members)

    def withdraw_from_brokerage_accounts(self, amount: float) -> float:
        """Sell ``amount`` from members' brokerage accounts (into the bank). Returns the unfilled
        remainder. Members are drained in canonical order (:meth:`_members_for`)."""
        for member in self._members_for("brokerage"):
            if amount <= 0:
                break
            amount -= member.withdraw_from_brokerage_accounts(amount)
        return amount

    def _preview_brokerage_gain(self, amount: float) -> "tuple[float, float]":
        """Preview the ``(long_term, short_term)`` gains selling ``amount`` across the unit would
        realize, mirroring ``withdraw_from_brokerage_accounts``' member order without mutating."""
        remaining = amount
        long_term = 0.0
        short_term = 0.0
        for member in self._members_for("brokerage"):
            if remaining <= 0:
                break
            take = min(remaining, member.brokerage_balance)
            member_long, member_short = member.preview_brokerage_gain(take)
            long_term += member_long
            short_term += member_short
            remaining -= take
        return long_term, short_term

    def _taxes_with_sale(self, gross: float) -> float:
        """Total taxes due if ``gross`` of brokerage were sold now, after the year's capital-gain
        netting.

        Settlement nets gains and losses (and applies prior-year carryforwards) only after the
        brokerage sale. When that netting would change anything (a carryforward, or a net loss) the
        sale's previewed gains are booked on a scratch copy of the members' ledgers, netted exactly
        as settlement will net them, taxed, and rolled back; without this the sale was sized against
        tax on gains a carryforward was about to cancel, over-selling and leaving the excess in the
        bank (the invariant checker's ``no_draw_above_cash_floor`` found it, Plan 29).
        """
        previews = {}
        remaining = gross
        for member in self._members_for("brokerage"):
            take = min(max(remaining, 0.0), member.brokerage_balance)
            previews[member.unique_id] = member.preview_brokerage_gain(take) if take > 0 else (0.0, 0.0)
            remaining -= take
        long_term = sum(p[0] for p in previews.values())
        short_term = sum(p[1] for p in previews.values())
        carryforward = sum(m.capital_loss_carryforward for m in self.members)
        realized = sum(sum(self._capital_gain_totals(m).values()) for m in self.members)
        if carryforward == 0 and realized + long_term + short_term >= 0:
            # Netting will leave the ledger untouched: the plain preview is exact.
            return self.get_income_taxes_due(additional_preferential=long_term, additional_short_term=short_term).total
        saved = [(m, len(m.income.entries), m.capital_loss_carryforward) for m in self.members]
        try:
            for member in self.members:
                member_long, member_short = previews.get(member.unique_id, (0.0, 0.0))
                if member_long:
                    member.income.add(IncomeType.LONG_TERM_CAPITAL_GAIN, member_long, source="sale preview")
                if member_short:
                    member.income.add(IncomeType.SHORT_TERM_CAPITAL_GAIN, member_short, source="sale preview")
            self._apply_capital_loss_netting()
            return self.get_income_taxes_due().total
        finally:
            for member, length, carried in saved:
                del member.income.entries[length:]
                member.capital_loss_carryforward = carried

    def _draw_hsa_for_medical(self, bills: float) -> None:
        """When bills exceed the bank, first reimburse this year's medical costs from HSAs.

        A qualified medical distribution is entirely tax-free, so it is the cheapest money to spend:
        it comes before brokerage sales and pre-tax withdrawals. Bounded by the shortfall, each
        member's medical costs, and their HSA balances. (With enough cash the HSA is left to grow.)
        """
        shortfall = bills - self.bank_account_balance
        for member in self._members_for("hsa"):
            if shortfall <= 0:
                break
            shortfall -= member.reimburse_medical_from_hsas(shortfall)

    def _draw_from_brokerage(self, bills: float) -> None:
        """Sell taxable brokerage to cover ``bills`` + the tax the sale triggers, before any
        retirement account is touched.

        The gross to sell is fixed-point sized against a *preview* of the capital gains the sale
        would realize (approach B), so the account is sold exactly once: ``gross = bills +
        taxes(gains(gross)) - bank``, capped at the available brokerage balance. Because the
        marginal rate is below 100% the map is a contraction and converges quickly. When the
        brokerage can't cover the whole shortfall it is fully drained and the residual is left for
        the pre-tax 401k solve that follows.

        Gains are netted (losses, prior-year carryforwards) only after the sale, so the tax estimate
        previews that netting (:meth:`_taxes_with_sale`); settled taxes are always computed from
        the real post-sale ledger.
        """
        available = self.brokerage_balance
        if available <= 0:
            return
        bank = self.bank_account_balance
        gross = 0.0
        for _ in range(100):
            taxes = self._taxes_with_sale(gross)
            needed = min(available, max(0.0, bills + taxes - bank))
            if abs(needed - gross) < 0.001:
                gross = needed
                break
            gross = needed
        if gross > 0:
            # Round the draw up to the cent (capped at the balance) so floating-point residue in
            # the tax fixed point can't leak a sub-cent shortfall into the 401k when the brokerage
            # alone can cover the year. The at-most-one-cent over-draw simply stays in the bank.
            gross = min(available, math.ceil(gross * 100) / 100)
            self.withdraw_from_brokerage_accounts(gross)

    def _capital_gain_totals(self, member: "Person") -> "dict[IncomeType, float]":
        """Short- and long-term realized capital gains for ``member`` this year.

        Qualified dividends are excluded: they are taxed at the same preferential rates but are not
        capital gains, so capital losses cannot offset them beyond the ordinary-income allowance.
        """
        totals = member.income.totals_by_type()
        return {
            IncomeType.SHORT_TERM_CAPITAL_GAIN: totals[IncomeType.SHORT_TERM_CAPITAL_GAIN],
            IncomeType.LONG_TERM_CAPITAL_GAIN: totals[IncomeType.LONG_TERM_CAPITAL_GAIN],
        }

    def _apply_capital_loss_netting(self) -> None:
        """Net capital gains and losses for the unit, then offset and carry forward the remainder.

        Losses first cancel the year's gains. Whatever loss remains offsets ordinary income up to
        the statutory annual limit, and anything still left carries forward on the members.

        Both members' carryforwards are applied to the joint netting, but a *new* carryforward is
        attributed to members in proportion to the loss each of them personally realized. That
        attribution is what makes the spouse-death case come out right without a special case: the
        survivor keeps only the share they generated, and the decedent's share dies with them.

        **v1 simplification:** a carryforward is a single netted figure with no short/long
        character, and it is applied against short-term (ordinary-rate) gains before long-term
        ones. Character only changes the answer when a carryforward meets a same-year gain of the
        opposite character.
        """
        gains_by_member = {m.unique_id: self._capital_gain_totals(m) for m in self.members}
        raw_net = sum(sum(g.values()) for g in gains_by_member.values())
        carryforward = sum(m.capital_loss_carryforward for m in self.members)

        # The overwhelmingly common case: no prior losses and no losses this year. Leaving the
        # ledger untouched here is what keeps gain-free simulations byte-identical.
        if carryforward == 0 and raw_net >= 0:
            return

        for member in self.members:
            member.capital_loss_carryforward = 0.0

        net = raw_net - carryforward
        if net >= 0:
            # The carryforward is fully absorbed by this year's gains; reduce them by that amount.
            self._reduce_gains(gains_by_member, carryforward)
            return

        # Everything nets to a loss. Every capital entry leaves the gain bases — the gains are
        # consumed by the loss and the loss itself is recognized only through the allowance below.
        self._zero_out_capital_gains(gains_by_member)
        loss = -net
        offset = min(loss, self.config.tax.federal.capital_loss_ordinary_offset)
        if offset > 0:
            self.members[0].income.add(IncomeType.ORDINARY, -offset, source="capital_loss_deduction")

        remaining = loss - offset
        if remaining <= 0:
            return
        member_losses = {m.unique_id: max(0.0, -sum(gains_by_member[m.unique_id].values())) for m in self.members}
        total_member_loss = sum(member_losses.values())
        for member in self.members:
            if total_member_loss > 0:
                share = member_losses[member.unique_id] / total_member_loss
            else:
                # Only reachable when the whole remaining loss came from prior-year carryforwards
                # that nobody realized this year; keep it with the head.
                share = 1.0 if member is self.members[0] else 0.0
            member.capital_loss_carryforward = remaining * share

    def _zero_out_capital_gains(self, gains_by_member: "dict[int, dict[IncomeType, float]]") -> None:
        """Remove every realized capital gain and loss from the members' tax bases."""
        for member in self.members:
            for income_type, amount in gains_by_member[member.unique_id].items():
                if amount != 0:
                    member.income.add(income_type, -amount, source="capital_loss_netting")

    def _reduce_gains(self, gains_by_member: "dict[int, dict[IncomeType, float]]", amount: float) -> None:
        """Post negative ledger entries cancelling ``amount`` of the unit's realized gains.

        Short-term gains are cancelled first because they are taxed at ordinary rates, so a
        taxpayer applying a character-less carryforward would spend it there. The reduction is
        posted as negative entries — the same mechanism the student-loan interest deduction uses —
        rather than by editing entries in place.
        """
        remaining = amount
        for income_type in (IncomeType.SHORT_TERM_CAPITAL_GAIN, IncomeType.LONG_TERM_CAPITAL_GAIN):
            for member in self.members:
                if remaining <= 0:
                    return
                available = gains_by_member[member.unique_id][income_type]
                if available <= 0:
                    continue
                take = min(remaining, available)
                member.income.add(income_type, -take, source="capital_loss_carryforward")
                remaining -= take

    # ------------------------------------------------------------------
    # Monthly bills
    # ------------------------------------------------------------------

    def _carried_debt_lines(self, interest_by_member: dict[int, float]) -> "tuple[list[_BillLine], float]":
        """Unpaid bills carried as debt are repaid with this month's bills, after a month of interest
        (credit-card-like by default): unpaid bills are a real liability, not a free loan. Zeroes the
        members' ``debt`` (whatever can't be paid is borrowed again)."""
        rate = self.config.debt.effective_unpaid_balance_interest_rate / 100 / 12
        lines: list[_BillLine] = []
        total = 0.0
        for member in self.members:
            if not member.debt:
                continue
            interest = member.debt * rate
            interest_by_member[member.unique_id] = interest_by_member.get(member.unique_id, 0.0) + interest
            carried = member.debt + interest
            total += carried
            lines.append(
                _BillLine(carried, FlowKind.DEBT_SERVICE, member, "repay unpaid bills", to_account=debt_label(member))
            )
            lines.append(
                _BillLine(
                    interest,
                    FlowKind.DEBT_SERVICE,
                    member,
                    "interest on unpaid bills",
                    from_account=debt_label(member),
                    sink="interest on unpaid bills",
                )
            )
            member.debt = 0
        return lines, total

    def _spending_lines(self, spending_by_member: dict[int, float]) -> "tuple[list[_BillLine], float]":
        """This month's living spending (a twelfth of the base) and one-time expenses, by category."""
        lines: list[_BillLine] = []
        total = 0.0
        for member in self.living_members:
            month = member.spending.take_month_lines()
            amount = sum(month.values())
            spending_by_member[member.unique_id] = spending_by_member.get(member.unique_id, 0.0) + amount
            # Cards that take a share of the month's spending (Plan 27 D7) are charged; the rest is a bill.
            charged = 0.0
            for card in member.credit_cards:
                take = card.spending_charge(amount - charged)
                if take > 0 and card.charge(take, post=False, grace=True):
                    charged += take
                    lines.append(
                        _BillLine(
                            take,
                            FlowKind.SPENDING,
                            member,
                            f"charged to {card.name}",
                            from_account=card,
                            sink="living expenses",
                        )
                    )
            share = 1 - charged / amount if amount > 0 else 1.0
            total += amount - charged
            for category, line_amount in month.items():
                kind = FlowKind.PREMIUM if category.endswith("premium") else FlowKind.SPENDING
                sink = "living expenses" if category == "base" else category.replace("_", " ")
                lines.append(_BillLine(line_amount * share, kind, member, sink, sink=sink))
        return lines, total

    def _housing_and_debt_lines(
        self, housing_by_member: dict[int, float], interest_by_member: dict[int, float]
    ) -> "tuple[list[_BillLine], float]":
        """This month's housing (home costs and a mortgage payment, rent) and personal-debt payments
        (car loans, credit cards, student loans: one payment each)."""
        lines: list[_BillLine] = []
        total = 0.0
        for member in self.living_members:
            uid = member.unique_id
            housing = 0.0
            interest = 0.0
            for home in member.homes:
                housing += home.make_monthly_payment()
                interest += home.year_payment.get("mortgage_interest", 0.0)
                lines.extend(self._housing_lines(member, home))
            for apartment in member.apartments:
                housing += apartment.monthly_rent
                rent = f"rent: {apartment.name}"
                lines.append(_BillLine(apartment.monthly_rent, FlowKind.HOUSING, member, rent, sink=rent))
            debt_paid = 0.0
            for debt, paid, debt_interest, before, after in member.debt_service.service_month_detail():
                debt_paid += paid
                interest += debt_interest
                lines.extend(_loan_lines(member, debt, paid, debt_interest, before, after, FlowKind.DEBT_SERVICE))
            housing_by_member[uid] = housing_by_member.get(uid, 0.0) + housing
            interest_by_member[uid] = interest_by_member.get(uid, 0.0) + interest
            total += housing + debt_paid
        return lines, total

    def settle_month(self):
        """Pay this month's bills (living spending, one-time expenses, housing, debt payments and
        repaying carried debt) through the household waterfall.

        Tax-free qualified HSA reimbursements of medical costs come first, then the members' banks,
        then each later source of ``withdrawal_order`` raises only what is still unpaid (unsized: the
        gains, distributions and penalties a draw creates are on the members' ledgers and are taxed
        when the year settles). Each bill is posted to the ledger by line from the household's payer
        account; a shortfall becomes debt on the head, repaid (with interest) with next month's bills.
        """
        model = self.members[0].model
        spending_by_member: dict[int, float] = {}
        housing_by_member: dict[int, float] = {}
        interest_by_member: dict[int, float] = {}
        self._receive_refunds()
        tax_lines, tax_payments = self._tax_payment_lines()
        debt_lines, carried = self._carried_debt_lines(interest_by_member)
        spending_lines, spending = self._spending_lines(spending_by_member)
        housing_lines, housing = self._housing_and_debt_lines(housing_by_member, interest_by_member)
        bill_lines = tax_lines + debt_lines + spending_lines + housing_lines
        bills = tax_payments + carried + spending + housing
        when = f"{model.year}-{model.month:02d}"
        if bills > 0:
            self._draw_hsa_for_medical(bills)
            with model.ledger.caused_by(f"pay {when} bills"):
                remaining = self._pay_from_banks(bills)
                for source in self.withdrawal_order[1:]:
                    if remaining < 0.005:
                        break
                    self._raise_cash(source, remaining)
                    remaining = self._pay_from_banks(remaining)
            shortfall = round_money(max(0.0, remaining))
            payer = self._payer_account()
            for line in bill_lines:
                line.post(model.ledger, payer)
            self.members[0].add_debt(shortfall, to_account=payer, cause=f"unpaid {when} bills")
        for member in self.members:
            uid = member.unique_id
            member.stat_money_spent = snap_money(member.stat_money_spent + spending_by_member.get(uid, 0.0))
            member.stat_housing_costs = snap_money(member.stat_housing_costs + housing_by_member.get(uid, 0.0))
            member.stat_interest_paid = snap_money(member.stat_interest_paid + interest_by_member.get(uid, 0.0))

    # ------------------------------------------------------------------
    # Tax payments during the year (Plan 31 D3)
    # ------------------------------------------------------------------

    @property
    def pays_during_year(self) -> bool:
        """Whether the unit pays taxes as it goes (withholding or estimated payments): its balance due or
        refund is then settled in April of the next year instead of in December."""
        return any(_pays_during_year(m) for m in self.members)

    def _receive_refunds(self) -> None:
        """April: last year's refunds arrive in the highest-yield bank (Plan 31 D3)."""
        from ..tax.payments import SETTLEMENT_MONTH

        model = self.members[0].model
        if model.month != SETTLEMENT_MONTH:
            return
        for member in self.living_members:
            refund = member.tax_refund_due
            if refund <= 0:
                continue
            accounts = self._bank_accounts_in_draw_order()
            target = accounts[-1] if accounts else member.cash_destination
            if isinstance(target, str):
                member.cash += refund
            else:
                target.balance += refund
            model.ledger.post(
                refund,
                FlowKind.TAX,
                from_account=tax_refund_label(member),
                to_account=target,
                cause=f"{model.year - 1} tax refund",
                agent=member,
            )
            member.tax_refund_due = 0.0

    def _tax_payment_lines(self) -> "tuple[list[_BillLine], float]":
        """This month's tax payments, paid with the month's bills: April's balance due on last year's
        return, and the estimated tax installments due this month (April, June, September; January's pays
        the previous year)."""
        from ..tax.payments import SETTLEMENT_MONTH, installment_index, payments_for

        model = self.members[0].model
        year, month = model.year, model.month
        lines: list[_BillLine] = []
        total = 0.0
        if month == SETTLEMENT_MONTH:
            for member in self.living_members:
                owed = member.taxes_owed
                if owed > 0:
                    lines.append(
                        _BillLine(
                            owed,
                            FlowKind.TAX,
                            member,
                            f"{year - 1} balance due",
                            to_account=tax_due_label(member),
                            on_post=_clear_owed(member, owed),
                        )
                    )
                    total += owed
        index = installment_index(month)
        if index is None:
            return lines, total
        head = self.members[0]
        for member in self.living_members:
            policy = getattr(member, "estimated_payments", None)
            if policy is None:
                continue
            tax_year = year - 1 if index == 3 else year
            if index == 3:
                amount = member.__dict__.pop("_estimated_q4", (None, 0.0))
                amount = amount[1] if amount[0] == tax_year else 0.0
            else:
                amount = self._installment(member, policy, index)
            if amount < 0.005:
                continue
            payments_for(member, tax_year).estimated.append((index, amount))
            cause = f"{tax_year} Q{index + 1} estimated tax"
            if index == 3:
                # The year's return is already accrued: the payment reduces the balance due on it (any excess
                # is refunded in April).
                owed_part = min(amount, max(0.0, head.taxes_owed))
                if owed_part > 0:
                    lines.append(
                        _BillLine(
                            owed_part,
                            FlowKind.TAX,
                            member,
                            cause,
                            to_account=tax_due_label(head),
                            on_post=_clear_owed(head, owed_part),
                        )
                    )
                if amount - owed_part > 0:
                    lines.append(
                        _BillLine(
                            amount - owed_part,
                            FlowKind.TAX,
                            member,
                            cause,
                            to_account=tax_refund_label(head),
                            on_post=_add_refund(head, amount - owed_part),
                        )
                    )
            else:
                lines.append(_BillLine(amount, FlowKind.TAX, member, cause, sink="IRS: federal income tax"))
            total += amount
        return lines, total

    def _installment(self, member: "Person", policy, index: int) -> float:
        """The estimated tax installment ``index`` (0-2) ``member``'s policy pays now."""
        from ..tax.payments import payments_of

        if policy.quarterly is not None:
            return float(policy.quarterly[index])
        year = member.model.year
        required = self._required_annual_payment(member, policy, projected=True)
        months = max(1, member.model.months_in_year(year) - (12 - member.model.month))
        withheld = self._withholding_for_estimates(year) * 12 / months
        paid = sum(payments_of(m, year).estimated_total for m in self.members)
        return max(0.0, (index + 1) / 4 * (required - withheld) - paid)

    def _required_annual_payment(self, member: "Person", policy, *, projected: bool, taxes=None) -> float:
        """What ``policy`` aims to pay for the year (withholding included): last year's tax (100%, 110% over
        the AGI threshold) or 90% of this year's tax (projected from the year so far, or ``taxes``)."""
        rules = self.config.tax.federal.estimated_tax
        if policy.policy == "safe_harbor":
            prior_tax, prior_agi = self._prior_year(member)
            if prior_tax is None:
                return 0.0
            threshold = rules.high_income_agi / (2 if self.filing_status.name == "MARRIED_FILING_SEPARATELY" else 1)
            pct = rules.required_prior_high_income_pct if (prior_agi or 0.0) > threshold else rules.required_prior_pct
            return prior_tax * pct / 100
        current = tax_for_estimates(taxes) if taxes is not None else self.projected_tax_for_estimates()
        return current * rules.required_current_pct / 100

    def _prior_year(self, member: "Person") -> "tuple[float | None, float | None]":
        """Last year's Form 2210 tax and AGI: from last year's return, else the policy's inputs."""
        year = member.model.year
        prior = member.tax_returns.get(year - 1)
        if prior is not None:
            return prior.tax_for_estimates, prior.agi
        for m in self.members:
            policy = getattr(m, "estimated_payments", None)
            if policy is not None and policy.prior_year_tax is not None:
                return policy.prior_year_tax, policy.prior_year_agi
        return None, None

    def _withholding_for_estimates(self, year: int) -> float:
        """Withholding that counts as estimated tax so far this year: federal income tax and the Additional
        Medicare Tax withheld (Form 2210 line 6, before any excess Social Security)."""
        from ..tax.payments import payments_of

        return sum(
            payments_of(m, year).federal_withheld + payments_of(m, year).additional_medicare_withheld
            for m in self.members
        )

    def projected_taxes(self) -> TaxesDue:
        """The year's taxes projected from the year so far: every income entry scaled to a full year (12 over
        the months simulated through this one), taxed, and rolled back. A projection for the estimated tax
        policy and the contribution hold-back; settlement always taxes the real ledger."""
        model = self.members[0].model
        elapsed = max(1, model.months_in_year(model.year) - (12 - model.month))
        factor = model.months_in_year(model.year) / elapsed
        if factor <= 1.0:
            return self.get_income_taxes_due()
        saved = [(m, len(m.income.entries)) for m in self.members]
        try:
            for member in self.members:
                extra = []
                for entry in member.income.entries:
                    copy = replace(entry)
                    copy.amount = entry.amount * (factor - 1)
                    copy.fica_wages = entry.fica_wages * (factor - 1)
                    copy.gross = entry.gross * (factor - 1)
                    extra.append(copy)
                member.income.entries.extend(extra)
            return self.get_income_taxes_due()
        finally:
            for member, length in saved:
                del member.income.entries[length:]
            self.get_income_taxes_due()

    def projected_tax_for_estimates(self) -> float:
        return tax_for_estimates(self.projected_taxes())

    def expected_unpaid_tax(self) -> float:
        """The tax this year's income so far still owes beyond what has been paid toward it: the projected
        year's tax (income tax, payroll and state taxes) times the share of the year elapsed, less the year's
        withholding and estimated payments so far. The bank-sourced contributions hold it back (Plan 31)."""
        from ..tax.payments import payments_of

        model = self.members[0].model
        year = model.year
        elapsed = max(1, model.months_in_year(year) - (12 - model.month))
        share = elapsed / model.months_in_year(year)
        accrued = max(0.0, self.projected_taxes().total) * share
        paid = sum(payments_of(m, year).withheld_total + payments_of(m, year).estimated_total for m in self.members)
        return max(0.0, accrued - paid)

    # ------------------------------------------------------------------
    # Year-end settlement
    # ------------------------------------------------------------------

    def settle_year(self):
        """Settle the tax year for this unit (in December, after the month's bills): the year's
        taxes, from the year's income ledger.

        The household waterfall (all banks, all brokerage, Roth basis under 59.5, pre-tax, remaining
        Roth) moves into the banks only what the taxes still need, each taxable step sized against
        the tax it triggers. The taxes are posted to the ledger by line (``_BillLine``) from the
        household's payer account (:meth:`_payer_account`); a shortfall becomes debt.
        """
        model = self.members[0].model
        year = model.year
        bill_lines: list[_BillLine] = []

        # The year's settlement-time adjustments, once, before anything is sized against the tax: half
        # of self-employment tax, taxable dependent care benefits, the Form 8814 inclusion, the IRA and
        # Roth phase-outs and the student loan interest deduction (IRC §221: the interest paid this year,
        # capped per return and phased out by MAGI; tax/household.py).
        post_year_end_adjustments(self)

        if self.pays_during_year:
            self._settle_year_paid_as_you_go()
            return

        bills = 0.0
        with model.ledger.caused_by(f"fund {year} taxes"):
            taxes = self._fund_bills(bills)

        # The year's return, from exactly the taxes about to be paid and the ledger they came from.
        tax_return = build_tax_return(self, taxes, self._payments_summary(taxes, None))
        model.tax_returns[(tax_return.year, tax_return.unit_id)] = tax_return
        for member in self.members:
            member.tax_returns[tax_return.year] = tax_return
        bill_lines.extend(self._tax_lines(taxes))

        # Record this year's AGI on every member. Each member records the AGI of the
        # return they filed — the unit's full AGI, not a per-member split — because Medicare/IRMAA
        # later compares the return's MAGI against filing-status thresholds with a two-year
        # lookback. Recorded after withdrawal solving so 401k distributions are included. AGI is
        # gross income less above-the-line adjustments only: the standard/itemized deductions come
        # after AGI, so subtracting them (as this once did) understated MAGI and the surcharges.
        agi = self.agi()
        for member in self.members:
            member.agi_history[year] = agi

        # Charity above the AGI limits carries forward (consumed/recorded exactly once), as do the
        # minimum tax credit, AOTC years and the saver's-credit distribution history.
        record_year_end(self, taxes, agi)
        itemized_claimed = taxes.itemized_deduction if taxes.itemize else 0.0

        # Pay everything from the combined banks exactly once; a shortfall becomes new debt (every
        # source has already been drawn into the banks as far as it could be). Refundable credits
        # can make the net due negative (a refund): deposit it instead of "paying" a negative bill
        # (which would create negative debt).
        payer = self._payer_account()
        net_due = bills + taxes.total
        if net_due >= 0:
            shortfall = round_money(max(0.0, self._pay_from_banks(net_due)))
        else:
            # The refund lands in the highest-yield bank (or the head's cash pocket without one).
            accounts = self._bank_accounts_in_draw_order()
            if accounts:
                accounts[-1].balance += -net_due
            else:
                self.members[0].receive_cash(-net_due, source="refundable tax credits", post=False)
            shortfall = 0.0
        for line in bill_lines:
            line.post(model.ledger, payer)
        self.members[0].add_debt(shortfall, to_account=payer, cause=f"unpaid {year} taxes")

        self._record_stats(taxes, tax_return)
        # Which deduction the return took: the itemized amount (split like the income taxes), or 0
        # when it took the standard one.
        shares = self._member_shares() if len(self.members) > 1 else {self.members[0].unique_id: 1.0}
        for member in self.members:
            member.stat_itemized_deductions = itemized_claimed * shares[member.unique_id]
        self._fold_decedent_stats()

    def _payments_summary(self, taxes: TaxesDue, form2210, estimated_q4: float = 0.0) -> dict:
        """The year's payments toward the return (Form 1040 lines 25-38) for the record."""
        from ..tax.payments import payments_of

        year = self.members[0].model.year
        records = [payments_of(m, year) for m in self.members]
        ss_withheld = [r.social_security_withheld for r in records]
        excess_ss = sum(
            max(0.0, withheld - (taxes.ss_by_worker[i] if i < len(taxes.ss_by_worker) else 0.0))
            for i, withheld in enumerate(ss_withheld)
        )
        return {
            "federal_income_tax_withheld": sum(r.federal_withheld for r in records),
            "additional_medicare_tax_withheld": sum(r.additional_medicare_withheld for r in records),
            "social_security_withheld": sum(ss_withheld),
            "medicare_withheld": sum(r.medicare_withheld for r in records),
            "state_withheld": sum(r.state_withheld for r in records),
            "excess_social_security_withheld": excess_ss,
            "estimated_tax_payments": sum(r.estimated_total for r in records) + estimated_q4,
            "estimated_tax_penalty": form2210.penalty if form2210 is not None else 0.0,
            "required_annual_payment": form2210.required_annual_payment if form2210 is not None else 0.0,
            "settled_in_april": form2210 is not None,
        }

    def _settle_year_paid_as_you_go(self) -> None:
        """December settlement of a unit that withholds or pays estimates (Plan 31 D3): the return is computed
        as always (no waterfall draw: nothing is paid now), the January installment and the Form 2210 penalty
        are figured, and the balance due (or refund) is accrued to the head's tax balance, paid (received) in
        April of the next year. The ledger's tax lines for the year are the return's liabilities: the
        withholding and estimated payments already posted, and here each line's remainder."""
        from ..tax.payments import payments_of, underpayment_penalty

        model = self.members[0].model
        year = model.year
        head = self.members[0]
        with model.ledger.caused_by(f"{year} return"):
            self._apply_capital_loss_netting()
            taxes = self.get_income_taxes_due()
        # January's installment (decided now, on the year's actual tax) and the underpayment penalty.
        estimated_q4 = 0.0
        for member in self.living_members:
            policy = getattr(member, "estimated_payments", None)
            if policy is None:
                continue
            if policy.quarterly is not None:
                q4 = float(policy.quarterly[3])
            else:
                required = self._required_annual_payment(member, policy, projected=False, taxes=taxes)
                paid = sum(payments_of(m, year).estimated_total for m in self.members) + estimated_q4
                q4 = max(0.0, required - self._withholding_for_estimates(year) - paid)
            if q4 > 0.005:
                member._estimated_q4 = (year, q4)
                estimated_q4 += q4
        records = [payments_of(m, year) for m in self.members]
        summary = self._payments_summary(taxes, None, estimated_q4)
        estimated = [item for r in records for item in r.estimated]
        if estimated_q4:
            estimated.append((3, estimated_q4))
        prior_tax, prior_agi = self._prior_year(head)
        form2210 = underpayment_penalty(
            year,
            tax_for_estimates(taxes),
            summary["federal_income_tax_withheld"]
            + summary["additional_medicare_tax_withheld"]
            + summary["excess_social_security_withheld"],
            estimated,
            prior_year_tax=prior_tax,
            prior_year_agi=prior_agi,
            separate=self.filing_status.name == "MARRIED_FILING_SEPARATELY",
            config=self.config,
        )
        taxes.estimated_tax_penalty = form2210.penalty
        tax_return = build_tax_return(self, taxes, self._payments_summary(taxes, form2210, estimated_q4))
        model.tax_returns[(tax_return.year, tax_return.unit_id)] = tax_return
        for member in self.members:
            member.tax_returns[tax_return.year] = tax_return
        agi = self.agi()
        for member in self.members:
            member.agi_history[year] = agi
        record_year_end(self, taxes, agi)
        itemized_claimed = taxes.itemized_deduction if taxes.itemize else 0.0

        lines = self._tax_lines(taxes)
        if form2210.penalty > 0:
            lines.append(
                _BillLine(
                    form2210.penalty,
                    FlowKind.PENALTY,
                    head,
                    "estimated tax penalty (Form 2210)",
                    sink="IRS: estimated tax penalty",
                )
            )
        self._net_payments(lines, records, head)
        # Remainders to the cent (withholding was computed exactly; float residue is not a balance).
        for line in lines:
            line.amount = round(line.amount, 2)
        lines = [line for line in lines if line.amount != 0.0]
        net = round(sum(line.amount for line in lines), 2)
        label = tax_due_label(head) if net >= 0 else tax_refund_label(head)
        model.ledger.name_label(tax_due_label(head), f"{head.name}'s taxes owed")
        model.ledger.name_label(tax_refund_label(head), f"{head.name}'s tax refund due")
        for line in lines:
            line.from_account = label
            line.post(model.ledger, None)
        if net >= 0:
            head.taxes_owed += net
        else:
            head.tax_refund_due += -net
        self._record_stats(taxes, tax_return)
        shares = self._member_shares() if len(self.members) > 1 else {self.members[0].unique_id: 1.0}
        for member in self.members:
            member.stat_itemized_deductions = itemized_claimed * shares[member.unique_id]
        self._fold_decedent_stats()

    def _net_payments(self, lines: "list[_BillLine]", records, head) -> None:
        """Take the year's withholding and in-year estimated payments off the matching tax lines (federal
        income tax, state income tax, each member's Social Security and Medicare)."""
        federal = sum(r.federal_withheld + r.estimated_total for r in records)
        state = sum(r.state_withheld for r in records)
        by_cause = {}
        for line in lines:
            by_cause.setdefault((line.cause, line.member.unique_id), line)
        for line in lines:
            if line.cause == "federal income tax":
                line.amount -= federal
                federal = 0.0
            elif line.cause == "state income tax":
                line.amount -= state
                state = 0.0
        for member, record in zip(self.members, records, strict=True):
            for cause, paid, sink in (
                ("social security tax", record.social_security_withheld, "IRS: social security tax"),
                ("medicare tax", record.medicare_withheld, "IRS: medicare tax"),
            ):
                if not paid:
                    continue
                line = by_cause.get((cause, member.unique_id))
                if line is None:
                    lines.append(_BillLine(-paid, FlowKind.TAX, member, cause, sink=sink))
                else:
                    line.amount -= paid
        if federal:
            lines.append(_BillLine(-federal, FlowKind.TAX, head, "federal income tax", sink="IRS: federal income tax"))
        if state:
            lines.append(
                _BillLine(-state, FlowKind.TAX, head, "state income tax", sink=f"state income tax ({self.state})")
            )

    def _housing_lines(self, member: "Person", home) -> "list[_BillLine]":
        """The ledger lines of a home's last payment (``home.year_payment``: a month's)."""
        lines = []
        payment = dict(home.year_payment)
        mortgage_paid = payment.pop("mortgage", 0.0)
        interest = payment.pop("mortgage_interest", 0.0)
        before = payment.pop("mortgage_principal_before", None)
        for name, amount in payment.items():
            sink = f"{name.replace('_', ' ')}: {home.name}"
            lines.append(_BillLine(amount, FlowKind.HOUSING, member, sink, sink=sink))
        if home.mortgage is not None and before is not None:
            lines.extend(
                _loan_lines(
                    member,
                    home.mortgage,
                    mortgage_paid,
                    interest,
                    before,
                    home.mortgage.principal,
                    FlowKind.HOUSING,
                    name=f"mortgage on {home.name}",
                )
            )
        return lines

    def _tax_lines(self, taxes: TaxesDue) -> "list[_BillLine]":
        """The year's taxes as ledger lines: they sum to ``taxes.total``."""
        head = self.members[0]
        federal = taxes.federal - taxes.penalties - taxes.credits
        lines = [
            _BillLine(federal, FlowKind.TAX, head, "federal income tax", sink="IRS: federal income tax"),
            _BillLine(
                taxes.niit, FlowKind.TAX, head, "net investment income tax", sink="IRS: net investment income tax"
            ),
            _BillLine(taxes.state, FlowKind.TAX, head, "state income tax", sink=f"state income tax ({self.state})"),
        ]
        for member in self.members:
            for source, amount in member.income.penalties_by_source.items():
                cause = f"additional tax: {source.replace('_', ' ')}"
                lines.append(_BillLine(amount, FlowKind.PENALTY, member, cause, sink=f"IRS: {cause}"))
                member.model.event_log.add(
                    Event(EventKind.PENALTY, person=member, amount=amount, cause=source.replace("_", " "))
                )
        for index, member in enumerate(self.members):
            if index < len(taxes.ss_by_worker):
                lines.append(
                    _BillLine(
                        taxes.ss_by_worker[index],
                        FlowKind.TAX,
                        member,
                        "social security tax",
                        sink="IRS: social security tax",
                    )
                )
            if index < len(taxes.medicare_by_worker):
                lines.append(
                    _BillLine(
                        taxes.medicare_by_worker[index], FlowKind.TAX, member, "medicare tax", sink="IRS: medicare tax"
                    )
                )
            if index < len(taxes.se_by_worker) and taxes.se_by_worker[index].total > 0:
                lines.append(
                    _BillLine(
                        taxes.se_by_worker[index].total,
                        FlowKind.TAX,
                        member,
                        "self-employment tax",
                        sink="IRS: self-employment tax",
                    )
                )
        if taxes.additional_medicare_se > 0:
            lines.append(
                _BillLine(
                    taxes.additional_medicare_se,
                    FlowKind.TAX,
                    head,
                    "additional medicare tax on self-employment income",
                    sink="IRS: medicare tax",
                )
            )
        return lines

    def _size_gross_withdrawal(self, bills: float) -> float:
        """Pure fixed-point solve for the pre-tax withdrawal needed to cover bills + taxes.

        Penalties scale linearly with the draw (10% below 59.5), so the map stays a contraction as
        long as marginal tax plus penalty stays below 100%.

        Side-effect-free: computes the gross amount without moving any money.
        """
        bank = self.bank_account_balance
        gross = 0.0
        for _ in range(100):
            taxes = self.get_income_taxes_due(self._prospective_taxable(gross)).total
            needed = max(0.0, bills + taxes - bank)
            if abs(needed - gross) < 0.001:
                return needed
            gross = needed
        return gross

    def _prospective_taxable(self, gross: float) -> float:
        """The taxable income a pre-tax draw of ``gross`` would produce across the members, in the order
        :meth:`withdraw_from_pretax_accounts` takes it (``gross`` itself unless a source holds basis)."""
        taxable = 0.0
        remaining = gross
        for member in self._members_for("pretax"):
            if remaining <= 0:
                break
            take = min(remaining, member.pretax_account_balance)
            taxable += member.prospective_taxable(take)
            remaining -= take
        return taxable + max(0.0, remaining)

    def _member_shares(self) -> dict[int, float]:
        """Each member's share of the unit's income taxes: their own ordinary plus preferential income
        over the unit's (negative contributions count as 0). Equal shares when nobody has income."""
        weights = {
            m.unique_id: max(0.0, m.income.ordinary_taxable + m.income.preferential_income) for m in self.members
        }
        total = sum(weights.values())
        if total <= 0:
            return {m.unique_id: 1.0 / len(self.members) for m in self.members}
        return {uid: weight / total for uid, weight in weights.items()}

    def _record_stats(self, taxes: TaxesDue, tax_return: "TaxReturn | None" = None):
        """Record the year's tax stats on every member.

        Tax stats are on **every member**: payroll taxes (Social Security, Medicare) and penalties
        are each member's own; the unit's income taxes (federal, state, NIIT), credits and claimed
        itemized deductions are split pro rata by each member's share of the return's income
        (:meth:`_member_shares`). The shares sum to 1, so model-level totals equal the return's.
        A one-person unit gets the return's figures unchanged.
        """
        for member in self.members:
            totals = member.income.totals_by_type()
            member.stat_capital_gains = (
                totals[IncomeType.SHORT_TERM_CAPITAL_GAIN] + totals[IncomeType.LONG_TERM_CAPITAL_GAIN]
            )

        for member in self.members:
            if tax_return is not None:
                member.stat_marginal_rate = tax_return.marginal_rate
                member.stat_standard_deduction_taken = tax_return.deduction_taken == "standard"

        if len(self.members) == 1:
            head = self.members[0]
            if tax_return is not None:
                head.stat_agi = tax_return.agi
                head.stat_taxable_income = tax_return.taxable_income
            head.stat_taxes_paid = taxes.total
            head.stat_taxes_paid_federal = taxes.federal
            head.stat_taxes_paid_state = taxes.state
            # Self-employment tax is the self-employed person's Social Security and Medicare tax.
            head.stat_taxes_paid_ss = taxes.ss + sum(se.social_security for se in taxes.se_by_worker)
            head.stat_taxes_paid_medicare = taxes.medicare + sum(se.medicare for se in taxes.se_by_worker)
            head.stat_taxes_paid_niit = taxes.niit
            head.stat_tax_credits = taxes.credits
            head.stat_tax_penalties = taxes.penalties
            return

        shares = self._member_shares()
        income_federal = taxes.federal - taxes.penalties
        self._record_member_tax_stats(taxes, tax_return, shares, income_federal)

    _TAX_STATS = (
        "stat_taxes_paid",
        "stat_taxes_paid_federal",
        "stat_taxes_paid_state",
        "stat_taxes_paid_ss",
        "stat_taxes_paid_medicare",
        "stat_taxes_paid_niit",
        "stat_tax_credits",
        "stat_tax_penalties",
        "stat_agi",
        "stat_taxable_income",
        "stat_itemized_deductions",
    )

    def _fold_decedent_stats(self) -> None:
        """A spouse who died this year is no longer reported: their share of the joint return's
        stats goes to the survivor (the head)."""
        head = self.members[0]
        for member in self.members:
            if member.is_deceased and member is not head:
                for name in self._TAX_STATS:
                    setattr(head, name, getattr(head, name, 0) + getattr(member, name, 0))
                    setattr(member, name, 0)

    def _record_member_tax_stats(self, taxes: TaxesDue, tax_return, shares, income_federal) -> None:
        for index, member in enumerate(self.members):
            share = shares[member.unique_id]
            penalties = member.income.penalties
            federal = share * income_federal + penalties
            state = share * taxes.state
            niit = share * taxes.niit
            credits = share * taxes.credits
            ss = taxes.ss_by_worker[index]
            medicare = taxes.medicare_by_worker[index]
            if index < len(taxes.se_by_worker):
                se = taxes.se_by_worker[index]
                se_total = sum(other.net_earnings for other in taxes.se_by_worker)
                ss += se.social_security
                medicare += se.medicare
                if se_total > 0:
                    medicare += taxes.additional_medicare_se * se.net_earnings / se_total
            member.stat_taxes_paid_federal = federal
            member.stat_taxes_paid_state = state
            member.stat_taxes_paid_ss = ss
            member.stat_taxes_paid_medicare = medicare
            member.stat_taxes_paid_niit = niit
            member.stat_tax_credits = credits
            member.stat_tax_penalties = penalties
            if tax_return is not None:
                member.stat_agi = share * tax_return.agi
                member.stat_taxable_income = share * tax_return.taxable_income
            member.stat_taxes_paid = federal + state + ss + medicare + niit - credits


class _BillLine:
    """One line of a settlement's bills, posted from the payer account once the year is paid.

    ``to_account`` makes it a transfer (a loan's principal, repaying carried debt), ``from_account``
    overrides the payer (a liability charged with capitalized interest), and a line with
    ``source`` is an inflow (a loan reduced by someone else).
    """

    __slots__ = ("amount", "cause", "from_account", "kind", "member", "on_post", "sink", "source", "to_account")

    def __init__(
        self, amount, kind, member, cause, *, sink=None, to_account=None, from_account=None, source=None, on_post=None
    ):
        self.amount = amount
        self.kind = kind
        self.member = member
        self.cause = cause
        self.sink = sink
        self.to_account = to_account
        self.from_account = from_account
        self.source = source
        #: Called after posting (a tax balance the payment settles).
        self.on_post = on_post

    def post(self, ledger, payer) -> None:
        if self.on_post is not None:
            self.on_post()
        if self.source is not None:
            ledger.post(
                self.amount,
                self.kind,
                to_account=self.to_account,
                source=self.source,
                cause=self.cause,
                agent=self.member,
            )
            return
        ledger.post(
            self.amount,
            self.kind,
            from_account=self.from_account if self.from_account is not None else payer,
            to_account=self.to_account,
            sink=self.sink,
            cause=self.cause,
            agent=self.member,
        )


def _loan_lines(
    member, loan, paid: float, interest: float, before: float, after: float, kind, name: str | None = None
) -> "list[_BillLine]":
    """A loan's year: interest paid (out), principal paid (a transfer into the loan), and any change in
    the balance the payments don't explain: interest capitalized (more debt) or principal relief
    (an income-driven plan's match, forgiveness)."""
    name = name or getattr(loan, "name", None) or getattr(loan, "school_name", None) or type(loan).__name__
    principal_paid = paid - interest
    lines = [
        _BillLine(interest, kind, member, f"interest: {name}", sink=f"interest: {name}"),
        _BillLine(principal_paid, kind, member, f"principal: {name}", to_account=loan),
    ]
    unexplained = after - (before - principal_paid)
    if unexplained > 0.005:
        lines.append(
            _BillLine(
                unexplained,
                kind,
                member,
                f"interest capitalized: {name}",
                from_account=loan,
                sink=f"interest capitalized: {name}",
            )
        )
    elif unexplained < -0.005:
        lines.append(
            _BillLine(
                -unexplained,
                FlowKind.BENEFIT,
                member,
                f"loan relief: {name}",
                to_account=loan,
                source="lender / loan program relief",
            )
        )
    return lines


def tax_due_label(person) -> str:
    """Label of a person's balance due on a filed return, payable in April (a liability; Plan 31 D3)."""
    return f"TaxDue:{person.unique_id}"


def tax_refund_label(person) -> str:
    """Label of a person's tax refund receivable in April (an asset; Plan 31 D3)."""
    return f"TaxRefund:{person.unique_id}"


def _clear_owed(person, amount: float):
    def apply() -> None:
        person.taxes_owed = snap_money(person.taxes_owed - amount)

    return apply


def _add_refund(person, amount: float):
    def apply() -> None:
        person.tax_refund_due = snap_money(person.tax_refund_due + amount)

    return apply


def _pays_during_year(member: "Person") -> bool:
    """A member who withholds (a job with a withholding policy), pays estimates or has paid any tax for a year."""
    if getattr(member, "estimated_payments", None) is not None or getattr(member, "tax_payments", None):
        return True
    return any(getattr(job, "withholding", None) is not None for job in member.jobs)


def tax_for_estimates(taxes: TaxesDue) -> float:
    """Form 2210 line 4 ("current year tax"): tax after nonrefundable credits, plus self-employment tax, the
    Additional Medicare Tax, NIIT, additional taxes on distributions and excess advance premium tax credit,
    less refundable credits."""
    return taxes.federal + taxes.niit + taxes.se_tax + taxes.additional_medicare - taxes.credits
