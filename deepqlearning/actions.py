# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from enum import Enum
from dataclasses import dataclass

from life_model.model import LifeModel
from life_model.people.person import Person


class ActionType(Enum):
    """Types of financial actions an RL agent can take"""

    # Account transfers
    TRANSFER_BANK_TO_401K_PRETAX = "transfer_bank_to_401k_pretax"
    TRANSFER_BANK_TO_401K_ROTH = "transfer_bank_to_401k_roth"
    TRANSFER_BANK_TO_IRA_TRADITIONAL = "transfer_bank_to_ira_traditional"
    TRANSFER_BANK_TO_IRA_ROTH = "transfer_bank_to_ira_roth"
    TRANSFER_BANK_TO_BROKERAGE = "transfer_bank_to_brokerage"
    TRANSFER_BANK_TO_HSA = "transfer_bank_to_hsa"

    # Withdrawals (with penalties if applicable)
    WITHDRAW_401K_PRETAX = "withdraw_401k_pretax"
    WITHDRAW_401K_ROTH = "withdraw_401k_roth"
    WITHDRAW_IRA_TRADITIONAL = "withdraw_ira_traditional"
    WITHDRAW_IRA_ROTH = "withdraw_ira_roth"
    WITHDRAW_BROKERAGE = "withdraw_brokerage"
    WITHDRAW_HSA = "withdraw_hsa"

    # Account conversions
    CONVERT_401K_PRETAX_TO_ROTH = "convert_401k_pretax_to_roth"
    CONVERT_IRA_TRADITIONAL_TO_ROTH = "convert_ira_traditional_to_roth"

    # Debt management
    PAY_EXTRA_MORTGAGE = "pay_extra_mortgage"
    PAY_EXTRA_CREDIT_CARD = "pay_extra_credit_card"
    PAY_EXTRA_STUDENT_LOAN = "pay_extra_student_loan"
    PAY_EXTRA_CAR_LOAN = "pay_extra_car_loan"

    # Lifestyle decisions
    INCREASE_SPENDING = "increase_spending"
    DECREASE_SPENDING = "decrease_spending"
    RETIRE_EARLY = "retire_early"

    # Housing decisions
    BUY_HOUSE = "buy_house"
    SELL_HOUSE = "sell_house"
    REFINANCE_MORTGAGE = "refinance_mortgage"

    # Investment decisions
    CHANGE_401K_ALLOCATION = "change_401k_allocation"
    CHANGE_INVESTMENT_STRATEGY = "change_investment_strategy"

    # Insurance decisions
    BUY_LIFE_INSURANCE = "buy_life_insurance"
    CANCEL_LIFE_INSURANCE = "cancel_life_insurance"

    # No action
    NO_ACTION = "no_action"


@dataclass
class ActionResult:
    """Result of executing a financial action"""
    success: bool
    amount_transferred: float = 0.0
    fees_paid: float = 0.0
    tax_implications: float = 0.0
    message: str = ""


class FinancialAction(ABC):
    """Abstract base class for financial actions"""

    def __init__(self, action_type: ActionType, person: Person, amount: Optional[float] = None):
        self.action_type = action_type
        self.person = person
        self.amount = amount or 0.0

    @abstractmethod
    def can_execute(self) -> bool:
        """Check if action can be executed given current state"""
        pass

    @abstractmethod
    def execute(self) -> ActionResult:
        """Execute the action and return result"""
        pass

    @abstractmethod
    def get_estimated_outcome(self) -> Dict[str, float]:
        """Get estimated financial impact without executing"""
        pass


class TransferAction(FinancialAction):
    """Action for transferring money between accounts"""

    def __init__(self, action_type: ActionType, person: Person, amount: float):
        super().__init__(action_type, person, amount)

    def can_execute(self) -> bool:
        """Check if transfer is possible"""
        if self.action_type == ActionType.TRANSFER_BANK_TO_401K_PRETAX:
            return (self.person.bank_account_balance >= self.amount and
                    len(self.person.all_retirement_accounts) > 0)
        elif self.action_type == ActionType.TRANSFER_BANK_TO_401K_ROTH:
            return (self.person.bank_account_balance >= self.amount and
                    len(self.person.all_retirement_accounts) > 0)
        elif self.action_type == ActionType.TRANSFER_BANK_TO_BROKERAGE:
            return self.person.bank_account_balance >= self.amount
        # Add more conditions for other transfer types
        return False

    def execute(self) -> ActionResult:
        """Execute the transfer"""
        if not self.can_execute():
            return ActionResult(success=False, message="Transfer cannot be executed")

        try:
            if self.action_type == ActionType.TRANSFER_BANK_TO_401K_PRETAX:
                self.person.deduct_from_bank_accounts(self.amount)
                # Add to 401k pretax balance
                retirement_account = self.person.all_retirement_accounts[0]
                retirement_account.pretax_balance += self.amount
                return ActionResult(success=True, amount_transferred=self.amount)

            elif self.action_type == ActionType.TRANSFER_BANK_TO_401K_ROTH:
                self.person.deduct_from_bank_accounts(self.amount)
                # Add to 401k roth balance
                retirement_account = self.person.all_retirement_accounts[0]
                retirement_account.roth_balance += self.amount
                return ActionResult(success=True, amount_transferred=self.amount)

            # Add more transfer implementations
            return ActionResult(success=False, message="Transfer type not implemented")

        except Exception as e:
            return ActionResult(success=False, message=f"Transfer failed: {str(e)}")

    def get_estimated_outcome(self) -> Dict[str, float]:
        """Estimate outcome of transfer"""
        return {
            "amount_transferred": self.amount,
            "bank_balance_change": -self.amount,
            "retirement_balance_change": self.amount
        }


class WithdrawalAction(FinancialAction):
    """Action for withdrawing money from retirement/investment accounts"""

    def can_execute(self) -> bool:
        """Check if withdrawal is possible"""
        if self.action_type == ActionType.WITHDRAW_401K_PRETAX:
            return any(acc.pretax_balance >= self.amount for acc in self.person.all_retirement_accounts)
        elif self.action_type == ActionType.WITHDRAW_401K_ROTH:
            return any(acc.roth_balance >= self.amount for acc in self.person.all_retirement_accounts)
        # Add more conditions
        return False

    def execute(self) -> ActionResult:
        """Execute withdrawal with potential penalties and taxes"""
        if not self.can_execute():
            return ActionResult(success=False, message="Withdrawal cannot be executed")

        try:
            if self.action_type == ActionType.WITHDRAW_401K_PRETAX:
                # Calculate penalties for early withdrawal
                penalty = 0.0
                if self.person.age < 59.5:  # Early withdrawal penalty
                    penalty = self.amount * 0.10

                # Execute withdrawal
                withdrawn = self.person.deduct_from_pretax_401ks(self.amount)
                self.person.deposit_into_bank_account(withdrawn - penalty)

                # Tax implications (will be handled in tax calculation)
                tax_implications = withdrawn  # Will be taxed as income

                return ActionResult(
                    success=True,
                    amount_transferred=withdrawn,
                    fees_paid=penalty,
                    tax_implications=tax_implications
                )

            # Add more withdrawal implementations
            return ActionResult(success=False, message="Withdrawal type not implemented")

        except Exception as e:
            return ActionResult(success=False, message=f"Withdrawal failed: {str(e)}")

    def get_estimated_outcome(self) -> Dict[str, float]:
        """Estimate outcome of withdrawal"""
        penalty = 0.0
        if self.person.age < 59.5:
            penalty = self.amount * 0.10

        return {
            "amount_withdrawn": self.amount,
            "penalty_paid": penalty,
            "net_to_bank": self.amount - penalty,
            "tax_implications": self.amount
        }


class SpendingAction(FinancialAction):
    """Action for adjusting spending patterns"""

    def __init__(self, action_type: ActionType, person: Person, percentage_change: float):
        super().__init__(action_type, person)
        self.percentage_change = percentage_change  # e.g., 0.1 for 10% increase

    def can_execute(self) -> bool:
        """Spending adjustments are generally always possible"""
        return True

    def execute(self) -> ActionResult:
        """Execute spending change"""
        try:
            if self.action_type == ActionType.INCREASE_SPENDING:
                multiplier = 1 + self.percentage_change
                self.person.spending.base *= multiplier
                return ActionResult(
                    success=True,
                    message=f"Increased spending by {self.percentage_change*100:.1f}%"
                )

            elif self.action_type == ActionType.DECREASE_SPENDING:
                multiplier = 1 - self.percentage_change
                self.person.spending.base *= multiplier
                return ActionResult(
                    success=True,
                    message=f"Decreased spending by {self.percentage_change*100:.1f}%"
                )

            return ActionResult(success=False, message="Spending action not implemented")

        except Exception as e:
            return ActionResult(success=False, message=f"Spending change failed: {str(e)}")

    def get_estimated_outcome(self) -> Dict[str, float]:
        """Estimate outcome of spending change"""
        current_spending = self.person.spending.base
        if self.action_type == ActionType.INCREASE_SPENDING:
            new_spending = current_spending * (1 + self.percentage_change)
        else:
            new_spending = current_spending * (1 - self.percentage_change)

        return {
            "spending_change": new_spending - current_spending,
            "new_annual_spending": new_spending
        }


class ActionSpace:
    """Defines the action space for reinforcement learning"""

    def __init__(self, person: Person):
        self.person = person
        self.actions = self._generate_action_list()

    def _generate_action_list(self) -> List[ActionType]:
        """Generate list of available actions based on person's accounts"""
        actions = [ActionType.NO_ACTION]

        # Transfer actions (if person has bank account)
        if len(self.person.bank_accounts) > 0:
            actions.extend([
                ActionType.TRANSFER_BANK_TO_401K_PRETAX,
                ActionType.TRANSFER_BANK_TO_401K_ROTH,
                ActionType.TRANSFER_BANK_TO_IRA_TRADITIONAL,
                ActionType.TRANSFER_BANK_TO_IRA_ROTH,
                ActionType.TRANSFER_BANK_TO_BROKERAGE,
                ActionType.TRANSFER_BANK_TO_HSA
            ])

        # Withdrawal actions (if person has retirement accounts)
        if len(self.person.all_retirement_accounts) > 0:
            actions.extend([
                ActionType.WITHDRAW_401K_PRETAX,
                ActionType.WITHDRAW_401K_ROTH,
                ActionType.WITHDRAW_IRA_TRADITIONAL,
                ActionType.WITHDRAW_IRA_ROTH
            ])

        # Spending actions (always available)
        actions.extend([
            ActionType.INCREASE_SPENDING,
            ActionType.DECREASE_SPENDING
        ])

        # Housing actions (if person has homes)
        if len(self.person.homes) > 0:
            actions.extend([
                ActionType.PAY_EXTRA_MORTGAGE,
                ActionType.SELL_HOUSE,
                ActionType.REFINANCE_MORTGAGE
            ])
        else:
            actions.append(ActionType.BUY_HOUSE)

        # Retirement action
        if not self.person.is_retired:
            actions.append(ActionType.RETIRE_EARLY)

        return actions

    def get_action_count(self) -> int:
        """Get number of possible actions"""
        return len(self.actions)

    def get_action_by_index(self, index: int) -> ActionType:
        """Get action type by index"""
        return self.actions[index]

    def get_action_index(self, action_type: ActionType) -> int:
        """Get index of action type"""
        return self.actions.index(action_type)


class ActionExecutor:
    """Executes actions and returns results"""

    def __init__(self, model: LifeModel):
        self.model = model

    def execute_action(self, person: Person, action_type: ActionType,
                       amount: Optional[float] = None,
                       **kwargs) -> ActionResult:
        """Execute a financial action"""

        # Create appropriate action instance
        if action_type in [ActionType.TRANSFER_BANK_TO_401K_PRETAX,
                           ActionType.TRANSFER_BANK_TO_401K_ROTH,
                           ActionType.TRANSFER_BANK_TO_BROKERAGE]:
            action = TransferAction(action_type, person, amount or 1000.0)

        elif action_type in [ActionType.WITHDRAW_401K_PRETAX,
                             ActionType.WITHDRAW_401K_ROTH]:
            action = WithdrawalAction(action_type, person, amount or 1000.0)

        elif action_type in [ActionType.INCREASE_SPENDING,
                             ActionType.DECREASE_SPENDING]:
            percentage = kwargs.get('percentage_change', 0.05)  # Default 5%
            action = SpendingAction(action_type, person, percentage)

        elif action_type == ActionType.NO_ACTION:
            return ActionResult(success=True, message="No action taken")

        else:
            return ActionResult(success=False, message=f"Action {action_type} not implemented")

        # Execute the action
        return action.execute()

    def can_execute_action(self, person: Person, action_type: ActionType,
                           amount: Optional[float] = None, **kwargs) -> bool:
        """Check if an action can be executed"""

        # Create appropriate action instance for checking
        if action_type in [ActionType.TRANSFER_BANK_TO_401K_PRETAX,
                           ActionType.TRANSFER_BANK_TO_401K_ROTH,
                           ActionType.TRANSFER_BANK_TO_BROKERAGE]:
            action = TransferAction(action_type, person, amount or 1000.0)

        elif action_type in [ActionType.WITHDRAW_401K_PRETAX,
                             ActionType.WITHDRAW_401K_ROTH]:
            action = WithdrawalAction(action_type, person, amount or 1000.0)

        elif action_type in [ActionType.INCREASE_SPENDING,
                             ActionType.DECREASE_SPENDING]:
            percentage = kwargs.get('percentage_change', 0.05)
            action = SpendingAction(action_type, person, percentage)

        elif action_type == ActionType.NO_ACTION:
            return True

        else:
            return False

        return action.can_execute()
