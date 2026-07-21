# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import math
import warnings
from typing import TYPE_CHECKING, Dict, List

from ..model import round_money
from ..tax.credits import child_tax_credit
from ..tax.federal import FilingStatus, get_federal_standard_deduction
from ..tax.income import IncomeType
from ..tax.state import state_income_tax_for_unit
from ..tax.tax import TaxesDue, compute_taxes

if TYPE_CHECKING:
    from .family import Family
    from .person import Person


class TaxUnit:
    """A tax-filing unit: a single person, or a married couple filing jointly.

    The tax unit owns the year-end settlement for its members:

      1. Gather every non-tax bill (discretionary spending, housing payments, apartment rent,
         and any personal debt carried by members) exactly once.
      2. Compute income taxes on the unit's combined taxable income.
      3. Size a pre-tax 401k withdrawal (plus the taxes it triggers) if the combined bank
         balance can't cover bills + taxes, and perform that withdrawal.
      4. Pay bills + taxes from the members' combined accounts exactly once. Any shortfall
         becomes new debt on the first member.

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

    def __init__(self, members: List["Person"]):
        if not members:
            raise ValueError("TaxUnit requires at least one member")
        self.members = members
        self.filing_status = members[0].filing_status
        self.config = members[0].model.config
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
    def build_units(cls, family: "Family") -> List["TaxUnit"]:
        """Group a family's members into filing units.

        A married-filing-jointly member and their spouse (when both are in the family) form one
        joint unit; every other member is its own single unit. An unmarried member with at least
        one dependent child files HEAD_OF_HOUSEHOLD (the unit's status only — the person's own
        ``filing_status`` is untouched); when the config carries no head_of_household data the
        deduction/brackets fall back to single.
        """
        units: List["TaxUnit"] = []
        seen = set()
        for member in family.members:
            if member.unique_id in seen:
                continue
            spouse = member.spouse
            if (
                member.filing_status == FilingStatus.MARRIED_FILING_JOINTLY
                and spouse is not None
                and spouse in family.members
            ):
                units.append(cls([member, spouse]))
                seen.add(member.unique_id)
                seen.add(spouse.unique_id)
            else:
                unit = cls([member])
                if member.filing_status == FilingStatus.SINGLE and cls._has_dependent_child(member):
                    unit.filing_status = FilingStatus.HEAD_OF_HOUSEHOLD
                units.append(unit)
                seen.add(member.unique_id)
        return units

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

    def _prospective_withdrawal_allocation(self, amount: float) -> Dict[int, float]:
        """Predict how ``withdraw_from_pretax_401ks`` would split ``amount`` across members.

        Mirrors the withdrawal order exactly (members in sequence, each up to their combined
        pre-tax balance) without moving any money, so income-dependent deductions can be
        evaluated during sizing against the same per-member incomes settlement will see.
        """
        allocation: Dict[int, float] = {}
        remaining = amount
        for member in self.members:
            available = sum(acct.pretax_balance for acct in member.all_retirement_accounts)
            take = min(remaining, available)
            allocation[member.unique_id] = take
            remaining -= take
        return allocation

    def federal_deductions_combined(self, additional_income: float = 0.0, state_income_tax_paid: float = 0.0) -> float:
        """Federal deductions folding in BOTH plans' income-dependent itemized adjustments.

        - The 7.5%-of-income medical floor depends on ordinary income, so a prospective
          401k withdrawal (``additional_income``) changes the deduction. It is allocated across
          members exactly as ``withdraw_from_pretax_401ks`` will split it, so each member's floor
          matches what settlement will see — otherwise sizing over-estimates the medical deduction
          and the shortfall lands as phantom year-end debt.
        - The unit's state income tax (``state_income_tax_paid``) enters the head's SALT
          bucket (mirrors ``_record_stats``' head convention), capped at the SALT limit per member.

        With both arguments 0 this is the plain standard-vs-itemized comparison.
        """
        standard_deduction = get_federal_standard_deduction(self.filing_status, self.config)
        allocation = self._prospective_withdrawal_allocation(additional_income) if additional_income > 0 else None
        itemized = 0.0
        for index, member in enumerate(self.members):
            member_income = allocation[member.unique_id] if allocation else 0.0
            member_state_tax = state_income_tax_paid if index == 0 else 0.0
            itemized += member.itemized_deductions(member_state_tax, member_income)
        return max(standard_deduction, itemized)

    @property
    def num_qualifying_children(self) -> int:
        """Children of unit members who qualify for the Child Tax Credit this year.

        A child qualifies when their age is between 0 and ``ctc_qualifying_age_max`` (inclusive);
        unborn children (negative age) and adult children do not. Each child is registered to
        exactly one (living) member, so no double-counting is possible.
        """
        max_age = self.config.dependents.ctc_qualifying_age_max
        return sum(1 for member in self.members for child in member.children if 0 <= child.age <= max_age)

    def _state_income_totals(self, additional_income: float) -> "Dict[IncomeType, float]":
        """Combined ordinary-taxable amount per income type across members.

        ``additional_income`` (a prospective pre-tax 401k withdrawal) is ordinary income taxed as a
        pre-tax distribution, so states that exempt retirement income exempt it too.
        """
        totals: Dict[IncomeType, float] = {income_type: 0.0 for income_type in IncomeType}
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

    def get_income_taxes_due(
        self,
        additional_income: float = 0,
        *,
        additional_preferential: float = 0.0,
        additional_short_term: float = 0.0,
    ) -> TaxesDue:
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
        return taxes

    def withdraw_from_pretax_401ks(self, amount: float) -> float:
        """Withdraw ``amount`` from members' pre-tax 401ks. Returns the amount not withdrawn."""
        for member in self.members:
            if amount <= 0:
                break
            amount -= member.withdraw_from_pretax_401ks(amount)
        return amount

    def pay_bills(self, amount: float) -> float:
        """Pay ``amount`` from members' combined accounts. Returns the unpaid shortfall."""
        for member in self.members:
            if amount <= 0:
                return 0
            amount = member.pay_bills(amount)
        return amount

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
            taxes = self.get_income_taxes_due(
                additional_preferential=long_term, additional_short_term=short_term
            ).total
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

    def _capital_gain_totals(self, member: "Person") -> "Dict[IncomeType, float]":
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

    def _zero_out_capital_gains(self, gains_by_member: "Dict[int, Dict[IncomeType, float]]") -> None:
        """Remove every realized capital gain and loss from the members' tax bases."""
        for member in self.members:
            for income_type, amount in gains_by_member[member.unique_id].items():
                if amount != 0:
                    member.income.add(income_type, -amount)

    def _reduce_gains(self, gains_by_member: "Dict[int, Dict[IncomeType, float]]", amount: float) -> None:
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
        spending_by_member: Dict[int, float] = {}
        housing_by_member: Dict[int, float] = {}
        interest_by_member: Dict[int, float] = {}
        debt_payment_by_member: Dict[int, float] = {}

        # Personal debt carried by members is settled exactly once (fixes double-pay / phantom
        # debt): zero it here and fold it into this year's bills.
        existing_debt = sum(m.debt for m in self.members)
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
            if student_loan_deduction > 0:
                member.income.add(IncomeType.ORDINARY, -student_loan_deduction)

            housing_by_member[member.unique_id] = member_housing
            interest_by_member[member.unique_id] = member_interest
            debt_payment_by_member[member.unique_id] = member_debt_paid

        total_spending = sum(spending_by_member.values())
        total_housing = sum(housing_by_member.values())
        total_debt_payments = sum(debt_payment_by_member.values())
        bills = total_spending + total_housing + total_debt_payments + existing_debt

        # Spending priority: bank first, then taxable brokerage, then retirement accounts. Draw
        # any brokerage needed to cover bills + the capital-gains tax the sale triggers before the
        # pre-tax 401k is considered. Proceeds land in the bank, so the 401k solve below naturally
        # sizes against the topped-up balance (and does nothing when brokerage already covered it).
        self._draw_from_brokerage(bills)

        # Net capital gains and losses once — after the brokerage sale — so brokerage gains net
        # with RSU vests and any loss carryforward before the tax bases are read for the 401k
        # solve. (Doing it here rather than up front keeps a single, all-in netting pass.)
        self._apply_capital_loss_netting()

        # Size and perform any pre-tax 401k withdrawal, then get the final taxes owed.
        taxes = self._solve_withdrawals_and_taxes(bills)

        # Record this year's AGI on every member. Each member records the AGI of the
        # return they filed — the unit's full AGI, not a per-member split — because Medicare/IRMAA
        # later compares the return's MAGI against filing-status thresholds with a two-year
        # lookback. Recorded after withdrawal solving so 401k distributions are included.
        # Preferential income is excluded from ``taxable_income`` (it has its own rate schedule) but
        # is fully part of AGI — leaving it out here would understate MAGI and silently under-charge
        # the IRMAA surcharges Medicare reads off this history.
        agi = max(self.taxable_income + self.preferential_income - self.federal_deductions, 0.0)
        year = self.members[0].model.year
        for member in self.members:
            member.agi_history[year] = agi

        # Pay everything from the combined accounts exactly once; a shortfall becomes new debt.
        # Refundable credits can make the net due negative (a refund): deposit it instead of
        # "paying" a negative bill (which would create negative debt).
        net_due = bills + taxes.total
        if net_due >= 0:
            shortfall = round_money(self.pay_bills(net_due))
        else:
            self.members[0].receive_cash(-net_due, source="refundable tax credits")
            shortfall = 0.0
        self.members[0].debt += shortfall

        self._record_stats(taxes, spending_by_member, housing_by_member, interest_by_member)

    def _solve_withdrawals_and_taxes(self, bills: float) -> TaxesDue:
        """Withdraw enough pre-tax 401k to cover bills + the taxes the withdrawal itself triggers
        when the bank can't, then return the final taxes due.

        The gross withdrawal is sized by a fixed-point iteration rather than a max-marginal-rate
        buffer: ``gross = bills + taxes(gross) - bank_balance``. Because the marginal tax rate is
        piecewise-constant and below 100%, the map is a contraction and converges quickly. This
        avoids the old heuristic's systematic over-withdrawal.
        """
        gross = self._size_gross_withdrawal(bills)
        if gross > 0:
            self.withdraw_from_pretax_401ks(gross)
        return self.get_income_taxes_due()

    def _size_gross_withdrawal(self, bills: float) -> float:
        """Pure fixed-point solve for the pre-tax 401k withdrawal needed to cover bills + taxes.

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
        spending_by_member: Dict[int, float],
        housing_by_member: Dict[int, float],
        interest_by_member: Dict[int, float],
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
