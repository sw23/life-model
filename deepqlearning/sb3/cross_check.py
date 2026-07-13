#!/usr/bin/env python3
# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Stable-Baselines3 cross-check (Plan 19 D4 optional integration).

Trains an *external* SB3 agent (DQN or PPO) on the exact same :class:`FinancialLifeEnv` and scores
it with the same statistical evaluation protocol used for the in-house agent. This is an
independent sanity bound: if a well-known library's agent lands in the same ballpark as ours (and
both clear the planner-heuristic bar), that is evidence the environment and objective are learnable
and our result is not an artifact of our own trainer.

This script is deliberately standalone: **nothing in the main trainer, the environment, or the
test suite imports it or Stable-Baselines3.** Install the optional dependency only to run it::

    pip install -r requirements-rl.txt -r requirements-rl-sb3.txt
    python deepqlearning/sb3/cross_check.py --algo dqn --timesteps 200000

SB3 has no built-in action masking, so illegal actions simply no-op in the env (they waste a turn);
the agent learns to avoid them. That is a weaker setup than our masked agent — appropriate for a
loose external bound, not a head-to-head.
"""

import argparse
import json
import os
import sys

# Make the flat RL modules importable (environment, baselines, evaluation) and the source tree.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..")))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "src")))

from environment import FinancialLifeEnv  # noqa: E402
from evaluation import EvalProtocol, run_policy_episode  # noqa: E402
from rewards import DEFAULT_PRESET  # noqa: E402


def _require_sb3():
    try:
        import stable_baselines3  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "Stable-Baselines3 is not installed. Run:\n"
            "    pip install -r requirements-rl.txt -r requirements-rl-sb3.txt"
        ) from exc


def sb3_policy(model):
    """Adapt a trained SB3 model to the evaluation protocol's ``env -> action`` interface."""

    def policy(env: FinancialLifeEnv) -> int:
        obs = env._get_observation()
        action, _ = model.predict(obs, deterministic=True)
        return int(action)

    return policy


def main() -> None:
    parser = argparse.ArgumentParser(description="SB3 cross-check on the financial life env")
    parser.add_argument("--algo", choices=["dqn", "ppo"], default="dqn")
    parser.add_argument("--timesteps", type=int, default=200_000)
    parser.add_argument("--reward-preset", default=DEFAULT_PRESET)
    parser.add_argument("--n-eval", type=int, default=50)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--report", default=os.path.join(_HERE, "sb3_cross_check_report.json"))
    args = parser.parse_args()

    _require_sb3()
    from stable_baselines3 import DQN, PPO

    def make_env():
        return FinancialLifeEnv({"reward_preset": args.reward_preset})

    Algo = DQN if args.algo == "dqn" else PPO
    print(f"Training SB3 {args.algo.upper()} for {args.timesteps} timesteps on preset {args.reward_preset}")
    model = Algo("MlpPolicy", make_env(), seed=args.seed, verbose=1)
    model.learn(total_timesteps=args.timesteps)

    # Score the SB3 agent alongside the baselines with the same protocol.
    protocol = EvalProtocol(
        env_config={}, reward_preset=args.reward_preset, n_eval=args.n_eval, master_seed=12345
    )
    env = make_env()
    seeds = protocol._conditions()["train"]["seeds"]
    outcomes = [run_policy_episode(env, sb3_policy(model), s) for s in seeds]
    import numpy as np

    sb3_mean = float(np.mean([o.total_reward for o in outcomes]))
    report = protocol.run()  # baselines on the same seeds
    report[f"sb3_{args.algo}"] = {
        "timesteps": args.timesteps,
        "mean_return_train": sb3_mean,
        "ruin_rate": float(np.mean([o.ruined for o in outcomes])),
        "success_rate": float(np.mean([o.success for o in outcomes])),
    }
    with open(args.report, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSB3 {args.algo.upper()} mean return (train): {sb3_mean:.2f}")
    print(f"Cross-check report written to {args.report}")


if __name__ == "__main__":
    main()
