# Copyright 2023 Google LLC
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import Union, TYPE_CHECKING
from ..model import LifeModelAgent
# It's important to handle potential circular imports with Person and Family
if TYPE_CHECKING:
    from ..person import Person
    from ..family import Family

class LifeInsurancePolicy(LifeModelAgent):
    def __init__(self, model, policy_holder: 'Person', beneficiary: Union['Person', 'Family'], coverage_amount: float, annual_premium: float):
        super().__init__(model)
        self.policy_holder = policy_holder
        self.beneficiary = beneficiary
        self.coverage_amount = coverage_amount
        self.annual_premium = annual_premium
        self.is_active = True # Policy is active by default, can be set to False if it lapses

    def pay_premium(self):
        '''Represents the payment of the annual premium.
        Actual deduction should be handled by the Person class.'''
        # In a more complex model, this could trigger checks or updates.
        pass

    def payout(self):
        '''Handles the payout to the beneficiary.'''
        if not self.is_active:
            self.model.event_log.add(f"Policy for {self.policy_holder.name} is not active. No payout.")
            return

        beneficiary_name = ""
        if hasattr(self.beneficiary, 'name'): # Person beneficiary
            beneficiary_name = self.beneficiary.name
            # Assuming Person has a method to receive funds or direct access to bank account
            if hasattr(self.beneficiary, 'deposit_into_bank_account'):
                self.beneficiary.deposit_into_bank_account(self.coverage_amount)
            else:
                # Fallback or error if no such method - this highlights a dependency.
                # For now, let's assume direct bank account deposit for simplicity if the method is missing.
                # This should be refined based on actual Person/Family class capabilities.
                # Attempting a generic deposit which might need specific implementation
                # on Person/Family or a shared bank account concept.
                # This part of the subtask might need adjustment based on how Person/Family handles finances.
                # For now, we'll log it.
                self.model.event_log.add(f"Beneficiary {beneficiary_name} received ${self.coverage_amount:,.2f}. Mechanism TBD.")


        elif hasattr(self.beneficiary, 'family_name'): # Family beneficiary
            beneficiary_name = self.beneficiary.family_name
            # How a Family receives money needs to be defined.
            # For now, log it. This might involve distributing to members or a family fund.
            self.model.event_log.add(f"Family {beneficiary_name} received ${self.coverage_amount:,.2f} as beneficiary. Distribution TBD.")


        self.model.event_log.add(
            f"Life insurance policy for {self.policy_holder.name} paid out ${self.coverage_amount:,.2f} to {beneficiary_name}."
        )
        self.is_active = False # Policy is no longer active after payout


class TermLifeInsurancePolicy(LifeInsurancePolicy):
    def __init__(self, model, policy_holder: 'Person', beneficiary: Union['Person', 'Family'], coverage_amount: float, annual_premium: float, term_length: int):
        super().__init__(model, policy_holder, beneficiary, coverage_amount, annual_premium)
        self.term_length = term_length
        self.current_year_in_term = 0

    def step(self):
        '''Advance the policy by one year.'''
        if not self.is_active:
            return

        self.current_year_in_term += 1
        if self.current_year_in_term > self.term_length:
            self.is_active = False
            self.model.event_log.add(
                f"Term life insurance policy for {self.policy_holder.name} has expired after {self.term_length} years."
            )

    def pay_premium(self):
        super().pay_premium()
        # Term policies don't typically build cash value from standard premium payments.


class WholeLifeInsurancePolicy(LifeInsurancePolicy):
    # For simplicity, using a fixed growth rate. In reality, this is variable.
    DEFAULT_CASH_VALUE_GROWTH_RATE = 0.02  # 2% annual growth

    def __init__(self, model, policy_holder: 'Person', beneficiary: Union['Person', 'Family'], coverage_amount: float, annual_premium: float, cash_value_growth_rate: float = DEFAULT_CASH_VALUE_GROWTH_RATE):
        super().__init__(model, policy_holder, beneficiary, coverage_amount, annual_premium)
        self.cash_value = 0.0
        self.cash_value_growth_rate = cash_value_growth_rate

    def pay_premium_and_grow_cash_value(self):
        '''Pays the premium and handles cash value accumulation.'''
        super().pay_premium()
        # A portion of the premium might go to cash value, or it grows independently.
        # This model assumes growth is separate from premium payment for simplicity.
        # A more complex model would detail how premiums contribute to cash value.
        self.cash_value += self.cash_value * self.cash_value_growth_rate
        # For simplicity, let's also add a small fixed portion of premium to cash value.
        # This is a placeholder for a more accurate calculation.
        self.cash_value += self.annual_premium * 0.1 # Example: 10% of premium contributes to cash value

    def withdraw_cash_value(self, amount: float) -> float:
        '''Withdraws from cash value. Reduces coverage if necessary.'''
        if amount <= 0:
            return 0.0
        
        withdrawn_amount = min(amount, self.cash_value)
        self.cash_value -= withdrawn_amount
        
        # Typically, withdrawing cash value can reduce the death benefit.
        # For simplicity, we'll directly reduce coverage_amount.
        # This is a simplification; actual policies have complex rules.
        self.coverage_amount -= withdrawn_amount 
        if self.coverage_amount < 0:
            self.coverage_amount = 0 # Coverage cannot be negative
        
        self.model.event_log.add(
            f"{self.policy_holder.name} withdrew ${withdrawn_amount:,.2f} from whole life policy. New cash value: ${self.cash_value:,.2f}. New coverage: ${self.coverage_amount:,.2f}."
        )
        return withdrawn_amount

    def step(self):
        '''Advance the policy by one year, growing cash value.'''
        if not self.is_active:
            return
        # Cash value growth is handled here annually, separate from premium payment effects.
        self.cash_value += self.cash_value * self.cash_value_growth_rate
