# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from ..base_classes import Investment
from ..model import Event
from ..people.person import Person
from ..tax.income import IncomeType


class InheritedPretaxAccount(Investment):
    """A non-spouse beneficiary's inherited pre-tax retirement balance under the SECURE Act 10-year rule.

    When a non-spouse inherits a decedent's pre-tax retirement money (traditional 401k / IRA), the
    balance moves into this account instead of being dumped into the beneficiary's income as a
    single-year lump sum (the lump-sum simplification). The account keeps growing like any equity
    :class:`~life_model.base_classes.Investment`, and each year distributes an even slice —
    ``balance / years_remaining`` — over ten years, recording each distribution as
    :class:`~life_model.tax.income.IncomeType.PRETAX_DISTRIBUTION` (ordinary income, no FICA) and
    depositing the cash. Because growth continues, the ten distributions sum to more than the
    starting balance; the tax is spread and deferred instead of stacked into the death year.

    Simplifications (documented, backlog for later refinement):
      * Even-spread strategy only (equal fractional withdrawals); real beneficiaries may bunch or
        defer distributions within the ten-year window to manage brackets.
      * No separate RMD-continuation rule for eligible designated beneficiaries; every non-spouse
        heir uses the flat ten-year spread.
    """

    def __init__(self, beneficiary: Person, balance: float, decedent_name: str, years: int = 10):
        """Create an inherited pre-tax account for a non-spouse beneficiary.

        Args:
            beneficiary: The person who inherited the pre-tax balance.
            balance: The inherited pre-tax balance.
            decedent_name: Name of the decedent (for event logging).
            years: Number of years over which to distribute the balance (SECURE Act: 10).
        """
        super().__init__(beneficiary, balance, asset_class="equity")
        self.decedent_name = decedent_name
        self.years_remaining = years

    def calculate_growth(self) -> float:
        """Calculate investment growth based on the equity return for the year."""
        return self.balance * (self.growth_rate / 100)

    def get_balance(self) -> float:
        return self.balance

    def deposit(self, amount: float) -> bool:
        # Inherited accounts do not accept new contributions.
        return False

    def withdraw(self, amount: float) -> float:
        if amount <= 0:
            return 0.0
        actual = min(amount, self.balance)
        self.balance -= actual
        return actual

    def step(self):
        """Apply growth (Investment.step), then surface the remaining corpus in the useable-balance
        stat so the inherited money is visible to balance reporting during the 10-year window.
        Inherited-account withdrawals carry no early-withdrawal penalty (death exception), so the
        full balance is genuinely useable."""
        super().step()
        self.stat_useable_balance = self.balance

    def pre_step(self):
        # Distribute this year's even slice before the step-stage tax settlement so the income
        # lands in the beneficiary's ledger for the current year. Growth is applied later in the
        # step stage (Investment.step), so the remaining balance keeps compounding.
        if self.years_remaining <= 0 or self.balance <= 0:
            self._finish()
            return

        distribution = self.withdraw(self.balance / self.years_remaining)
        self.years_remaining -= 1
        if distribution > 0:
            self.person.income.add(IncomeType.PRETAX_DISTRIBUTION, distribution)
            self.person.receive_cash(distribution, source=f"inherited retirement from {self.decedent_name}")

        # Once the ten-year window closes (or the balance is exhausted), remove the account so it
        # stops stepping.
        if self.years_remaining <= 0 or self.balance <= 0:
            self._finish()

    def _finish(self):
        """Distribute any residual balance and remove the account from the simulation."""
        if self.balance > 0:
            residual = self.withdraw(self.balance)
            self.person.income.add(IncomeType.PRETAX_DISTRIBUTION, residual)
            self.person.receive_cash(residual, source=f"inherited retirement from {self.decedent_name}")
        self.model.event_log.add(
            Event(f"{self.person.name}'s inherited account from {self.decedent_name} fully distributed")
        )
        self.remove()

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Inherited from: {self.decedent_name}</li>"
        desc += f"<li>Balance: ${self.balance:,.2f}</li>"
        desc += f"<li>Years Remaining: {self.years_remaining}</li>"
        desc += "</ul>"
        return desc
