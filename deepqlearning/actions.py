# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Financial actions available to the RL agent.

Every :class:`ActionType` listed here is fully implemented and reachable: the environment
creates the accounts each action operates on, and :meth:`FinancialAction.can_execute` is the
single source of truth for legality. The invariant ``can_execute() => execute() succeeds`` is
covered by a property test, which keeps the action mask and the executor from drifting apart.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Type

from life_model.account.brokerage import BrokerageAccount
from life_model.account.hsa import HealthSavingsAccount
from life_model.account.job401k import Job401kAccount
from life_model.account.roth_IRA import RothIRA
from life_model.account.traditional_IRA import TraditionalIRA
from life_model.base_classes import FinancialAccount
from life_model.model import LifeModel
from life_model.people.person import Person


class ActionType(Enum):
    """Financial actions an RL agent can take.

    Only actions that are implemented end-to-end and reachable in the environment are listed.
    """

    # Contributions / transfers from the bank account into an investment or retirement account
    TRANSFER_BANK_TO_401K_PRETAX = "transfer_bank_to_401k_pretax"
    TRANSFER_BANK_TO_401K_ROTH = "transfer_bank_to_401k_roth"
    TRANSFER_BANK_TO_IRA_TRADITIONAL = "transfer_bank_to_ira_traditional"
    TRANSFER_BANK_TO_IRA_ROTH = "transfer_bank_to_ira_roth"
    TRANSFER_BANK_TO_BROKERAGE = "transfer_bank_to_brokerage"
    TRANSFER_BANK_TO_HSA = "transfer_bank_to_hsa"

    # Withdrawals back into the bank account (with early-withdrawal penalty where applicable)
    WITHDRAW_401K_PRETAX = "withdraw_401k_pretax"
    WITHDRAW_401K_ROTH = "withdraw_401k_roth"
    WITHDRAW_IRA_TRADITIONAL = "withdraw_ira_traditional"
    WITHDRAW_IRA_ROTH = "withdraw_ira_roth"
    WITHDRAW_BROKERAGE = "withdraw_brokerage"
    WITHDRAW_HSA = "withdraw_hsa"

    # Lifestyle decisions
    INCREASE_SPENDING = "increase_spending"
    DECREASE_SPENDING = "decrease_spending"
    RETIRE_EARLY = "retire_early"

    # No action
    NO_ACTION = "no_action"


# Transfer/withdrawal action types grouped by the account class they operate on. Used both to
# route execution and to discover the target account for a person.
_TRANSFER_TARGETS = {
    ActionType.TRANSFER_BANK_TO_401K_PRETAX: Job401kAccount,
    ActionType.TRANSFER_BANK_TO_401K_ROTH: Job401kAccount,
    ActionType.TRANSFER_BANK_TO_IRA_TRADITIONAL: TraditionalIRA,
    ActionType.TRANSFER_BANK_TO_IRA_ROTH: RothIRA,
    ActionType.TRANSFER_BANK_TO_BROKERAGE: BrokerageAccount,
    ActionType.TRANSFER_BANK_TO_HSA: HealthSavingsAccount,
}

_WITHDRAW_SOURCES = {
    ActionType.WITHDRAW_401K_PRETAX: Job401kAccount,
    ActionType.WITHDRAW_401K_ROTH: Job401kAccount,
    ActionType.WITHDRAW_IRA_TRADITIONAL: TraditionalIRA,
    ActionType.WITHDRAW_IRA_ROTH: RothIRA,
    ActionType.WITHDRAW_BROKERAGE: BrokerageAccount,
    ActionType.WITHDRAW_HSA: HealthSavingsAccount,
}

# Person-level withdrawal helper for each withdrawal action (Plan 18 D1). Every withdrawal goes
# through the model's real money path: the helper deposits into the bank and records the correct
# income-ledger entry (pre-tax 401k / traditional IRA distributions are ordinary income), so the
# tax unit actually taxes the withdrawal when it settles the year inside ``model.step()``.
_WITHDRAW_HELPERS = {
    ActionType.WITHDRAW_401K_PRETAX: Person.withdraw_from_pretax_401ks,
    ActionType.WITHDRAW_401K_ROTH: Person.withdraw_from_roth_401ks,
    ActionType.WITHDRAW_IRA_TRADITIONAL: Person.withdraw_from_traditional_iras,
    ActionType.WITHDRAW_IRA_ROTH: Person.withdraw_from_roth_iras,
    ActionType.WITHDRAW_BROKERAGE: Person.withdraw_from_brokerage_accounts,
    ActionType.WITHDRAW_HSA: Person.withdraw_from_hsas,
}

# Withdrawals from these account types incur a 10% early-withdrawal penalty before age 59.5.
_PENALIZED_WITHDRAWALS = frozenset(
    {
        ActionType.WITHDRAW_401K_PRETAX,
        ActionType.WITHDRAW_401K_ROTH,
        ActionType.WITHDRAW_IRA_TRADITIONAL,
        ActionType.WITHDRAW_IRA_ROTH,
        ActionType.WITHDRAW_HSA,
    }
)

TRANSFER_ACTIONS = frozenset(_TRANSFER_TARGETS)
WITHDRAWAL_ACTIONS = frozenset(_WITHDRAW_SOURCES)
SPENDING_ACTIONS = frozenset({ActionType.INCREASE_SPENDING, ActionType.DECREASE_SPENDING})

EARLY_WITHDRAWAL_AGE = 59.5
EARLY_WITHDRAWAL_PENALTY = 0.10


def owned_accounts(person: Person, account_cls: Type[FinancialAccount]) -> List[FinancialAccount]:
    """Return this person's accounts of ``account_cls``.

    Brokerage/IRA/HSA accounts are not registry-backed (they reference ``person`` directly), so
    they are discovered by scanning the model's agents. 401k accounts are reached through jobs.
    """
    if account_cls is Job401kAccount:
        return list(person.all_retirement_accounts)
    return [a for a in person.model.agents if isinstance(a, account_cls) and getattr(a, "person", None) is person]


def _first_account(person: Person, account_cls: Type[FinancialAccount]) -> Optional[FinancialAccount]:
    accounts = owned_accounts(person, account_cls)
    return accounts[0] if accounts else None


def _remaining_contribution_room(account: FinancialAccount) -> float:
    """Remaining annual contribution room for capped accounts (IRA/HSA); ``inf`` if uncapped."""
    if isinstance(account, (TraditionalIRA, RothIRA)):
        return max(0.0, account.contribution_limit - account.contributions_this_year)
    if isinstance(account, HealthSavingsAccount):
        return max(0.0, account.contribution_limit - account.annual_contributions)
    return float("inf")


@dataclass
class ActionResult:
    """Result of executing a financial action.

    There is deliberately no tax field here: taxable withdrawals are recorded on the person's
    income ledger and settled by the tax unit at year end, so taxes flow through the model's
    real money path rather than action-local bookkeeping (Plan 18 D1).
    """

    success: bool
    amount_transferred: float = 0.0
    fees_paid: float = 0.0
    message: str = ""


class FinancialAction(ABC):
    """Abstract base class for financial actions"""

    def __init__(self, action_type: ActionType, person: Person, amount: Optional[float] = None):
        self.action_type = action_type
        self.person = person
        self.amount = amount or 0.0

    @abstractmethod
    def can_execute(self) -> bool:
        """Check if the action can be executed given current state.

        Must be consistent with :meth:`execute`: whenever this returns ``True``, ``execute()``
        returns a successful :class:`ActionResult`.
        """

    @abstractmethod
    def execute(self) -> ActionResult:
        """Execute the action and return the result."""


class TransferAction(FinancialAction):
    """Move money from the bank account into a retirement/investment account."""

    def _target(self) -> Optional[FinancialAccount]:
        return _first_account(self.person, _TRANSFER_TARGETS[self.action_type])

    def _transferable(self) -> float:
        """Dollars that can actually be moved: min(requested, bank balance, contribution room)."""
        target = self._target()
        if target is None:
            return 0.0
        return min(self.amount, self.person.bank_account_balance, _remaining_contribution_room(target))

    def can_execute(self) -> bool:
        return self._transferable() > 0

    def execute(self) -> ActionResult:
        amount = self._transferable()
        if amount <= 0:
            return ActionResult(success=False, message="Transfer cannot be executed")

        target = self._target()
        self.person.deduct_from_bank_accounts(amount)

        if self.action_type == ActionType.TRANSFER_BANK_TO_401K_PRETAX:
            target.pretax_balance += amount
        elif self.action_type == ActionType.TRANSFER_BANK_TO_401K_ROTH:
            target.roth_balance += amount
        else:
            target.deposit(amount)

        return ActionResult(success=True, amount_transferred=amount)


class WithdrawalAction(FinancialAction):
    """Withdraw money from a retirement/investment account back into the bank account.

    Execution goes through the person-level helpers (``_WITHDRAW_HELPERS``), so taxable
    withdrawals create income-ledger entries and are taxed at year-end settlement inside
    ``model.step()`` — not instantly. The early-withdrawal penalty stays at the action level
    (deducted from the bank after the helper's deposit) until the core penalty backlog item
    lands.
    """

    def _available(self) -> float:
        accounts = owned_accounts(self.person, _WITHDRAW_SOURCES[self.action_type])
        if self.action_type == ActionType.WITHDRAW_401K_PRETAX:
            return sum(a.pretax_balance for a in accounts)
        if self.action_type == ActionType.WITHDRAW_401K_ROTH:
            return sum(a.roth_balance for a in accounts)
        return sum(a.balance for a in accounts)

    def can_execute(self) -> bool:
        return self.amount > 0 and self._available() > 0

    def execute(self) -> ActionResult:
        available = self._available()
        amount = min(self.amount, available)
        if amount <= 0:
            return ActionResult(success=False, message="Withdrawal cannot be executed")

        # The model's real money path: moves the money into the bank and records any taxable
        # income on the person's ledger for year-end settlement.
        withdrawn = _WITHDRAW_HELPERS[self.action_type](self.person, amount)

        penalized = self.action_type in _PENALIZED_WITHDRAWALS and self.person.age < EARLY_WITHDRAWAL_AGE
        penalty = withdrawn * EARLY_WITHDRAWAL_PENALTY if penalized else 0.0
        if penalty > 0:
            # The helper deposited the gross amount; pull the penalty back out of the bank.
            self.person.deduct_from_bank_accounts(penalty)

        return ActionResult(success=True, amount_transferred=withdrawn, fees_paid=penalty)


class SpendingAction(FinancialAction):
    """Adjust the person's base spending up or down."""

    def __init__(self, action_type: ActionType, person: Person, percentage_change: float):
        super().__init__(action_type, person)
        self.percentage_change = percentage_change

    def can_execute(self) -> bool:
        return True

    def execute(self) -> ActionResult:
        if self.action_type == ActionType.INCREASE_SPENDING:
            self.person.spending.base *= 1 + self.percentage_change
            return ActionResult(success=True, message=f"Increased spending by {self.percentage_change * 100:.1f}%")
        self.person.spending.base *= max(0.0, 1 - self.percentage_change)
        return ActionResult(success=True, message=f"Decreased spending by {self.percentage_change * 100:.1f}%")


class RetirementAction(FinancialAction):
    """Retire the person immediately by bringing the retirement age forward to the current age."""

    def can_execute(self) -> bool:
        return not self.person.is_retired

    def execute(self) -> ActionResult:
        if self.person.is_retired:
            return ActionResult(success=False, message="Already retired")
        self.person.retirement_age = self.person.age
        for job in self.person.jobs:
            job.retire()
        return ActionResult(success=True, message=f"Retired early at age {self.person.age}")


def build_action(
    action_type: ActionType, person: Person, amount: Optional[float] = None, percentage_change: float = 0.05
) -> Optional[FinancialAction]:
    """Construct the :class:`FinancialAction` for ``action_type`` (``None`` for NO_ACTION)."""
    if action_type in TRANSFER_ACTIONS:
        return TransferAction(action_type, person, amount if amount is not None else 1000.0)
    if action_type in WITHDRAWAL_ACTIONS:
        return WithdrawalAction(action_type, person, amount if amount is not None else 1000.0)
    if action_type in SPENDING_ACTIONS:
        return SpendingAction(action_type, person, percentage_change)
    if action_type == ActionType.RETIRE_EARLY:
        return RetirementAction(action_type, person)
    return None


class ActionExecutor:
    """Executes actions and reports whether they are legal."""

    def __init__(self, model: LifeModel):
        self.model = model

    def execute_action(
        self, person: Person, action_type: ActionType, amount: Optional[float] = None, **kwargs
    ) -> ActionResult:
        """Execute a financial action."""
        if action_type == ActionType.NO_ACTION:
            return ActionResult(success=True, message="No action taken")
        action = build_action(action_type, person, amount, kwargs.get("percentage_change", 0.05))
        if action is None:
            return ActionResult(success=False, message=f"Action {action_type} not implemented")
        return action.execute()

    def can_execute_action(
        self, person: Person, action_type: ActionType, amount: Optional[float] = None, **kwargs
    ) -> bool:
        """Check if an action can be executed."""
        if action_type == ActionType.NO_ACTION:
            return True
        action = build_action(action_type, person, amount, kwargs.get("percentage_change", 0.05))
        if action is None:
            return False
        return action.can_execute()
