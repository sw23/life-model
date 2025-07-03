# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from collections import deque, namedtuple
import random
from typing import Dict, List, Optional
import os

from environment import FinancialLifeEnv


# Experience tuple for replay buffer
Experience = namedtuple('Experience',
                        ['state', 'action', 'reward', 'next_state', 'done', 'legal_actions'])


class DQNNetwork(nn.Module):
    """Deep Q-Network for financial decision making"""

    def __init__(self, state_size: int, action_size: int, hidden_sizes: List[int] = [512, 256, 128]):
        super(DQNNetwork, self).__init__()

        self.state_size = state_size
        self.action_size = action_size

        # Build the network
        layers = []
        input_size = state_size

        for hidden_size in hidden_sizes:
            layers.append(nn.Linear(input_size, hidden_size))
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(0.1))
            input_size = hidden_size

        # Output layer
        layers.append(nn.Linear(input_size, action_size))

        self.network = nn.Sequential(*layers)

        # Initialize weights
        self.apply(self._init_weights)

    def _init_weights(self, module):
        """Initialize network weights"""
        if isinstance(module, nn.Linear):
            torch.nn.init.xavier_uniform_(module.weight)
            module.bias.data.fill_(0.01)

    def forward(self, state):
        """Forward pass through the network"""
        return self.network(state)


class DuelingDQN(nn.Module):
    """Dueling DQN architecture for better value estimation"""

    def __init__(self, state_size: int, action_size: int, hidden_sizes: List[int] = [512, 256]):
        super(DuelingDQN, self).__init__()

        self.state_size = state_size
        self.action_size = action_size

        # Shared feature extraction layers
        self.feature_layers = nn.Sequential(
            nn.Linear(state_size, hidden_sizes[0]),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_sizes[0], hidden_sizes[1]),
            nn.ReLU(),
            nn.Dropout(0.1)
        )

        # Value stream
        self.value_stream = nn.Sequential(
            nn.Linear(hidden_sizes[1], 128),
            nn.ReLU(),
            nn.Linear(128, 1)
        )

        # Advantage stream
        self.advantage_stream = nn.Sequential(
            nn.Linear(hidden_sizes[1], 128),
            nn.ReLU(),
            nn.Linear(128, action_size)
        )

        self.apply(self._init_weights)

    def _init_weights(self, module):
        if isinstance(module, nn.Linear):
            torch.nn.init.xavier_uniform_(module.weight)
            module.bias.data.fill_(0.01)

    def forward(self, state):
        features = self.feature_layers(state)

        value = self.value_stream(features)
        advantage = self.advantage_stream(features)

        # Combine value and advantage: Q(s,a) = V(s) + A(s,a) - mean(A(s,a))
        q_value = value + advantage - advantage.mean(dim=1, keepdim=True)

        return q_value


class ReplayBuffer:
    """Experience replay buffer for training stability"""

    def __init__(self, capacity: int):
        self.buffer = deque(maxlen=capacity)

    def push(self, *args):
        """Add experience to buffer"""
        self.buffer.append(Experience(*args))

    def sample(self, batch_size: int) -> List[Experience]:
        """Sample random batch from buffer"""
        return random.sample(self.buffer, batch_size)

    def __len__(self):
        return len(self.buffer)


class FinancialDQNAgent:
    """Deep Q-Network agent for financial decision making"""

    def __init__(self,
                 state_size: int,
                 action_size: int,
                 config: Optional[Dict] = None):

        # Default configuration
        self.config = {
            'learning_rate': 1e-4,
            'batch_size': 64,
            'gamma': 0.99,
            'epsilon_start': 1.0,
            'epsilon_end': 0.01,
            'epsilon_decay': 0.995,
            'target_update_freq': 100,
            'replay_buffer_size': 100000,
            'min_replay_size': 1000,
            'hidden_sizes': [512, 256, 128],
            'use_dueling': True,
            'use_double_dqn': True,
            'use_prioritized_replay': False
        }

        if config:
            self.config.update(config)

        self.state_size = state_size
        self.action_size = action_size
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # Initialize networks
        if self.config['use_dueling']:
            self.q_network = DuelingDQN(state_size, action_size, self.config['hidden_sizes']).to(self.device)
            self.target_network = DuelingDQN(state_size, action_size, self.config['hidden_sizes']).to(self.device)
        else:
            self.q_network = DQNNetwork(state_size, action_size, self.config['hidden_sizes']).to(self.device)
            self.target_network = DQNNetwork(state_size, action_size, self.config['hidden_sizes']).to(self.device)

        # Copy weights to target network
        self.target_network.load_state_dict(self.q_network.state_dict())

        # Optimizer
        self.optimizer = optim.Adam(self.q_network.parameters(), lr=self.config['learning_rate'])

        # Replay buffer
        self.replay_buffer = ReplayBuffer(self.config['replay_buffer_size'])

        # Training state
        self.epsilon = self.config['epsilon_start']
        self.steps_done = 0
        self.training_losses = []
        self.episode_rewards = []

        print(f"Initialized DQN Agent on {self.device}")
        print(f"Network architecture: {self.config['hidden_sizes']}")
        print(f"Using Dueling DQN: {self.config['use_dueling']}")
        print(f"Using Double DQN: {self.config['use_double_dqn']}")

    def select_action(self, state: np.ndarray, legal_actions: List[int], training: bool = True) -> int:
        """Select action using epsilon-greedy policy"""

        if training and random.random() < self.epsilon:
            # Random action from legal actions
            return random.choice(legal_actions)

        # Greedy action
        state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
        q_values = self.q_network(state_tensor)

        # Mask illegal actions
        masked_q_values = q_values.clone()
        mask = torch.full_like(masked_q_values, float('-inf'))
        mask[0, legal_actions] = 0
        masked_q_values += mask

        return masked_q_values.argmax().item()

    def store_experience(self, state: np.ndarray, action: int, reward: float,
                         next_state: np.ndarray, done: bool, legal_actions: List[int]):
        """Store experience in replay buffer"""
        self.replay_buffer.push(state, action, reward, next_state, done, legal_actions)

    def train(self) -> Optional[float]:
        """Train the agent on a batch of experiences"""

        if len(self.replay_buffer) < self.config['min_replay_size']:
            return None

        # Sample batch
        experiences = self.replay_buffer.sample(self.config['batch_size'])
        batch = Experience(*zip(*experiences))

        # Convert to tensors
        state_batch = torch.FloatTensor(np.array(batch.state)).to(self.device)
        action_batch = torch.LongTensor(batch.action).to(self.device)
        reward_batch = torch.FloatTensor(batch.reward).to(self.device)
        next_state_batch = torch.FloatTensor(np.array(batch.next_state)).to(self.device)
        done_batch = torch.BoolTensor(batch.done).to(self.device)

        # Current Q values
        current_q_values = self.q_network(state_batch).gather(1, action_batch.unsqueeze(1))

        # Next Q values
        with torch.no_grad():
            if self.config['use_double_dqn']:
                # Double DQN: use main network to select action, target network to evaluate
                next_actions = self.q_network(next_state_batch).argmax(1)
                next_q_values = self.target_network(next_state_batch).gather(1, next_actions.unsqueeze(1))
            else:
                # Standard DQN
                next_q_values = self.target_network(next_state_batch).max(1)[0].detach()
                next_q_values = next_q_values.unsqueeze(1)

            # Compute target Q values
            target_q_values = reward_batch.unsqueeze(1)
            target_q_values += (self.config['gamma'] * next_q_values * ~done_batch.unsqueeze(1))

        # Compute loss
        loss = F.mse_loss(current_q_values, target_q_values)

        # Optimize
        self.optimizer.zero_grad()
        loss.backward()

        # Gradient clipping
        torch.nn.utils.clip_grad_norm_(self.q_network.parameters(), 1.0)

        self.optimizer.step()

        # Update target network
        if self.steps_done % self.config['target_update_freq'] == 0:
            self.target_network.load_state_dict(self.q_network.state_dict())

        # Update epsilon
        if self.epsilon > self.config['epsilon_end']:
            self.epsilon *= self.config['epsilon_decay']

        self.steps_done += 1
        loss_value = loss.item()
        self.training_losses.append(loss_value)

        return loss_value

    def save_model(self, filepath: str):
        """Save model and training state"""
        save_dict = {
            'q_network_state_dict': self.q_network.state_dict(),
            'target_network_state_dict': self.target_network.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'config': self.config,
            'epsilon': self.epsilon,
            'steps_done': self.steps_done,
            'training_losses': self.training_losses,
            'episode_rewards': self.episode_rewards
        }
        torch.save(save_dict, filepath)
        print(f"Model saved to {filepath}")

    def load_model(self, filepath: str):
        """Load model and training state"""
        if not os.path.exists(filepath):
            print(f"Model file {filepath} not found")
            return

        save_dict = torch.load(filepath, map_location=self.device)

        self.q_network.load_state_dict(save_dict['q_network_state_dict'])
        self.target_network.load_state_dict(save_dict['target_network_state_dict'])
        self.optimizer.load_state_dict(save_dict['optimizer_state_dict'])

        self.epsilon = save_dict.get('epsilon', self.config['epsilon_end'])
        self.steps_done = save_dict.get('steps_done', 0)
        self.training_losses = save_dict.get('training_losses', [])
        self.episode_rewards = save_dict.get('episode_rewards', [])

        print(f"Model loaded from {filepath}")
        print(f"Training steps: {self.steps_done}, Epsilon: {self.epsilon:.4f}")


class FinancialDQNTrainer:
    """Trainer for the financial DQN agent"""

    def __init__(self,
                 env: FinancialLifeEnv,
                 agent: FinancialDQNAgent,
                 config: Optional[Dict] = None):

        self.env = env
        self.agent = agent

        # Training configuration
        self.config = {
            'num_episodes': 1000,
            'max_steps_per_episode': None,  # Use environment default
            'save_freq': 100,
            'eval_freq': 50,
            'eval_episodes': 10,
            'print_freq': 10,
            'model_save_path': 'financial_dqn_model.pt'
        }

        if config:
            self.config.update(config)

        self.episode_rewards = []
        self.eval_rewards = []
        self.training_metrics = {
            'avg_reward': [],
            'avg_net_worth': [],
            'success_rate': [],
            'avg_retirement_age': []
        }

    def train(self):
        """Train the agent"""
        print(f"Starting training for {self.config['num_episodes']} episodes")
        print(f"Environment: {type(self.env).__name__}")
        print(f"Action space size: {self.env.action_space['action_type'].n}")
        print(f"State space size: {self.env.observation_space.shape[0]}")

        for episode in range(self.config['num_episodes']):
            episode_reward = self._run_episode(training=True)
            self.episode_rewards.append(episode_reward)
            self.agent.episode_rewards.append(episode_reward)

            # Print progress
            if episode % self.config['print_freq'] == 0:
                avg_reward = np.mean(self.episode_rewards[-100:])
                print(f"Episode {episode:4d}, "
                      f"Reward: {episode_reward:8.2f}, "
                      f"Avg Reward (100): {avg_reward:8.2f}, "
                      f"Epsilon: {self.agent.epsilon:.4f}")

            # Evaluate agent
            if episode % self.config['eval_freq'] == 0 and episode > 0:
                eval_reward = self._evaluate_agent()
                self.eval_rewards.append(eval_reward)
                print(f"Evaluation at episode {episode}: {eval_reward:.2f}")

            # Save model
            if episode % self.config['save_freq'] == 0 and episode > 0:
                self.agent.save_model(self.config['model_save_path'])

        # Final save
        self.agent.save_model(self.config['model_save_path'])
        print("Training completed!")

    def _run_episode(self, training: bool = True) -> float:
        """Run a single episode"""
        state = self.env.reset()
        total_reward = 0.0
        step = 0
        max_steps = self.config['max_steps_per_episode'] or self.env.max_steps

        while step < max_steps:
            # Get legal actions
            legal_actions = self.env.get_legal_actions()

            # Select action
            action_type = self.agent.select_action(state, legal_actions, training=training)

            # For amount_percentage, use a simple heuristic or learn this too
            # For now, use a moderate percentage
            amount_percentage = np.array([0.1])  # 10% of available amount

            action = {
                'action_type': action_type,
                'amount_percentage': amount_percentage
            }

            # Take action
            next_state, reward, done, info = self.env.step(action)
            total_reward += reward

            # Store experience for training
            if training:
                self.agent.store_experience(state, action_type, reward, next_state, done, legal_actions)

                # Train agent
                self.agent.train()

            state = next_state
            step += 1

            if done:
                break

        return total_reward

    def _evaluate_agent(self) -> float:
        """Evaluate agent performance"""
        eval_rewards = []
        mortality_deaths = 0
        natural_deaths = 0
        bankruptcy_deaths = 0
        successful_completions = 0
        total_ages_at_death = []

        for _ in range(self.config['eval_episodes']):
            reward = self._run_episode(training=False)
            eval_rewards.append(reward)

            # Track evaluation metrics
            if hasattr(self.env, 'died_from_natural_causes') and self.env.died_from_natural_causes:
                mortality_deaths += 1
                natural_deaths += 1
            elif self.env._calculate_net_worth() < -100000:
                bankruptcy_deaths += 1
            elif self.env.current_step >= self.env.max_steps:
                successful_completions += 1

            total_ages_at_death.append(self.env.person.age)

        # Print evaluation summary
        avg_age_at_death = np.mean(total_ages_at_death)
        print(f"  Eval Summary: Natural deaths: {natural_deaths}/{self.config['eval_episodes']}, "
              f"Bankruptcies: {bankruptcy_deaths}/{self.config['eval_episodes']}, "
              f"Successful completions: {successful_completions}/{self.config['eval_episodes']}, "
              f"Avg age at death: {avg_age_at_death:.1f}")

        return float(np.mean(eval_rewards))

    def get_training_stats(self) -> Dict:
        """Get training statistics"""
        return {
            'episode_rewards': self.episode_rewards,
            'eval_rewards': self.eval_rewards,
            'training_losses': self.agent.training_losses,
            'total_episodes': len(self.episode_rewards),
            'total_steps': self.agent.steps_done
        }
