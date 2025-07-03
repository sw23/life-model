# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import gymnasium as gym
from gymnasium import spaces
import numpy as np
from typing import Dict, List, Optional, Tuple, Any

from life_model.model import LifeModel
from life_model.people.family import Family
from life_model.people.person import Person, Spending, GenderAtBirth
from life_model.people.mortality import get_random_mortality, get_chance_of_mortality
from life_model.account.bank import BankAccount
from life_model.work.job import Job, Salary
from actions import ActionSpace, ActionExecutor, ActionType, ActionResult


class FinancialLifeEnv(gym.Env):
    """
    OpenAI Gym environment for financial life simulation.

    This environment allows an RL agent to make financial decisions for a person
    over their lifetime, with the goal of optimizing financial outcomes.
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__()

        # Default configuration
        self.config = {
            'start_year': 2025,
            'person_start_age': 25,
            'person_retirement_age': 65,
            'person_max_age': 119,
            'person_gender': GenderAtBirth.MALE,  # Default gender for mortality calculations
            'initial_salary': 50000,
            'initial_bank_balance': 10000,
            'initial_spending': 30000,
            'max_action_amount': 50000,  # Max amount for transfer/withdrawal actions
            'reward_weights': {
                'net_worth': 1.0,
                'spending_satisfaction': 0.3,
                'early_retirement_bonus': 2.0,
                'bankruptcy_penalty': -10.0,
                'death_with_money_bonus': 1.0,
                'unexpected_death_penalty': -5.0  # Penalty for dying unexpectedly early
            }
        }

        if config:
            self.config.update(config)

        # Calculate max steps before reset
        self.max_steps = self.config['person_max_age'] - self.config['person_start_age']
        self.current_step = 0

        # Initialize the simulation
        self.reset()

        # Define action space
        # We'll use a discrete action space with different action types
        # and a continuous parameter for amounts/percentages
        self.action_space = spaces.Dict({
            'action_type': spaces.Discrete(len(ActionType)),
            'amount_percentage': spaces.Box(low=0.0, high=1.0, shape=(1,), dtype=np.float32)
        })

        # Define observation space
        # This includes financial state, personal state, and market conditions
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(self._get_state_size(),),
            dtype=np.float32
        )

    def _get_state_size(self) -> int:
        """Calculate the size of the state vector"""
        # Person state: age, years_to_retirement, is_retired, mortality_probability
        person_state_size = 4

        # Financial state: bank_balance, 401k_pretax, 401k_roth, debt, annual_income, annual_spending
        financial_state_size = 6

        # Ratios and derived metrics: savings_rate, debt_to_income, net_worth, etc.
        derived_metrics_size = 8

        # Market/economic state: year, economic_cycle_phase
        market_state_size = 2

        return person_state_size + financial_state_size + derived_metrics_size + market_state_size

    def reset(self) -> np.ndarray:
        """Reset the environment to initial state"""

        # Create new model instance
        self.model = LifeModel(start_year=self.config['start_year'])
        self.family = Family(self.model)

        # Create person
        self.person = Person(
            family=self.family,
            name='RL_Agent',
            age=self.config['person_start_age'],
            retirement_age=self.config['person_retirement_age'],
            spending=Spending(
                model=self.model,
                base=self.config['initial_spending'],
                yearly_increase=2  # 2% inflation
            )
        )

        # Store gender for mortality calculations
        self.person_gender = self.config['person_gender']

        # Track mortality state
        self.died_from_natural_causes = False

        # Create bank account
        self.bank_account = BankAccount(
            owner=self.person,
            company='Bank',
            type='Checking',
            balance=self.config['initial_bank_balance'],
            interest_rate=0.5
        )

        # Create job
        self.job = Job(
            owner=self.person,
            company='Company',
            role='Employee',
            salary=Salary(
                model=self.model,
                base=self.config['initial_salary'],
                yearly_increase=3,  # 3% annual raises
                yearly_bonus=1
            )
        )

        # Initialize action space and executor
        self.action_space_obj = ActionSpace(self.person)
        self.action_executor = ActionExecutor(self.model)

        # Reset step counter
        self.current_step = 0

        # Set initial model end year
        self.model.end_year = self.model.start_year + self.max_steps

        # Track initial state
        self.initial_net_worth = self._calculate_net_worth()
        self.total_lifetime_spending = 0
        self.years_retired_early = 0

        return self._get_observation()

    def step(self, action: Dict[str, Any]) -> Tuple[np.ndarray, float, bool, Dict]:
        """
        Execute one step in the environment.

        Args:
            action: Dictionary with 'action_type' (int) and 'amount_percentage' (float)

        Returns:
            observation, reward, done, info
        """

        # Parse action
        action_type_idx = action['action_type']
        amount_percentage = action['amount_percentage'][0]

        # Convert action index to ActionType
        action_type = list(ActionType)[action_type_idx]

        # Calculate action amount based on percentage and financial state
        action_amount = self._calculate_action_amount(action_type, amount_percentage)

        # Execute the action
        action_result = self.action_executor.execute_action(
            self.person,
            action_type,
            amount=action_amount,
            percentage_change=amount_percentage * 0.2  # Max 20% spending change
        )

        # Step the simulation forward one year
        self.model.step()
        self.current_step += 1

        # Check for mortality
        if not self.died_from_natural_causes:
            self.died_from_natural_causes = get_random_mortality(self.person.age, self.person_gender)

        # Calculate reward
        reward = self._calculate_reward(action_result)

        # Check if episode is done
        done = self._is_done()

        # Gather info
        info = {
            'action_result': action_result,
            'net_worth': self._calculate_net_worth(),
            'age': self.person.age,
            'is_retired': self.person.age >= self.person.retirement_age,
            'bank_balance': self.person.bank_account_balance,
            'annual_spending': self.person.spending.get_yearly_spending(),
            'action_type': action_type.value,
            'action_amount': action_amount,
            'died_from_natural_causes': self.died_from_natural_causes,
            'mortality_probability': get_chance_of_mortality(self.person.age, self.person_gender)
        }

        return self._get_observation(), reward, done, info

    def _calculate_action_amount(self, action_type: ActionType, percentage: float) -> float:
        """Calculate the actual dollar amount for an action based on percentage"""

        if action_type in [ActionType.TRANSFER_BANK_TO_401K_PRETAX,
                           ActionType.TRANSFER_BANK_TO_401K_ROTH,
                           ActionType.TRANSFER_BANK_TO_BROKERAGE]:
            # Percentage of bank balance
            return min(self.person.bank_account_balance * percentage, self.config['max_action_amount'])

        elif action_type in [ActionType.WITHDRAW_401K_PRETAX, ActionType.WITHDRAW_401K_ROTH]:
            # Percentage of retirement balance
            retirement_balance = sum(acc.balance for acc in self.person.all_retirement_accounts)
            return min(retirement_balance * percentage, self.config['max_action_amount'])

        elif action_type in [ActionType.PAY_EXTRA_MORTGAGE]:
            # Percentage of bank balance for extra payments
            return min(self.person.bank_account_balance * percentage, self.config['max_action_amount'])

        else:
            # For other actions, use a base amount
            return min(percentage * self.config['max_action_amount'], self.config['max_action_amount'])

    def _get_observation(self) -> np.ndarray:
        """Get current state observation"""

        # Person state
        mortality_prob = get_chance_of_mortality(self.person.age, self.person_gender)
        person_state = [
            self.person.age / 100.0,  # Normalized age
            max(0, self.person.retirement_age - self.person.age) / 50.0,  # Years to retirement
            1.0 if self.person.age >= self.person.retirement_age else 0.0,  # Is retired
            mortality_prob  # Current year mortality probability
        ]

        # Financial state (normalized)
        bank_balance = self.person.bank_account_balance
        retirement_balance = sum(acc.balance for acc in self.person.all_retirement_accounts)
        pretax_401k = sum(acc.pretax_balance for acc in self.person.all_retirement_accounts)
        roth_401k = sum(acc.roth_balance for acc in self.person.all_retirement_accounts)
        debt = self.person.debt
        annual_income = sum(job.salary.base for job in self.person.jobs)
        annual_spending = self.person.spending.get_yearly_spending()

        # Normalize financial values by a reasonable scale (e.g., $1M)
        scale = 1000000.0
        financial_state = [
            bank_balance / scale,
            pretax_401k / scale,
            roth_401k / scale,
            debt / scale,
            annual_income / scale,
            annual_spending / scale
        ]

        # Derived metrics
        net_worth = self._calculate_net_worth()
        savings_rate = max(0, (annual_income - annual_spending) / max(annual_income, 1))
        debt_to_income = debt / max(annual_income, 1)
        retirement_readiness = retirement_balance / max(annual_spending * 25, 1)  # 4% rule
        emergency_fund_months = bank_balance / max(annual_spending / 12, 1)

        derived_metrics = [
            net_worth / scale,
            savings_rate,
            debt_to_income,
            retirement_readiness,
            emergency_fund_months / 12.0,  # Normalize to years
            annual_income / max(annual_spending, 1),  # Income to spending ratio
            (self.person.age - self.config['person_start_age']) / self.max_steps,  # Life progress
            min(max(bank_balance / 50000, 0), 2.0)  # Emergency fund adequacy (0-2 scale)
        ]

        # Market/economic state
        market_state = [
            (self.model.year - self.config['start_year']) / self.max_steps,  # Time progress
            np.sin(2 * np.pi * (self.model.year - self.config['start_year']) / 10) * 0.1  # Economic cycle
        ]

        # Combine all states
        observation = np.array(person_state + financial_state + derived_metrics + market_state, dtype=np.float32)

        return observation

    def _calculate_net_worth(self) -> float:
        """Calculate person's net worth"""
        assets = (self.person.bank_account_balance +
                  sum(acc.balance for acc in self.person.all_retirement_accounts) +
                  sum(home.value for home in self.person.homes))
        liabilities = (self.person.debt +
                       sum(home.mortgage.principal for home in self.person.homes if home.mortgage))
        return assets - liabilities

    def _calculate_reward(self, action_result: ActionResult) -> float:
        """Calculate reward for current step"""

        reward = 0.0
        weights = self.config['reward_weights']

        # Net worth growth reward
        current_net_worth = self._calculate_net_worth()
        net_worth_growth = current_net_worth - getattr(self, 'previous_net_worth', self.initial_net_worth)
        self.previous_net_worth = current_net_worth
        reward += weights['net_worth'] * (net_worth_growth / 100000.0)  # Normalized by $100k

        # Spending satisfaction (diminishing returns on spending)
        annual_spending = self.person.spending.get_yearly_spending()
        self.total_lifetime_spending += annual_spending
        spending_satisfaction = np.log(max(annual_spending, 1000)) / 10.0
        reward += weights['spending_satisfaction'] * spending_satisfaction

        # Early retirement bonus - can retire with 4% rule
        if (self.person.age < self.person.retirement_age and current_net_worth > annual_spending * 25):
            self.years_retired_early += 1
            reward += weights['early_retirement_bonus']

        # Bankruptcy penalty
        if current_net_worth < -10000:
            reward += weights['bankruptcy_penalty']

        # Death with money bonus
        if (self.current_step >= self.max_steps - 1 or self.died_from_natural_causes) and current_net_worth > 0:
            reward += weights['death_with_money_bonus'] * (current_net_worth / 1000000.0)

        # Unexpected death penalty - penalize dying much earlier than expected lifespan
        if self.died_from_natural_causes:
            # Calculate expected remaining years based on life tables
            expected_years_remaining = 0
            for future_age in range(self.person.age, min(self.config['person_max_age'], 100)):
                survival_prob = 1.0 - get_chance_of_mortality(future_age, self.person_gender)
                expected_years_remaining += survival_prob

            # If dying significantly earlier than expected, apply penalty
            if expected_years_remaining > 20:  # More than 20 years expected remaining
                penalty_factor = min(expected_years_remaining / 20.0, 2.0)  # Cap at 2x penalty
                reward += weights['unexpected_death_penalty'] * penalty_factor

        # Action execution penalty for failed actions
        if not action_result.success:
            reward -= 0.1

        # Fee penalty
        reward -= action_result.fees_paid / 10000.0  # Penalty for fees

        return reward

    def _is_done(self) -> bool:
        """Check if episode is finished"""
        return (self.current_step >= self.max_steps or
                self.person.age >= self.config['person_max_age'] or
                self._calculate_net_worth() < -100000 or  # Bankruptcy threshold
                self.died_from_natural_causes)  # Natural mortality

    def render(self, mode='human') -> Optional[str]:
        """Render the environment"""
        if mode == 'human':
            net_worth = self._calculate_net_worth()
            mortality_prob = get_chance_of_mortality(self.person.age, self.person_gender)
            status = "DECEASED" if self.died_from_natural_causes else "ALIVE"
            print(f"Year: {self.model.year}, Age: {self.person.age}, Status: {status}, "
                  f"Mortality Risk: {mortality_prob:.1%}, "
                  f"Net Worth: ${net_worth:,.0f}, "
                  f"Bank: ${self.person.bank_account_balance:,.0f}, "
                  f"Retirement: ${sum(acc.balance for acc in self.person.all_retirement_accounts):,.0f}")

        return None

    def get_legal_actions(self) -> List[int]:
        """Get list of legal action indices for current state"""
        legal_actions = []

        for i, action_type in enumerate(ActionType):
            if self.action_executor.can_execute_action(self.person, action_type, amount=1000.0):
                legal_actions.append(i)

        # NO_ACTION is always legal
        if list(ActionType).index(ActionType.NO_ACTION) not in legal_actions:
            legal_actions.append(list(ActionType).index(ActionType.NO_ACTION))

        return legal_actions


class FinancialLifeEnvGenerator:
    """Generator for creating different environment configurations"""

    @staticmethod
    def create_basic_env() -> FinancialLifeEnv:
        """Create basic environment with default settings"""
        return FinancialLifeEnv()

    @staticmethod
    def create_high_earner_env() -> FinancialLifeEnv:
        """Create environment for high earner scenario"""
        config = {
            'initial_salary': 120000,
            'initial_bank_balance': 50000,
            'initial_spending': 60000,
            'person_start_age': 30,
            'person_gender': GenderAtBirth.MALE
        }
        return FinancialLifeEnv(config)

    @staticmethod
    def create_low_earner_env() -> FinancialLifeEnv:
        """Create environment for low earner scenario"""
        config = {
            'initial_salary': 30000,
            'initial_bank_balance': 2000,
            'initial_spending': 25000,
            'person_start_age': 22,
            'person_gender': GenderAtBirth.FEMALE
        }
        return FinancialLifeEnv(config)

    @staticmethod
    def create_mid_career_env() -> FinancialLifeEnv:
        """Create environment for mid-career professional"""
        config = {
            'initial_salary': 80000,
            'initial_bank_balance': 30000,
            'initial_spending': 50000,
            'person_start_age': 35,
            'person_retirement_age': 62,
            'person_gender': GenderAtBirth.FEMALE
        }
        return FinancialLifeEnv(config)

    @staticmethod
    def create_custom_env(config: Dict) -> FinancialLifeEnv:
        """Create environment with custom configuration"""
        return FinancialLifeEnv(config)
