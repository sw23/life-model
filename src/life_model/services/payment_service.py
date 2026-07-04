# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..people.person import Person


class PaymentService:
    """Service for handling payment prioritization and execution.

    This service performs the *final, tax-free* drain used to pay a person's share of bills once
    the tax unit has already liquidated taxable investments (brokerage, pre-tax 401k) and sized the
    resulting taxes. It draws in a configurable priority order; the default keeps the most tax- and
    growth-favored money for last:

        1. Bank accounts (most liquid, no tax).
        2. Roth 401k balances (contributions withdrawn tax-free).
        3. Roth IRA basis (contributions withdrawn tax-free).

    Taxable sources (brokerage gains, pre-tax retirement) are drained earlier, before taxes are
    computed, by the tax unit — not here — so the service never has to decide tax treatment.
    """

    #: Default ordered list of tax-free draw sources (method names on this service).
    DEFAULT_PRIORITY = ("_pay_from_bank_accounts", "_pay_from_roth_401ks", "_pay_from_roth_iras")

    def __init__(self, person: "Person", priority=None):
        self.person = person
        self.priority = tuple(priority) if priority is not None else self.DEFAULT_PRIORITY

    def pay_bills_with_prioritization(self, total_amount: float) -> float:
        """Pay bills following the configured tax-free withdrawal order.

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
        """Pay from bank accounts first (most liquid)."""
        return self.person.deduct_from_bank_accounts(amount)

    def _pay_from_roth_401ks(self, amount: float) -> float:
        """Pay from Roth 401k balances (contributions are tax-free)."""
        return self.person.deduct_from_roth_401ks(amount)

    def _pay_from_roth_iras(self, amount: float) -> float:
        """Pay from Roth IRA contribution basis (tax-free)."""
        return self.person.deduct_from_roth_iras(amount)
