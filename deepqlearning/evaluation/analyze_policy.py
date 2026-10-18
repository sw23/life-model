#!/usr/bin/env python3
# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Policy-analysis artifacts for a trained agent.

Turns a black-box checkpoint into human-checkable pictures of *what the policy does*:

* **Action heatmap** — the dominant action category over an age x wealth-decile grid, built from
  real greedy-eval trajectories (not synthetic states). This is where a human checks the agent
  learned sane behavior — "contribute early, draw down in retirement" — rather than an exploit.
* **Contribution / withdrawal schedule by age** — average dollars contributed and withdrawn per
  year of age across eval episodes.
* **Lifetime trace** — one annotated episode: a year-by-year table of age, net worth, action, and
  reward, saved as JSON and rendered as a net-worth-over-life figure.
* **Policy vector by age** (factored action space, Plan 32 D8) — the standing policies the agent
  keeps in force at each age: per slot, the modal value across greedy episodes and the share of
  decisions at that age that held it, as a table (``policy_vector_by_age.txt`` / ``.json``) and a
  slot x age figure. This replaces the action-category heatmap and the dollar schedule, which
  describe one-off money moves the factored agent does not make.

All figures are written with the headless Agg backend, so artifacts generate on servers/CI. The
functions return the underlying data too, so a notebook can render them inline.
"""

import argparse
import json
import os
import sys
from collections import Counter

import matplotlib

matplotlib.use("Agg")  # headless: never require a display

# Importable both as ``deepqlearning.evaluation.analyze_policy`` and as a bare script path.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import matplotlib.pyplot as plt
import numpy as np

from deepqlearning.algos import ALGORITHMS
from deepqlearning.algos.base import Algorithm
from deepqlearning.envs.financial.actions import ActionType
from deepqlearning.envs.financial.environment import OBS_VERSION, FinancialLifeEnv, FinancialLifeEnvGenerator
from deepqlearning.envs.financial.policies import SLOT_BY_NAME, SLOT_NAMES
from deepqlearning.training.rollout import rollout

# Coarse action categories for a readable heatmap.
_CATEGORIES = ["noop", "contribute", "withdraw", "spend", "retire"]
_CATEGORY_COLORS = ["#d9d9d9", "#2c7fb8", "#d95f0e", "#7fbf7b", "#756bb1"]


def _categorize(action_type: str | None) -> str:
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
    agent: Algorithm, env_config: dict | None, n_episodes: int, seed_base: int = 3_000_000
) -> list[list[dict]]:
    """Run ``n_episodes`` greedy episodes and return their step-by-step trajectories."""
    env = FinancialLifeEnv(env_config or {})
    trajectories = []
    for i in range(n_episodes):
        result = rollout(env, agent, training=False, seed=seed_base + i, collect_trajectory=True)
        trajectories.append(result.trajectory)
    return trajectories


def action_heatmap(trajectories: list[list[dict]], out_path: str, n_wealth_bins: int = 10) -> dict:
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
    buckets: dict = {(a, w): Counter() for a in range(n_age) for w in range(n_wealth)}
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


def contribution_schedule(trajectories: list[list[dict]], out_path: str) -> dict:
    """Average dollars contributed / withdrawn per year of age across episodes, saved as a PNG."""
    by_age_contrib: dict[int, list[float]] = {}
    by_age_withdraw: dict[int, list[float]] = {}
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


def policy_vector_schedule(trajectories: list[list[dict]], out_png: str, out_txt: str | None = None) -> dict:
    """The standing policies in force by age (factored action space), as data, a table and a figure.

    For each age and slot: the modal value over every greedy decision made at that age (across
    episodes) and the share of those decisions that held it. ``out_txt`` gets a fixed-width table
    (one row per age, one column per slot) with the per-slot share of the modal value.
    """
    by_age: dict[int, dict[str, Counter]] = {}
    for traj in trajectories:
        for step in traj:
            age, vector = step.get("age"), step.get("policy_vector")
            if age is None or vector is None:
                continue
            slots = by_age.setdefault(int(age), {name: Counter() for name in SLOT_NAMES})
            for name in SLOT_NAMES:
                slots[name][vector[name]] += 1
    ages = sorted(by_age)
    table: dict[int, dict[str, dict]] = {}
    for age in ages:
        row = {}
        for name in SLOT_NAMES:
            counter = by_age[age][name]
            value, count = counter.most_common(1)[0]
            row[name] = {"value": value, "share": round(count / max(1, sum(counter.values())), 3)}
        table[age] = row

    if out_txt is not None:
        short = {
            "pretax_401k_rate": "pretax",
            "roth_401k_rate": "roth",
            "ira_contribution": "ira",
            "hsa_contribution": "hsa",
            "sweep_policy": "sweep",
            "spending_adjust": "spend",
            "withdrawal_order": "order",
            "retire": "retired",
            "claim_social_security": "ss",
            "roth_conversion": "conversion",
        }
        widths = {name: max(len(short[name]), 15) for name in SLOT_NAMES}
        lines = ["age  " + " ".join(f"{short[name]:<{widths[name]}}" for name in SLOT_NAMES)]
        for age in ages:
            cells = []
            for name in SLOT_NAMES:
                cell = table[age][name]
                text = cell["value"] if cell["share"] >= 0.995 else f"{cell['value']} {cell['share']:.0%}"
                cells.append(f"{text:<{widths[name]}}")
            lines.append(f"{age:<4d} " + " ".join(cells))
        with open(out_txt, "w") as f:
            f.write("\n".join(lines) + "\n")

    if ages:
        grid = np.array(
            [
                [
                    (SLOT_BY_NAME[name].values.index(table[age][name]["value"]))
                    / max(1, len(SLOT_BY_NAME[name].values) - 1)
                    for age in ages
                ]
                for name in SLOT_NAMES
            ]
        )
        fig, ax = plt.subplots(figsize=(max(8, len(ages) * 0.18), 5))
        ax.imshow(grid, aspect="auto", cmap="viridis", vmin=0, vmax=1, interpolation="nearest")
        ax.set_yticks(range(len(SLOT_NAMES)))
        ax.set_yticklabels(SLOT_NAMES)
        step = max(1, len(ages) // 15)
        ax.set_xticks(range(0, len(ages), step))
        ax.set_xticklabels([str(a) for a in ages[::step]])
        ax.set_xlabel("Age")
        ax.set_title("Standing policy in force by age (modal value; position in the slot's value list)")
        fig.tight_layout()
        fig.savefig(out_png, dpi=120, bbox_inches="tight")
        plt.close(fig)
    return {"ages": ages, "by_age": {str(age): table[age] for age in ages}}


def lifetime_trace(
    agent: Algorithm, env_config: dict | None, out_png: str, out_json: str, seed: int = 4_000_000
) -> dict:
    """One annotated greedy episode: step-by-step state/action/reward (and, on the factored space, the
    standing policy vector), as JSON + a net-worth figure."""
    env = FinancialLifeEnv(env_config or {})
    state, _ = env.reset(seed=seed)
    rows: list[dict] = []
    while True:
        legal = env.get_legal_actions()
        action = agent.select_action(state, legal, training=False)
        state, reward, terminated, truncated, info = env.step(action)
        row = {
            "age": info.get("age"),
            "net_worth": float(info.get("net_worth", 0.0)),
            "action_type": info.get("action_type"),
            "action_amount": float(info.get("action_amount") or 0.0),
            "reward": float(reward),
            "is_retired": bool(info.get("is_retired")),
        }
        if info.get("policy_vector") is not None:
            row["year"], row["month"] = info.get("year"), info.get("month")
            row["policy_changes"] = info.get("policy_changes")
            row["policy_vector"] = info.get("policy_vector")
        rows.append(row)
        if terminated or truncated:
            break

    with open(out_json, "w") as f:
        json.dump(rows, f, indent=2)
        f.write("\n")  # end-of-file newline (pre-commit)

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


def analyze(agent: Algorithm, env_config: dict | None, out_dir: str, n_episodes: int = 50) -> dict:
    """Generate all policy-analysis artifacts into ``out_dir`` and return a manifest of their data + paths."""
    os.makedirs(out_dir, exist_ok=True)
    trajectories = collect_greedy_trajectories(agent, env_config, n_episodes)
    factored = (env_config or {}).get("action_space") == "factored"
    manifest: dict = {"n_episodes": n_episodes}
    if factored:
        manifest["action_space"] = "factored"
        manifest["decision_interval"] = (env_config or {}).get("decision_interval", "year")
        schedule = policy_vector_schedule(
            trajectories,
            os.path.join(out_dir, "policy_vector_by_age.png"),
            os.path.join(out_dir, "policy_vector_by_age.txt"),
        )
        with open(os.path.join(out_dir, "policy_vector_by_age.json"), "w") as f:
            json.dump(schedule, f, indent=2)
            f.write("\n")  # end-of-file newline (pre-commit)
        manifest["policy_vector_by_age"] = schedule
    else:
        manifest["heatmap"] = action_heatmap(trajectories, os.path.join(out_dir, "policy_heatmap.png"))
        manifest["schedule"] = contribution_schedule(trajectories, os.path.join(out_dir, "contribution_schedule.png"))
    trace = lifetime_trace(
        agent, env_config, os.path.join(out_dir, "lifetime_trace.png"), os.path.join(out_dir, "lifetime_trace.json")
    )
    manifest["lifetime_trace_summary"] = {k: v for k, v in trace.items() if k != "rows"}
    with open(os.path.join(out_dir, "analysis_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")  # end-of-file newline (pre-commit)
    print(f"Policy analysis artifacts written to {out_dir}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate policy-analysis artifacts for a checkpoint")
    parser.add_argument("--checkpoint", required=True, help="Path to a trained .pt checkpoint")
    parser.add_argument("--algo", default="dqn", choices=sorted(ALGORITHMS), help="Algorithm that wrote the checkpoint")
    parser.add_argument("--reward-preset", default="retirement_security")
    parser.add_argument("--out-dir", default=None, help="Output dir (default: next to the checkpoint)")
    parser.add_argument("--episodes", type=int, default=50)
    parser.add_argument("--scenario", default="basic", help="Household scenario the checkpoint was trained on")
    parser.add_argument("--action-space", default="flat", choices=["flat", "factored"])
    parser.add_argument("--decision-interval", default="year", choices=["year", "quarter", "month"])
    args = parser.parse_args()

    # Rebuild the exact env the trainer used (financial:<scenario>: the scenario's point household
    # plus the named-env settings), not the bare FinancialLifeEnv defaults.
    env = FinancialLifeEnvGenerator.create_scenario_env(
        args.scenario,
        {
            "reward_preset": args.reward_preset,
            "action_space": args.action_space,
            "decision_interval": args.decision_interval,
        },
    )
    env_config = dict(env.config)
    algo_config = {"num_envs": 1} if args.algo == "ppo" else {}
    if args.algo == "dqn":
        algo_config["obs_version"] = OBS_VERSION
    agent = ALGORITHMS[args.algo](env.observation_space, env.action_space, algo_config)
    agent.load(args.checkpoint)
    out_dir = args.out_dir or os.path.join(os.path.dirname(os.path.abspath(args.checkpoint)), "analysis")
    analyze(agent, env_config, out_dir, n_episodes=args.episodes)


if __name__ == "__main__":
    main()
