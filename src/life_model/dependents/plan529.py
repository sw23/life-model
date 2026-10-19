# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html
from typing import TYPE_CHECKING, Optional

from ..base_classes import Investment
from ..deprecated_names import deprecated_arguments
from ..ledger import FlowKind
from ..model import compound_interest
from ..tax.income import IncomeType

if TYPE_CHECKING:
    from ..people.person import Person
    from .child import Child


class Plan529(Investment):
    STATS_OWNED = frozenset({"stat_529_balance"})
    BALANCE_STAT = "stat_529_balance"

    @deprecated_arguments(
        {"growth_rate": "growth_pct", "annual_contribution_limit": "contribution_limit_annual"},
        positional=(
            "beneficiary",
            "balance",
            "state",
            "growth_pct",
            "contribution_limit_annual",
            "lifetime_contribution_limit",
        ),
    )
    def __init__(
        self,
        owner: "Person",
        *,
        beneficiary: Optional["Child"] = None,
        balance: float = 0,
        state: str = "NY",
        growth_pct: float | None = None,
        contribution_limit_annual: float | None = None,
        lifetime_contribution_limit: float | None = None,
        basis: float | None = None,
        allocation: "dict[str, float] | None" = None,
        expense_ratio_pct: float = 0.0,
    ):
        """Models a 529 education savings plan for a person

        Args:
            owner: The person who owns this 529 plan (typically a parent)
            beneficiary: The child beneficiary of this plan (optional)
            balance: Current balance in the plan
            state: The state sponsoring the plan
            growth_pct: Expected annual growth rate percentage (deprecated alias ``growth_rate``).
                Defers to the economy's equity return when None.
            contribution_limit_annual: Annual contribution limit (deprecated alias
                ``annual_contribution_limit``). Uses configured default if None.
            lifetime_contribution_limit: Lifetime contribution limit. Uses configured default if None.
            basis: Contributions in the balance (Plan 27 D1); the rest is earnings, taxed and penalized
                pro rata on a non-qualified withdrawal. The whole balance when None.
            allocation: Target allocation in percent by asset class (Plan 27 D5).
            expense_ratio_pct: Fund expense ratio (percent a year).
        """
        growth_rate = growth_pct
        annual_contribution_limit = contribution_limit_annual
        if basis is not None and not 0 <= basis <= balance + 1e-9:
            raise ValueError("basis must be between 0 and the balance")
        # Get defaults from config
        plan_529_config = owner.model.config.accounts.plan_529

        super().__init__(owner, balance, growth_rate, allocation=allocation, expense_ratio_pct=expense_ratio_pct)
        self.beneficiary = beneficiary
        self.state = state

        # Get contribution limits from config or use provided values
        self.annual_contribution_limit = (
            annual_contribution_limit
            if annual_contribution_limit is not None
            else plan_529_config.annual_contribution_limit
        )
        self.lifetime_contribution_limit = (
            lifetime_contribution_limit
            if lifetime_contribution_limit is not None
            else plan_529_config.lifetime_contribution_limit
        )

        # Track contributions and earnings separately for tax purposes
        # Without a basis the opening balance is assumed to be all contributions.
        self.total_contributions = balance if basis is None else basis
        self.total_earnings = 0 if basis is None else balance - basis
        self.contributions_this_year = 0
        self.total_withdrawals = 0
        self.qualified_withdrawals = 0
        self.non_qualified_withdrawals = 0

        # Stats tracking
        self.stat_contributions_history = []
        self.stat_qualified_withdrawals_history = []
        self.stat_non_qualified_withdrawals_history = []
        self.stat_penalties_paid = 0.0
        self.stat_529_balance = 0

        # Register with the model registry
        self.model.registries.plan_529s.register(owner, self)

    def contribute(
        self, amount: float, *, from_account=None, source: str = "contribution from outside the model"
    ) -> float:
        """Make a contribution to the 529 plan

        Args:
            amount: Amount to contribute
            from_account: Household account the caller already debited for it (keyword-only); when
                None the money is posted to the ledger as new money from ``source``.

        Returns:
            Amount actually contributed (limited by contribution limits)
        """
        if amount <= 0:
            return 0.0

        # Check annual limit
        available_annual = self.annual_contribution_limit - self.contributions_this_year
        # Check lifetime limit
        available_lifetime = self.lifetime_contribution_limit - self.total_contributions

        # Take the minimum of requested amount and both limits
        actual_contribution = min(amount, available_annual, available_lifetime)

        if actual_contribution > 0:
            self.balance += actual_contribution
            self.total_contributions += actual_contribution
            self.contributions_this_year += actual_contribution
            self.model.ledger.post(
                actual_contribution,
                FlowKind.CONTRIBUTION,
                from_account=from_account,
                to_account=self,
                source=None if from_account is not None else source,
                agent=self.person,
            )

        return actual_contribution

    def _reduce_basis_pro_rata(self, withdrawal_amount: float) -> float:
        """Reduce tracked contributions and earnings pro-rata for a withdrawal.

        Returns the earnings portion of the withdrawal (based on the pre-withdrawal
        composition). Keeping contributions/earnings in sync with the balance prevents the
        earnings ratio from drifting toward/past 1.0 after successive withdrawals.
        """
        if self.balance <= 0 or withdrawal_amount <= 0:
            return 0.0
        fraction = withdrawal_amount / self.balance
        earnings_withdrawn = self.total_earnings * fraction
        self.total_contributions -= self.total_contributions * fraction
        self.total_earnings -= earnings_withdrawn
        return earnings_withdrawn

    def withdraw_qualified(self, amount: float) -> float:
        """Withdraw funds for qualified education expenses (tax-free)

        Args:
            amount: Amount to withdraw

        Returns:
            Amount actually withdrawn
        """
        if amount <= 0:
            return 0.0

        actual_withdrawal = min(self.balance, amount)
        if actual_withdrawal > 0:
            # Reduce basis pro-rata before drawing down the balance.
            self._reduce_basis_pro_rata(actual_withdrawal)
            self.balance -= actual_withdrawal
            self.total_withdrawals += actual_withdrawal
            self.qualified_withdrawals += actual_withdrawal
            # Qualified withdrawals are tax-free; deposit the cash to the owner.
            self.person.receive_cash(
                actual_withdrawal,
                source="529 qualified withdrawal",
                kind=FlowKind.WITHDRAWAL,
                from_account=self,
                cause=self.model.ledger.current_cause or "qualified education expenses (tax-free)",
            )

        return actual_withdrawal

    def withdraw_non_qualified(self, amount: float) -> tuple[float, float]:
        """Withdraw funds for non-qualified expenses (subject to penalty on earnings)

        The earnings portion of the withdrawal is ordinary taxable income and is subject to a
        penalty; the full withdrawal is deposited into the owner's bank account and the penalty
        is debited from it.

        Args:
            amount: Amount to withdraw

        Returns:
            Tuple of (amount_withdrawn, penalty_amount)
        """
        if amount <= 0:
            return (0.0, 0.0)

        actual_withdrawal = min(self.balance, amount)
        if actual_withdrawal == 0:
            return (0.0, 0.0)

        # Earnings portion is proportional to the account's pre-withdrawal composition.
        earnings_withdrawn = self._reduce_basis_pro_rata(actual_withdrawal)

        # Apply penalty to earnings portion
        penalty_rate = self.model.config.accounts.plan_529.qualified_expense_penalty / 100
        penalty_amount = earnings_withdrawn * penalty_rate

        self.balance -= actual_withdrawal
        self.total_withdrawals += actual_withdrawal
        self.non_qualified_withdrawals += actual_withdrawal

        # Route the cash and taxes: full withdrawal to the owner's bank, the earnings portion is
        # ordinary income, and the penalty is debited from the owner.
        self.person.receive_cash(
            actual_withdrawal, source="529 non-qualified withdrawal", kind=FlowKind.WITHDRAWAL, from_account=self
        )
        if earnings_withdrawn > 0:
            self.person.income.add(IncomeType.ORDINARY, earnings_withdrawn, source="529_nonqualified")
        if penalty_amount > 0:
            self.person.deduct_from_bank_accounts(
                penalty_amount, kind=FlowKind.PENALTY, sink="IRS", cause="529 non-qualified withdrawal penalty"
            )
            self.stat_penalties_paid += penalty_amount

        return (actual_withdrawal, penalty_amount)

    def get_balance(self) -> float:
        """Get current account balance"""
        return self.balance

    def deposit(self, amount: float) -> bool:
        """Deposit amount into account via contribution. Returns success status"""
        contribution = self.contribute(amount)
        return contribution > 0

    def withdraw(self, amount: float, qualified: bool = True) -> float | tuple[float, float]:
        """Withdraw amount from account. Returns actual amount withdrawn (and penalty if non-qualified)

        Args:
            amount: Amount to withdraw
            qualified: Whether this is a qualified educational expense withdrawal (default: True)

        Returns:
            If qualified=True: float (amount withdrawn)
            If qualified=False: tuple of (amount_withdrawn, penalty_amount)
        """
        if qualified:
            return self.withdraw_qualified(amount)
        else:
            return self.withdraw_non_qualified(amount)

    def calculate_growth(self) -> float:
        """A year of growth on the current balance at the annual rate (display; growth is monthly)."""
        return compound_interest(self.balance, self.growth_rate, 1, 1)

    def reset_annual_contributions(self):
        """Reset annual contribution tracking (called at year end)"""
        self.contributions_this_year = 0

    def change_beneficiary(self, new_beneficiary: Optional["Child"]):
        """Change the beneficiary of the 529 plan (allowed by IRS for family members)

        Args:
            new_beneficiary: New child beneficiary
        """
        self.beneficiary = new_beneficiary

    def _repr_html_(self):
        beneficiary_name = self.beneficiary.name if self.beneficiary else "No beneficiary"
        desc = "<ul>"
        desc += f"<li>Beneficiary: {html.escape(beneficiary_name)}</li>"
        desc += f"<li>Balance: ${self.balance:,.2f}</li>"
        desc += f"<li>Contributions: ${self.total_contributions:,.2f}</li>"
        desc += f"<li>Earnings: ${self.total_earnings:,.2f}</li>"
        desc += f"<li>State: {html.escape(self.state)}</li>"
        desc += f"<li>Growth Rate: {self.growth_rate}%</li>"
        desc += f"<li>Annual Contribution Limit: ${self.annual_contribution_limit:,.2f}</li>"
        desc += "</ul>"
        return desc

    def step(self):
        """Apply the month's growth and update earnings tracking."""
        growth = self.apply_growth()
        self.total_earnings += growth

    def on_year_end(self):
        """Track the year's statistics, then reset the annual tracking."""
        self.stat_contributions_history.append(self.contributions_this_year)
        self.stat_qualified_withdrawals_history.append(self.qualified_withdrawals)
        self.stat_non_qualified_withdrawals_history.append(self.non_qualified_withdrawals)
        super().on_year_end()  # balance history
        self.reset_annual_contributions()
        # Reset yearly withdrawal tracking
        self.qualified_withdrawals = 0
        self.non_qualified_withdrawals = 0
