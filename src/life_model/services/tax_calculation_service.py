# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import TYPE_CHECKING

from ..tax.tax import TaxesDue

if TYPE_CHECKING:
    from ..people.person import Person


class TaxCalculationService:
    """Single-person pre-tax 401k withdrawal planning.

    Sizing is side-effect free and exact: the gross withdrawal is the fixed point of
    ``gross = expenses + taxes(gross) - bank``, the same solve the tax unit uses at settlement, so
    no max-marginal-rate safety buffer is needed (Plan 05 item 9). Execution is a separate step.
    """

    def __init__(self, person: "Person"):
        self.person = person

    def calculate_pretax_401k_withdrawal_needed(self, total_expenses: float) -> float:
        """Calculate how much needs to be withdrawn from pre-tax 401k accounts

        Args:
            total_expenses: Total expenses including bills and current taxes

        Returns:
            Amount needed from pre-tax 401k (0 if bank balance is sufficient)
        """
        return max(0, total_expenses - self.person.bank_account_balance)

    def calculate_taxes_on_401k_withdrawal(self, withdrawal_amount: float) -> float:
        """Additional taxes (and any early-withdrawal penalty) a pre-tax withdrawal would trigger.

        Args:
            withdrawal_amount: Amount being withdrawn from pre-tax 401k

        Returns:
            The exact increase in this year's taxes due to the withdrawal.
        """
        if withdrawal_amount <= 0:
            return 0.0
        taxes_before = self.person.get_income_taxes_due()
        taxes_after = self.person.get_income_taxes_due(withdrawal_amount)
        return taxes_after.total - taxes_before.total

    def size_401k_withdrawal(self, expenses_without_taxes: float) -> float:
        """Pre-tax withdrawal that covers ``expenses_without_taxes`` plus the taxes it triggers.

        Side-effect free. The map is a contraction because the marginal rate (plus penalty) stays
        below 100%, so it converges in a handful of iterations.
        """
        bank = self.person.bank_account_balance
        gross = 0.0
        for _ in range(100):
            needed = max(0.0, expenses_without_taxes + self.person.get_income_taxes_due(gross).total - bank)
            if abs(needed - gross) < 0.001:
                return needed
            gross = needed
        return gross

    def calculate_total_401k_withdrawal(self, expenses_without_taxes: float) -> tuple[float, TaxesDue]:
        """Size and perform the pre-tax withdrawal needed to cover expenses plus taxes.

        Args:
            expenses_without_taxes: Total expenses excluding taxes

        Returns:
            Tuple of (total_withdrawal_amount, final_taxes_due)
        """
        total_withdrawal = self.size_401k_withdrawal(expenses_without_taxes)
        if total_withdrawal > 0:
            self.person.withdraw_from_pretax_401ks(total_withdrawal)
        return total_withdrawal, self.person.get_income_taxes_due()
