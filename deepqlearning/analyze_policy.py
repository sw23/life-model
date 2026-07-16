#!/usr/bin/env python3
# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Policy-analysis artifacts for a trained agent (Plan 19 D5).

Turns a black-box checkpoint into human-checkable pictures of *what the policy does*:

* **Action heatmap** — the dominant action category over an age x wealth-decile grid, built from
  real greedy-eval trajectories (not synthetic states). This is where a human checks the agent
  learned sane behavior — "contribute early, draw down in retirement" — rather than an exploit.
* **Contribution / withdrawal schedule by age** — average dollars contributed and withdrawn per
  year of age across eval episodes.
* **Lifetime trace** — one annotated episode: a year-by-year table of age, net worth, action, and
  reward, saved as JSON and rendered as a net-worth-over-life figure.

All figures are written with the headless Agg backend, so artifacts generate on servers/CI. The
functions return the underlying data too, so a notebook can render them inline.
"""

import argparse
import json
import os
from collections import Counter
from typing import Dict, List, Optional

import matplotlib

matplotlib.use("Agg")  # headless: never require a display (Plan 19 D5)

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from actions import ActionType  # noqa: E402
from agent import FinancialDQNAgent, rollout  # noqa: E402
from environment import FinancialLifeEnv  # noqa: E402

# Coarse action categories for a readable heatmap.
_CATEGORIES = ["noop", "contribute", "withdraw", "spend", "retire"]
_CATEGORY_COLORS = ["#d9d9d9", "#2c7fb8", "#d95f0e", "#7fbf7b", "#756bb1"]


def _categorize(action_type: Optional[str]) -> str:
    if action_type is None:
        return "noop"
    if action_type.startswith("transfer_"):
        return "contribute"
    if action_type.startswith("withdraw_"):
        return "withdraw"
    if action_type in (ActionType.INCREASE_SPENDING.value, ActionType.DECREASE_SPENDING.value):
        return "spend"
    if action_type == ActionType.RETIRE_EARLY.value:
        return "retire"
    return "noop"


def collect_greedy_trajectories(
    agent: FinancialDQNAgent, env_config: Optional[Dict], n_episodes: int, seed_base: int = 3_000_000
) -> List[List[Dict]]:
    """Run ``n_episodes`` greedy episodes and return their step-by-step trajectories."""
    env = FinancialLifeEnv(env_config or {})
    old_eps = agent.epsilon
    agent.epsilon = 0.0
    trajectories = []
    for i in range(n_episodes):
        result = rollout(env, agent, training=False, seed=seed_base + i, collect_trajectory=True)
        trajectories.append(result.trajectory)
    agent.epsilon = old_eps
    return trajectories


def action_heatmap(trajectories: List[List[Dict]], out_path: str, n_wealth_bins: int = 10) -> Dict:
    """Dominant action category over an age x wealth-decile grid, saved as a PNG.

    Returns the grid data (category index per cell, plus the age/wealth edges) for inline rendering.
    """
    ages = np.array([s["age"] for traj in trajectories for s in traj if s.get("age") is not None])
    nets = np.array([s["net_worth"] for traj in trajectories for s in traj if s.get("age") is not None])
    cats = [_categorize(s.get("action_type")) for traj in trajectories for s in traj if s.get("age") is not None]

    age_edges = np.linspace(ages.min(), ages.max() + 1e-6, 9)
    wealth_edges = np.unique(np.quantile(nets, np.linspace(0, 1, n_wealth_bins + 1)))
    n_age = len(age_edges) - 1
    n_wealth = len(wealth_edges) - 1

    # Per cell: modal category (or -1 if empty).
    buckets: Dict = {(a, w): Counter() for a in range(n_age) for w in range(n_wealth)}
    age_idx = np.clip(np.digitize(ages, age_edges) - 1, 0, n_age - 1)
    wealth_idx = np.clip(np.digitize(nets, wealth_edges) - 1, 0, n_wealth - 1)
    for a, w, c in zip(age_idx, wealth_idx, cats):
        buckets[(a, w)][c] += 1

    grid = np.full((n_wealth, n_age), -1, dtype=int)
    for (a, w), counter in buckets.items():
        if counter:
            grid[w, a] = _CATEGORIES.index(counter.most_common(1)[0][0])

    cmap = matplotlib.colors.ListedColormap(_CATEGORY_COLORS)
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.imshow(
        np.ma.masked_less(grid, 0),
        origin="lower",
        aspect="auto",
        cmap=cmap,
        vmin=0,
        vmax=len(_CATEGORIES) - 1,
    )
    ax.set_xticks(range(n_age))
    ax.set_xticklabels([f"{age_edges[i]:.0f}-{age_edges[i + 1]:.0f}" for i in range(n_age)], rotation=45, ha="right")
    ax.set_yticks(range(n_wealth))
    ax.set_yticklabels([f"${wealth_edges[i] / 1e3:.0f}k" for i in range(n_wealth)])
    ax.set_xlabel("Age")
    ax.set_ylabel("Net worth decile (lower edge)")
    ax.set_title("Dominant action by age x wealth")
    handles = [plt.Rectangle((0, 0), 1, 1, color=_CATEGORY_COLORS[i]) for i in range(len(_CATEGORIES))]
    ax.legend(handles, _CATEGORIES, bbox_to_anchor=(1.02, 1), loc="upper left")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return {
        "grid": grid.tolist(),
        "categories": _CATEGORIES,
        "age_edges": age_edges.tolist(),
        "wealth_edges": wealth_edges.tolist(),
    }


def contribution_schedule(trajectories: List[List[Dict]], out_path: str) -> Dict:
    """Average dollars contributed / withdrawn per year of age across episodes, saved as a PNG."""
    by_age_contrib: Dict[int, List[float]] = {}
    by_age_withdraw: Dict[int, List[float]] = {}
    for traj in trajectories:
        for s in traj:
            age = s.get("age")
            if age is None:
                continue
            cat = _categorize(s.get("action_type"))
            amount = float(s.get("action_amount") or 0.0)
            by_age_contrib.setdefault(age, []).append(amount if cat == "contribute" else 0.0)
            by_age_withdraw.setdefault(age, []).append(amount if cat == "withdraw" else 0.0)

    ages = sorted(by_age_contrib)
    contrib = [float(np.mean(by_age_contrib[a])) for a in ages]
    withdraw = [float(np.mean(by_age_withdraw[a])) for a in ages]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(ages, contrib, label="avg contribution", color="#2c7fb8")
    ax.plot(ages, withdraw, label="avg withdrawal", color="#d95f0e")
    ax.set_xlabel("Age")
    ax.set_ylabel("Average $ / year")
    ax.set_title("Contribution & withdrawal schedule by age")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return {"ages": ages, "avg_contribution": contrib, "avg_withdrawal": withdraw}


def lifetime_trace(
    agent: FinancialDQNAgent, env_config: Optional[Dict], out_png: str, out_json: str, seed: int = 4_000_000
) -> Dict:
    """One annotated greedy episode: year-by-year state/action/reward, as JSON + a net-worth figure."""
    env = FinancialLifeEnv(env_config or {})
    old_eps = agent.epsilon
    agent.epsilon = 0.0
    state, _ = env.reset(seed=seed)
    rows: List[Dict] = []
    while True:
        legal = env.get_legal_actions()
        action = agent.select_action(state, legal, training=False)
        state, reward, terminated, truncated, info = env.step(action)
        rows.append(
            {
                "age": info.get("age"),
                "net_worth": float(info.get("net_worth", 0.0)),
                "action_type": info.get("action_type"),
                "action_amount": float(info.get("action_amount") or 0.0),
                "reward": float(reward),
                "is_retired": bool(info.get("is_retired")),
            }
        )
        if terminated or truncated:
            break
    agent.epsilon = old_eps

    with open(out_json, "w") as f:
        json.dump(rows, f, indent=2)

    ages = [r["age"] for r in rows]
    nets = [r["net_worth"] for r in rows]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(ages, nets, color="#2c7fb8")
    ax.fill_between(ages, nets, alpha=0.15, color="#2c7fb8")
    retire_age = next((r["age"] for r in rows if r["is_retired"]), None)
    if retire_age is not None:
        ax.axvline(retire_age, color="#d95f0e", linestyle="--", label=f"retired @ {retire_age}")
        ax.legend()
    ax.set_xlabel("Age")
    ax.set_ylabel("Net worth ($)")
    ax.set_title("Lifetime trace: net worth over life (greedy policy)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_png, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return {"rows": rows, "final_net_worth": nets[-1] if nets else 0.0, "steps": len(rows)}


def analyze(agent: FinancialDQNAgent, env_config: Optional[Dict], out_dir: str, n_episodes: int = 50) -> Dict:
    """Generate all D5 artifacts into ``out_dir`` and return a manifest of their data + paths."""
    os.makedirs(out_dir, exist_ok=True)
    trajectories = collect_greedy_trajectories(agent, env_config, n_episodes)
    heatmap = action_heatmap(trajectories, os.path.join(out_dir, "policy_heatmap.png"))
    schedule = contribution_schedule(trajectories, os.path.join(out_dir, "contribution_schedule.png"))
    trace = lifetime_trace(
        agent, env_config, os.path.join(out_dir, "lifetime_trace.png"), os.path.join(out_dir, "lifetime_trace.json")
    )
    manifest = {
        "n_episodes": n_episodes,
        "heatmap": heatmap,
        "schedule": schedule,
        "lifetime_trace_summary": {k: v for k, v in trace.items() if k != "rows"},
    }
    with open(os.path.join(out_dir, "analysis_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Policy analysis artifacts written to {out_dir}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate policy-analysis artifacts for a checkpoint")
    parser.add_argument("--checkpoint", required=True, help="Path to a trained .pt checkpoint")
    parser.add_argument("--reward-preset", default="retirement_security")
    parser.add_argument("--out-dir", default=None, help="Output dir (default: next to the checkpoint)")
    parser.add_argument("--episodes", type=int, default=50)
    args = parser.parse_args()

    env_config = {"reward_preset": args.reward_preset}
    env = FinancialLifeEnv(env_config)
    agent = FinancialDQNAgent(env.observation_space.shape[0], env.action_space.n)
    agent.load_model(args.checkpoint)
    out_dir = args.out_dir or os.path.join(os.path.dirname(os.path.abspath(args.checkpoint)), "analysis")
    analyze(agent, env_config, out_dir, n_episodes=args.episodes)


if __name__ == "__main__":
    main()
