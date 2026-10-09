# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Pool protocol reports from several pre-registered training seeds into one verdict.

A single training seed evaluated on 50 episodes can neither confirm nor refute an algorithm: DQN
and PPO results vary more across training seeds than across evaluation episodes. Instead of
discarding every run but seed 0, the seeds are fixed in advance (``--seed 0..4``) and pooled:

* per condition, each run's **paired gap** to the best policy in the bar (same evaluation seeds,
  so the bar's numbers are identical across runs) is one observation;
* the pooled verdict is a Student-t 95% interval over those per-seed gaps — it carries the
  training-seed variance, which is the variance that matters for "does this algorithm work";
* a seed-averaged agent (per-episode return averaged over the runs) is also compared with the bar
  episode by episode, for context.

CLI::

    python -m deepqlearning.evaluation.pool_seeds results/protocol_report_financial_basic_ppo_s*.json \
        --out reports/retirement_security_ppo/pooled_report.json
"""

import argparse
import json
import math

import numpy as np

from .baselines import PLANNER_BASELINES

# Two-sided 95% Student-t quantiles by degrees of freedom (normal beyond the table).
_T_975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228}


def _t_interval(values: np.ndarray) -> tuple[float, float, float]:
    """(mean, low, high) of a two-sided 95% Student-t interval for the mean of ``values``."""
    n = values.size
    mean = float(values.mean())
    if n < 2:
        return mean, float("-inf"), float("inf")
    half = _T_975.get(n - 1, 1.96) * float(values.std(ddof=1)) / math.sqrt(n)
    return mean, mean - half, mean + half


def _bootstrap(values: np.ndarray, rng: np.random.Generator, resamples: int = 2000) -> tuple[float, float]:
    means = values[rng.integers(0, values.size, size=(resamples, values.size))].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def pool_reports(reports: list[dict], labels: list[str] | None = None) -> dict:
    """Pool per-seed protocol reports (each with an ``agent``) into one report + verdict."""
    if not reports:
        raise ValueError("no reports to pool")
    first = reports[0]
    for key in ("reward_preset", "master_seed", "n_eval"):
        if any(r[key] != first[key] for r in reports):
            raise ValueError(f"reports disagree on {key!r}; pool only runs evaluated identically")
    labels = labels or [f"run{i}" for i in range(len(reports))]
    rng = np.random.default_rng(first["master_seed"])

    pooled: dict = {
        "reward_preset": first["reward_preset"],
        "master_seed": first["master_seed"],
        "n_eval": first["n_eval"],
        "n_runs": len(reports),
        "runs": labels,
        "bar": list(PLANNER_BASELINES),
        "conditions": {},
    }
    for cond_name, cond in first["conditions"].items():
        bar = {name: cond[name] for name in PLANNER_BASELINES if name in cond}
        best = max(bar, key=lambda n: bar[n]["mean_return"])
        best_returns = np.array(cond[best]["returns"])
        agent_returns = np.array([r["conditions"][cond_name]["agent"]["returns"] for r in reports])
        per_run_gap = agent_returns.mean(axis=1) - best_returns.mean()
        mean, low, high = _t_interval(per_run_gap)
        averaged = agent_returns.mean(axis=0) - best_returns
        avg_low, avg_high = _bootstrap(averaged, rng)
        pooled["conditions"][cond_name] = {
            "best_in_bar": best,
            "best_in_bar_mean_return": float(best_returns.mean()),
            "per_run_agent_mean_return": [float(x) for x in agent_returns.mean(axis=1)],
            "per_run_gap_vs_best": [float(x) for x in per_run_gap],
            "gap_mean": mean,
            "gap_t95_low": low,
            "gap_t95_high": high,
            "runs_beating_best_on_mean": int((per_run_gap > 0).sum()),
            "seed_averaged_agent_gap": float(averaged.mean()),
            "seed_averaged_agent_gap_ci": [avg_low, avg_high],
        }
    train = pooled["conditions"]["train"]
    pooled["verdict_intelligent_pooled"] = bool(train["gap_t95_low"] > 0.0)
    return pooled


def format_pooled(pooled: dict) -> str:
    lines = [
        f"Pooled protocol — preset={pooled['reward_preset']} runs={pooled['n_runs']} n_eval={pooled['n_eval']}",
        f"{'condition':18s} {'best in bar':24s} {'gap mean':>9s} {'t95 interval':>20s} {'runs > best':>11s}",
    ]
    for name, c in pooled["conditions"].items():
        interval = f"[{c['gap_t95_low']:+.2f}, {c['gap_t95_high']:+.2f}]"
        lines.append(
            f"{name:18s} {c['best_in_bar']:24s} {c['gap_mean']:+9.2f} {interval:>20s} "
            f"{c['runs_beating_best_on_mean']:>5d}/{pooled['n_runs']}"
        )
    lines.append(f"Pooled verdict (train t95 interval above zero): INTELLIGENT={pooled['verdict_intelligent_pooled']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Pool per-seed protocol reports into one verdict.")
    parser.add_argument("reports", nargs="+", help="Per-seed protocol_report JSON files (with an agent).")
    parser.add_argument("--out", default=None, help="Write the pooled JSON here.")
    args = parser.parse_args(argv)
    reports = []
    for path in args.reports:
        with open(path) as fh:
            reports.append(json.load(fh))
    pooled = pool_reports(reports, labels=args.reports)
    print(format_pooled(pooled))
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(pooled, fh, indent=2, sort_keys=True)
            fh.write("\n")


if __name__ == "__main__":
    main()
