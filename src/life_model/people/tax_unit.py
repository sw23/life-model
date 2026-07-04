# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import TYPE_CHECKING, Dict, List

from ..model import round_money
from ..tax.federal import FilingStatus, get_federal_standard_deduction, max_tax_rate
from ..tax.tax import TaxesDue, get_income_taxes_due

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

    def get_income_taxes_due(self, additional_income: float = 0) -> TaxesDue:
        income_amount = self.taxable_income + additional_income
        return get_income_taxes_due(income_amount, self.federal_deductions, self.filing_status, self.config)

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
                # Capture interest for the year *before* the payment reduces the principal.
                member_interest += home.mortgage.get_interest_for_year()
                member_housing += home.make_yearly_payment()
            for apartment in member.apartments:
                member_housing += apartment.yearly_rent

            housing_by_member[member.unique_id] = member_housing
            interest_by_member[member.unique_id] = member_interest

        total_spending = sum(spending_by_member.values())
        total_housing = sum(housing_by_member.values())
        bills = total_spending + total_housing + existing_debt

        # Size and perform any pre-tax 401k withdrawal, then get the final taxes owed.
        taxes = self._solve_withdrawals_and_taxes(bills)

        # Pay everything from the combined accounts exactly once; a shortfall becomes new debt.
        shortfall = round_money(self.pay_bills(bills + taxes.total))
        self.members[0].debt += shortfall

        self._record_stats(taxes, spending_by_member, housing_by_member, interest_by_member)

    def _solve_withdrawals_and_taxes(self, bills: float) -> TaxesDue:
        """Withdraw enough pre-tax 401k to cover bills + taxes when the bank can't, then return
        the final taxes due after the withdrawal is included in taxable income."""
        initial_taxes = self.get_income_taxes_due()
        total_needed = bills + initial_taxes.total
        base_withdrawal = max(0.0, total_needed - self.bank_account_balance)
        if base_withdrawal <= 0:
            return initial_taxes

        taxes_after = self.get_income_taxes_due(base_withdrawal)
        extra_tax = taxes_after.total - initial_taxes.total
        # Add a buffer based on the max marginal rate so the withdrawal also covers its own tax.
        tax_buffer = extra_tax * (max_tax_rate(self.filing_status, self.config) / 100)
        self.withdraw_from_pretax_401ks(base_withdrawal + extra_tax + tax_buffer)

        return self.get_income_taxes_due()

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
