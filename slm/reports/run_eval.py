# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Produce the committed adviser evaluation report.

Every adviser runs through the identical outcome harness on the same held-out households (seeds
disjoint from the generation seed) under the held-out seeds and the held-out ``recession`` economy.
One :class:`~slm.evaluate_adviser.AdviserEvaluator` scores each household once (in a process pool)
and is shared by every adviser, so an adviser only adds the scoring of its own off-search plans.

Advisers (``--advisers``, comma-separated):

* ``oracle`` — emits each household's best scored plan (the harness sanity check: zero regret);
* ``stub`` — a fixed plan (``--stub-plan``) standing in for a model, the lower bound a constant
  answer sets (every report also carries the regret of each constant plan and reference heuristic);
* ``tool_loop`` — the same stub wrapped in the draft -> simulate -> revise loop;
* ``hf:<label>=<model_id>[@<adapter>[+<adapter>...]]`` — a local Hugging Face model, zero-shot or
  with fine-tuned adapters (``+``-joined adapters are merged in order, e.g. SFT then DPO);
* ``tabular[=<dataset.jsonl>]`` — gradient-boosted trees on the structured household fields,
  trained on the dataset's labels (the learnability bar; needs scikit-learn);
* ``api`` — the hosted upper bound (needs ``ANTHROPIC_API_KEY``; skipped with a note otherwise).

Usage::

    PYTHONPATH=src:. python slm/reports/run_eval.py --advisers oracle,stub,tool_loop --workers 8
"""

import argparse
import json
import os
import time

from slm.advise import ToolLoopAdviser, ToolLoopConfig
from slm.adviser import StubAdviserModel
from slm.evaluate_adviser import AdviserEvaluator, format_report
from slm.generate_data import DEFAULT_SCENARIOS

DEFAULT_STUB_PLAN = "save0_roth_claim70_conventional"


def _summary_row(name: str, report: dict) -> dict:
    row = {"adviser": name}
    for cond_name, cond in report["conditions"].items():
        reg = cond["adviser_regret"]
        row[cond_name] = {
            "parse_rate": cond["parse_rate"],
            "normalized_regret": reg["normalized_regret"],
            "mean_regret": reg["mean_regret"],
            "regret_ci": [reg["regret_ci_low"], reg["regret_ci_high"]],
            "vs_best_constant": cond["adviser_vs_best_constant"],
            "vs_best_heuristic": cond["adviser_vs_best_heuristic"],
            "top_set_agreement": cond["top_set_agreement_rate"],
            "label_agreement": cond["label_agreement_rate"],
            "dimension_agreement": cond["dimension_agreement_rate"],
            "success_rate": cond["adviser_mean_success_rate"],
            "numeric_consistency": cond["numeric_consistency_rate"],
            "numeric_faithfulness_exact": cond["numeric_faithfulness_rate"],
        }
    row["refusal_rate"] = report["refusals"]["refusal_rate"]
    return row


def format_summary(summary: list[dict]) -> str:
    lines = []
    conds = [k for k in summary[0] if k not in ("adviser", "refusal_rate")] if summary else []
    for cond in conds:
        lines.append(f"[{cond}]")
        lines.append(
            f"{'adviser':42s} {'parse':>5s} {'norm.regret':>11s} {'regret [95% CI]':>24s} "
            f"{'vs best constant':>18s} {'top-set':>7s} {'dims':>5s} {'consist':>7s}"
        )
        for row in summary:
            c = row[cond]
            ci = f"{c['mean_regret']:.3f} [{c['regret_ci'][0]:.3f},{c['regret_ci'][1]:.3f}]"
            vs = c["vs_best_constant"]
            vs_text = f"{vs['mean_regret_advantage']:+.3f}{'*' if vs['adviser_better'] else ' '}"
            lines.append(
                f"{row['adviser']:42s} {c['parse_rate']:5.2f} {c['normalized_regret']:11.3f} {ci:>24s} "
                f"{vs_text:>18s} {c['top_set_agreement']:7.2f} {c['dimension_agreement']:5.2f} "
                f"{c['numeric_consistency']:7.2f}"
            )
        lines.append("")
    lines.append("* = regret advantage over the best constant answer has a 95% CI above zero")
    lines.append("refusal rate: " + ", ".join(f"{r['adviser']}={r['refusal_rate']:.2f}" for r in summary))
    return "\n".join(lines)


def _build_adviser(spec: str, evaluator: AdviserEvaluator, args) -> tuple[str, object] | None:
    if spec == "oracle":
        return "oracle", evaluator.build_oracle()
    if spec == "stub":
        return f"stub ({args.stub_plan})", StubAdviserModel(fixed_decision=args.stub_plan)
    if spec == "tool_loop":
        loop = ToolLoopAdviser(StubAdviserModel(fixed_decision=args.stub_plan), ToolLoopConfig(n_trials=16))
        return f"tool_loop ({args.stub_plan})", loop
    if spec == "api":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("Skipping api: ANTHROPIC_API_KEY is not set")
            return None
        from slm.backends import APIAdviserModel

        return "api", APIAdviserModel()
    if spec == "tabular" or spec.startswith("tabular="):
        from slm.tabular_baseline import TabularAdviser
        from slm.train import load_rows

        path = spec.partition("=")[2] or "slm/data/dataset.jsonl"
        return "tabular (gradient-boosted trees)", TabularAdviser(load_rows(path))
    if spec.startswith("hf:"):
        label, _, target = spec[3:].partition("=")
        model_id, _, adapters = target.partition("@")
        from slm.backends import HFAdviserModel

        adapter_path = adapters.replace("+", ",") or None
        return label, HFAdviserModel(model_id, adapter_path=adapter_path, max_new_tokens=args.max_new_tokens)
    raise SystemExit(f"unknown adviser spec {spec!r}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Evaluate advisers on the shared outcome harness.")
    parser.add_argument("--advisers", default="oracle,stub,tool_loop")
    parser.add_argument("--stub-plan", default=DEFAULT_STUB_PLAN)
    parser.add_argument("--per-scenario", type=int, default=12)
    parser.add_argument("--n-trials", type=int, default=32)
    parser.add_argument("--seed", type=int, default=777)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=320)
    parser.add_argument("--out", default="slm/reports/adviser_eval.json")
    parser.add_argument("--note", default="")
    args = parser.parse_args(argv)

    evaluator = AdviserEvaluator(
        scenarios=list(DEFAULT_SCENARIOS),
        n_per_scenario=args.per_scenario,
        n_trials=args.n_trials,
        master_seed=args.seed,  # disjoint from the generation seed (20)
        held_out_scenario="recession",
        workers=args.workers,
    )
    started = time.time()
    evaluator.prepare()
    print(f"Scored {len(evaluator._cache)} household-conditions in {time.time() - started:.0f}s")

    report = {"note": args.note, "advisers": {}, "summary": []}
    for spec in [s.strip() for s in args.advisers.split(",") if s.strip()]:
        built = _build_adviser(spec, evaluator, args)
        if built is None:
            report.setdefault("skipped", []).append(spec)
            continue
        name, adviser = built
        started = time.time()
        print(f"\nEvaluating {name}...")
        result = evaluator.run(adviser, include_oracle=False)
        result["eval_seconds"] = round(time.time() - started)
        report["advisers"][name] = result
        report["summary"].append(_summary_row(name, result))
        print(format_report(result))
        del adviser

    table = format_summary(report["summary"])
    print("\n" + table)
    with open(args.out, "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    with open(args.out.rsplit(".", 1)[0] + "_summary.txt", "w") as fh:
        fh.write(table + "\n")
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
