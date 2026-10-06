#!/usr/bin/env python3
# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Unified training entry point: any registered environment x any algorithm.

    python -m deepqlearning.train --env financial:basic      --algo dqn --total-env-steps 200000 --num-envs 8
    python -m deepqlearning.train --env financial:mid_career --algo ppo --total-env-steps 200000

Two collection modes: ``--total-env-steps`` (the default) runs the vectorized step-budget trainer,
``--episodes`` runs the single-environment episodic trainer. Hyperparameters are set with repeatable
``--set key=value`` overrides, routed by a dotted prefix — ``--set algo.learning_rate=3e-4``,
``--set env.reward_preset=wealth_max``, ``--set train.eval_freq_steps=2000``.

The financial-only options (reward preset, the statistical evaluation protocol, the scripted
baseline comparison) are rejected on non-financial environments rather than silently ignored, and
outputs are keyed ``{env}_{algo}`` so runs of different pairings never overwrite each other.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import matplotlib

# Use a non-interactive backend when there is no display so training never blocks in headless
# runs (CI, servers). Interactive backends are kept when a display is available.
if not os.environ.get("DISPLAY") and not sys.platform.startswith("darwin"):
    matplotlib.use("Agg")

# Importable both as ``python -m deepqlearning.train`` and as a bare script path.
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

import matplotlib.pyplot as plt
import numpy as np

from deepqlearning.algos import ALGORITHMS
from deepqlearning.envs.registry import make_env, registered_env_names, resolve_env_spec
from deepqlearning.training.episode_trainer import EpisodeTrainer
from deepqlearning.training.rollout import rollout
from deepqlearning.training.trainer import Trainer

# Output roots live next to this file so a run started from anywhere writes to the same place.
BASE_PATH = Path(__file__).resolve().parent


def parse_overrides(assignments: list[str] | None) -> dict[str, dict]:
    """Split ``section.key=value`` strings into per-section config dicts.

    Values are parsed as JSON when possible (so ``true``, ``0.001``, ``[64,64]``, and ``null`` come
    through as the right Python types) and kept as strings otherwise. A key with no section prefix
    is treated as an algorithm hyperparameter, which is what most tuning touches.
    """
    sections: dict[str, dict] = {"algo": {}, "env": {}, "train": {}}
    for assignment in assignments or []:
        if "=" not in assignment:
            raise SystemExit(f"--set expects KEY=VALUE, got {assignment!r}")
        key, raw_value = assignment.split("=", 1)
        section, _, name = key.rpartition(".")
        section = section or "algo"
        if section not in sections:
            raise SystemExit(f"Unknown --set section {section!r}; expected one of {sorted(sections)}")
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError:
            value = raw_value
        sections[section][name] = value
    return sections


def plot_training_results(trainer: EpisodeTrainer, save_path: str | None = None, show: bool = False):
    """Plot training results.

    Args:
        trainer: The trainer whose metrics to plot.
        save_path: If given, the figure is written here.
        show: Whether to display the figure interactively. Ignored on the non-interactive Agg
            backend so headless runs never block.
    """

    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle("Training Results", fontsize=16)

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
    if trainer.algo.training_losses:
        axes[1, 0].plot(trainer.algo.training_losses)
        axes[1, 0].set_title("Training Loss")
        axes[1, 0].set_xlabel("Update")
        axes[1, 0].set_ylabel("Loss")
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


def evaluate_agent(algo, env, num_episodes: int = 10, financial: bool = False, compare_baselines: bool = False):
    """Run greedy episodes, print a per-episode line, and return their results.

    ``financial`` adds the household columns (terminal net worth, age at the end) that only the
    financial environment publishes. With ``compare_baselines`` the scripted baselines are scored
    on the same seeds: an agent that cannot beat "do nothing" is a red flag for the environment or
    the training run, not a subtle tuning problem.
    """

    print(f"\nEvaluating trained agent over {num_episodes} episodes...")

    episode_results = []

    for episode in range(num_episodes):
        result = rollout(env, algo, training=False, seed=2_000_000 + episode, collect_trajectory=financial)
        final_info = result.trajectory[-1] if result.trajectory else {}
        record = {"episode": episode, "total_reward": result.total_reward, "steps": result.steps}
        line = f"Episode {episode + 1:2d}: Reward={result.total_reward:8.2f}, Steps={result.steps:3d}"
        if financial:
            record["final_net_worth"] = final_info.get("net_worth") or 0.0
            record["final_age"] = final_info.get("age") or 0
            record["trajectory"] = result.trajectory
            line += f", Final Net Worth=${record['final_net_worth']:,.0f}, Final Age={record['final_age']}"
        episode_results.append(record)
        print(line)

    # Calculate statistics
    avg_reward = np.mean([r["total_reward"] for r in episode_results])

    print("\nEvaluation Summary:")
    print(f"Average Reward: {avg_reward:.2f}")
    print(f"Average Steps: {np.mean([r['steps'] for r in episode_results]):.1f}")
    if financial:
        print(f"Average Final Net Worth: ${np.mean([r['final_net_worth'] for r in episode_results]):,.0f}")
        print(f"Average Final Age: {np.mean([r['final_age'] for r in episode_results]):.1f}")

    if compare_baselines:
        from deepqlearning.evaluation.baselines import evaluate_all_baselines

        seeds = [2_000_000 + i for i in range(num_episodes)]
        baseline_scores = evaluate_all_baselines(env, seeds)
        print("\nBaseline comparison (same seeds):")
        print(f"  Agent:           {avg_reward:8.2f}")
        for name, score in baseline_scores.items():
            print(f"  {name:16s} {score:8.2f}")

    return episode_results


def run_protocol_report(agent, env_config, preset, out_path, n_eval, master_seed=12345):
    """Run the statistical protocol on the trained agent + all baselines, print the comparison
    table, and write the JSON report."""
    from deepqlearning.evaluation.protocol import EvalProtocol, format_comparison_table

    protocol = EvalProtocol(env_config=env_config, reward_preset=preset, n_eval=n_eval, master_seed=master_seed)
    report = protocol.run(agent=agent)
    print("\n" + format_comparison_table(report))
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nProtocol report saved to {out_path}")
    return report


def build_parser() -> argparse.ArgumentParser:
    from deepqlearning.envs.financial.rewards import DEFAULT_PRESET, REWARD_PRESETS

    parser = argparse.ArgumentParser(description="Train an RL agent on a registered environment")
    parser.add_argument(
        "--env",
        type=str,
        default="financial:basic",
        help=f"Registered environment name. Known: {', '.join(registered_env_names())}",
    )
    parser.add_argument("--algo", type=str, default="dqn", choices=sorted(ALGORITHMS), help="Algorithm to train")
    parser.add_argument("--episodes", type=int, default=None, help="Train with the episodic trainer for N episodes")
    parser.add_argument("--total-env-steps", type=int, default=200_000, help="Vectorized trainer: collection budget")
    parser.add_argument("--num-envs", type=int, default=8, help="Vectorized trainer: number of parallel envs")
    parser.add_argument("--backend", type=str, default="sync", choices=["sync", "async"], help="Vector env backend")
    parser.add_argument("--load-model", type=str, default=None, help="Path to an existing checkpoint to load")
    parser.add_argument("--eval-only", action="store_true", help="Only evaluate, do not train")
    parser.add_argument("--tensorboard", type=str, default=None, help="TensorBoard log dir (vectorized trainer)")
    parser.add_argument("--plot-results", action="store_true", help="Plot training results (episodic trainer)")
    parser.add_argument("--save-plots", type=str, default=None, help="Path to save training plots")
    parser.add_argument("--eval-episodes", type=int, default=10, help="Greedy episodes in the final evaluation")
    parser.add_argument(
        "--set",
        dest="overrides",
        action="append",
        metavar="SECTION.KEY=VALUE",
        help="Config override; SECTION is algo (default), env, or train. Repeatable.",
    )
    # --- financial-only ---
    parser.add_argument(
        "--reward-preset",
        type=str,
        default=DEFAULT_PRESET,
        choices=sorted(REWARD_PRESETS),
        help="Reward objective preset (financial environments only)",
    )
    parser.add_argument("--protocol-eval", action="store_true", help="Run the statistical protocol at the end")
    parser.add_argument("--protocol-n-eval", type=int, default=50, help="Episodes per policy per condition")
    parser.add_argument(
        "--compare-baselines", action="store_true", help="Score the scripted baselines on the eval seeds"
    )
    return parser


def _reject_financial_only_flags(args, parser) -> None:
    """Fail loudly when a financial-only flag is used on an environment that has no such notion."""
    used = []
    if args.protocol_eval:
        used.append("--protocol-eval")
    if args.compare_baselines:
        used.append("--compare-baselines")
    if args.reward_preset != parser.get_default("reward_preset"):
        used.append("--reward-preset")
    if used:
        parser.error(f"{', '.join(used)} apply to financial environments only, but --env is {args.env!r}")


def main():
    """Parse the command line, train, evaluate, and write the run's artifacts."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        spec = resolve_env_spec(args.env)
    except KeyError as exc:
        parser.error(exc.args[0])
    is_financial = spec.domain == "financial"
    if not is_financial:
        _reject_financial_only_flags(args, parser)

    overrides = parse_overrides(args.overrides)

    for directory in ("models", "plots", "results"):
        Path(BASE_PATH, directory).mkdir(exist_ok=True)
    run_key = f"{args.env.replace(':', '_')}_{args.algo}"
    model_path = str(BASE_PATH / "models" / f"{run_key}.pt")

    # Build the environment first: the algorithm is sized from its spaces.
    env_config = dict(overrides["env"])
    if is_financial:
        env_config.setdefault("reward_preset", args.reward_preset)
    print(f"Creating environment {args.env} (domain: {spec.domain})")
    env = make_env(args.env, env_config)
    print(f"Observation space: {env.observation_space}")
    print(f"Action space: {env.action_space}")

    algo_config = dict(overrides["algo"])
    if is_financial:
        # The financial observation layout is versioned, so checkpoints are pinned to it.
        from deepqlearning.envs.financial.environment import OBS_VERSION

        algo_config.setdefault("obs_version", OBS_VERSION)
    if args.algo == "ppo":
        algo_config.setdefault("num_envs", 1 if args.episodes else args.num_envs)
    algo = ALGORITHMS[args.algo](env.observation_space, env.action_space, algo_config)

    if args.load_model:
        algo.load(args.load_model)

    # The exact config the env was built with, so the vector trainer and the protocol rebuild it
    # faithfully rather than falling back to the registry defaults.
    resolved_env_config = dict(getattr(env, "config", env_config))

    trainer = None
    if not args.eval_only:
        print("Starting training...")
        if args.episodes:
            episode_config = {
                "num_episodes": args.episodes,
                "save_freq": 100,
                "eval_freq": 50,
                "eval_episodes": 5,
                "print_freq": 25,
                "model_save_path": model_path,
            }
            if is_financial:
                from deepqlearning.evaluation.protocol import format_final_infos

                episode_config["eval_summary"] = format_final_infos
            episode_config.update(overrides["train"])
            trainer = EpisodeTrainer(env, algo, episode_config)
            trainer.train()
            results_path = BASE_PATH / "results" / f"training_results_{run_key}.json"
            with open(results_path, "w") as f:
                json.dump(trainer.get_training_stats(), f, indent=2)
            print(f"Training results saved to {results_path}")
        else:
            vector_config = {
                "num_envs": args.num_envs,
                "backend": args.backend,
                "total_env_steps": args.total_env_steps,
                "tensorboard_logdir": args.tensorboard,
                "model_save_path": model_path,
                "lr_schedule": "cosine",
            }
            vector_config.update(overrides["train"])
            stats = Trainer(algo, args.env, resolved_env_config, vector_config).train()
            print(
                f"Vectorized training done: {stats['episodes']} episodes, "
                f"{stats['collected_env_steps']} env steps, best eval {stats['best_eval_return']:.2f}"
            )

    # Evaluate the agent
    print("\nEvaluating final agent performance...")
    eval_results = evaluate_agent(
        algo,
        env,
        num_episodes=args.eval_episodes,
        financial=is_financial,
        compare_baselines=args.compare_baselines,
    )

    eval_path = BASE_PATH / "results" / f"evaluation_results_{run_key}.json"
    with open(eval_path, "w") as f:
        json.dump(eval_results, f, indent=2)
    print(f"Evaluation results saved to {eval_path}")

    # Statistical protocol report: agent vs every baseline on shared seeds.
    if args.protocol_eval:
        report_path = BASE_PATH / "results" / f"protocol_report_{run_key}_{args.reward_preset}.json"
        run_protocol_report(algo, resolved_env_config, args.reward_preset, str(report_path), args.protocol_n_eval)

    # Plot results (episodic trainer only — the vectorized trainer has no per-episode curve)
    if (args.plot_results or args.save_plots) and trainer is not None:
        plot_path = args.save_plots or os.path.join(BASE_PATH, "plots", f"training_results_{run_key}.png")
        plot_training_results(trainer, plot_path, show=args.plot_results)

    print("Training and evaluation completed!")


if __name__ == "__main__":
    main()
