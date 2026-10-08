# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Outcome-based evaluation of an adviser (built before training).

Extends the RL-policy evaluation protocol to *text advice*. For each held-out household the
harness:

1. asks the adviser for a decision (``AdviserModel.generate`` on the rendered household + menu),
2. parses the structured ``DECISION`` block (format/parse-rate metric),
3. **executes** the recommended lever in the simulator — a shared-seed Monte Carlo run — and
   compares its success rate / terminal-wealth percentiles against the heuristic (planner-grade)
   baselines on the *same* seeds (outcome-quality metric),
4. checks the rationale's numbers against a fresh scoring run (numeric-faithfulness metric),
5. compares the answer with the dataset label (:func:`~slm.scoring.label_decision`), including
   whether the adviser says ``no_plan_lever`` exactly when no lever is viable.

A ``no_plan_lever`` answer is executed as the default plan (``NO_LEVER_DEFAULT_PLAN``), so abstaining
costs outcome quality whenever some lever would have helped.

Because the adviser must choose from the fixed decision menu, its choice is always one of the
scored candidates — so a single ``score_household`` pass per household covers the adviser, every
heuristic, the oracle argmax, and the faithfulness targets.

Held-out conditions mirror the RL evaluation protocol: ``held_out_seeds`` (unseen draws) and ``held_out_scenario``
(an economy the data was not generated under). An out-of-scope ``refusal`` set measures trained
scope discipline. The JSON report is committed as documentation, like the RL protocol report.

The **oracle sanity check** (acceptance): a ``ScriptedAdviserModel`` that emits each household's
argmax scores at least as high as every heuristic on outcome quality — proving the harness
measures decision quality independent of any model.
"""

import argparse
import datetime
import json
from dataclasses import dataclass, field

import numpy as np

from .adviser import AdviserModel, ScriptedAdviserModel, StubAdviserModel
from .faithfulness import is_consistent, is_faithful
from .generate_data import DEFAULT_SCENARIOS, _sample_households, _to_profile, _trial_seeds
from .prompts import (
    OUT_OF_SCOPE_DOMAINS,
    REFUSAL_EVAL_PHRASINGS,
    build_messages,
    build_refusal_messages,
    is_refusal,
    parse_decision,
)
from .provenance import config_hash, simulator_commit
from .rationales import rationale_of
from .schema import ScoredCandidate
from .scoring import argmax_candidate, label_decision, paired_bootstrap_ci, score_household
from .serializer import render_household
from .strategies import NO_LEVER, NO_LEVER_DEFAULT_PLAN, STRATEGY_NAMES

DEFAULT_REWARD_PRESET = "retirement_security"

# Heuristic candidates the adviser is measured against (planner-grade baselines present in the
# decision menu). The Roth/pre-tax levers are candidates but not "planner heuristics", so they are
# reported but not part of the heuristic bar.
HEURISTIC_NAMES = ("contribution_waterfall", "age_glide", "emergency_fund_first", "four_percent_drawdown")


@dataclass
class HouseholdResult:
    """Per-household evaluation outcome."""

    household_text: str
    parsed: bool
    decision: str | None
    adviser_success: float | None
    adviser_p50: float | None
    argmax_decision: str
    faithful: bool
    label: str = ""
    # Mean utility return of every candidate on this household (the regret baseline), the return
    # of what the adviser's answer executes (the default plan when unparsed or abstaining), and
    # whether the answer is in the top set / within Monte Carlo noise of the scored numbers.
    returns: dict = field(default_factory=dict)
    executed: str = ""
    in_top_set: bool = False
    consistent: bool = True


def _scored_by_name(scored: list[ScoredCandidate]) -> dict[str, ScoredCandidate]:
    return {c.decision: c for c in scored}


@dataclass
class AdviserEvaluator:
    """Runs the outcome harness over held-out households + an out-of-scope refusal set.

    Args:
        scenarios: Household scenarios to draw held-out households from.
        n_per_scenario: Held-out households per scenario.
        n_trials: Shared Monte Carlo trials per candidate.
        reward_preset: Objective preset (matches the data generation preset).
        master_seed: Held-out master seed (choose disjoint from the generation seed).
        held_out_scenario: Named economy scenario for the out-of-distribution condition.
    """

    scenarios: list[str] = field(default_factory=lambda: list(DEFAULT_SCENARIOS))
    n_per_scenario: int = 10
    n_trials: int = 16
    reward_preset: str = DEFAULT_REWARD_PRESET
    master_seed: int = 777
    held_out_scenario: str | None = "recession"

    def _households(self) -> list[tuple]:
        return _sample_households(self.scenarios, self.n_per_scenario, self.master_seed)

    def _score(self, household: dict, index: int, economy_scenario: str | None) -> list[ScoredCandidate]:
        h = dict(household)
        if economy_scenario is not None:
            h["economy_scenario"] = economy_scenario
        seeds = _trial_seeds(self.master_seed, index, self.n_trials)
        return score_household(h, seeds, self.reward_preset)

    def _evaluate_condition(self, adviser: AdviserModel, economy_scenario: str | None) -> dict:
        """Evaluate one condition (an economy overlay of the held-out households)."""
        households = self._households()
        results: list[HouseholdResult] = []
        # Accumulate per-heuristic success/p50 to compare against the adviser on identical seeds.
        heuristic_success: dict[str, list[float]] = {n: [] for n in HEURISTIC_NAMES}
        heuristic_p50: dict[str, list[float]] = {n: [] for n in HEURISTIC_NAMES}
        oracle_success: list[float] = []

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
            label = label_decision(scored)
            oracle_success.append(by_name[argmax].success_rate)
            for n in HEURISTIC_NAMES:
                heuristic_success[n].append(by_name[n].success_rate)
                heuristic_p50[n].append(by_name[n].net_worth_p50)

            returns = {c.decision: c.mean_return for c in scored}
            if decision is not None and (decision in by_name or decision == NO_LEVER):
                executed = NO_LEVER_DEFAULT_PLAN if decision == NO_LEVER else decision
                adviser_stats = by_name[executed]
                results.append(
                    HouseholdResult(
                        household_text,
                        True,
                        decision,
                        adviser_stats.success_rate,
                        adviser_stats.net_worth_p50,
                        argmax,
                        is_faithful(answer, scored, decision),
                        label,
                        returns=returns,
                        executed=executed,
                        # Abstaining is "in the top set" exactly when the label is no_plan_lever.
                        in_top_set=(label == NO_LEVER) if decision == NO_LEVER else by_name[decision].in_top_set,
                        consistent=is_consistent(answer, scored, decision),
                    )
                )
            else:
                # An unparseable answer executes the default plan for regret (it is not free).
                results.append(
                    HouseholdResult(
                        household_text,
                        False,
                        None,
                        None,
                        None,
                        argmax,
                        True,
                        label,
                        returns=returns,
                        executed=NO_LEVER_DEFAULT_PLAN,
                    )
                )

        return self._summarize(results, heuristic_success, heuristic_p50, oracle_success)

    def _summarize(self, results, heuristic_success, heuristic_p50, oracle_success) -> dict:
        parsed = [r for r in results if r.parsed]
        parse_rate = len(parsed) / len(results) if results else 0.0
        adviser_success = float(np.mean([r.adviser_success for r in parsed])) if parsed else 0.0
        adviser_p50 = float(np.mean([r.adviser_p50 for r in parsed])) if parsed else 0.0
        faithfulness_rate = float(np.mean([r.faithful for r in parsed])) if parsed else 1.0
        label_agreement = float(np.mean([r.decision == r.label for r in parsed])) if parsed else 0.0
        abstain_rate = float(np.mean([r.decision == NO_LEVER for r in parsed])) if parsed else 0.0
        label_abstain_rate = float(np.mean([r.label == NO_LEVER for r in results])) if results else 0.0

        heuristics = {
            n: {
                "mean_success_rate": float(np.mean(heuristic_success[n])),
                "mean_net_worth_p50": float(np.mean(heuristic_p50[n])),
            }
            for n in HEURISTIC_NAMES
        }
        best_name = max(heuristics, key=lambda n: heuristics[n]["mean_success_rate"])
        best_success = heuristics[best_name]["mean_success_rate"]
        regret_block = self._regret_summary(results)
        return {
            **regret_block,
            "top_set_agreement_rate": float(np.mean([r.in_top_set for r in parsed])) if parsed else 0.0,
            "numeric_consistency_rate": float(np.mean([r.consistent for r in parsed])) if parsed else 1.0,
            "n_households": len(results),
            "parse_rate": parse_rate,
            "adviser_mean_success_rate": adviser_success,
            "adviser_mean_net_worth_p50": adviser_p50,
            "numeric_faithfulness_rate": faithfulness_rate,
            "label_agreement_rate": label_agreement,
            "abstain_rate": abstain_rate,
            "label_abstain_rate": label_abstain_rate,
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

    @staticmethod
    def _regret_summary(results: list[HouseholdResult]) -> dict:
        """Regret vs the per-household oracle, for the adviser and for every constant answer.

        Regret on a household = oracle mean return - the executed answer's mean return (>= 0);
        normalized regret divides by the oracle-to-worst span (0 when every option ties). The
        adviser is compared with each constant policy by the paired per-household regret
        difference, with a household-bootstrap 95% CI; "beats" requires the CI to exclude zero.
        """
        if not results:
            return {}
        names = list(results[0].returns)
        oracle = np.array([max(r.returns.values()) for r in results])
        span = oracle - np.array([min(r.returns.values()) for r in results])
        safe_span = np.where(span > 1e-9, span, 1.0)

        def regret_of(executed: list[str]) -> np.ndarray:
            return oracle - np.array([r.returns[e] for r, e in zip(results, executed)])

        def block(regret: np.ndarray) -> dict:
            low, high = paired_bootstrap_ci(regret)
            return {
                "mean_regret": float(regret.mean()),
                "regret_ci_low": low,
                "regret_ci_high": high,
                "normalized_regret": float(np.mean(np.where(span > 1e-9, regret / safe_span, 0.0))),
            }

        adviser_regret = regret_of([r.executed for r in results])
        policies = {name: regret_of([name] * len(results)) for name in names}
        policy_blocks = {name: block(regret) for name, regret in policies.items()}

        def versus(name: str) -> dict:
            low, high = paired_bootstrap_ci(policies[name] - adviser_regret)
            return {
                "policy": name,
                "mean_regret_advantage": float((policies[name] - adviser_regret).mean()),
                "ci_low": low,
                "ci_high": high,
                "adviser_better": bool(low > 0.0),
            }

        heuristic_names = [n for n in HEURISTIC_NAMES if n in policies]
        best_heuristic = min(heuristic_names, key=lambda n: policy_blocks[n]["mean_regret"])
        best_constant = min(names, key=lambda n: policy_blocks[n]["mean_regret"])
        return {
            "adviser_regret": block(adviser_regret),
            "constant_policy_regret": policy_blocks,
            "best_heuristic_by_regret": best_heuristic,
            "best_constant_policy": best_constant,
            "adviser_vs_best_heuristic": versus(best_heuristic),
            "adviser_vs_best_constant": versus(best_constant),
        }

    def evaluate_refusals(self, adviser: AdviserModel) -> dict:
        """Refusal-set metric: fraction of out-of-scope prompts the adviser refuses."""
        # Held-out wordings (disjoint from the training phrasings) so this measures generalization.
        prompts = [t.format(d=desc) for desc in OUT_OF_SCOPE_DOMAINS.values() for t in REFUSAL_EVAL_PHRASINGS]
        refused = sum(1 for q in prompts if is_refusal(adviser.generate(build_refusal_messages(q))))
        return {"n_prompts": len(prompts), "refusal_rate": refused / len(prompts) if prompts else 0.0}

    def build_oracle(self) -> ScriptedAdviserModel:
        """Construct the oracle adviser: each held-out household mapped to its argmax decision.

        The oracle never abstains (it always names the best lever), so it upper-bounds outcome
        quality; its label agreement is below 1 exactly on the no-viable-lever households.

        The mapping key is a scenario-unique substring of the rendered household so the oracle can
        route by the user turn's text alone (keeping the generate(messages)->text contract).
        """
        mapping: dict[str, str] = {}
        for economy_scenario in self._condition_scenarios():
            for scenario, household, index in self._households():
                scored = self._score(household, index, economy_scenario)
                profile = _to_profile(scenario, household)
                if economy_scenario is not None:
                    profile = profile.model_copy(update={"economy_scenario": economy_scenario})
                mapping[render_household(profile)] = argmax_candidate(scored).decision
        return ScriptedAdviserModel(mapping)

    def _condition_scenarios(self) -> list[str | None]:
        conds: list[str | None] = [None]
        if self.held_out_scenario is not None:
            conds.append(self.held_out_scenario)
        return conds

    def run(self, adviser: AdviserModel, include_oracle: bool = True) -> dict:
        """Run the full protocol and return the JSON-serializable report."""
        report: dict = {
            "reward_preset": self.reward_preset,
            "master_seed": self.master_seed,
            "n_per_scenario": self.n_per_scenario,
            "n_trials": self.n_trials,
            "scenarios": list(self.scenarios),
            "held_out_scenario": self.held_out_scenario,
            "simulator_commit": simulator_commit(),
            "config_hash": config_hash(),
            "created_utc": datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat(),
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


def format_report(report: dict) -> str:
    """Render the adviser eval report as a short text table."""
    lines = [
        (
            f"Adviser evaluation — preset={report['reward_preset']} "
            f"seed={report['master_seed']} n_trials={report['n_trials']}"
        )
    ]
    for cond_name, cond in report["conditions"].items():
        lines.append("")
        lines.append(f"[{cond_name}] n={cond['n_households']}")
        lines.append(f"  parse_rate            {cond['parse_rate']:.2f}")
        if "adviser_regret" in cond:
            reg = cond["adviser_regret"]
            lines.append(
                f"  adviser regret        {reg['mean_regret']:.3f} [{reg['regret_ci_low']:.3f}, "
                f"{reg['regret_ci_high']:.3f}] normalized {reg['normalized_regret']:.3f}"
            )
            for key in ("adviser_vs_best_constant", "adviser_vs_best_heuristic"):
                v = cond[key]
                lines.append(
                    f"  vs {v['policy']:<22s} advantage {v['mean_regret_advantage']:+.3f} "
                    f"[{v['ci_low']:+.3f}, {v['ci_high']:+.3f}] better={v['adviser_better']}"
                )
            lines.append(f"  top-set agreement     {cond['top_set_agreement_rate']:.2f}")
            lines.append(f"  numeric consistency   {cond['numeric_consistency_rate']:.2f}")
        lines.append(f"  adviser success       {cond['adviser_mean_success_rate']:.3f}")
        lines.append(f"  best heuristic ({cond['best_heuristic']}) {cond['best_heuristic_mean_success_rate']:.3f}")
        lines.append(f"  beats best heuristic  {cond['adviser_beats_best_heuristic']}")
        lines.append(f"  numeric faithfulness  {cond['numeric_faithfulness_rate']:.2f}")
        lines.append(f"  label agreement       {cond['label_agreement_rate']:.2f}")
        lines.append(f"  no_plan_lever rate    {cond['abstain_rate']:.2f} (labels: {cond['label_abstain_rate']:.2f})")
        lines.append(
            f"  oracle success        {cond['oracle_mean_success_rate']:.3f} "
            f"(>= all heuristics: {cond['oracle_beats_all_heuristics']})"
        )
    r = report["refusals"]
    lines.append("")
    lines.append(f"[refusals] n={r['n_prompts']} refusal_rate={r['refusal_rate']:.2f}")
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Outcome-based adviser evaluation.")
    parser.add_argument("--scenarios", default=",".join(DEFAULT_SCENARIOS))
    parser.add_argument("--per-scenario", type=int, default=10)
    parser.add_argument("--n-trials", type=int, default=16)
    parser.add_argument("--seed", type=int, default=777)
    parser.add_argument("--held-out-scenario", default="recession")
    parser.add_argument("--reward-preset", default=DEFAULT_REWARD_PRESET)
    parser.add_argument(
        "--adviser",
        default="oracle",
        choices=["oracle", "stub", "hf"],
        help="Adviser to evaluate: the oracle or stub, or a local Hugging Face model ('hf').",
    )
    parser.add_argument("--fixed-decision", default=None, help="Fixed decision for the stub adviser.")
    parser.add_argument("--model-id", default=None, help="--adviser hf: base model id or local path.")
    parser.add_argument("--adapter-path", default=None, help="--adviser hf: optional LoRA adapter directory.")
    parser.add_argument("--max-new-tokens", type=int, default=384, help="--adviser hf: generation budget.")
    parser.add_argument("--out", default=None, help="Write the JSON report here.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
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
    elif args.adviser == "hf":
        if not args.model_id:
            raise SystemExit("--adviser hf needs --model-id")
        from slm.backends import HFAdviserModel

        adviser = HFAdviserModel(args.model_id, adapter_path=args.adapter_path, max_new_tokens=args.max_new_tokens)
    else:
        adviser = StubAdviserModel(fixed_decision=args.fixed_decision)
    report = evaluator.run(adviser)
    print(format_report(report))
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
            fh.write("\n")


# Re-exported for tests/tools that want the exact dataset rationale for an adviser stub.
__all__ = ["STRATEGY_NAMES", "AdviserEvaluator", "HouseholdResult", "format_report", "rationale_of"]


if __name__ == "__main__":
    main()
