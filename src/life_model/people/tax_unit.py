# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import TYPE_CHECKING, Dict, List

from ..model import round_money
from ..tax.credits import child_tax_credit
from ..tax.federal import FilingStatus, get_federal_standard_deduction
from ..tax.income import IncomeType
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
    """

    def __init__(self, members: List["Person"]):
        if not members:
            raise ValueError("TaxUnit requires at least one member")
        self.members = members
        self.filing_status = members[0].filing_status
        self.config = members[0].model.config

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

    @property
    def num_qualifying_children(self) -> int:
        """Children of unit members who qualify for the Child Tax Credit this year.

        A child qualifies when their age is between 0 and ``ctc_qualifying_age_max`` (inclusive);
        unborn children (negative age) and adult children do not. Each child is registered to
        exactly one (living) member, so no double-counting is possible.
        """
        max_age = self.config.dependents.ctc_qualifying_age_max
        return sum(1 for member in self.members for child in member.children if 0 <= child.age <= max_age)

    def get_income_taxes_due(self, additional_income: float = 0) -> TaxesDue:
        # ``additional_income`` models a prospective pre-tax 401k withdrawal: it is ordinary
        # income but not FICA wages, so it is not added to the per-member wage bases.
        ordinary_income = self.taxable_income + additional_income
        wage_incomes = [m.fica_wages for m in self.members]
        taxes = compute_taxes(ordinary_income, self.federal_deductions, self.filing_status, wage_incomes, self.config)
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
