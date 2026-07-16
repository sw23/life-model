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

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

import matplotlib

# Use a non-interactive backend when there is no display so training never blocks in headless
# runs (CI, servers). Interactive backends are kept when a display is available.
if not os.environ.get("DISPLAY") and not sys.platform.startswith("darwin"):
    matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from agent import FinancialDQNAgent, FinancialDQNTrainer, rollout  # noqa: E402
from baselines import evaluate_all_baselines  # noqa: E402
from environment import FinancialLifeEnv, FinancialLifeEnvGenerator  # noqa: E402
from evaluation import EvalProtocol, format_comparison_table  # noqa: E402
from rewards import DEFAULT_PRESET, REWARD_PRESETS  # noqa: E402
from vector_trainer import VectorizedTrainer  # noqa: E402

# set base path to be the root of this file
BASE_PATH = Path(__file__).resolve().parent


def create_training_config(scenario: str = "basic") -> dict:
    """Create training configuration for different scenarios"""

    base_config = {
        "num_episodes": 2000,
        "save_freq": 100,
        "eval_freq": 50,
        "eval_episodes": 5,
        "print_freq": 25,
        "model_save_path": BASE_PATH / "models" / f"financial_dqn_{scenario}.pt",
    }

    if scenario == "basic":
        return base_config
    elif scenario == "high_earner":
        config = base_config.copy()
        config["model_save_path"] = BASE_PATH / "models" / "financial_dqn_high_earner.pt"
        config["num_episodes"] = 1500
        return config
    elif scenario == "low_earner":
        config = base_config.copy()
        config["model_save_path"] = BASE_PATH / "models" / "financial_dqn_low_earner.pt"
        config["num_episodes"] = 2500
        return config
    else:
        return base_config


def create_agent_config(scenario: str = "basic") -> dict:
    """Create agent configuration for different scenarios.

    Note: the legacy ``epsilon_decay`` key is gone — the agent decays epsilon per-episode over
    ``epsilon_decay_fraction`` of training, so a per-step multiplier was dead config that misled
    tuners (Plan 19 D4). The D4 upgrades (prioritized replay, n-step returns) are on by default in
    the agent's own config.
    """

    base_config = {
        "learning_rate": 1e-4,
        "batch_size": 64,
        "gamma": 0.99,
        "epsilon_start": 1.0,
        "epsilon_end": 0.01,
        "epsilon_decay_fraction": 0.6,
        "target_update_freq": 100,
        "replay_buffer_size": 50000,
        "min_replay_size": 1000,
        "hidden_sizes": [512, 256, 128],
        "use_dueling": True,
        "use_double_dqn": True,
        "use_prioritized_replay": True,
        "n_step": 3,
    }

    if scenario == "high_earner":
        # High earners might need more complex decision making
        config = base_config.copy()
        config["hidden_sizes"] = [1024, 512, 256]
        config["replay_buffer_size"] = 100000
        return config
    elif scenario == "low_earner":
        # Low earners might need longer exploration
        config = base_config.copy()
        config["epsilon_decay_fraction"] = 0.75
        config["epsilon_end"] = 0.05
        return config
    else:
        return base_config


def plot_training_results(trainer: FinancialDQNTrainer, save_path: Optional[str] = None, show: bool = False):
    """Plot training results.

    Args:
        trainer: The trainer whose metrics to plot.
        save_path: If given, the figure is written here.
        show: Whether to display the figure interactively. Ignored on the non-interactive Agg
            backend so headless runs never block.
    """

    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle("Financial DQN Training Results", fontsize=16)

    # Episode rewards
    axes[0, 0].plot(trainer.episode_rewards)
    axes[0, 0].set_title("Episode Rewards")
    axes[0, 0].set_xlabel("Episode")
    axes[0, 0].set_ylabel("Total Reward")
    axes[0, 0].grid(True)

    # Moving average of rewards
    if len(trainer.episode_rewards) > 100:
        moving_avg = np.convolve(trainer.episode_rewards, np.ones(100) / 100, mode="valid")
        axes[0, 1].plot(moving_avg)
        axes[0, 1].set_title("Moving Average Reward (100 episodes)")
        axes[0, 1].set_xlabel("Episode")
        axes[0, 1].set_ylabel("Average Reward")
        axes[0, 1].grid(True)

    # Training loss
    if trainer.agent.training_losses:
        axes[1, 0].plot(trainer.agent.training_losses)
        axes[1, 0].set_title("Training Loss")
        axes[1, 0].set_xlabel("Training Step")
        axes[1, 0].set_ylabel("MSE Loss")
        axes[1, 0].grid(True)

    # Evaluation rewards
    if trainer.eval_rewards:
        eval_episodes = np.arange(len(trainer.eval_rewards)) * trainer.config["eval_freq"]
        axes[1, 1].plot(eval_episodes, trainer.eval_rewards, "o-")
        axes[1, 1].set_title("Evaluation Rewards")
        axes[1, 1].set_xlabel("Episode")
        axes[1, 1].set_ylabel("Average Evaluation Reward")
        axes[1, 1].grid(True)

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches="tight")
        print(f"Training plots saved to {save_path}")

    if show and matplotlib.get_backend().lower() != "agg":
        plt.show()
    plt.close(fig)


def evaluate_trained_agent(agent: FinancialDQNAgent, env: FinancialLifeEnv, num_episodes: int = 10):
    """Evaluate a trained agent and show detailed results"""

    print(f"\nEvaluating trained agent over {num_episodes} episodes...")

    episode_results = []

    for episode in range(num_episodes):
        result = rollout(env, agent, training=False, seed=2_000_000 + episode, collect_trajectory=True)
        final_info = result.trajectory[-1] if result.trajectory else {}
        episode_results.append(
            {
                "episode": episode,
                "total_reward": result.total_reward,
                "final_net_worth": final_info.get("net_worth", 0),
                "final_age": final_info.get("age", 0),
                "steps": result.steps,
                "trajectory": result.trajectory,
            }
        )

        print(
            f"Episode {episode + 1:2d}: Reward={result.total_reward:8.2f}, "
            f"Final Net Worth=${final_info.get('net_worth', 0):,.0f}, "
            f"Final Age={final_info.get('age', 0)}"
        )

    # Calculate statistics
    avg_reward = np.mean([r["total_reward"] for r in episode_results])
    avg_net_worth = np.mean([r["final_net_worth"] for r in episode_results])
    avg_final_age = np.mean([r["final_age"] for r in episode_results])

    print("\nEvaluation Summary:")
    print(f"Average Reward: {avg_reward:.2f}")
    print(f"Average Final Net Worth: ${avg_net_worth:,.0f}")
    print(f"Average Final Age: {avg_final_age:.1f}")

    # Compare against scripted baselines on the same seeds (an agent that can't beat "do nothing"
    # is a red flag for the environment or training).
    seeds = [2_000_000 + i for i in range(num_episodes)]
    baseline_scores = evaluate_all_baselines(env, seeds)
    print("\nBaseline comparison (same seeds):")
    print(f"  Agent:           {avg_reward:8.2f}")
    for name, score in baseline_scores.items():
        print(f"  {name:16s} {score:8.2f}")

    return episode_results


def run_protocol_report(agent, env_config, preset, out_path, n_eval, master_seed=12345):
    """Run the D3 statistical protocol on the trained agent + all baselines, print the comparison
    table, and write the JSON report."""
    protocol = EvalProtocol(env_config=env_config, reward_preset=preset, n_eval=n_eval, master_seed=master_seed)
    report = protocol.run(agent=agent)
    print("\n" + format_comparison_table(report))
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nProtocol report saved to {out_path}")
    return report


def main():
    """Main training function"""
    training_scenarios = ["basic", "high_earner", "low_earner", "mid_career"]

    parser = argparse.ArgumentParser(description="Train Financial DQN Agent")
    parser.add_argument("--scenario", type=str, default="basic", choices=training_scenarios, help="Training scenario")
    parser.add_argument("--episodes", type=int, default=None, help="Number of training episodes (single-env trainer)")
    parser.add_argument("--load_model", type=str, default=None, help="Path to load existing model")
    parser.add_argument("--eval_only", action="store_true", help="Only evaluate, do not train")
    parser.add_argument("--plot_results", action="store_true", help="Plot training results")
    parser.add_argument("--save_plots", type=str, default=None, help="Path to save training plots")
    parser.add_argument(
        "--reward-preset",
        type=str,
        default=DEFAULT_PRESET,
        choices=sorted(REWARD_PRESETS),
        help="Reward objective preset (Plan 19 D1)",
    )
    parser.add_argument("--vectorized", action="store_true", help="Use the vectorized trainer (Plan 19 D4)")
    parser.add_argument("--num-envs", type=int, default=8, help="Vectorized trainer: number of parallel envs")
    parser.add_argument("--backend", type=str, default="sync", choices=["sync", "async"], help="Vector env backend")
    parser.add_argument("--total-env-steps", type=int, default=200_000, help="Vectorized trainer: collection budget")
    parser.add_argument("--tensorboard", type=str, default=None, help="TensorBoard log dir (vectorized trainer)")
    parser.add_argument("--protocol-eval", action="store_true", help="Run the D3 statistical protocol at the end")
    parser.add_argument("--protocol-n-eval", type=int, default=50, help="Episodes per policy per condition")

    args = parser.parse_args()

    # Create output directories
    Path(BASE_PATH, "models").mkdir(exist_ok=True)
    Path(BASE_PATH, "plots").mkdir(exist_ok=True)
    Path(BASE_PATH, "results").mkdir(exist_ok=True)

    # Create environment. The scenario supplies the point household; the reward preset is threaded
    # through so training and evaluation share one objective.
    print(f"Creating environment for scenario: {args.scenario} (reward preset: {args.reward_preset})")
    env_config = {"reward_preset": args.reward_preset}
    if args.scenario == "basic":
        env = FinancialLifeEnvGenerator.create_scenario_env("basic", env_config)
    else:
        env = FinancialLifeEnvGenerator.create_scenario_env(args.scenario, env_config)
    # The exact config the env was built with (so the vector trainer / protocol rebuild it faithfully).
    scenario_config = dict(env.config)
    scenario_config["reward_preset"] = args.reward_preset

    state_size = env.observation_space.shape[0]
    action_size = env.action_space.n
    print(f"State size: {state_size}")
    print(f"Action size: {action_size}")

    # Create agent
    agent_config = create_agent_config(args.scenario)
    agent = FinancialDQNAgent(state_size, action_size, agent_config)

    if args.load_model:
        agent.load_model(args.load_model)

    trainer = None
    if not args.eval_only:
        print("Starting training...")
        if args.vectorized:
            model_path = str(BASE_PATH / "models" / f"financial_dqn_{args.scenario}.pt")
            vtrainer = VectorizedTrainer(
                agent,
                env_config=scenario_config,
                config={
                    "num_envs": args.num_envs,
                    "backend": args.backend,
                    "total_env_steps": args.total_env_steps,
                    "tensorboard_logdir": args.tensorboard,
                    "model_save_path": model_path,
                    "lr_schedule": "cosine",
                },
            )
            stats = vtrainer.train()
            print(
                f"Vectorized training done: {stats['episodes']} episodes, "
                f"{stats['collected_env_steps']} env steps, best eval {stats['best_eval_return']:.2f}"
            )
        else:
            training_config = create_training_config(args.scenario)
            if args.episodes:
                training_config["num_episodes"] = args.episodes
            trainer = FinancialDQNTrainer(env, agent, training_config)
            trainer.train()
            results_path = BASE_PATH / "results" / f"training_results_{args.scenario}.json"
            with open(results_path, "w") as f:
                json.dump(trainer.get_training_stats(), f, indent=2)
            print(f"Training results saved to {results_path}")

    # Evaluate the agent
    print("\nEvaluating final agent performance...")
    eval_results = evaluate_trained_agent(agent, env, num_episodes=10)

    eval_path = BASE_PATH / "results" / f"evaluation_results_{args.scenario}.json"
    with open(eval_path, "w") as f:
        json.dump([{**r, "trajectory": r["trajectory"]} for r in eval_results], f, indent=2)
    print(f"Evaluation results saved to {eval_path}")

    # Statistical protocol report (Plan 19 D3): agent vs every baseline on shared seeds.
    if args.protocol_eval:
        report_path = BASE_PATH / "results" / f"protocol_report_{args.scenario}_{args.reward_preset}.json"
        run_protocol_report(agent, scenario_config, args.reward_preset, str(report_path), args.protocol_n_eval)

    # Plot results (single-env trainer only)
    if (args.plot_results or args.save_plots) and trainer is not None:
        plot_path = args.save_plots or os.path.join(BASE_PATH, "plots", f"training_results_{args.scenario}.png")
        plot_training_results(trainer, plot_path, show=args.plot_results)

    print("Training and evaluation completed!")


if __name__ == "__main__":
    main()
