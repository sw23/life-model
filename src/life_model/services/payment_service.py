# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..people.person import Person


class PaymentService:
    """Service for handling payment prioritization and execution.

    This service pays a person's share of bills once the tax unit has already drawn taxable
    sources it sizes itself (brokerage sales and pre-tax 401k withdrawals sized against the taxes
    they trigger). It draws in a configurable priority order; the default keeps the most tax- and
    growth-favored money for last:

        1. Bank accounts (most liquid, no tax).
        2. Taxable brokerage accounts (sales realize capital gains, taxed at year-end settlement).
        3. Roth 401k balances.
        4. Roth IRAs (contribution basis is drawn before earnings).

    https://www.investopedia.com/retirement/how-to-manage-timing-and-sources-of-income-retirement/
    """

    #: Default ordered list of draw sources (method names on this service).
    DEFAULT_PRIORITY = (
        "_pay_from_bank_accounts",
        "_pay_from_brokerage_accounts",
        "_pay_from_roth_401ks",
        "_pay_from_roth_iras",
    )

    def __init__(self, person: "Person", priority=None):
        self.person = person
        self.priority = tuple(priority) if priority is not None else self.DEFAULT_PRIORITY

    def pay_bills_with_prioritization(self, total_amount: float) -> float:
        """Pay bills following the configured withdrawal order.

        Args:
            total_amount: Total amount of bills to pay

        Returns:
            Amount that could not be paid (remaining debt)
        """
        remaining_balance = total_amount
        for source in self.priority:
            if remaining_balance <= 0:
                return 0
            remaining_balance = getattr(self, source)(remaining_balance)
        return remaining_balance

    def _pay_from_bank_accounts(self, amount: float) -> float:
        """Pay from bank accounts first (most liquid). Returns the unpaid remainder."""
        return self.person.deduct_from_bank_accounts(amount)

    def _pay_from_brokerage_accounts(self, amount: float) -> float:
        """Sell brokerage holdings into the bank, then pay from the bank. Returns the unpaid remainder.

        ``withdraw_from_brokerage_accounts`` sells lots FIFO into the bank and posts the realized
        capital gains to the income ledger, so the sale is taxed when the unit settles the year. The
        proceeds must then actually leave the bank: counting them as paid while they sit in the bank
        would create money.
        """
        self.person.withdraw_from_brokerage_accounts(amount)
        return self.person.deduct_from_bank_accounts(amount)

    def _pay_from_roth_401ks(self, amount: float) -> float:
        """Pay from Roth 401k balances. Returns the unpaid remainder."""
        return self.person.deduct_from_roth_401ks(amount)

    def _pay_from_roth_iras(self, amount: float) -> float:
        """Pay from Roth IRAs, contribution basis before earnings. Returns the unpaid remainder."""
        return self.person.deduct_from_roth_iras(amount)
