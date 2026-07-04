# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import Any, Dict, List, Optional, Tuple

import gymnasium as gym
import numpy as np
from actions import (
    _WITHDRAW_SOURCES,
    TRANSFER_ACTIONS,
    WITHDRAWAL_ACTIONS,
    ActionExecutor,
    ActionResult,
    ActionType,
    owned_accounts,
)
from gymnasium import spaces

from life_model.account.bank import BankAccount
from life_model.account.brokerage import BrokerageAccount
from life_model.account.hsa import HealthSavingsAccount, HSAType
from life_model.account.job401k import Job401kAccount
from life_model.account.roth_IRA import RothIRA
from life_model.account.traditional_IRA import TraditionalIRA
from life_model.base_classes import FinancialAccount
from life_model.model import LifeModel
from life_model.people.family import Family
from life_model.people.mortality import get_chance_of_mortality, get_random_mortality
from life_model.people.person import GenderAtBirth, Person, Spending
from life_model.work.job import Job, Salary


class FinancialLifeEnv(gym.Env):
    """Gymnasium environment for financial life simulation.

    An RL agent makes one financial decision per simulated year over a person's lifetime, with
    the goal of optimizing long-term financial outcomes. The environment follows the modern
    Gymnasium API: ``reset(seed=..., options=...) -> (obs, info)`` and
    ``step(action) -> (obs, reward, terminated, truncated, info)``.
    """

    metadata = {"render_modes": ["human"]}

    # Below this net worth the episode ends and the bankruptcy penalty applies (single threshold
    # so the penalty and the termination condition can never disagree).
    BANKRUPTCY_THRESHOLD = -100000

    def __init__(self, config: Optional[Dict] = None, render_mode: Optional[str] = None):
        super().__init__()

        # Default configuration
        self.config = {
            "start_year": 2025,
            "person_start_age": 25,
            "person_retirement_age": 65,
            "person_max_age": 119,
            "person_gender": GenderAtBirth.MALE,  # Default gender for mortality calculations
            "initial_salary": 50000,
            "initial_bank_balance": 10000,
            "initial_spending": 30000,
            "max_action_amount": 50000,  # Max amount for transfer/withdrawal actions
            "account_growth": 6.0,  # Average annual growth for the created 401k (percent)
            "reward_weights": {
                "net_worth": 1.0,
                "spending_satisfaction": 0.3,
                "bankruptcy_penalty": -10.0,
                "death_with_money_bonus": 1.0,
                "unexpected_death_penalty": -5.0,  # Penalty for dying unexpectedly early
            },
        }

        if config:
            self.config.update(config)

        self.render_mode = render_mode

        # Calculate max steps before reset
        self.max_steps = self.config["person_max_age"] - self.config["person_start_age"]
        self.current_step = 0

        # Define action space: a discrete action type plus a continuous amount fraction.
        self.action_space = spaces.Dict(
            {
                "action_type": spaces.Discrete(len(ActionType)),
                "amount_percentage": spaces.Box(low=0.0, high=1.0, shape=(1,), dtype=np.float32),
            }
        )

        # Define observation space (financial + personal + market state).
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(self._get_state_size(),), dtype=np.float32)

        # Initialize the simulation
        self.reset()

    def _get_state_size(self) -> int:
        """Calculate the size of the state vector"""
        # Person state: age, years_to_retirement, is_retired, mortality_probability
        person_state_size = 4

        # Financial state: bank_balance, 401k_pretax, 401k_roth, debt, annual_income, annual_spending
        financial_state_size = 6

        # Ratios and derived metrics: savings_rate, debt_to_income, net_worth, etc.
        derived_metrics_size = 8

        # Market/economic state: year, equity_return
        market_state_size = 2

        return person_state_size + financial_state_size + derived_metrics_size + market_state_size

    def reset(self, *, seed: Optional[int] = None, options: Optional[Dict] = None) -> Tuple[np.ndarray, Dict[str, Any]]:
        """Reset the environment to its initial state.

        Args:
            seed: Seeds both the Gymnasium RNG and the underlying :class:`LifeModel` so that a
                given seed reproduces an identical episode.
            options: Unused; accepted for Gymnasium API compatibility.

        Returns:
            A ``(observation, info)`` tuple per the Gymnasium API.
        """
        super().reset(seed=seed)

        # Create new model instance, seeded for reproducibility.
        self.model = LifeModel(start_year=self.config["start_year"], seed=seed)
        self.family = Family(self.model)

        # Create person
        self.person = Person(
            family=self.family,
            name="RL_Agent",
            age=self.config["person_start_age"],
            retirement_age=self.config["person_retirement_age"],
            spending=Spending(
                model=self.model,
                base=self.config["initial_spending"],
                yearly_increase=2,  # 2% inflation
            ),
        )

        # Store gender for mortality calculations
        self.person_gender = self.config["person_gender"]

        # Track mortality state
        self.died_from_natural_causes = False

        # Create bank account
        self.bank_account = BankAccount(
            owner=self.person,
            company="Bank",
            type="Checking",
            balance=self.config["initial_bank_balance"],
            interest_rate=0.5,
        )

        # Create job
        self.job = Job(
            owner=self.person,
            company="Company",
            role="Employee",
            salary=Salary(
                model=self.model,
                base=self.config["initial_salary"],
                yearly_increase=3,  # 3% annual raises
                yearly_bonus=1,
            ),
        )

        # Create the accounts the agent can act on so every action type is reachable.
        self.job401k = Job401kAccount(job=self.job, average_growth=self.config["account_growth"])
        self.brokerage = BrokerageAccount(person=self.person, company="Brokerage")
        self.traditional_ira = TraditionalIRA(person=self.person)
        self.roth_ira = RothIRA(person=self.person)
        self.hsa = HealthSavingsAccount(person=self.person, hsa_type=HSAType.INDIVIDUAL)

        # Action executor
        self.action_executor = ActionExecutor(self.model)

        # Reset step counter
        self.current_step = 0

        # Set initial model end year
        self.model.end_year = self.model.start_year + self.max_steps

        # Track initial state
        self.initial_net_worth = self._calculate_net_worth()
        self.previous_net_worth = self.initial_net_worth
        self.total_lifetime_spending = 0.0

        return self._get_observation(), self._get_info(None)

    def step(self, action: Dict[str, Any]) -> Tuple[np.ndarray, float, bool, bool, Dict]:
        """Execute one step (one simulated year) in the environment.

        Args:
            action: Dictionary with 'action_type' (int) and 'amount_percentage' (float).

        Returns:
            ``(observation, reward, terminated, truncated, info)`` per the Gymnasium API.
        """

        # Parse action
        action_type_idx = int(action["action_type"])
        amount_percentage = float(np.asarray(action["amount_percentage"]).reshape(-1)[0])

        # Convert action index to ActionType
        action_type = list(ActionType)[action_type_idx]

        # Calculate action amount based on percentage and financial state
        action_amount = self._calculate_action_amount(action_type, amount_percentage)

        # Execute the action
        action_result = self.action_executor.execute_action(
            self.person,
            action_type,
            amount=action_amount,
            percentage_change=amount_percentage * 0.2,  # Max 20% spending change
        )

        # Step the simulation forward one year
        self.model.step()
        self.current_step += 1

        # Check for mortality (seeded through the model RNG for reproducibility)
        if not self.died_from_natural_causes:
            self.died_from_natural_causes = get_random_mortality(
                self.person.age, self.person_gender, rng=self.model.random
            )

        # Calculate reward
        reward = self._calculate_reward(action_result)

        # Terminal (task-ending) vs. truncation (time-limit) conditions
        terminated = self._is_terminated()
        truncated = self.current_step >= self.max_steps and not terminated

        info = self._get_info(action_result, action_type=action_type, action_amount=action_amount)

        return self._get_observation(), reward, terminated, truncated, info

    def _get_info(
        self,
        action_result: Optional[ActionResult],
        action_type: Optional[ActionType] = None,
        action_amount: float = 0.0,
    ) -> Dict[str, Any]:
        """Build the info dict returned by reset/step."""
        return {
            "action_result": action_result,
            "net_worth": self._calculate_net_worth(),
            "age": self.person.age,
            "is_retired": self.person.is_retired,
            "bank_balance": self.person.bank_account_balance,
            "annual_spending": self.person.spending.get_yearly_spending(),
            "action_type": action_type.value if action_type is not None else None,
            "action_amount": action_amount,
            "died_from_natural_causes": self.died_from_natural_causes,
            "mortality_probability": get_chance_of_mortality(self.person.age, self.person_gender),
        }

    def _calculate_action_amount(self, action_type: ActionType, percentage: float) -> float:
        """Calculate the actual dollar amount for a transfer/withdrawal action."""
        max_amount = self.config["max_action_amount"]

        if action_type in TRANSFER_ACTIONS:
            # Fraction of the bank balance available to move.
            return min(self.person.bank_account_balance * percentage, max_amount)

        if action_type in WITHDRAWAL_ACTIONS:
            # Fraction of the source account's balance.
            source = owned_accounts(self.person, _WITHDRAW_SOURCES[action_type])
            balance = source[0].balance if source else 0.0
            return min(balance * percentage, max_amount)

        # Spending / retire / no-op actions don't use a dollar amount.
        return 0.0

    def _owned_accounts(self) -> List[FinancialAccount]:
        """All balance-holding accounts owned by the person."""
        return [
            a
            for a in self.model.agents
            if isinstance(a, FinancialAccount) and getattr(a, "person", None) is self.person
        ]

    def _get_observation(self) -> np.ndarray:
        """Get current state observation"""

        # Person state
        mortality_prob = get_chance_of_mortality(self.person.age, self.person_gender)
        person_state = [
            self.person.age / 100.0,  # Normalized age
            max(0, self.person.retirement_age - self.person.age) / 50.0,  # Years to retirement
            1.0 if self.person.is_retired else 0.0,  # Is retired
            mortality_prob,  # Current year mortality probability
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
            annual_spending / scale,
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
            (self.person.age - self.config["person_start_age"]) / self.max_steps,  # Life progress
            min(max(bank_balance / 50000, 0), 2.0),  # Emergency fund adequacy (0-2 scale)
        ]

        # Market/economic state
        market_state = [
            (self.model.year - self.config["start_year"]) / self.max_steps,  # Time progress
            self.model.economy.equity_return(self.model.year) / 100.0,  # Real equity return for the year
        ]

        # Combine all states
        observation = np.array(person_state + financial_state + derived_metrics + market_state, dtype=np.float32)

        return observation

    def _calculate_net_worth(self) -> float:
        """Calculate person's net worth across all owned accounts and property."""
        assets = sum(acc.balance for acc in self._owned_accounts())
        assets += sum(home.home_value for home in self.person.homes)
        liabilities = self.person.debt + sum(home.mortgage.principal for home in self.person.homes if home.mortgage)
        return assets - liabilities

    def _calculate_reward(self, action_result: ActionResult) -> float:
        """Calculate reward for the current step.

        The reward is a change-in-net-worth base plus a spending-utility term, with terminal
        wealth and mortality adjustments. There is no pre-retirement "bonus" term (it was farmable
        by simply cutting spending), so the agent is rewarded for genuinely growing wealth.
        """

        reward = 0.0
        weights = self.config["reward_weights"]

        # Net worth growth reward (change since last step)
        current_net_worth = self._calculate_net_worth()
        net_worth_growth = current_net_worth - self.previous_net_worth
        self.previous_net_worth = current_net_worth
        reward += weights["net_worth"] * (net_worth_growth / 100000.0)  # Normalized by $100k

        # Spending satisfaction (diminishing returns on spending)
        annual_spending = self.person.spending.get_yearly_spending()
        self.total_lifetime_spending += annual_spending
        spending_satisfaction = np.log(max(annual_spending, 1000)) / 10.0
        reward += weights["spending_satisfaction"] * spending_satisfaction

        # Bankruptcy penalty (same threshold as termination, so they never disagree)
        if current_net_worth < self.BANKRUPTCY_THRESHOLD:
            reward += weights["bankruptcy_penalty"]

        # Death with money bonus (terminal wealth)
        if (self.current_step >= self.max_steps - 1 or self.died_from_natural_causes) and current_net_worth > 0:
            reward += weights["death_with_money_bonus"] * (current_net_worth / 1000000.0)

        # Unexpected death penalty - penalize dying much earlier than expected lifespan
        if self.died_from_natural_causes:
            expected_years_remaining = 0
            for future_age in range(self.person.age, min(self.config["person_max_age"], 100)):
                survival_prob = 1.0 - get_chance_of_mortality(future_age, self.person_gender)
                expected_years_remaining += survival_prob

            if expected_years_remaining > 20:  # More than 20 years expected remaining
                penalty_factor = min(expected_years_remaining / 20.0, 2.0)  # Cap at 2x penalty
                reward += weights["unexpected_death_penalty"] * penalty_factor

        # Action execution penalty for failed actions
        if not action_result.success:
            reward -= 0.1

        # Fee penalty
        reward -= action_result.fees_paid / 10000.0  # Penalty for fees

        return float(reward)

    def _is_terminated(self) -> bool:
        """Whether the episode reached a terminal (task-ending) state.

        Terminal = the person died, reached the maximum modeled age, or went bankrupt. Reaching
        the episode's step budget is reported as truncation, not termination.
        """
        return (
            self.person.age >= self.config["person_max_age"]
            or self._calculate_net_worth() < self.BANKRUPTCY_THRESHOLD
            or self.died_from_natural_causes
        )

    def render(self) -> Optional[str]:
        """Render the environment for the configured ``render_mode``."""
        if self.render_mode == "human":
            net_worth = self._calculate_net_worth()
            mortality_prob = get_chance_of_mortality(self.person.age, self.person_gender)
            status = "DECEASED" if self.died_from_natural_causes else "ALIVE"
            print(
                f"Year: {self.model.year}, Age: {self.person.age}, Status: {status}, "
                f"Mortality Risk: {mortality_prob:.1%}, "
                f"Net Worth: ${net_worth:,.0f}, "
                f"Bank: ${self.person.bank_account_balance:,.0f}, "
                f"Retirement: ${sum(acc.balance for acc in self.person.all_retirement_accounts):,.0f}"
            )

        return None

    def get_legal_actions(self) -> List[int]:
        """Get list of legal action indices for the current state.

        Legality is decided solely by ``Action.can_execute`` (via the executor), so the mask can
        never disagree with what ``execute`` will do.
        """
        legal_actions = []
        for i, action_type in enumerate(ActionType):
            if action_type == ActionType.NO_ACTION:
                legal_actions.append(i)
                continue
            # Probe with the amount the environment would actually use this step.
            amount = self._calculate_action_amount(action_type, 0.1)
            if self.action_executor.can_execute_action(self.person, action_type, amount=amount, percentage_change=0.05):
                legal_actions.append(i)
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
            "initial_salary": 120000,
            "initial_bank_balance": 50000,
            "initial_spending": 60000,
            "person_start_age": 30,
            "person_gender": GenderAtBirth.MALE,
        }
        return FinancialLifeEnv(config)

    @staticmethod
    def create_low_earner_env() -> FinancialLifeEnv:
        """Create environment for low earner scenario"""
        config = {
            "initial_salary": 30000,
            "initial_bank_balance": 2000,
            "initial_spending": 25000,
            "person_start_age": 22,
            "person_gender": GenderAtBirth.FEMALE,
        }
        return FinancialLifeEnv(config)

    @staticmethod
    def create_mid_career_env() -> FinancialLifeEnv:
        """Create environment for mid-career professional"""
        config = {
            "initial_salary": 80000,
            "initial_bank_balance": 30000,
            "initial_spending": 50000,
            "person_start_age": 35,
            "person_retirement_age": 62,
            "person_gender": GenderAtBirth.FEMALE,
        }
        return FinancialLifeEnv(config)

    @staticmethod
    def create_custom_env(config: Dict) -> FinancialLifeEnv:
        """Create environment with custom configuration"""
        return FinancialLifeEnv(config)
