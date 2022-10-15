from .basemodel import BaseModel
from .tax.federal import FilingStatus, federal_income_tax, max_tax_rate


class Family(BaseModel):
    def __init__(self, simulation, *args):
        """Family

        Args:
            simulation (Simulation): Simulation.
            args (Person): Family members.
        """
        self.simulation = simulation
        self.simulation.top_level_models.append(self)
        self.members = list(args)

    @property
    def bank_account_balance(self):
        return sum(x.bank_account_balance for x in self.members)

    @property
    def debt(self):
        return sum(x.debt for x in self.members)

    @property
    def filing_status(self):
        # TODO - Currently using the first member's filing status for the whole family
        return self.members[0].filing_status

    @property
    def combined_spending(self):
        return sum(x.spending.base for x in self.members)

    @property
    def combined_taxable_income(self):
        return sum(x.taxable_income for x in self.members)

    def __getitem__(self, key):
        matches = {x.name: x for x in self.members}
        return matches[key]

    def _repr_html_(self):
        return '<b>Family:</b><ul>' + ''.join(f"<li>{x._repr_html_()}</li>" for x in self.members) + '</ul>'

    def withdraw_from_pretax_401ks(self, amount):
        for member in self.members:
            if (amount == 0):
                break
            amount -= member.withdraw_from_pretax_401ks(amount)
        return amount

    def pay_bills(self, spending_balance):
        for member in self.members:
            if (spending_balance == 0):
                return 0
            spending_balance = member.pay_bills(spending_balance)
        return spending_balance

    def get_federal_taxes_due(self, additional_income=0):
        income_amount = self.combined_taxable_income + additional_income
        if self.filing_status == FilingStatus.MARRIED_FILING_JOINTLY:
            return federal_income_tax(income_amount, self.filing_status)
        else:
            raise NotImplementedError(f"Unsupported filing status: {self.filing_status}")

    def advance_year(self, objects=None):
        super().advance_year(objects)

        # Pay off spending, taxes, and debts for the year
        # - People filing MFJ is handled individually here, single is handled in family
        if self.filing_status == FilingStatus.MARRIED_FILING_JOINTLY:
            # 1. See what amount needs to come from pre-tax 401k
            #    - RMDs are handled before this by moving the RMD from 401k to bank account
            # 2. Withdraw that amount plus max tax rate to cover taxes
            # 3. Deposit that amount into checking
            yearly_taxes = self.get_federal_taxes_due()
            spending_plus_pre_401k_taxes = self.combined_spending + yearly_taxes
            amount_from_pretax_401k = max(0, spending_plus_pre_401k_taxes - self.bank_account_balance)
            taxes_from_pretax_401k = self.get_federal_taxes_due(amount_from_pretax_401k) - yearly_taxes
            taxes_from_pretax_401k += taxes_from_pretax_401k * (max_tax_rate(self.filing_status) / 100)
            self.withdraw_from_pretax_401ks(amount_from_pretax_401k + taxes_from_pretax_401k)

            # Now that 401k withdrawal is complete (if necessary), calculatue taxes
            if amount_from_pretax_401k:
                yearly_taxes = self.get_federal_taxes_due()

            self.members[0].debt += self.pay_bills(self.combined_spending + yearly_taxes)
            self.members[0].debt = self.pay_bills(self.debt)
        else:
            yearly_taxes = 0

        # Pay off any debts for other family members
        # TODO - Probably want to add some rules around this (e.g. parents vs. kids)
        # TODO - Currently all debts are paid off right away, but this should be modeled better
        # TODO - Also right now a pre-tax 401k won't be accessed (but roth will)
        for person_x in self.members:
            if person_x.debt > 0:
                person_x.debt = self.pay_bills(person_x.debt)

        self.stat_taxes_paid = yearly_taxes
        self.stat_debt = self.debt
