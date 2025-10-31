# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html
from typing import Optional, TYPE_CHECKING
from ..base_classes import Investment
from ..model import compound_interest
from ..config.config_manager import config

if TYPE_CHECKING:
    from ..people.person import Person
    from .child import Child


class Plan529(Investment):
    def __init__(self, owner: 'Person', beneficiary: Optional['Child'] = None,
                 balance: float = 0, state: str = 'NY',
                 growth_rate: float | None = None,
                 annual_contribution_limit: float | None = None,
                 lifetime_contribution_limit: float | None = None):
        """ Models a 529 education savings plan for a person

        Args:
            owner: The person who owns this 529 plan (typically a parent)
            beneficiary: The child beneficiary of this plan (optional)
            balance: Current balance in the plan
            state: The state sponsoring the plan
            growth_rate: Expected annual growth rate percentage. Uses configured default if None.
            annual_contribution_limit: Annual contribution limit. Uses configured default if None.
            lifetime_contribution_limit: Lifetime contribution limit. Uses configured default if None.
        """
        # Get defaults from config
        default_growth = config.financial.get('accounts.plan_529.default_growth_rate', 7.0)
        if growth_rate is None:
            growth_rate = default_growth

        super().__init__(owner, balance, growth_rate)
        self.beneficiary = beneficiary
        self.state = state

        # Get contribution limits from config or use provided values
        default_annual = config.financial.get(
            'accounts.plan_529.annual_contribution_limit', 18000
        )
        self.annual_contribution_limit = (
            annual_contribution_limit if annual_contribution_limit is not None
            else default_annual
        )
        default_lifetime = config.financial.get(
            'accounts.plan_529.lifetime_contribution_limit', 500000
        )
        self.lifetime_contribution_limit = (
            lifetime_contribution_limit if lifetime_contribution_limit is not None
            else default_lifetime
        )

        # Track contributions and earnings separately for tax purposes
        self.total_contributions = balance  # Assume initial balance is all contributions
        self.total_earnings = 0
        self.contributions_this_year = 0
        self.total_withdrawals = 0
        self.qualified_withdrawals = 0
        self.non_qualified_withdrawals = 0

        # Stats tracking
        self.stat_contributions_history = []
        self.stat_qualified_withdrawals_history = []
        self.stat_non_qualified_withdrawals_history = []
        self.stat_529_balance = 0

        # Register with the model registry
        self.model.registries.plan_529s.register(owner, self)

    def contribute(self, amount: float) -> float:
        """Make a contribution to the 529 plan

        Args:
            amount: Amount to contribute

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

        return actual_contribution

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
            self.balance -= actual_withdrawal
            self.total_withdrawals += actual_withdrawal
            self.qualified_withdrawals += actual_withdrawal

        return actual_withdrawal

    def withdraw_non_qualified(self, amount: float) -> tuple[float, float]:
        """Withdraw funds for non-qualified expenses (subject to penalty on earnings)

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

        # Calculate earnings portion of withdrawal
        # Earnings are proportional to total account composition
        if self.balance > 0:
            earnings_ratio = self.total_earnings / self.balance
        else:
            earnings_ratio = 0

        earnings_withdrawn = actual_withdrawal * earnings_ratio

        # Apply penalty to earnings portion
        penalty_rate = config.financial.get('accounts.plan_529.qualified_expense_penalty', 10.0) / 100
        penalty_amount = earnings_withdrawn * penalty_rate

        self.balance -= actual_withdrawal
        self.total_withdrawals += actual_withdrawal
        self.non_qualified_withdrawals += actual_withdrawal

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
        """Calculate investment growth for the period"""
        return compound_interest(self.balance, self.growth_rate, 1, 1)

    def reset_annual_contributions(self):
        """Reset annual contribution tracking (called at year end)"""
        self.contributions_this_year = 0

    def change_beneficiary(self, new_beneficiary: Optional['Child']):
        """Change the beneficiary of the 529 plan (allowed by IRS for family members)

        Args:
            new_beneficiary: New child beneficiary
        """
        self.beneficiary = new_beneficiary

    def _repr_html_(self):
        beneficiary_name = self.beneficiary.name if self.beneficiary else "No beneficiary"
        desc = '<ul>'
        desc += f'<li>Beneficiary: {html.escape(beneficiary_name)}</li>'
        desc += f'<li>Balance: ${self.balance:,.2f}</li>'
        desc += f'<li>Contributions: ${self.total_contributions:,.2f}</li>'
        desc += f'<li>Earnings: ${self.total_earnings:,.2f}</li>'
        desc += f'<li>State: {html.escape(self.state)}</li>'
        desc += f'<li>Growth Rate: {self.growth_rate}%</li>'
        desc += f'<li>Annual Contribution Limit: ${self.annual_contribution_limit:,.2f}</li>'
        desc += '</ul>'
        return desc

    def pre_step(self):
        """Pre-step phase: Apply growth and update earnings tracking"""
        # Calculate growth
        growth = self.calculate_growth()
        self.balance += growth
        self.total_earnings += growth
        self.stat_growth_history.append(growth)

    def step(self):
        """Step phase: Track statistics"""
        self.stat_529_balance = self.balance
        self.stat_contributions_history.append(self.contributions_this_year)
        self.stat_qualified_withdrawals_history.append(self.qualified_withdrawals)
        self.stat_non_qualified_withdrawals_history.append(self.non_qualified_withdrawals)

        # Track balance history (from FinancialAccount)
        self.stat_balance_history.append(self.balance)

    def post_step(self):
        """Post-step phase: Reset annual tracking"""
        self.reset_annual_contributions()
        # Reset yearly withdrawal tracking
        self.qualified_withdrawals = 0
        self.non_qualified_withdrawals = 0
