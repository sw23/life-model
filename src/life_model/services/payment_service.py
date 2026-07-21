# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..people.person import Person


class PaymentService:
    """Service for handling payment prioritization and execution"""

    def __init__(self, person: "Person"):
        self.person = person

    def pay_bills_with_prioritization(self, total_amount: float) -> float:
        """Pay bills following the optimal withdrawal order

        Payment priority order:
        1. Bank accounts (most liquid, no penalties)
        2. Taxable brokerage accounts (liquid; sales realize capital gains taxed at year end)
        3. Roth retirement accounts (contributions can be withdrawn penalty-free)

        Args:
            total_amount: Total amount of bills to pay

        Returns:
            Amount that could not be paid (remaining debt)
        """
        remaining_balance = total_amount

        # First priority: Pay from bank accounts
        remaining_balance = self._pay_from_bank_accounts(remaining_balance)
        if remaining_balance == 0:
            return 0

        # Second priority: Pay from taxable brokerage accounts, before any retirement account.
        # Selling realizes capital gains that the tax unit settles at year end.
        remaining_balance = self._pay_from_brokerage_accounts(remaining_balance)
        if remaining_balance == 0:
            return 0

        # Last priority: Pay from Roth retirement accounts
        # These are last because we want to keep investments growing as long as possible
        # https://www.investopedia.com/retirement/how-to-manage-timing-and-sources-of-income-retirement/
        remaining_balance = self._pay_from_roth_accounts(remaining_balance)

        return remaining_balance

    def _pay_from_bank_accounts(self, amount: float) -> float:
        """Pay from bank accounts first (most liquid)

        Args:
            amount: Amount to pay

        Returns:
            Remaining amount that couldn't be paid
        """
        return self.person.deduct_from_bank_accounts(amount)

    def _pay_from_brokerage_accounts(self, amount: float) -> float:
        """Pay from taxable brokerage accounts, before retirement accounts.

        ``withdraw_from_brokerage_accounts`` sells lots FIFO into the bank and posts the realized
        capital gains to the income ledger, so the sale is taxed when the unit settles the year.

        Args:
            amount: Amount to pay

        Returns:
            Remaining amount that couldn't be paid
        """
        return amount - self.person.withdraw_from_brokerage_accounts(amount)

    def _pay_from_roth_accounts(self, amount: float) -> float:
        """Pay from Roth retirement accounts as last resort

        Args:
            amount: Amount to pay

        Returns:
            Remaining amount that couldn't be paid
        """
        return self.person.deduct_from_roth_401ks(amount)
