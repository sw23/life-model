# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import warnings
from typing import TYPE_CHECKING, Dict, List

from ..model import round_money
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

    ``Family`` is only a container/aggregator built on top of tax units; it no longer performs
    any tax math. This single abstraction is what makes married-couple housing, family debt,
    and mixed-filing-status families settle correctly.

    **Single-state simplification (Plan 17 D2):** the whole unit files in the *head's* state
    (``members[0].state``), and the head is whichever spouse was constructed first (agent order ==
    construction order, Plan 04 D2). A CA-head/TX-spouse couple therefore pays CA tax on the full
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
        # A tax unit files in a single state — the head's (Plan 17 D2). No part-year/multi-state.
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
        joint unit; every other member is its own single unit.
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
                units.append(cls([member]))
                seen.add(member.unique_id)
        return units

    @property
    def taxable_income(self) -> float:
        return sum(m.taxable_income for m in self.members)

    @property
    def bank_account_balance(self) -> float:
        return sum(m.bank_account_balance for m in self.members)

    @property
    def total_itemized_deductions(self) -> float:
        return sum(m.total_itemized_deductions for m in self.members)

    @property
    def federal_deductions(self) -> float:
        """Greater of the standard deduction for the filing status or combined itemized."""
        standard_deduction = get_federal_standard_deduction(self.filing_status, self.config)
        return max(standard_deduction, self.total_itemized_deductions)

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

    def state_income_tax_due(self, additional_income: float = 0) -> float:
        """State income tax for the unit, resolving the head's state pack (Plan 17).

        Computed against the property-only AGI base so it does not depend on itself being folded
        into SALT (D4 no-circularity). ``DEFAULT`` residents get the legacy flat number exactly.
        """
        ordinary_income = self.taxable_income + additional_income
        legacy_agi = max(ordinary_income - self.federal_deductions, 0)
        return state_income_tax_for_unit(
            self._state_income_totals(additional_income), self.filing_status, self.state, legacy_agi, self.config
        )

    def federal_deductions_with_state_tax(self, state_tax: float) -> float:
        """Federal deductions with the unit's state income tax folded into the head's SALT bucket.

        Attributing the whole unit's state tax to the head (mirrors ``_record_stats``' head
        convention) keeps the per-member SALT cap behavior unchanged when ``state_tax`` is 0.
        """
        standard_deduction = get_federal_standard_deduction(self.filing_status, self.config)
        itemized = 0.0
        for index, member in enumerate(self.members):
            itemized += member.itemized_deductions(state_tax if index == 0 else 0.0)
        return max(standard_deduction, itemized)

    def get_income_taxes_due(self, additional_income: float = 0) -> TaxesDue:
        # ``additional_income`` models a prospective pre-tax 401k withdrawal: it is ordinary
        # income but not FICA wages, so it is not added to the per-member wage bases.
        ordinary_income = self.taxable_income + additional_income
        wage_incomes = [m.fica_wages for m in self.members]
        state_tax = self.state_income_tax_due(additional_income)
        deductions = self.federal_deductions_with_state_tax(state_tax)
        return compute_taxes(
            ordinary_income, deductions, self.filing_status, wage_incomes, self.config, state_tax=state_tax
        )

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

        # Size and perform any pre-tax 401k withdrawal, then get the final taxes owed.
        taxes = self._solve_withdrawals_and_taxes(bills)

        # Pay everything from the combined accounts exactly once; a shortfall becomes new debt.
        shortfall = round_money(self.pay_bills(bills + taxes.total))
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
            # Clear tax stats on every member; the unit's taxes are attributed to the head only
            # (below) so the model's per-agent sum counts them exactly once.
            member.stat_taxes_paid = 0.0
            member.stat_taxes_paid_federal = 0.0
            member.stat_taxes_paid_state = 0.0
            member.stat_taxes_paid_ss = 0.0
            member.stat_taxes_paid_medicare = 0.0

        head = self.members[0]
        head.stat_taxes_paid = taxes.total
        head.stat_taxes_paid_federal = taxes.federal
        head.stat_taxes_paid_state = taxes.state
        head.stat_taxes_paid_ss = taxes.ss
        head.stat_taxes_paid_medicare = taxes.medicare
