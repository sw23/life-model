# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from ..model import LifeModel, LifeModelAgent
from ..tax.federal import FilingStatus, federal_standard_deduction
from ..tax.tax import TaxesDue, get_income_taxes_due
from .tax_unit import TaxUnit


class Family(LifeModelAgent):
    def __init__(self, model: LifeModel, *args):
        """Family

        Args:
            model (LifeModel): LifeModel.
            args (Person): Family members.
        """
        super().__init__(model)
        self.members = list(args)

    @property
    def federal_deductions(self) -> float:
        """Get federal deductions - use greater of standard or itemized"""
        standard_deduction = federal_standard_deduction[self.filing_status]
        itemized_deductions = self.total_itemized_deductions
        return max(standard_deduction, itemized_deductions)

    @property
    def total_itemized_deductions(self) -> float:
        """Calculate total itemized deductions for the family

        For married filing jointly, combine all family members' itemized deductions
        """
        return sum(member.total_itemized_deductions for member in self.members)

    @property
    def bank_account_balance(self) -> float:
        return sum(x.bank_account_balance for x in self.members)

    @property
    def debt(self) -> float:
        return sum(x.debt for x in self.members)

    @property
    def filing_status(self) -> FilingStatus:
        # TODO - Currently using the first member's filing status for the whole family
        if not self.members:
            return FilingStatus.SINGLE
        return self.members[0].filing_status

    @property
    def combined_spending(self) -> float:
        return sum(x.spending.base for x in self.members)

    @property
    def combined_taxable_income(self) -> float:
        return sum(x.taxable_income for x in self.members)

    def __getitem__(self, key):
        matches = {x.name: x for x in self.members}
        return matches[key]

    def _repr_html_(self):
        return "<b>Family:</b><ul>" + "".join(f"<li>{x._repr_html_()}</li>" for x in self.members) + "</ul>"

    def withdraw_from_pretax_401ks(self, amount: float) -> float:
        for member in self.members:
            if amount <= 0:
                break
            amount -= member.withdraw_from_pretax_401ks(amount)
        return amount

    def pay_bills(self, spending_balance: float) -> float:
        """Pay bills for the year.

        Args:
            spending_balance (float): Amount of spending left to pay.

        Returns:
            float: Balance remaining after paying bills.
        """
        for member in self.members:
            if spending_balance <= 0:
                return 0
            spending_balance = member.pay_bills(spending_balance)
        return spending_balance

    def get_income_taxes_due(self, additional_income: float = 0) -> TaxesDue:
        """Get income taxes due for the year.

        Args:
            additional_income (float, optional): Additional income to include in calculation. Defaults to 0.

        Raises:
            NotImplementedError: Unsupported filing status.

        Returns:
            float: Federal taxes due.
        """
        income_amount = self.combined_taxable_income + additional_income
        if self.filing_status == FilingStatus.MARRIED_FILING_JOINTLY:
            return get_income_taxes_due(income_amount, self.federal_deductions, self.filing_status)
        else:
            raise NotImplementedError(f"Unsupported filing status: {self.filing_status}")

    def step(self):
        # Family performs no tax math. It groups its members into filing units and lets each
        # tax unit settle the year (taxes, spending, housing, one-time expenses, and debt).
        for unit in TaxUnit.build_units(self):
            unit.settle_year()

        self.stat_debt = self.debt
