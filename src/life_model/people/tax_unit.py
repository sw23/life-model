# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import math
import warnings
from typing import TYPE_CHECKING

from ..model import round_money
from ..tax.credits import child_tax_credit
from ..tax.deductions import deductible_charity, senior_deduction, settle_charitable_carryforwards
from ..tax.federal import FilingStatus, get_federal_standard_deduction
from ..tax.income import IncomeType
from ..tax.state import state_income_tax_for_unit
from ..tax.tax import TaxesDue, compute_taxes

if TYPE_CHECKING:
    from .family import Family
    from .person import Person

#: The household payment waterfall, in draw order (D4). ``bank`` is cash already in members' bank
#: accounts; ``brokerage`` sells taxable holdings (gains taxed this year); ``roth_basis`` draws Roth
#: IRA contribution basis of members under the federal retirement age (59.5), which is tax- and
#: penalty-free; ``pretax`` draws 401k / Traditional IRA / HSA money (ordinary income, plus the
#: early-withdrawal penalty when young); ``roth_earnings`` draws the remaining tax-free Roth money
#: (Roth 401k balances, and whole Roth IRAs from 59.5).
DEFAULT_WITHDRAWAL_ORDER: tuple[str, ...] = ("bank", "brokerage", "roth_basis", "pretax", "roth_earnings")


def validate_withdrawal_order(order: "tuple[str, ...] | list[str] | None") -> tuple[str, ...]:
    """Return ``order`` as a tuple, or the default when None.

    A valid order names every source of :data:`DEFAULT_WITHDRAWAL_ORDER` exactly once, ``bank``
    first (cash on hand is always spent before anything is sold or withdrawn).
    """
    if order is None:
        return DEFAULT_WITHDRAWAL_ORDER
    order = tuple(order)
    if sorted(order) != sorted(DEFAULT_WITHDRAWAL_ORDER) or order[0] != "bank":
        raise ValueError(
            f"withdrawal_order must list each of {DEFAULT_WITHDRAWAL_ORDER} exactly once, starting with 'bank'; "
            f"got {order}"
        )
    return order


class TaxUnit:
    """A tax-filing unit: a single person, or a married couple filing jointly.

    The tax unit owns the year-end settlement for its members:

      1. Gather every non-tax bill (discretionary spending, housing payments, apartment rent,
         and any personal debt carried by members) exactly once.
      2. Compute income taxes on the unit's combined taxable income.
      3. Fund bills + taxes through one household waterfall (``withdrawal_order``, default
         :data:`DEFAULT_WITHDRAWAL_ORDER`): every member's bank, then every member's brokerage
         (sized against the gains tax it triggers), then Roth basis of members under 59.5, then a
         pre-tax withdrawal sized against the tax and penalty it triggers, then the remaining Roth
         money. Each step moves only what the previous ones could not cover into the banks.
      4. Pay bills + taxes from the members' combined banks exactly once. Any shortfall becomes new
         debt on the first member.

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
        joint unit; every other member is its own single unit. An unmarried member with at least
        one dependent child files HEAD_OF_HOUSEHOLD (the unit's status only — the person's own
        ``filing_status`` is untouched); when the config carries no head_of_household data the
        deduction/brackets fall back to single.
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
                if member.filing_status == FilingStatus.SINGLE and cls._has_dependent_child(member):
                    unit.filing_status = FilingStatus.HEAD_OF_HOUSEHOLD
                units.append(unit)
                seen.add(member.unique_id)
        return units

    @classmethod
    def for_member(cls, person: "Person") -> "TaxUnit":
        """The filing unit ``person`` belongs to this year (with their spouse when filing jointly).

        Mid-year purchases and other immediate payments go through this unit's :meth:`pay_bills`, so
        they draw on the same household waterfall as year-end settlement.
        """
        family = getattr(person, "family", None)
        if family is not None and person in family.members:
            for unit in cls.build_units(family):
                if person in unit.members:
                    return unit
        return cls([person], withdrawal_order=getattr(family, "withdrawal_order", None))

    @staticmethod
    def _has_dependent_child(member: "Person") -> bool:
        """Whether ``member`` has a dependent child this year (born, and under ``adult_age``)."""
        adult_age = member.model.config.dependents.adult_age
        return any(0 <= child.age < adult_age for child in member.children)

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
        return sum(m.bank_account_balance for m in self.members)

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
        for member in self.members:
            available = member.pretax_account_balance
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
        standard_deduction, itemized = self._deduction_choice(additional_income, state_income_tax_paid)
        agi = self.agi(additional_income)
        year = self.members[0].model.year
        senior = senior_deduction(self.members, self.filing_status, agi, year, self.config)
        return max(standard_deduction, itemized) + senior

    def _deduction_choice(self, additional_income: float = 0.0, state_income_tax_paid: float = 0.0):
        """``(standard, itemized)`` for the return; itemized includes charity capped at its AGI limit."""
        standard_deduction = get_federal_standard_deduction(self.filing_status, self.config)
        if self.filing_status == FilingStatus.MARRIED_FILING_SEPARATELY:
            standard_deduction = self.members[0].standard_deduction
        allocation = self._prospective_withdrawal_allocation(additional_income) if additional_income > 0 else None
        itemized = 0.0
        for index, member in enumerate(self.members):
            member_income = allocation[member.unique_id] if allocation else 0.0
            member_state_tax = state_income_tax_paid if index == 0 else 0.0
            itemized += member.itemized_deductions(member_state_tax, member_income, include_charitable=False)
        itemized += deductible_charity(self.members, self.agi(additional_income), self.config)
        return standard_deduction, itemized

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
        return state_income_tax_for_unit(totals, self.filing_status, self.state, legacy_agi, self.config)

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
        state_tax = self.state_income_tax_due(
            additional_income,
            additional_preferential=additional_preferential,
            additional_short_term=additional_short_term,
        )
        deductions = self.federal_deductions_combined(additional_income + additional_short_term, state_tax)
        taxes = compute_taxes(
            ordinary_income,
            deductions,
            self.filing_status,
            wage_incomes,
            self.config,
            state_tax=state_tax,
            preferential_income=self.preferential_income + additional_preferential,
            net_investment_income=self.net_investment_income + additional_preferential + additional_short_term,
        )
        # Child Tax Credit: computed here (the only place with members, filing status, and AGI in
        # scope) and recorded on the credits stage. Because the withdrawal-sizing fixed point
        # consumes this method, credits automatically shrink sized 401k withdrawals.
        num_children = self.num_qualifying_children
        if num_children > 0:
            taxes.credits += child_tax_credit(
                num_children, ordinary_income, taxes.federal, self.filing_status, self.config
            )
        # Early-withdrawal penalties are additional federal tax (added after the credit so the
        # nonrefundable CTC cannot offset them): those already on members' ledgers plus the ones a
        # prospective pre-tax draw of ``additional_income`` would trigger, split across members in
        # the order the draw will actually happen.
        taxes.federal += sum(m.income.penalties for m in self.members)
        if additional_income > 0:
            allocation = self._prospective_withdrawal_allocation(additional_income)
            taxes.federal += sum(m.prospective_penalty(allocation.get(m.unique_id, 0.0)) for m in self.members)
        return taxes

    def withdraw_from_pretax_401ks(self, amount: float) -> float:
        """Withdraw ``amount`` from members' pre-tax 401ks. Returns the amount not withdrawn."""
        for member in self.members:
            if amount <= 0:
                break
            amount -= member.withdraw_from_pretax_401ks(amount)
        return amount

    def withdraw_from_pretax_accounts(self, amount: float) -> float:
        """Withdraw ``amount`` from members' pre-tax 401ks then Traditional IRAs, member by member.

        Returns the amount not withdrawn. This order is what ``_prospective_withdrawal_allocation``
        predicts during sizing.
        """
        for member in self.members:
            if amount <= 0:
                break
            amount -= member.withdraw_from_pretax_accounts(amount)
        return amount

    def pay_bills(self, amount: float) -> float:
        """Pay ``amount`` now through the household waterfall. Returns the unpaid shortfall.

        The immediate-payment entry point (a home's down payment, an estate tax, any mid-year
        purchase): every member's bank first, then each later source of ``withdrawal_order`` raises
        only what is still unpaid. Gains, pre-tax distributions and penalties this creates are on the
        members' ledgers, so the year's settlement taxes them (and sizes any further draw for that
        tax). Year-end settlement funds its bills with the sized version of the same order.
        """
        remaining = self._pay_from_banks(amount)
        for source in self.withdrawal_order[1:]:
            if remaining <= 0:
                break
            self._raise_cash(source, remaining)
            remaining = self._pay_from_banks(remaining)
        return max(0.0, remaining)

    def _pay_from_banks(self, amount: float) -> float:
        """Pay ``amount`` from every member's bank accounts, in member order. Returns the shortfall."""
        for member in self.members:
            if amount <= 0:
                return 0.0
            amount = member.deduct_from_bank_accounts(amount)
        return amount

    def _raise_cash(self, source: str, amount: float) -> float:
        """Move up to ``amount`` from ``source`` (a non-bank waterfall step) into members' banks,
        posting whatever the draw makes taxable. Unsized: the caller accounts for any tax. Returns
        the amount raised."""
        raised = 0.0
        for member in self.members:
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
            else:  # pragma: no cover - validated in __init__
                raise ValueError(f"Unknown withdrawal source {source!r}")
        return raised

    @staticmethod
    def _under_retirement_age(member: "Person") -> bool:
        from ..limits import federal_retirement_age

        return member.age < federal_retirement_age(member.model.config)

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
                self._draw_from_brokerage(bills)
                # Net capital gains and losses once — after the brokerage sale — so brokerage gains
                # net with RSU vests and any loss carryforward before later steps read the tax bases.
                self._apply_capital_loss_netting()
                netted = True
            elif source == "pretax":
                # Size and perform any pre-tax withdrawal against the tax and penalty it triggers.
                gross = self._size_gross_withdrawal(bills)
                if gross > 0:
                    self.withdraw_from_pretax_accounts(gross)
            else:
                gap = bills + self.get_income_taxes_due().total - self.bank_account_balance
                # Sub-cent gaps are fixed-point residue from the sized steps, not a real shortfall.
                if gap >= 0.005:
                    self._raise_cash(source, gap)
        if not netted:
            self._apply_capital_loss_netting()
        return self.get_income_taxes_due()

    @property
    def brokerage_balance(self) -> float:
        """Combined taxable brokerage balance across the unit's members."""
        return sum(m.brokerage_balance for m in self.members)

    def withdraw_from_brokerage_accounts(self, amount: float) -> float:
        """Sell ``amount`` from members' brokerage accounts (into the bank). Returns the unfilled
        remainder. Members are drained in order, mirroring the pre-tax 401k helper."""
        for member in self.members:
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
        for member in self.members:
            if remaining <= 0:
                break
            take = min(remaining, member.brokerage_balance)
            member_long, member_short = member.preview_brokerage_gain(take)
            long_term += member_long
            short_term += member_short
            remaining -= take
        return long_term, short_term

    def _draw_hsa_for_medical(self, bills: float) -> None:
        """When bills exceed the bank, first reimburse this year's medical costs from HSAs.

        A qualified medical distribution is entirely tax-free, so it is the cheapest money to spend:
        it comes before brokerage sales and pre-tax withdrawals. Bounded by the shortfall, each
        member's medical costs, and their HSA balances. (With enough cash the HSA is left to grow.)
        """
        shortfall = bills - self.bank_account_balance
        for member in self.members:
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

        The tax estimate reads the not-yet-netted ledger, so a rare in-year capital-loss
        carryforward makes the sizing slightly conservative (sells marginally more than needed;
        the excess simply lands in the bank). Settled taxes are always computed from the real
        post-sale ledger, so they are exact regardless.
        """
        available = self.brokerage_balance
        if available <= 0:
            return
        bank = self.bank_account_balance
        gross = 0.0
        for _ in range(100):
            long_term, short_term = self._preview_brokerage_gain(gross)
            taxes = self.get_income_taxes_due(additional_preferential=long_term, additional_short_term=short_term).total
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
            self.members[0].income.add(IncomeType.ORDINARY, -offset)

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
                    member.income.add(income_type, -amount)

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
                member.income.add(income_type, -take)
                remaining -= take

    def settle_year(self):
        """Settle the tax year for this unit: taxes, spending, housing, and debt."""
        spending_by_member: dict[int, float] = {}
        housing_by_member: dict[int, float] = {}
        interest_by_member: dict[int, float] = {}
        debt_payment_by_member: dict[int, float] = {}

        # Personal debt carried by members is settled exactly once (fixes double-pay / phantom
        # debt): zero it here and fold it into this year's bills.
        # The carried balance accrues a year of interest (credit-card-like by default) before it
        # is repaid: unpaid bills are a real liability, not a free loan.
        debt_rate = self.config.debt.effective_unpaid_balance_interest_rate / 100
        existing_debt = sum(m.debt for m in self.members)
        carried_interest_by_member = {m.unique_id: m.debt * debt_rate for m in self.members}
        existing_debt += sum(carried_interest_by_member.values())
        for member in self.members:
            member.debt = 0

        for member in self.members:
            spending_by_member[member.unique_id] = member.spending.get_yearly_spending()

            member_housing = 0.0
            member_interest = 0.0
            for home in member.homes:
                # Amortize the mortgage (12 monthly periods) then read the interest actually
                # charged this year — captured on the mortgage as the year is amortized.
                member_housing += home.make_yearly_payment()
                if home.mortgage is not None:
                    member_interest += home.mortgage.interest_paid_this_year
            for apartment in member.apartments:
                member_housing += apartment.yearly_rent

            # Service the member's personal debts (car loans, credit cards, student loans). Each
            # debt accrues 12 months of interest and receives 12 scheduled payments internally; the
            # cash paid is folded into this year's bills, the interest into the interest statistic.
            member_debt_paid, member_debt_interest = member.debt_service.service_year()
            member_interest += member_debt_interest

            # Above-the-line student-loan interest deduction (IRC §221): the interest actually paid
            # on student loans this year, capped, reduces ordinary taxable income (not FICA wages).
            student_loan_interest = sum(sl.interest_paid_this_year for sl in member.student_loans)
            deduction_limit = self.config.debt.student_loan.interest_deduction_limit
            student_loan_deduction = min(student_loan_interest, deduction_limit)
            if self.filing_status == FilingStatus.MARRIED_FILING_SEPARATELY:
                student_loan_deduction = 0.0  # not allowed on a separate return (IRC §221(e)(2))
            if student_loan_deduction > 0:
                member.income.add(IncomeType.ORDINARY, -student_loan_deduction)

            housing_by_member[member.unique_id] = member_housing
            interest_by_member[member.unique_id] = member_interest + carried_interest_by_member[member.unique_id]
            debt_payment_by_member[member.unique_id] = member_debt_paid

        total_spending = sum(spending_by_member.values())
        total_housing = sum(housing_by_member.values())
        total_debt_payments = sum(debt_payment_by_member.values())
        bills = total_spending + total_housing + total_debt_payments + existing_debt

        # Tax-free qualified HSA reimbursements of this year's medical costs come first, then the
        # household waterfall (all banks, all brokerage, Roth basis under 59.5, pre-tax, remaining
        # Roth) moves into the banks only what bills + taxes still need. Proceeds land in the bank,
        # so each step sizes against the topped-up balance and does nothing once it is covered.
        self._draw_hsa_for_medical(bills)
        taxes = self._fund_bills(bills)

        # Record this year's AGI on every member. Each member records the AGI of the
        # return they filed — the unit's full AGI, not a per-member split — because Medicare/IRMAA
        # later compares the return's MAGI against filing-status thresholds with a two-year
        # lookback. Recorded after withdrawal solving so 401k distributions are included. AGI is
        # gross income less above-the-line adjustments only: the standard/itemized deductions come
        # after AGI, so subtracting them (as this once did) understated MAGI and the surcharges.
        agi = self.agi()
        year = self.members[0].model.year
        for member in self.members:
            member.agi_history[year] = agi

        # Charity above the AGI limit carries forward; consume/record carryforwards exactly once.
        standard_deduction, itemized = self._deduction_choice(0.0, taxes.state)
        settle_charitable_carryforwards(self.members, agi, year, self.config)
        itemized_claimed = itemized if itemized > standard_deduction else 0.0

        # Pay everything from the combined banks exactly once; a shortfall becomes new debt (every
        # source has already been drawn into the banks as far as it could be). Refundable credits
        # can make the net due negative (a refund): deposit it instead of "paying" a negative bill
        # (which would create negative debt).
        net_due = bills + taxes.total
        if net_due >= 0:
            shortfall = round_money(max(0.0, self._pay_from_banks(net_due)))
        else:
            self.members[0].receive_cash(-net_due, source="refundable tax credits")
            shortfall = 0.0
        self.members[0].debt += shortfall

        self._record_stats(taxes, spending_by_member, housing_by_member, interest_by_member)
        # Which deduction the return took: the itemized amount, or 0 when it took the standard one.
        self.members[0].stat_itemized_deductions = itemized_claimed

    def _size_gross_withdrawal(self, bills: float) -> float:
        """Pure fixed-point solve for the pre-tax withdrawal needed to cover bills + taxes.

        Penalties scale linearly with the draw (10% below 59.5), so the map stays a contraction as
        long as marginal tax plus penalty stays below 100%.

        Side-effect-free: computes the gross amount without moving any money.
        """
        bank = self.bank_account_balance
        gross = 0.0
        for _ in range(100):
            taxes = self.get_income_taxes_due(gross).total
            needed = max(0.0, bills + taxes - bank)
            if abs(needed - gross) < 0.001:
                return needed
            gross = needed
        return gross

    def _record_stats(
        self,
        taxes: TaxesDue,
        spending_by_member: dict[int, float],
        housing_by_member: dict[int, float],
        interest_by_member: dict[int, float],
    ):
        for member in self.members:
            member.stat_money_spent = spending_by_member[member.unique_id]
            member.stat_housing_costs = housing_by_member[member.unique_id]
            member.stat_interest_paid = interest_by_member[member.unique_id]
            member.stat_bank_balance = member.bank_account_balance
            member.stat_brokerage_balance = member.brokerage_balance
            # Clear tax stats on every member; the unit's taxes are attributed to the head only
            # (below) so the model's per-agent sum counts them exactly once.
            member.stat_taxes_paid = 0.0
            member.stat_taxes_paid_federal = 0.0
            member.stat_taxes_paid_state = 0.0
            member.stat_taxes_paid_ss = 0.0
            member.stat_taxes_paid_medicare = 0.0
            member.stat_taxes_paid_niit = 0.0
            member.stat_capital_gains = 0.0
            member.stat_itemized_deductions = 0.0

        for member in self.members:
            totals = member.income.totals_by_type()
            member.stat_capital_gains = (
                totals[IncomeType.SHORT_TERM_CAPITAL_GAIN] + totals[IncomeType.LONG_TERM_CAPITAL_GAIN]
            )

        head = self.members[0]
        head.stat_taxes_paid = taxes.total
        head.stat_taxes_paid_federal = taxes.federal
        head.stat_taxes_paid_state = taxes.state
        head.stat_taxes_paid_ss = taxes.ss
        head.stat_taxes_paid_medicare = taxes.medicare
        head.stat_taxes_paid_niit = taxes.niit
