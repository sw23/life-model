# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Outcome-based evaluation of an adviser (Plan 20 D4, task 3 — built before training).

Extends Plan 19's protocol from RL policies to *text advice*. For each held-out household the
harness:

1. asks the adviser for a decision (``AdviserModel.generate`` on the rendered household + menu),
2. parses the structured ``DECISION`` block (format/parse-rate metric),
3. **executes** the recommended lever in the simulator — a shared-seed Monte Carlo run — and
   compares its success rate / terminal-wealth percentiles against the Plan 19 heuristics on the
   *same* seeds (outcome-quality metric),
4. checks the rationale's numbers against a fresh scoring run (numeric-faithfulness metric).

Because the adviser must choose from the fixed decision menu, its choice is always one of the
scored candidates — so a single ``score_household`` pass per household covers the adviser, every
heuristic, the oracle argmax, and the faithfulness targets.

Held-out conditions mirror Plan 19: ``held_out_seeds`` (unseen draws) and ``held_out_scenario``
(an economy the data was not generated under). An out-of-scope ``refusal`` set measures trained
scope discipline (D6). The JSON report is committed as documentation, exactly like Plan 19's.

The **oracle sanity check** (acceptance): a ``ScriptedAdviserModel`` that emits each household's
argmax scores at least as high as every heuristic on outcome quality — proving the harness
measures decision quality independent of any model.
"""

import argparse
import datetime
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from .adviser import AdviserModel, ScriptedAdviserModel, StubAdviserModel
from .faithfulness import is_faithful
from .generate_data import DEFAULT_SCENARIOS, _sample_households, _to_profile, _trial_seeds
from .prompts import OUT_OF_SCOPE_DOMAINS, build_messages, build_refusal_messages, is_refusal, parse_decision
from .provenance import config_hash, simulator_commit
from .rationales import rationale_of
from .schema import ScoredCandidate
from .scoring import argmax_candidate, score_household
from .serializer import render_household
from .strategies import STRATEGY_NAMES

DEFAULT_REWARD_PRESET = "retirement_security"

# Heuristic candidates the adviser is measured against (Plan 19 planner baselines present in the
# decision menu). The Roth/pre-tax levers are candidates but not "planner heuristics", so they are
# reported but not part of the heuristic bar.
HEURISTIC_NAMES = ("contribution_waterfall", "age_glide", "emergency_fund_first", "four_percent_drawdown")


@dataclass
class HouseholdResult:
    """Per-household evaluation outcome."""

    household_text: str
    parsed: bool
    decision: Optional[str]
    adviser_success: Optional[float]
    adviser_p50: Optional[float]
    argmax_decision: str
    faithful: bool


def _scored_by_name(scored: List[ScoredCandidate]) -> Dict[str, ScoredCandidate]:
    return {c.decision: c for c in scored}


@dataclass
class AdviserEvaluator:
    """Runs the D4 outcome harness over held-out households + an out-of-scope refusal set.

    Args:
        scenarios: Household scenarios to draw held-out households from.
        n_per_scenario: Held-out households per scenario.
        n_trials: Shared Monte Carlo trials per candidate.
        reward_preset: Objective preset (matches the data generation preset).
        master_seed: Held-out master seed (choose disjoint from the generation seed).
        held_out_scenario: Named economy scenario for the out-of-distribution condition.
    """

    scenarios: List[str] = field(default_factory=lambda: list(DEFAULT_SCENARIOS))
    n_per_scenario: int = 10
    n_trials: int = 16
    reward_preset: str = DEFAULT_REWARD_PRESET
    master_seed: int = 777
    held_out_scenario: Optional[str] = "recession"

    def _households(self) -> List[tuple]:
        return _sample_households(self.scenarios, self.n_per_scenario, self.master_seed)

    def _score(self, household: Dict, index: int, economy_scenario: Optional[str]) -> List[ScoredCandidate]:
        h = dict(household)
        if economy_scenario is not None:
            h["economy_scenario"] = economy_scenario
        seeds = _trial_seeds(self.master_seed, index, self.n_trials)
        return score_household(h, seeds, self.reward_preset)

    def _evaluate_condition(self, adviser: AdviserModel, economy_scenario: Optional[str]) -> Dict:
        """Evaluate one condition (an economy overlay of the held-out households)."""
        households = self._households()
        results: List[HouseholdResult] = []
        # Accumulate per-heuristic success/p50 to compare against the adviser on identical seeds.
        heuristic_success: Dict[str, List[float]] = {n: [] for n in HEURISTIC_NAMES}
        heuristic_p50: Dict[str, List[float]] = {n: [] for n in HEURISTIC_NAMES}
        oracle_success: List[float] = []

        for scenario, household, index in households:
            scored = self._score(household, index, economy_scenario)
            by_name = _scored_by_name(scored)
            profile = _to_profile(scenario, household)
            if economy_scenario is not None:
                profile = profile.model_copy(update={"economy_scenario": economy_scenario})
            household_text = render_household(profile)

            answer = adviser.generate(build_messages(household_text))
            decision = parse_decision(answer)
            argmax = argmax_candidate(scored).decision
            oracle_success.append(by_name[argmax].success_rate)
            for n in HEURISTIC_NAMES:
                heuristic_success[n].append(by_name[n].success_rate)
                heuristic_p50[n].append(by_name[n].net_worth_p50)

            if decision is not None and decision in by_name:
                adviser_stats = by_name[decision]
                faithful = is_faithful(answer, scored, decision)
                results.append(
                    HouseholdResult(
                        household_text,
                        True,
                        decision,
                        adviser_stats.success_rate,
                        adviser_stats.net_worth_p50,
                        argmax,
                        faithful,
                    )
                )
            else:
                results.append(HouseholdResult(household_text, False, None, None, None, argmax, True))

        return self._summarize(results, heuristic_success, heuristic_p50, oracle_success)

    def _summarize(self, results, heuristic_success, heuristic_p50, oracle_success) -> Dict:
        parsed = [r for r in results if r.parsed]
        parse_rate = len(parsed) / len(results) if results else 0.0
        adviser_success = float(np.mean([r.adviser_success for r in parsed])) if parsed else 0.0
        adviser_p50 = float(np.mean([r.adviser_p50 for r in parsed])) if parsed else 0.0
        faithfulness_rate = float(np.mean([r.faithful for r in parsed])) if parsed else 1.0

        heuristics = {
            n: {
                "mean_success_rate": float(np.mean(heuristic_success[n])),
                "mean_net_worth_p50": float(np.mean(heuristic_p50[n])),
            }
            for n in HEURISTIC_NAMES
        }
        best_name = max(heuristics, key=lambda n: heuristics[n]["mean_success_rate"])
        best_success = heuristics[best_name]["mean_success_rate"]
        return {
            "n_households": len(results),
            "parse_rate": parse_rate,
            "adviser_mean_success_rate": adviser_success,
            "adviser_mean_net_worth_p50": adviser_p50,
            "numeric_faithfulness_rate": faithfulness_rate,
            "heuristics": heuristics,
            "best_heuristic": best_name,
            "best_heuristic_mean_success_rate": best_success,
            "adviser_beats_best_heuristic": bool(adviser_success >= best_success),
            "oracle_mean_success_rate": float(np.mean(oracle_success)) if oracle_success else 0.0,
            "oracle_beats_all_heuristics": bool(
                (float(np.mean(oracle_success)) if oracle_success else 0.0)
                >= max(h["mean_success_rate"] for h in heuristics.values())
            ),
        }

    def evaluate_refusals(self, adviser: AdviserModel) -> Dict:
        """Refusal-set metric (D6): fraction of out-of-scope prompts the adviser refuses."""
        phrasings = ("Should I {d}?", "Is it a good idea to {d} right now?", "Can you advise whether to {d}?")
        prompts = [t.format(d=desc) for desc in OUT_OF_SCOPE_DOMAINS.values() for t in phrasings]
        refused = sum(1 for q in prompts if is_refusal(adviser.generate(build_refusal_messages(q))))
        return {"n_prompts": len(prompts), "refusal_rate": refused / len(prompts) if prompts else 0.0}

    def build_oracle(self) -> ScriptedAdviserModel:
        """Construct the oracle adviser: each held-out household mapped to its argmax decision.

        The mapping key is a scenario-unique substring of the rendered household so the oracle can
        route by the user turn's text alone (keeping the generate(messages)->text contract).
        """
        mapping: Dict[str, str] = {}
        for economy_scenario in self._condition_scenarios():
            for scenario, household, index in self._households():
                scored = self._score(household, index, economy_scenario)
                profile = _to_profile(scenario, household)
                if economy_scenario is not None:
                    profile = profile.model_copy(update={"economy_scenario": economy_scenario})
                mapping[render_household(profile)] = argmax_candidate(scored).decision
        return ScriptedAdviserModel(mapping)

    def _condition_scenarios(self) -> List[Optional[str]]:
        conds: List[Optional[str]] = [None]
        if self.held_out_scenario is not None:
            conds.append(self.held_out_scenario)
        return conds

    def run(self, adviser: AdviserModel, include_oracle: bool = True) -> Dict:
        """Run the full protocol and return the JSON-serializable report."""
        report: Dict = {
            "reward_preset": self.reward_preset,
            "master_seed": self.master_seed,
            "n_per_scenario": self.n_per_scenario,
            "n_trials": self.n_trials,
            "scenarios": list(self.scenarios),
            "held_out_scenario": self.held_out_scenario,
            "simulator_commit": simulator_commit(),
            "config_hash": config_hash(),
            "created_utc": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
            "conditions": {},
            "refusals": self.evaluate_refusals(adviser),
        }
        report["conditions"]["held_out_seeds"] = self._evaluate_condition(adviser, None)
        if self.held_out_scenario is not None:
            report["conditions"]["held_out_scenario"] = self._evaluate_condition(adviser, self.held_out_scenario)

        if include_oracle:
            oracle = self.build_oracle()
            report["oracle"] = {
                "held_out_seeds": self._evaluate_condition(oracle, None),
            }
            if self.held_out_scenario is not None:
                report["oracle"]["held_out_scenario"] = self._evaluate_condition(oracle, self.held_out_scenario)
            report["oracle"]["refusals"] = self.evaluate_refusals(oracle)
        return report


def format_report(report: Dict) -> str:
    """Render the adviser eval report as a short text table."""
    lines = [
        f"Adviser evaluation — preset={report['reward_preset']} "
        f"seed={report['master_seed']} n_trials={report['n_trials']}"
    ]
    for cond_name, cond in report["conditions"].items():
        lines.append("")
        lines.append(f"[{cond_name}] n={cond['n_households']}")
        lines.append(f"  parse_rate            {cond['parse_rate']:.2f}")
        lines.append(f"  adviser success       {cond['adviser_mean_success_rate']:.3f}")
        lines.append(f"  best heuristic ({cond['best_heuristic']}) {cond['best_heuristic_mean_success_rate']:.3f}")
        lines.append(f"  beats best heuristic  {cond['adviser_beats_best_heuristic']}")
        lines.append(f"  numeric faithfulness  {cond['numeric_faithfulness_rate']:.2f}")
        lines.append(
            f"  oracle success        {cond['oracle_mean_success_rate']:.3f} "
            f"(>= all heuristics: {cond['oracle_beats_all_heuristics']})"
        )
    r = report["refusals"]
    lines.append("")
    lines.append(f"[refusals] n={r['n_prompts']} refusal_rate={r['refusal_rate']:.2f}")
    return "\n".join(lines)


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Outcome-based adviser evaluation (Plan 20 D4).")
    parser.add_argument("--scenarios", default=",".join(DEFAULT_SCENARIOS))
    parser.add_argument("--per-scenario", type=int, default=10)
    parser.add_argument("--n-trials", type=int, default=16)
    parser.add_argument("--seed", type=int, default=777)
    parser.add_argument("--held-out-scenario", default="recession")
    parser.add_argument("--reward-preset", default=DEFAULT_REWARD_PRESET)
    parser.add_argument(
        "--adviser",
        default="oracle",
        choices=["oracle", "stub"],
        help="Which stub adviser to evaluate (real backends load via slm.backends).",
    )
    parser.add_argument("--fixed-decision", default=None, help="Fixed decision for the stub adviser.")
    parser.add_argument("--out", default=None, help="Write the JSON report here.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = _parse_args(argv)
    evaluator = AdviserEvaluator(
        scenarios=[s.strip() for s in args.scenarios.split(",") if s.strip()],
        n_per_scenario=args.per_scenario,
        n_trials=args.n_trials,
        reward_preset=args.reward_preset,
        master_seed=args.seed,
        held_out_scenario=None if args.held_out_scenario in ("", "none", "None") else args.held_out_scenario,
    )
    adviser: AdviserModel
    if args.adviser == "oracle":
        adviser = evaluator.build_oracle()
    else:
        adviser = StubAdviserModel(fixed_decision=args.fixed_decision)
    report = evaluator.run(adviser)
    print(format_report(report))
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
            fh.write("\n")


# Re-exported for tests/tools that want the exact dataset rationale for an adviser stub.
__all__ = ["AdviserEvaluator", "HouseholdResult", "format_report", "rationale_of", "STRATEGY_NAMES"]


if __name__ == "__main__":
    main()
