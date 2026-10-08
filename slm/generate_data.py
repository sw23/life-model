# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Simulator-verified decision-pair generation.

The pipeline, fully offline and deterministic under ``generation_seed``:

1. Sample seeded households across named scenarios (:mod:`slm.households`: the RL scenarios plus
   older households, varied economies, and children budgeted inside the household's spending).
2. Search the compositional plan grid (:mod:`slm.strategies`): the default plan, every
   one-lever variant, and the combinations (:func:`slm.scoring.search_plans`); no RL policy is a
   candidate (teacher gating, :mod:`slm.candidates`).
3. Score each candidate with a shared-seed Monte Carlo run (:mod:`slm.scoring`), adaptively
   doubling trials while a lever is promising but unproven.
4. Label = the evidence-backed plan (each lever off its default only on a paired gain beyond
   noise), or ``no_plan_lever`` when nothing is viable (:func:`slm.scoring.label_decision`);
   rationale = a templated counterfactual against the default plan whose every number is copied
   from the scoring run (:mod:`slm.rationales`) — certified, not stylistic. Optionally cap any one
   label's share.
5. Emit versioned JSONL + a datasheet (generation seed, simulator commit, config hash, trial
   count) and explicit out-of-scope refusal examples.

Determinism guarantees:

* household draws come from a single ``default_rng(generation_seed)`` walked in a fixed
  (scenario-major) order;
* per-household trial seeds come from ``SeedSequence([generation_seed, index])``;
* every stored float is rounded at scoring time and the JSON is dumped with sorted keys — so the
  same seed produces byte-identical JSONL.

CLI::

    python -m slm.generate_data --scenarios basic,high_earner --per-scenario 25 \
        --n-trials 24 --seed 20 --out slm/data/dataset.jsonl
"""

import argparse
import collections
import datetime
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from .households import SLM_SCENARIOS, resolved_ss_claim_age, sample_households
from .prompts import (
    OUT_OF_SCOPE_DOMAINS,
    REFUSAL_TRAIN_PHRASINGS,
    SYSTEM_PROMPT,
    build_decision_question,
    build_refusal_messages,
    format_decision_answer,
    format_refusal_answer,
    refusal_reason,
)
from .provenance import config_hash, simulator_commit
from .rationales import build_rationale
from .schema import (
    AdviceExample,
    ChatMessage,
    Datasheet,
    HouseholdProfile,
    Provenance,
    ScoredCandidate,
)
from .scoring import decision_basis, label_decision, score_household
from .serializer import render_household
from .strategies import decision_space

DEFAULT_REWARD_PRESET = "retirement_security"
DEFAULT_SCENARIOS = ("basic", "high_earner", "low_earner", "mid_career", "late_career", "pre_retiree")

# Teacher-gating provenance string recorded in the datasheet, so the dataset states honestly that no
# RL policy was used as a teacher (see slm.candidates).
TEACHER_GATING = (
    "No RL teacher (no learned policy cleared the pre-registered protocol bar); candidates = the "
    "coordinate-searched plan grid, label = evidence-backed plan (no_plan_lever when nothing is viable)."
)


def _trial_seeds(generation_seed: int, index: int, n_trials: int) -> list[int]:
    """Reproducible per-household trial seeds from the master seed and the household index."""
    seq = np.random.SeedSequence([generation_seed, index])
    return [int(child.generate_state(1)[0]) for child in seq.spawn(n_trials)]


def _to_profile(scenario: str, household: dict) -> HouseholdProfile:
    """Convert a sampled household dict (enum gender) to the schema profile (string gender)."""
    return HouseholdProfile(
        scenario=scenario,
        person_start_age=int(household["person_start_age"]),
        person_retirement_age=int(household["person_retirement_age"]),
        person_gender=household["person_gender"].name.capitalize(),
        initial_salary=float(household["initial_salary"]),
        initial_bank_balance=float(household["initial_bank_balance"]),
        initial_spending=float(household["initial_spending"]),
        economy_scenario=household.get("economy_scenario"),
        children_ages=[int(a) for a in household.get("children_ages", [])],
        models_healthcare=bool(household.get("models_healthcare", False)),
        ss_claim_age=resolved_ss_claim_age(household),
        retirement_spending_ratio=float(household.get("retirement_spending_ratio", 1.0)),
        employer_match_rate=float(household.get("employer_match_rate", 0.0)),
        employer_match_cap=float(household.get("employer_match_cap", 0.0)),
        initial_401k_pretax=float(household.get("initial_401k_pretax", 0.0)),
        initial_401k_roth=float(household.get("initial_401k_roth", 0.0)),
        initial_brokerage=float(household.get("initial_brokerage", 0.0)),
    )


def _decision_example(
    scenario: str,
    household: dict,
    scored: list[ScoredCandidate],
    provenance: Provenance,
    index: int,
) -> AdviceExample:
    """Assemble one in-scope decision example from a scored household."""
    profile = _to_profile(scenario, household)
    household_text = render_household(profile)
    chosen = label_decision(scored)
    rationale = build_rationale(scored, chosen)
    question = build_decision_question(household_text)
    answer = format_decision_answer(chosen, rationale)
    return AdviceExample(
        example_id=f"{scenario}-{index:05d}",
        kind="decision",
        household=profile,
        household_text=household_text,
        question=question,
        decision_space=decision_space(),
        chosen_decision=chosen,
        decision_basis=decision_basis(scored),
        scored_alternatives=scored,
        rationale=rationale,
        out_of_scope=False,
        messages=[
            ChatMessage(role="system", content=SYSTEM_PROMPT),
            ChatMessage(role="user", content=question),
            ChatMessage(role="assistant", content=answer),
        ],
        provenance=provenance,
    )


def _refusal_examples(provenance: Provenance) -> list[AdviceExample]:
    """Explicit out-of-scope refusal examples, so scope discipline is trained, not just prompted."""
    # Several phrasings per topic, with rotating refusal wording, give the behavior linguistic
    # coverage without a paraphrase model.
    examples: list[AdviceExample] = []
    for domain, desc in OUT_OF_SCOPE_DOMAINS.items():
        for j, template in enumerate(REFUSAL_TRAIN_PHRASINGS):
            question = template.format(d=desc)
            reason = refusal_reason(desc, j)
            answer = format_refusal_answer(reason)
            messages = build_refusal_messages(question) + [{"role": "assistant", "content": answer}]
            examples.append(
                AdviceExample(
                    example_id=f"refuse-{domain}-{j:02d}",
                    kind="refusal",
                    question=question,
                    rationale=reason,
                    out_of_scope=True,
                    messages=[ChatMessage(**m) for m in messages],
                    provenance=provenance,
                )
            )
    return examples


# The evaluator imports the sampler under this name.
_sample_households = sample_households


def _balance_labels(examples: list[AdviceExample], max_share: float) -> tuple[list[AdviceExample], int]:
    """Drop decision examples so no label exceeds ``max_share`` of the kept decisions.

    Over-represented labels shed their ``equivalent`` examples first (the least informative), then
    their ``clear`` ones, in a seed-independent hash order of ``example_id`` so drops spread evenly
    across scenarios. Refusals are never dropped. Returns the kept examples and the drop count.
    """
    decisions = [e for e in examples if e.kind == "decision"]
    counts = collections.Counter(e.chosen_decision for e in decisions)
    # Fixed point of cap = max_share * sum(min(count, cap)): the largest per-label cap that holds
    # once the over-represented labels are trimmed to it.
    cap = max_share * len(decisions)
    for _ in range(100):
        new_cap = max_share * sum(min(c, cap) for c in counts.values())
        if abs(new_cap - cap) < 1e-9:
            break
        cap = new_cap
    keep_n = {label: min(c, int(cap)) for label, c in counts.items()}

    def drop_order(e: AdviceExample) -> tuple:
        # Lower sorts first = kept first: clear before equivalent, then by a stable hash.
        return (e.decision_basis != "clear", hashlib.sha256(e.example_id.encode()).hexdigest())

    kept_ids: set[str] = set()
    for label, n in keep_n.items():
        group = sorted((e for e in decisions if e.chosen_decision == label), key=drop_order)
        kept_ids.update(e.example_id for e in group[:n])
    kept = [e for e in examples if e.kind != "decision" or e.example_id in kept_ids]
    return kept, len(examples) - len(kept)


def _score_worker(args: tuple[dict, list[int], str, int | None]) -> list[ScoredCandidate]:
    """Top-level (picklable) scoring worker for the process pool (mirrors montecarlo._run_trial)."""
    household, seeds, reward_preset, min_trials = args
    return score_household(household, seeds, reward_preset, min_trials=min_trials)


def generate_examples(
    scenarios: list[str],
    n_per_scenario: int,
    n_trials: int,
    generation_seed: int,
    reward_preset: str = DEFAULT_REWARD_PRESET,
    include_refusals: bool = True,
    workers: int = 1,
    max_label_share: float | None = None,
    min_trials: int | None = None,
) -> list[AdviceExample]:
    """Generate the full example list deterministically (in-scope decisions + refusals).

    Households are drawn sequentially (fast, deterministic) and then scored; scoring is
    order-preserving whether run sequentially (``workers=1``) or across a process pool, so the
    output is byte-identical regardless of ``workers``. Pool failures fall back to sequential
    scoring (as in :mod:`life_model.montecarlo`). ``max_label_share`` (if set) caps any one label's
    share of the decision examples (see :func:`_balance_labels`). ``min_trials`` (if set) makes
    scoring adaptive: households start at ``min_trials`` and double toward ``n_trials`` while the
    label is within noise (see :func:`slm.scoring.score_household`).
    """
    provenance = Provenance(
        generation_seed=generation_seed,
        simulator_commit=simulator_commit(),
        config_hash=config_hash(),
        n_trials=n_trials,
        reward_preset=reward_preset,
    )
    items = _sample_households(scenarios, n_per_scenario, generation_seed)
    work = [(h, _trial_seeds(generation_seed, idx, n_trials), reward_preset, min_trials) for _, h, idx in items]

    if workers == 1:
        scored_lists = [_score_worker(a) for a in work]
    else:
        try:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                scored_lists = list(pool.map(_score_worker, work))
        except Exception:  # noqa: BLE001 - any pool failure falls back to the sequential path
            scored_lists = [_score_worker(a) for a in work]

    examples: list[AdviceExample] = [
        _decision_example(scenario, household, scored, provenance, idx)
        for (scenario, household, idx), scored in zip(items, scored_lists)
    ]
    if max_label_share is not None:
        examples, _ = _balance_labels(examples, max_label_share)
    if include_refusals:
        examples.extend(_refusal_examples(provenance))
    return examples


def examples_to_jsonl(examples: list[AdviceExample]) -> str:
    """Serialize examples to canonical (sorted-key) JSONL — byte-identical under seed."""
    return "".join(json.dumps(ex.model_dump(mode="json"), sort_keys=True) + "\n" for ex in examples)


def solvency_by_scenario(examples: list[AdviceExample]) -> dict[str, dict[str, float]]:
    """Per-scenario calibration of the household distribution (see ``Datasheet.solvency_by_scenario``)."""
    best_by_scenario: dict[str, list[float]] = collections.defaultdict(list)
    no_viable_by_scenario: dict[str, list[bool]] = collections.defaultdict(list)
    for e in examples:
        if e.kind != "decision":
            continue
        best_by_scenario[e.household.scenario].append(max(c.success_rate for c in e.scored_alternatives))
        no_viable_by_scenario[e.household.scenario].append(e.decision_basis == "no_viable")
    return {
        scenario: {
            "mean_best_success": round(float(np.mean(best)), 4),
            "share_best_at_most_half": round(float(np.mean([b <= 0.5 for b in best])), 4),
            "share_no_viable": round(float(np.mean(no_viable_by_scenario[scenario])), 4),
            "n": len(best),
        }
        for scenario, best in sorted(best_by_scenario.items())
    }


def build_datasheet(
    examples: list[AdviceExample],
    scenarios: list[str],
    n_trials: int,
    generation_seed: int,
    reward_preset: str,
    name: str,
    scale_note: str,
    max_label_share: float | None = None,
    n_dropped_for_balance: int = 0,
    min_trials: int | None = None,
) -> Datasheet:
    """Build the dataset-level provenance + statistics record."""
    n_decision = sum(1 for e in examples if e.kind == "decision")
    decisions = [e for e in examples if e.kind == "decision"]
    n_refusal = sum(1 for e in examples if e.kind == "refusal")
    return Datasheet(
        name=name,
        description=(
            "Simulator-verified plan-level financial decisions with counterfactual rationales, "
            "plus out-of-scope refusals. Faithfulness-by-construction: every rationale number is a "
            "copy of a stored Monte Carlo score."
        ),
        generation_seed=generation_seed,
        simulator_commit=simulator_commit(),
        config_hash=config_hash(),
        reward_preset=reward_preset,
        n_trials_per_candidate=n_trials,
        n_examples=len(examples),
        n_decision_examples=n_decision,
        n_refusal_examples=n_refusal,
        household_scenarios=list(scenarios),
        decision_space=decision_space(),
        teacher_gating=TEACHER_GATING,
        scale_note=scale_note,
        label_counts=dict(sorted(collections.Counter(e.chosen_decision for e in decisions).items())),
        decision_basis_counts=dict(sorted(collections.Counter(e.decision_basis for e in decisions).items())),
        max_label_share=max_label_share,
        n_dropped_for_balance=n_dropped_for_balance,
        solvency_by_scenario=solvency_by_scenario(examples),
        min_trials_per_candidate=min_trials,
        created_utc=datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat(),
    )


def write_dataset(
    out_path: str,
    scenarios: list[str],
    n_per_scenario: int,
    n_trials: int,
    generation_seed: int,
    reward_preset: str = DEFAULT_REWARD_PRESET,
    datasheet_path: str | None = None,
    scale_note: str = "pipeline-validation scale",
    include_refusals: bool = True,
    workers: int = 1,
    max_label_share: float | None = None,
    min_trials: int | None = None,
) -> Datasheet:
    """Generate a dataset, write the JSONL and datasheet, and return the datasheet."""
    examples = generate_examples(
        scenarios,
        n_per_scenario,
        n_trials,
        generation_seed,
        reward_preset,
        include_refusals,
        workers,
        max_label_share,
        min_trials=min_trials,
    )
    n_kept = sum(1 for e in examples if e.kind == "decision")
    with open(out_path, "w") as fh:
        fh.write(examples_to_jsonl(examples))
    datasheet = build_datasheet(
        examples,
        scenarios,
        n_trials,
        generation_seed,
        reward_preset,
        name=out_path,
        scale_note=scale_note,
        max_label_share=max_label_share,
        n_dropped_for_balance=len(scenarios) * n_per_scenario - n_kept,
        min_trials=min_trials,
    )
    if datasheet_path is None:
        datasheet_path = out_path.rsplit(".", 1)[0] + ".datasheet.json"
    with open(datasheet_path, "w") as fh:
        json.dump(datasheet.model_dump(mode="json"), fh, indent=2, sort_keys=True)
        fh.write("\n")
    return datasheet


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate simulator-verified adviser data.")
    parser.add_argument("--scenarios", default=",".join(DEFAULT_SCENARIOS), help="Comma-separated household scenarios.")
    parser.add_argument("--per-scenario", type=int, default=25, help="Households per scenario.")
    parser.add_argument("--n-trials", type=int, default=24, help="Monte Carlo trials per candidate (the maximum).")
    parser.add_argument(
        "--min-trials",
        type=int,
        default=None,
        help="Adaptive scoring: start here and double toward --n-trials while the label is within noise.",
    )
    parser.add_argument("--seed", type=int, default=20, help="Generation master seed.")
    parser.add_argument("--reward-preset", default=DEFAULT_REWARD_PRESET)
    parser.add_argument("--out", default="slm/data/dataset.jsonl", help="Output JSONL path.")
    parser.add_argument("--datasheet", default=None, help="Datasheet path (defaults next to --out).")
    parser.add_argument("--scale-note", default="pipeline-validation scale")
    parser.add_argument("--no-refusals", action="store_true", help="Skip refusal examples.")
    parser.add_argument("--workers", type=int, default=1, help="Process-pool size for scoring (1 = sequential).")
    parser.add_argument(
        "--max-label-share",
        type=float,
        default=None,
        help="Cap any one label's share of the decision examples (drops the excess; default: no cap).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    unknown = [s for s in scenarios if s not in SLM_SCENARIOS]
    if unknown:
        raise SystemExit(f"Unknown scenarios: {unknown}; known: {sorted(SLM_SCENARIOS)}")
    datasheet = write_dataset(
        out_path=args.out,
        scenarios=scenarios,
        n_per_scenario=args.per_scenario,
        n_trials=args.n_trials,
        generation_seed=args.seed,
        reward_preset=args.reward_preset,
        datasheet_path=args.datasheet,
        scale_note=args.scale_note,
        include_refusals=not args.no_refusals,
        workers=args.workers,
        max_label_share=args.max_label_share,
        min_trials=args.min_trials,
    )
    print(
        f"Wrote {datasheet.n_examples} examples "
        f"({datasheet.n_decision_examples} decisions, {datasheet.n_refusal_examples} refusals) to {args.out}"
    )


if __name__ == "__main__":
    main()
