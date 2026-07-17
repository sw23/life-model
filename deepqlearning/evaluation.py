# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Statistical evaluation protocol for RL policies.

The old evaluation was a hand-rolled mean of a handful of greedy episodes with no statistics. This
module replaces it with a defensible protocol that runs **every policy (the trained agent plus all
baselines) on identical seed sets** and reports, per policy:

* mean return with a bootstrap confidence interval,
* ruin rate (fraction of episodes ending in bankruptcy),
* success rate (fraction that stayed solvent to the end of life — "alive to death, fully funded"),
* terminal **real** net-worth percentiles (p10/p50/p90).

Three conditions isolate generalization:

* ``train`` — seeds from the training distribution,
* ``held_out_seeds`` — a disjoint seed set from the same distribution (generalization to unseen
  draws),
* ``held_out_scenario`` — the same seeds under a named economy scenario the agent did not train on
  (e.g. ``recession``), the harder out-of-distribution test.

Per-condition/per-policy seeds are spawned with :class:`numpy.random.SeedSequence` (the same
mechanism as :class:`life_model.montecarlo.MonteCarlo`), so a report is reproducible under its
master seed. The **operational definition of "intelligent"** is computed on the ``train``
condition for the default objective: the agent's mean return exceeds every planner heuristic's and
its CI does not overlap the best heuristic's. The held-out gap is reported, not gated.
"""

from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional

import numpy as np
from baselines import BASELINES, PLANNER_BASELINES
from environment import FinancialLifeEnv
from rewards import DEFAULT_PRESET, get_reward_config

# A policy maps the environment's current state to a legal flat action index.
Policy = Callable[[FinancialLifeEnv], int]


def spawn_seeds(master_seed: Optional[int], n: int) -> List[int]:
    """Derive ``n`` independent, reproducible seeds from a master seed via ``SeedSequence``."""
    sequence = np.random.SeedSequence(master_seed)
    return [int(child.generate_state(1)[0]) for child in sequence.spawn(n)]


def greedy_agent_policy(agent) -> Policy:
    """Adapt a trained DQN agent to the ``env -> action`` policy interface (greedy, no exploration).

    Duck-typed so this module does not import the agent (keeps evaluation dependency-light). The
    agent only needs ``select_action(state, legal_actions, training=False)``.
    """

    def policy(env: FinancialLifeEnv) -> int:
        state = env._get_observation()
        legal = env.get_legal_actions()
        return agent.select_action(state, legal, training=False)

    return policy


@dataclass
class EpisodeOutcome:
    """Outcome of a single evaluation episode."""

    total_reward: float
    real_terminal_net_worth: float
    ruined: bool
    success: bool
    died_natural: bool
    steps: int


def run_policy_episode(env: FinancialLifeEnv, policy: Policy, seed: int) -> EpisodeOutcome:
    """Run one episode under ``policy`` and return its outcome (reward + terminal financial state).

    Terminal net worth is deflated to real (start-of-episode) dollars; when the person died it is
    the estate value captured at death, not the ~0 post-dissolution net worth.
    """
    env.reset(seed=seed)
    total_reward = 0.0
    steps = 0
    info: Dict = {}
    terminated = truncated = False
    while True:
        action = policy(env)
        _, reward, terminated, truncated, info = env.step(action)
        total_reward += reward
        steps += 1
        if terminated or truncated:
            break

    died_natural = bool(info.get("died_from_natural_causes"))
    estate = info.get("estate_value_at_death")
    nominal_net_worth = float(estate) if (died_natural and estate is not None) else env._calculate_net_worth()
    deflator = env.model.economy.cumulative_inflation(env.model.year)
    real_net_worth = nominal_net_worth / max(deflator, 1e-9)

    ruined = nominal_net_worth < env.BANKRUPTCY_THRESHOLD
    # Success = stayed solvent to the end of life (natural death, max age, or horizon) with a
    # positive estate — "alive to death, fully funded".
    success = (not ruined) and nominal_net_worth > 0.0
    return EpisodeOutcome(
        total_reward=float(total_reward),
        real_terminal_net_worth=float(real_net_worth),
        ruined=bool(ruined),
        success=bool(success),
        died_natural=died_natural,
        steps=int(steps),
    )


def _bootstrap_ci(values: np.ndarray, resamples: int, ci: float, rng: np.random.Generator) -> tuple:
    """Percentile-bootstrap confidence interval for the mean of ``values``."""
    arr = np.asarray(values, dtype=float)
    if arr.size < 2:
        m = float(arr.mean()) if arr.size else 0.0
        return m, m
    idx = rng.integers(0, arr.size, size=(resamples, arr.size))
    means = arr[idx].mean(axis=1)
    lo = (1.0 - ci) / 2.0 * 100.0
    hi = (1.0 + ci) / 2.0 * 100.0
    return float(np.percentile(means, lo)), float(np.percentile(means, hi))


@dataclass
class PolicyStats:
    """Aggregated statistics for one policy on one condition (all JSON-serializable)."""

    n: int
    mean_return: float
    ci_low: float
    ci_high: float
    ruin_rate: float
    success_rate: float
    net_worth_p10: float
    net_worth_p50: float
    net_worth_p90: float
    mean_steps: float

    def as_dict(self) -> Dict:
        return asdict(self)


def summarize(outcomes: List[EpisodeOutcome], resamples: int, ci: float, rng: np.random.Generator) -> PolicyStats:
    """Summarize a list of episode outcomes into a :class:`PolicyStats`."""
    returns = np.array([o.total_reward for o in outcomes], dtype=float)
    net_worths = np.array([o.real_terminal_net_worth for o in outcomes], dtype=float)
    ci_low, ci_high = _bootstrap_ci(returns, resamples, ci, rng)
    return PolicyStats(
        n=len(outcomes),
        mean_return=float(returns.mean()),
        ci_low=ci_low,
        ci_high=ci_high,
        ruin_rate=float(np.mean([o.ruined for o in outcomes])),
        success_rate=float(np.mean([o.success for o in outcomes])),
        net_worth_p10=float(np.percentile(net_worths, 10)),
        net_worth_p50=float(np.percentile(net_worths, 50)),
        net_worth_p90=float(np.percentile(net_worths, 90)),
        mean_steps=float(np.mean([o.steps for o in outcomes])),
    )


@dataclass
class EvalProtocol:
    """Runs the statistical evaluation protocol over all policies and conditions.

    Args:
        env_config: Base environment config for the training distribution (merged over the env
            defaults). The reward preset is forced to ``reward_preset``.
        reward_preset: Objective preset the report is computed under (default ``retirement_security``).
        n_eval: Episodes per policy per condition.
        master_seed: Master seed; per-condition seed sets are disjoint ``SeedSequence`` spawns.
        held_out_scenario: Named economy scenario for the out-of-distribution condition. ``None``
            skips that condition.
        bootstrap_resamples: Bootstrap resamples for the CI.
        ci: Confidence level (e.g. 0.95).
    """

    env_config: Dict = field(default_factory=dict)
    reward_preset: str = DEFAULT_PRESET
    n_eval: int = 50
    master_seed: int = 12345
    held_out_scenario: Optional[str] = "recession"
    bootstrap_resamples: int = 2000
    ci: float = 0.95

    def _make_env(self, extra_config: Optional[Dict] = None) -> FinancialLifeEnv:
        config = dict(self.env_config)
        config["reward_preset"] = self.reward_preset
        if extra_config:
            config.update(extra_config)
        return FinancialLifeEnv(config)

    def _conditions(self) -> Dict[str, Dict]:
        """Map condition name -> {env_extra_config, seeds}. Seed sets are disjoint spawns."""
        # Two disjoint seed sets from the master seed: train and held-out.
        both = spawn_seeds(self.master_seed, 2 * self.n_eval)
        train_seeds, held_out_seeds = both[: self.n_eval], both[self.n_eval :]
        conditions = {
            "train": {"extra": None, "seeds": train_seeds},
            "held_out_seeds": {"extra": None, "seeds": held_out_seeds},
        }
        if self.held_out_scenario is not None:
            conditions["held_out_scenario"] = {
                "extra": {"economy_scenario": self.held_out_scenario},
                "seeds": held_out_seeds,
            }
        return conditions

    def evaluate_policy(self, policy: Policy, env: FinancialLifeEnv, seeds: List[int]) -> PolicyStats:
        """Evaluate one policy on one env over ``seeds`` and return its statistics."""
        outcomes = [run_policy_episode(env, policy, seed) for seed in seeds]
        rng = np.random.default_rng(self.master_seed)
        return summarize(outcomes, self.bootstrap_resamples, self.ci, rng)

    def run(self, policies: Optional[Dict[str, Policy]] = None, agent=None) -> Dict:
        """Run the protocol and return the JSON-serializable report.

        Args:
            policies: Name -> policy map to evaluate. Defaults to all :data:`BASELINES`.
            agent: Optional trained agent; if given, a greedy ``agent`` policy is added and the
                "intelligent" verdict is computed against the planner heuristics.
        """
        policies = dict(policies) if policies is not None else dict(BASELINES)
        if agent is not None:
            policies = {"agent": greedy_agent_policy(agent), **policies}

        conditions = self._conditions()
        report: Dict = {
            "reward_preset": self.reward_preset,
            "reward_config": asdict(get_reward_config(self.reward_preset)),
            "master_seed": self.master_seed,
            "n_eval": self.n_eval,
            "ci": self.ci,
            "held_out_scenario": self.held_out_scenario,
            "conditions": {},
        }
        for cond_name, spec in conditions.items():
            env = self._make_env(spec["extra"])
            report["conditions"][cond_name] = {
                name: self.evaluate_policy(policy, env, spec["seeds"]).as_dict() for name, policy in policies.items()
            }

        if agent is not None:
            report["intelligent"] = self._intelligence_verdict(report)
        return report

    def _intelligence_verdict(self, report: Dict) -> Dict:
        """Operational 'intelligent' verdict, computed on the train condition.

        The agent is intelligent iff its mean return exceeds every planner heuristic's AND its CI
        low is above the best heuristic's CI high (non-overlapping). The held-out-seeds gap is
        reported for context but not gated.
        """
        train = report["conditions"]["train"]
        agent_stats = train["agent"]
        heuristics = {name: train[name] for name in PLANNER_BASELINES if name in train}
        best_name = max(heuristics, key=lambda n: heuristics[n]["mean_return"])
        best = heuristics[best_name]

        beats_all = all(agent_stats["mean_return"] > s["mean_return"] for s in heuristics.values())
        ci_no_overlap = agent_stats["ci_low"] > best["ci_high"]

        held_out_gap = None
        if "held_out_seeds" in report["conditions"]:
            ho = report["conditions"]["held_out_seeds"]
            if "agent" in ho and best_name in ho:
                held_out_gap = ho["agent"]["mean_return"] - ho[best_name]["mean_return"]

        return {
            "preset": self.reward_preset,
            "agent_mean_return": agent_stats["mean_return"],
            "best_heuristic": best_name,
            "best_heuristic_mean_return": best["mean_return"],
            "agent_beats_all_heuristics": bool(beats_all),
            "ci_does_not_overlap_best": bool(ci_no_overlap),
            "verdict_intelligent": bool(beats_all and ci_no_overlap),
            "held_out_seeds_gap_vs_best": held_out_gap,
        }


def format_comparison_table(report: Dict) -> str:
    """Render the protocol report as a plain-text comparison table for the trainer to print."""
    lines: List[str] = []
    lines.append(
        f"Evaluation protocol — preset={report['reward_preset']} n={report['n_eval']} "
        f"master_seed={report['master_seed']}"
    )
    header = f"{'policy':22s} {'mean':>9s} {'95% CI':>19s} {'ruin':>6s} {'succ':>6s} {'nw_p50':>12s}"
    for cond_name, cond in report["conditions"].items():
        lines.append("")
        lines.append(f"[{cond_name}]")
        lines.append(header)
        # Sort by mean return descending so the leader is on top.
        for name in sorted(cond, key=lambda n: cond[n]["mean_return"], reverse=True):
            s = cond[name]
            ci = f"[{s['ci_low']:.2f},{s['ci_high']:.2f}]"
            lines.append(
                f"{name:22s} {s['mean_return']:9.2f} {ci:>19s} "
                f"{s['ruin_rate']:6.2f} {s['success_rate']:6.2f} {s['net_worth_p50']:12,.0f}"
            )
    if "intelligent" in report:
        v = report["intelligent"]
        lines.append("")
        lines.append(
            f"Intelligent verdict (train, {v['preset']}): "
            f"agent={v['agent_mean_return']:.2f} vs best heuristic "
            f"{v['best_heuristic']}={v['best_heuristic_mean_return']:.2f} | "
            f"beats_all={v['agent_beats_all_heuristics']} ci_no_overlap={v['ci_does_not_overlap_best']} "
            f"=> INTELLIGENT={v['verdict_intelligent']}"
        )
        if v["held_out_seeds_gap_vs_best"] is not None:
            lines.append(f"Held-out-seeds gap vs best heuristic: {v['held_out_seeds_gap_vs_best']:+.2f}")
    return "\n".join(lines)
