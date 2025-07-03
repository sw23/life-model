# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from ..tax.federal import FilingStatus, max_tax_rate, federal_standard_deduction
from ..tax.tax import get_income_taxes_due, TaxesDue
from ..model import LifeModelAgent, LifeModel


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
        # TODO - Using std deduction for now, but should be able to itemize
        return federal_standard_deduction[self.filing_status]

    @property
    def bank_account_balance(self) -> float:
        return sum(x.bank_account_balance for x in self.members)

    @property
    def debt(self) -> float:
        return sum(x.debt for x in self.members)

    @property
    def filing_status(self) -> FilingStatus:
        # TODO - Currently using the first member's filing status for the whole family
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
        return '<b>Family:</b><ul>' + ''.join(f"<li>{x._repr_html_()}</li>" for x in self.members) + '</ul>'

    def withdraw_from_pretax_401ks(self, amount: float) -> float:
        for member in self.members:
            if (amount == 0):
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
            if (spending_balance == 0):
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

        # Pay off spending, taxes, and debts for the year
        # - People filing MFJ is handled individually here, single is handled in family
        if self.filing_status == FilingStatus.MARRIED_FILING_JOINTLY:
            # 1. See what amount needs to come from pre-tax 401k
            #    - RMDs are handled before this by moving the RMD from 401k to bank account
            # 2. Withdraw that amount plus max tax rate to cover taxes
            # 3. Deposit that amount into checking
            yearly_taxes = self.get_income_taxes_due()
            spending_plus_pre_401k_taxes = self.combined_spending + yearly_taxes.total
            amount_from_pretax_401k = max(0, spending_plus_pre_401k_taxes - self.bank_account_balance)
            yearly_taxes_plus_401k_income = self.get_income_taxes_due(amount_from_pretax_401k)
            taxes_from_pretax_401k = yearly_taxes_plus_401k_income.total - yearly_taxes.total
            taxes_from_pretax_401k += taxes_from_pretax_401k * (max_tax_rate(self.filing_status) / 100)
            self.withdraw_from_pretax_401ks(amount_from_pretax_401k + taxes_from_pretax_401k)

            # Now that 401k withdrawal is complete (if necessary), calculatue taxes
            if amount_from_pretax_401k:
                yearly_taxes = self.get_income_taxes_due()

            self.members[0].debt += self.pay_bills(self.combined_spending + yearly_taxes.total)
            self.members[0].debt = self.pay_bills(self.debt)
        else:
            yearly_taxes = TaxesDue()

        # Pay off any debts for other family members
        # TODO - Probably want to add some rules around this (e.g. parents vs. kids)
        # TODO - Currently all debts are paid off right away, but this should be modeled better
        # TODO - Also right now a pre-tax 401k won't be accessed (but roth will)
        for person_x in self.members:
            if person_x.debt > 0:
                person_x.debt = self.pay_bills(person_x.debt)

        self.stat_taxes_paid = yearly_taxes.total
        self.stat_debt = self.debt

        # Additional tax stats
        self.stat_taxes_paid_federal = yearly_taxes.federal
        self.stat_taxes_paid_state = yearly_taxes.state
        self.stat_taxes_paid_ss = yearly_taxes.ss
        self.stat_taxes_paid_medicare = yearly_taxes.medicare
