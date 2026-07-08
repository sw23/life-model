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
from life_model.config.financial_config import FinancialConfig
from life_model.config.scenarios import get_scenario
from life_model.limits import required_min_distrib, rmd_start_age
from life_model.model import LifeModel
from life_model.people.family import Family
from life_model.people.mortality import get_blended_chance_of_mortality, get_chance_of_mortality
from life_model.people.person import GenderAtBirth, MortalityMode, Person, Spending
from life_model.work.job import Job, Salary

# Observation layout version (Plan 18 D4). Bumped whenever the feature list, ordering,
# normalization, or bounds below change, so checkpoints trained against a different layout are
# rejected instead of silently misread.
OBS_VERSION = 2

# Age at which tax-advantaged accounts can be tapped without the early-withdrawal penalty.
PENALTY_FREE_AGE = 59.5

# Observation feature spec: (name, low, high). Values are clipped into [low, high] before being
# returned, so the declared Box bounds are honest. Unless noted otherwise, money features are in
# *real* (inflation-deflated, start-of-episode) dollars normalized by $1M and clipped at 10
# (= $10M real).
OBS_SPEC = [
    # --- person ---
    ("age", 0.0, 1.5),  # age / 100
    ("years_to_retirement", 0.0, 1.0),  # max(0, retirement_age - age) / 50
    ("is_retired", 0.0, 1.0),  # 0/1
    ("mortality_probability", 0.0, 1.0),  # SSA table chance of death at current age
    ("life_progress", 0.0, 1.5),  # (age - start_age) / max_steps
    # --- balances (real $M) ---
    ("bank_balance", 0.0, 10.0),
    ("pretax_401k", 0.0, 10.0),
    ("roth_401k", 0.0, 10.0),
    ("traditional_ira", 0.0, 10.0),
    ("roth_ira", 0.0, 10.0),
    ("hsa", 0.0, 10.0),
    ("brokerage", 0.0, 10.0),
    ("debt", 0.0, 10.0),  # outstanding_debt_balance: real serviced debts + mortgages (real $M)
    ("annual_income", 0.0, 10.0),  # wages from non-retired jobs (real $M)
    ("annual_spending", 0.0, 10.0),  # yearly spending (real $M)
    # --- derived ratios ---
    ("net_worth", -10.0, 10.0),  # real $M
    ("savings_rate", 0.0, 1.0),  # (income - spending) / income
    ("debt_to_income", 0.0, 10.0),
    ("retirement_readiness", 0.0, 10.0),  # retirement balances / (25 x spending), 4% rule
    ("emergency_fund_years", 0.0, 10.0),  # bank balance / spending
    ("income_to_spending", 0.0, 10.0),
    # --- tax position (for the upcoming simulated year; the ledger itself is settled and
    #     cleared inside model.step(), so the decision-relevant quantity is the projection) ---
    ("projected_taxable_income", 0.0, 10.0),  # projected wages + RMD (real $M)
    ("bracket_headroom", 0.0, 10.0),  # $ to the next federal bracket edge / $100k (real)
    ("marginal_rate", 0.0, 1.0),  # marginal federal rate at the projected income
    # --- retirement timing ---
    ("years_to_59_5", 0.0, 1.0),  # max(0, 59.5 - age) / 35
    ("years_to_rmd_start", 0.0, 1.0),  # max(0, rmd_start_age - age) / 50
    ("projected_rmd", 0.0, 10.0),  # RMD due in the upcoming year (real $M)
    # --- contribution room ---
    ("ira_room_fraction", 0.0, 1.0),  # remaining IRA contribution room / limit
    ("hsa_room_fraction", 0.0, 1.0),  # remaining HSA contribution room / limit
    # --- market / economy (realized, no lookahead of the upcoming year's draw) ---
    ("time_progress", 0.0, 1.5),  # (year - start_year) / max_steps
    ("inflation", -1.0, 1.0),  # last realized year's inflation, percent / 100
    ("equity_return", -1.0, 1.0),  # last realized year's equity return, percent / 100
    ("bond_return", -1.0, 1.0),  # last realized year's bond return, percent / 100
    ("log_deflator", 0.0, 5.0),  # log of cumulative inflation since the episode start
]

_MONEY_SCALE = 1_000_000.0

# Economy modes the environment accepts (see EconomyModel; "path" is reachable via a named
# economy_scenario rather than directly).
_ECONOMY_MODES = ("fixed", "stochastic")


class FinancialLifeEnv(gym.Env):
    """Gymnasium environment for financial life simulation.

    An RL agent makes one financial decision per simulated year over a person's lifetime, with
    the goal of optimizing long-term financial outcomes. The environment follows the modern
    Gymnasium API: ``reset(seed=..., options=...) -> (obs, info)`` and
    ``step(action) -> (obs, reward, terminated, truncated, info)``.

    **Tax semantics (Plan 18 D1):** actions execute through the model's real money path. A
    taxable withdrawal (pre-tax 401k, traditional IRA) records ordinary income on the person's
    ledger, and the tax unit settles all taxes once per simulated year inside ``model.step()`` —
    so the tax on a withdrawal bites at year-end settlement within the same ``step()`` call, not
    at the instant of withdrawal. That is the simulator's actual semantics, and it is what makes
    pre-tax and Roth withdrawals genuinely different to the agent.
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
            # Economy behavior (Plan 18 D3): "stochastic" draws correlated equity/bond/inflation
            # each year from the model's seeded RNG (training default — the agent sees bad years);
            # "fixed" reproduces the constant-rate economy for unit tests. A named economy
            # scenario (config/scenarios, e.g. "recession") overrides where it sets values.
            "economy_mode": "stochastic",
            "economy_scenario": None,
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

        if self.config["economy_mode"] not in _ECONOMY_MODES:
            raise ValueError(f"Unknown economy_mode {self.config['economy_mode']!r}; expected one of {_ECONOMY_MODES}")

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

        # Define observation space with the finite, documented per-feature bounds from OBS_SPEC
        # (observations are clipped to these bounds, so they are honest).
        self.observation_space = spaces.Box(
            low=np.array([low for _, low, _ in OBS_SPEC], dtype=np.float32),
            high=np.array([high for _, _, high in OBS_SPEC], dtype=np.float32),
            dtype=np.float32,
        )

        # Initialize the simulation
        self.reset()

    def _get_state_size(self) -> int:
        """Size of the observation vector (see OBS_SPEC for the feature layout)."""
        return len(OBS_SPEC)

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

        # Economy (Plan 18 D3): stochastic by default so training sees good and bad years; a
        # named economy scenario (curriculum knob) is applied on top and wins where it sets
        # values. Draws use the model's seeded RNG, so a given seed reproduces the same economy.
        financial_config = FinancialConfig()
        financial_config.model.economy.mode = self.config["economy_mode"]
        if self.config["economy_scenario"] is not None:
            scenario_name = self.config["economy_scenario"]
            financial_config.apply_scenario(scenario_name, get_scenario(scenario_name))

        # Create new model instance, seeded for reproducibility. RL rollouts never read the
        # DataCollector frames, so collection is skipped for throughput (Plan 18 D7).
        self.model = LifeModel(
            start_year=self.config["start_year"], seed=seed, config=financial_config, collect_data=False
        )
        self.family = Family(self.model)

        # Create person with model-native stochastic mortality (Plan 18 D2): death is decided by
        # Person._check_mortality against the model's seeded RNG, and dying runs the full death
        # machinery (life insurance, estate transfer/tax, survivor adjustments) inside the
        # reward-visible world.
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
            gender=self.config["person_gender"],
            mortality_mode=MortalityMode.STOCHASTIC,
        )

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
        # Net worth captured just before the person died (the estate value the reward sees);
        # None while the person is alive.
        self._estate_value_at_death: Optional[float] = None

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

        # Step the simulation forward one year. Mortality is model-native (Plan 18 D2): the
        # person may die inside this call, which runs the full death machinery and removes their
        # agents from the model. Snapshot the pre-step net worth so the estate value at death is
        # observable to the reward (post-death net worth reads ~0 once assets dissolve).
        net_worth_before_step = self._calculate_net_worth()
        self.model.step()
        self.current_step += 1
        if self.person.is_deceased and self._estate_value_at_death is None:
            self._estate_value_at_death = net_worth_before_step

        # Calculate reward
        reward = self._calculate_reward(action_result)

        # Terminal (task-ending) vs. truncation (time-limit) conditions
        terminated = self._is_terminated()
        truncated = self.current_step >= self.max_steps and not terminated

        info = self._get_info(action_result, action_type=action_type, action_amount=action_amount)

        return self._get_observation(), reward, terminated, truncated, info

    @property
    def died_from_natural_causes(self) -> bool:
        """Whether the person died in-simulation (model-native stochastic mortality)."""
        return self.person.is_deceased

    def _mortality_probability(self) -> float:
        """The person's current-year chance of death from the SSA table (blended for OTHER)."""
        if self.person.gender == GenderAtBirth.OTHER:
            return get_blended_chance_of_mortality(self.person.age)
        return get_chance_of_mortality(self.person.age, self.person.gender)

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
            "estate_value_at_death": self._estate_value_at_death,
            "mortality_probability": self._mortality_probability(),
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

    def _observed_market_rates(self) -> Tuple[float, float, float]:
        """(inflation, equity return, bond return), in percent, without lookahead.

        After at least one simulated year, these are the *realized* rates of the most recently
        simulated year. Before any year has been simulated there is nothing realized yet, so the
        configured long-run means are reported instead (never the upcoming year's stochastic
        draw, which would leak the future to the first decision).
        """
        if self.current_step == 0:
            economy_config = self.model.config.economy
            if economy_config.mode == "stochastic":
                s = economy_config.stochastic
                return s.inflation_mean, s.equity_mean, s.bond_mean
            return economy_config.inflation, economy_config.equity_return, economy_config.bond_return
        economy = self.model.economy
        realized_year = self.model.year - 1
        return (
            economy.inflation(realized_year),
            economy.equity_return(realized_year),
            economy.bond_return(realized_year),
        )

    def _projected_tax_position(self, projected_ordinary_income: float) -> Tuple[float, float]:
        """(dollars of headroom to the next federal bracket edge, marginal rate fraction) for the
        upcoming simulated year, at the projected ordinary income for a single filer."""
        params = self.model.tax_params_for_year(self.model.year)
        taxable_base = max(0.0, projected_ordinary_income - params.standard_deduction.single)
        for _lower, upper, rate in params.tax_brackets.single:
            if taxable_base < upper:
                return upper - taxable_base, rate / 100.0
        # Above the top edge (only possible if the top bracket has a finite upper bound).
        top_rate = params.tax_brackets.single[-1][2]
        return float("inf"), top_rate / 100.0

    def _compute_observation_features(self) -> Dict[str, float]:
        """Raw (unclipped) value of every observation feature, keyed by OBS_SPEC name.

        Split from :meth:`_get_observation` so tests can check individual features against
        hand-computed values by name.
        """
        person = self.person
        economy = self.model.economy

        # Cumulative price level over the simulated years so far (1.0 at reset). Money features
        # are divided by this so the agent sees real (start-of-episode dollar) values and isn't
        # fooled by nominal growth under inflation.
        deflator = economy.cumulative_inflation(self.model.year)

        # Balances (nominal, then deflated below).
        bank_balance = person.bank_account_balance
        pretax_401k = sum(acc.pretax_balance for acc in person.all_retirement_accounts)
        roth_401k = sum(acc.roth_balance for acc in person.all_retirement_accounts)
        traditional_ira = sum(acc.balance for acc in person.traditional_iras)
        roth_ira = sum(acc.balance for acc in person.roth_iras)
        hsa = sum(acc.balance for acc in person.hsas)
        brokerage = sum(acc.balance for acc in person.brokerage_accounts)
        retirement_balance = pretax_401k + roth_401k + traditional_ira + roth_ira
        # Real debt (car loans, credit cards, student loans, mortgages) — not the dead
        # unpaid-bills carryover `person.debt` the old observation read.
        debt = person.outstanding_debt_balance
        annual_income = sum(job.salary.base for job in person.jobs if not job.retired)
        annual_spending = person.spending.get_yearly_spending()
        net_worth = self._calculate_net_worth()

        # Tax position for the upcoming year. The income ledger is settled and cleared inside
        # model.step(), so at decision time the honest quantity is the projection: wages the
        # jobs will deposit plus the RMD the 401k will force. (Documented deviation from "income
        # so far": intra-year state is never observable at the env's decision boundary.)
        next_age = person.age + 1
        birth_year = self.model.year - next_age
        start_age = rmd_start_age(birth_year, config=self.model.config, year=self.model.year)
        projected_rmd = required_min_distrib(next_age, pretax_401k, config=self.model.config, start_age=start_age)
        projected_ordinary_income = annual_income + projected_rmd
        bracket_headroom, marginal_rate = self._projected_tax_position(projected_ordinary_income)

        # Remaining contribution-room fractions for the capped account types.
        ira_limit = self.traditional_ira.contribution_limit + self.roth_ira.contribution_limit
        ira_used = self.traditional_ira.contributions_this_year + self.roth_ira.contributions_this_year
        ira_room_fraction = max(0.0, ira_limit - ira_used) / max(ira_limit, 1)
        hsa_room_fraction = max(0.0, self.hsa.contribution_limit - self.hsa.annual_contributions) / max(
            self.hsa.contribution_limit, 1
        )

        inflation, equity_return, bond_return = self._observed_market_rates()

        return {
            "age": person.age / 100.0,
            "years_to_retirement": max(0.0, person.retirement_age - person.age) / 50.0,
            "is_retired": 1.0 if person.is_retired else 0.0,
            "mortality_probability": self._mortality_probability(),
            "life_progress": (person.age - self.config["person_start_age"]) / self.max_steps,
            "bank_balance": bank_balance / deflator / _MONEY_SCALE,
            "pretax_401k": pretax_401k / deflator / _MONEY_SCALE,
            "roth_401k": roth_401k / deflator / _MONEY_SCALE,
            "traditional_ira": traditional_ira / deflator / _MONEY_SCALE,
            "roth_ira": roth_ira / deflator / _MONEY_SCALE,
            "hsa": hsa / deflator / _MONEY_SCALE,
            "brokerage": brokerage / deflator / _MONEY_SCALE,
            "debt": debt / deflator / _MONEY_SCALE,
            "annual_income": annual_income / deflator / _MONEY_SCALE,
            "annual_spending": annual_spending / deflator / _MONEY_SCALE,
            "net_worth": net_worth / deflator / _MONEY_SCALE,
            "savings_rate": max(0.0, (annual_income - annual_spending) / max(annual_income, 1)),
            "debt_to_income": debt / max(annual_income, 1),
            "retirement_readiness": retirement_balance / max(annual_spending * 25, 1),
            "emergency_fund_years": bank_balance / max(annual_spending, 1),
            "income_to_spending": annual_income / max(annual_spending, 1),
            "projected_taxable_income": projected_ordinary_income / deflator / _MONEY_SCALE,
            "bracket_headroom": (
                bracket_headroom / deflator / 100_000.0 if np.isfinite(bracket_headroom) else float("inf")
            ),
            "marginal_rate": marginal_rate,
            "years_to_59_5": max(0.0, PENALTY_FREE_AGE - person.age) / 35.0,
            "years_to_rmd_start": max(0.0, start_age - person.age) / 50.0,
            "projected_rmd": projected_rmd / deflator / _MONEY_SCALE,
            "ira_room_fraction": ira_room_fraction,
            "hsa_room_fraction": hsa_room_fraction,
            "time_progress": (self.model.year - self.config["start_year"]) / self.max_steps,
            "inflation": inflation / 100.0,
            "equity_return": equity_return / 100.0,
            "bond_return": bond_return / 100.0,
            "log_deflator": float(np.log(max(deflator, 1e-9))),
        }

    def _get_observation(self) -> np.ndarray:
        """Observation vector v2 (Plan 18 D4): assembled in OBS_SPEC order and clipped into the
        declared per-feature bounds."""
        features = self._compute_observation_features()
        raw = np.array([features[name] for name, _, _ in OBS_SPEC], dtype=np.float32)
        return np.clip(raw, self.observation_space.low, self.observation_space.high)

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

        # Net worth growth reward (change since last step). When the person died this step, use
        # the estate value at death rather than the post-dissolution ~0 net worth: the estate
        # passing out of the simulation is not wealth the agent destroyed, and penalizing it
        # would perversely reward dying poor.
        if self.died_from_natural_causes and self._estate_value_at_death is not None:
            current_net_worth = self._estate_value_at_death
        else:
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

        # Death with money bonus (terminal wealth — the estate value when the person died)
        if (self.current_step >= self.max_steps - 1 or self.died_from_natural_causes) and current_net_worth > 0:
            reward += weights["death_with_money_bonus"] * (current_net_worth / 1000000.0)

        # Unexpected death penalty - penalize dying much earlier than expected lifespan
        if self.died_from_natural_causes:
            expected_years_remaining = 0
            for future_age in range(self.person.age, min(self.config["person_max_age"], 100)):
                survival_prob = 1.0 - get_chance_of_mortality(
                    future_age,
                    self.person.gender if self.person.gender != GenderAtBirth.OTHER else GenderAtBirth.MALE,
                )
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

        Terminal = the person died in-simulation (model-native mortality), reached the maximum
        modeled age, or went bankrupt. Reaching the episode's step budget is reported as
        truncation, not termination.
        """
        return bool(
            self.person.is_deceased
            or self.person.age >= self.config["person_max_age"]
            or self._calculate_net_worth() < self.BANKRUPTCY_THRESHOLD
        )

    def render(self) -> Optional[str]:
        """Render the environment for the configured ``render_mode``."""
        if self.render_mode == "human":
            net_worth = self._calculate_net_worth()
            mortality_prob = self._mortality_probability()
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
