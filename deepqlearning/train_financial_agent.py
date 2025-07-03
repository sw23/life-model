#!/usr/bin/env python3
# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""
Deep Reinforcement Learning Training Script for Financial Life Model

This script trains a DQN agent to make optimal financial decisions over a person's lifetime.
The agent learns to manage bank accounts, retirement funds, debt, and lifestyle choices
to maximize long-term financial well-being.
"""

import os
import argparse
import numpy as np
import matplotlib.pyplot as plt
import json
from pathlib import Path
from typing import Optional

from environment import FinancialLifeEnv, FinancialLifeEnvGenerator
from agent import FinancialDQNAgent, FinancialDQNTrainer

# set base path to be the root of this file
BASE_PATH = Path(__file__).resolve().parent

def create_training_config(scenario: str = 'basic') -> dict:
    """Create training configuration for different scenarios"""

    base_config = {
        'num_episodes': 2000,
        'save_freq': 100,
        'eval_freq': 50,
        'eval_episodes': 5,
        'print_freq': 25,
        'model_save_path': BASE_PATH / 'models' / f'financial_dqn_{scenario}.pt'
    }

    if scenario == 'basic':
        return base_config
    elif scenario == 'high_earner':
        config = base_config.copy()
        config['model_save_path'] = BASE_PATH / 'models' / 'financial_dqn_high_earner.pt'
        config['num_episodes'] = 1500
        return config
    elif scenario == 'low_earner':
        config = base_config.copy()
        config['model_save_path'] = BASE_PATH / 'models' / 'financial_dqn_low_earner.pt'
        config['num_episodes'] = 2500
        return config
    else:
        return base_config


def create_agent_config(scenario: str = 'basic') -> dict:
    """Create agent configuration for different scenarios"""

    base_config = {
        'learning_rate': 1e-4,
        'batch_size': 64,
        'gamma': 0.99,
        'epsilon_start': 1.0,
        'epsilon_end': 0.01,
        'epsilon_decay': 0.995,
        'target_update_freq': 100,
        'replay_buffer_size': 50000,
        'min_replay_size': 1000,
        'hidden_sizes': [512, 256, 128],
        'use_dueling': True,
        'use_double_dqn': True
    }

    if scenario == 'high_earner':
        # High earners might need more complex decision making
        config = base_config.copy()
        config['hidden_sizes'] = [1024, 512, 256]
        config['replay_buffer_size'] = 100000
        return config
    elif scenario == 'low_earner':
        # Low earners might need longer exploration
        config = base_config.copy()
        config['epsilon_decay'] = 0.998
        config['epsilon_end'] = 0.05
        return config
    else:
        return base_config


def plot_training_results(trainer: FinancialDQNTrainer, save_path: Optional[str] = None):
    """Plot training results"""

    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle('Financial DQN Training Results', fontsize=16)

    # Episode rewards
    axes[0, 0].plot(trainer.episode_rewards)
    axes[0, 0].set_title('Episode Rewards')
    axes[0, 0].set_xlabel('Episode')
    axes[0, 0].set_ylabel('Total Reward')
    axes[0, 0].grid(True)

    # Moving average of rewards
    if len(trainer.episode_rewards) > 100:
        moving_avg = np.convolve(trainer.episode_rewards, np.ones(100)/100, mode='valid')
        axes[0, 1].plot(moving_avg)
        axes[0, 1].set_title('Moving Average Reward (100 episodes)')
        axes[0, 1].set_xlabel('Episode')
        axes[0, 1].set_ylabel('Average Reward')
        axes[0, 1].grid(True)

    # Training loss
    if trainer.agent.training_losses:
        axes[1, 0].plot(trainer.agent.training_losses)
        axes[1, 0].set_title('Training Loss')
        axes[1, 0].set_xlabel('Training Step')
        axes[1, 0].set_ylabel('MSE Loss')
        axes[1, 0].grid(True)

    # Evaluation rewards
    if trainer.eval_rewards:
        eval_episodes = np.arange(len(trainer.eval_rewards)) * trainer.config['eval_freq']
        axes[1, 1].plot(eval_episodes, trainer.eval_rewards, 'o-')
        axes[1, 1].set_title('Evaluation Rewards')
        axes[1, 1].set_xlabel('Episode')
        axes[1, 1].set_ylabel('Average Evaluation Reward')
        axes[1, 1].grid(True)

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"Training plots saved to {save_path}")

    plt.show()


def evaluate_trained_agent(agent: FinancialDQNAgent, env: FinancialLifeEnv, num_episodes: int = 10):
    """Evaluate a trained agent and show detailed results"""

    print(f"\nEvaluating trained agent over {num_episodes} episodes...")

    episode_results = []

    for episode in range(num_episodes):
        state = env.reset()
        total_reward = 0
        steps = 0
        episode_info = []

        while steps < env.max_steps:
            legal_actions = env.get_legal_actions()
            action_type = agent.select_action(state, legal_actions, training=False)

            action = {
                'action_type': action_type,
                'amount_percentage': np.array([0.1])  # Conservative 10%
            }

            state, reward, done, info = env.step(action)
            total_reward += reward
            steps += 1

            episode_info.append({
                'age': info['age'],
                'net_worth': info['net_worth'],
                'bank_balance': info['bank_balance'],
                'action_type': info['action_type'],
                'action_amount': info['action_amount']
            })

            if done:
                break

        final_info = episode_info[-1] if episode_info else {}
        episode_results.append({
            'episode': episode,
            'total_reward': total_reward,
            'final_net_worth': final_info.get('net_worth', 0),
            'final_age': final_info.get('age', 0),
            'steps': steps,
            'trajectory': episode_info
        })

        print(f"Episode {episode + 1:2d}: Reward={total_reward:8.2f}, "
              f"Final Net Worth=${final_info.get('net_worth', 0):,.0f}, "
              f"Final Age={final_info.get('age', 0)}")

    # Calculate statistics
    avg_reward = np.mean([r['total_reward'] for r in episode_results])
    avg_net_worth = np.mean([r['final_net_worth'] for r in episode_results])
    avg_final_age = np.mean([r['final_age'] for r in episode_results])

    print("\nEvaluation Summary:")
    print(f"Average Reward: {avg_reward:.2f}")
    print(f"Average Final Net Worth: ${avg_net_worth:,.0f}")
    print(f"Average Final Age: {avg_final_age:.1f}")

    return episode_results


def main():
    """Main training function"""
    training_scenarios = ['basic', 'high_earner', 'low_earner', 'mid_career']

    parser = argparse.ArgumentParser(description='Train Financial DQN Agent')
    parser.add_argument('--scenario', type=str, default='basic', choices=training_scenarios, help='Training scenario')
    parser.add_argument('--episodes', type=int, default=None, help='Number of training episodes')
    parser.add_argument('--load_model', type=str, default=None, help='Path to load existing model')
    parser.add_argument('--eval_only', action='store_true', help='Only evaluate, do not train')
    parser.add_argument('--plot_results', action='store_true', help='Plot training results')
    parser.add_argument('--save_plots', type=str, default=None, help='Path to save training plots')

    args = parser.parse_args()

    # Create output directories
    Path(BASE_PATH, 'models').mkdir(exist_ok=True)
    Path(BASE_PATH, 'plots').mkdir(exist_ok=True)
    Path(BASE_PATH, 'results').mkdir(exist_ok=True)

    # Create environment
    print(f"Creating environment for scenario: {args.scenario}")

    if args.scenario == 'basic':
        env = FinancialLifeEnvGenerator.create_basic_env()
    elif args.scenario == 'high_earner':
        env = FinancialLifeEnvGenerator.create_high_earner_env()
    elif args.scenario == 'low_earner':
        env = FinancialLifeEnvGenerator.create_low_earner_env()
    elif args.scenario == 'mid_career':
        env = FinancialLifeEnvGenerator.create_mid_career_env()
    else:
        env = FinancialLifeEnvGenerator.create_basic_env()

    # Get environment info
    state_size = env.observation_space.shape[0]
    action_size = env.action_space['action_type'].n

    print(f"State size: {state_size}")
    print(f"Action size: {action_size}")

    # Create agent
    agent_config = create_agent_config(args.scenario)
    agent = FinancialDQNAgent(state_size, action_size, agent_config)

    # Load existing model if specified
    if args.load_model:
        agent.load_model(args.load_model)

    # Create trainer
    training_config = create_training_config(args.scenario)
    if args.episodes:
        training_config['num_episodes'] = args.episodes

    trainer = FinancialDQNTrainer(env, agent, training_config)

    if not args.eval_only:
        # Train the agent
        print("Starting training...")
        trainer.train()

        # Save training results
        results_path = BASE_PATH / 'results' / f'training_results_{args.scenario}.json'
        with open(results_path, 'w') as f:
            json.dump(trainer.get_training_stats(), f, indent=2)
        print(f"Training results saved to {results_path}")

    # Evaluate the agent
    print("\nEvaluating final agent performance...")
    eval_results = evaluate_trained_agent(agent, env, num_episodes=10)

    # Save evaluation results
    eval_path = BASE_PATH / 'results' / f'evaluation_results_{args.scenario}.json'
    with open(eval_path, 'w') as f:
        # Convert numpy arrays to lists for JSON serialization
        json_results = []
        for result in eval_results:
            json_result = result.copy()
            json_result['trajectory'] = result['trajectory']  # Already JSON-serializable
            json_results.append(json_result)
        json.dump(json_results, f, indent=2)
    print(f"Evaluation results saved to {eval_path}")

    # Plot results
    if args.plot_results or args.save_plots:
        plot_path = args.save_plots or os.path.join(BASE_PATH, 'plots', f'training_results_{args.scenario}.png')
        plot_training_results(trainer, plot_path)

    print("Training and evaluation completed!")


if __name__ == '__main__':
    main()
