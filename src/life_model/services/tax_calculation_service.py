# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import TYPE_CHECKING
from ..tax.tax import TaxesDue
from ..tax.federal import max_tax_rate

if TYPE_CHECKING:
    from ..people.person import Person


class TaxCalculationService:
    """Service for handling tax calculations and 401k withdrawal planning"""

    def __init__(self, person: 'Person'):
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
        """Calculate additional taxes owed on 401k withdrawal

        Args:
            withdrawal_amount: Amount being withdrawn from pre-tax 401k

        Returns:
            Additional taxes owed on the withdrawal
        """
        if withdrawal_amount <= 0:
            return 0.0

        # Calculate taxes before and after 401k withdrawal
        taxes_before = self.person.get_income_taxes_due()
        taxes_after = self.person.get_income_taxes_due(withdrawal_amount)
        base_tax_increase = taxes_after.total - taxes_before.total

        # Add buffer based on max tax rate to ensure sufficient funds for taxes
        tax_buffer = base_tax_increase * (max_tax_rate(self.person.filing_status) / 100)

        return base_tax_increase + tax_buffer

    def calculate_total_401k_withdrawal(self, expenses_without_taxes: float) -> tuple[float, TaxesDue]:
        """Calculate total 401k withdrawal needed including taxes

        Args:
            expenses_without_taxes: Total expenses excluding taxes

        Returns:
            Tuple of (total_withdrawal_amount, final_taxes_due)
        """
        # Get initial tax calculation
        initial_taxes = self.person.get_income_taxes_due()
        total_expenses_with_taxes = expenses_without_taxes + initial_taxes.total

        # Calculate base withdrawal needed
        base_withdrawal = self.calculate_pretax_401k_withdrawal_needed(total_expenses_with_taxes)

        if base_withdrawal <= 0:
            return 0.0, initial_taxes

        # Calculate additional taxes on withdrawal
        additional_taxes = self.calculate_taxes_on_401k_withdrawal(base_withdrawal)
        total_withdrawal = base_withdrawal + additional_taxes

        # Perform the withdrawal
        self.person.withdraw_from_pretax_401ks(total_withdrawal)

        # Recalculate final taxes after withdrawal
        final_taxes = self.person.get_income_taxes_due()

        return total_withdrawal, final_taxes
