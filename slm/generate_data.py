# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Simulator-verified decision-pair generation.

The pipeline, fully offline and deterministic under ``generation_seed``:

1. Sample seeded households from the RL environment's :class:`EpisodeSampler` across named scenarios.
2. Enumerate candidate plan-level levers (:mod:`slm.candidates`) — heuristics + Roth/pre-tax
   split; the DQN is excluded by teacher gating (see :mod:`slm.candidates`).
3. Score each candidate with a shared-seed Monte Carlo run (:mod:`slm.scoring`).
4. Label = the argmax candidate; rationale = a templated counterfactual whose every number is
   copied from the scoring run (:mod:`slm.rationales`) — certified, not stylistic.
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
import datetime
import json
from concurrent.futures import ProcessPoolExecutor
from typing import Dict, List, Optional, Tuple

import numpy as np
from scenarios import HOUSEHOLD_SCENARIOS, EpisodeSampler

from .prompts import (
    OUT_OF_SCOPE_DOMAINS,
    SYSTEM_PROMPT,
    build_decision_question,
    build_refusal_messages,
    format_decision_answer,
    format_refusal_answer,
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
from .scoring import argmax_candidate, score_household
from .serializer import render_household
from .strategies import decision_space

DEFAULT_REWARD_PRESET = "retirement_security"
DEFAULT_SCENARIOS = ("basic", "high_earner", "low_earner", "mid_career")

# Teacher-gating provenance string recorded in the datasheet (protocol report:
# verdict_intelligent=false), so the dataset states honestly that the DQN was not used as a teacher.
TEACHER_GATING = (
    "DQN excluded (protocol report: verdict_intelligent=false, "
    "ci_does_not_overlap_best=false); candidates = heuristics + Roth/pre-tax levers, label = grid argmax."
)


def _trial_seeds(generation_seed: int, index: int, n_trials: int) -> List[int]:
    """Reproducible per-household trial seeds from the master seed and the household index."""
    seq = np.random.SeedSequence([generation_seed, index])
    return [int(child.generate_state(1)[0]) for child in seq.spawn(n_trials)]


def _to_profile(scenario: str, household: Dict) -> HouseholdProfile:
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
    )


def _decision_example(
    scenario: str,
    household: Dict,
    scored: List[ScoredCandidate],
    provenance: Provenance,
    index: int,
) -> AdviceExample:
    """Assemble one in-scope decision example from a scored household."""
    profile = _to_profile(scenario, household)
    household_text = render_household(profile)
    chosen = argmax_candidate(scored).decision
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


def _refusal_examples(provenance: Provenance) -> List[AdviceExample]:
    """Explicit out-of-scope refusal examples, so scope discipline is trained, not just prompted."""
    # A few phrasings per domain give the refusal behavior linguistic coverage without a paraphrase model.
    phrasings = ("Should I {d}?", "Is it a good idea to {d} right now?", "Can you advise whether to {d}?")
    examples: List[AdviceExample] = []
    for domain, desc in OUT_OF_SCOPE_DOMAINS.items():
        for j, template in enumerate(phrasings):
            question = template.format(d=desc)
            reason = (
                f"That question is about {desc}, which the life-model simulator does not price, so "
                f"it is outside this tool's scope and I can't give a simulation-grounded answer."
            )
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


def _sample_households(scenarios: List[str], n_per_scenario: int, generation_seed: int) -> List[Tuple[str, Dict, int]]:
    """Draw every household sequentially from one seeded RNG (scenario-major, deterministic)."""
    rng = np.random.default_rng(generation_seed)
    items: List[Tuple[str, Dict, int]] = []
    index = 0
    for scenario in scenarios:
        sampler = EpisodeSampler(scenario)
        for _ in range(n_per_scenario):
            items.append((scenario, sampler.sample(rng), index))
            index += 1
    return items


def _score_worker(args: Tuple[Dict, List[int], str]) -> List[ScoredCandidate]:
    """Top-level (picklable) scoring worker for the process pool (mirrors montecarlo._run_trial)."""
    household, seeds, reward_preset = args
    return score_household(household, seeds, reward_preset)


def generate_examples(
    scenarios: List[str],
    n_per_scenario: int,
    n_trials: int,
    generation_seed: int,
    reward_preset: str = DEFAULT_REWARD_PRESET,
    include_refusals: bool = True,
    workers: int = 1,
) -> List[AdviceExample]:
    """Generate the full example list deterministically (in-scope decisions + refusals).

    Households are drawn sequentially (fast, deterministic) and then scored; scoring is
    order-preserving whether run sequentially (``workers=1``) or across a process pool, so the
    output is byte-identical regardless of ``workers``. Pool failures fall back to sequential
    scoring (as in :mod:`life_model.montecarlo`).
    """
    provenance = Provenance(
        generation_seed=generation_seed,
        simulator_commit=simulator_commit(),
        config_hash=config_hash(),
        n_trials=n_trials,
        reward_preset=reward_preset,
    )
    items = _sample_households(scenarios, n_per_scenario, generation_seed)
    work = [(h, _trial_seeds(generation_seed, idx, n_trials), reward_preset) for _, h, idx in items]

    if workers == 1:
        scored_lists = [_score_worker(a) for a in work]
    else:
        try:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                scored_lists = list(pool.map(_score_worker, work))
        except Exception:
            scored_lists = [_score_worker(a) for a in work]

    examples: List[AdviceExample] = [
        _decision_example(scenario, household, scored, provenance, idx)
        for (scenario, household, idx), scored in zip(items, scored_lists)
    ]
    if include_refusals:
        examples.extend(_refusal_examples(provenance))
    return examples


def examples_to_jsonl(examples: List[AdviceExample]) -> str:
    """Serialize examples to canonical (sorted-key) JSONL — byte-identical under seed."""
    return "".join(json.dumps(ex.model_dump(mode="json"), sort_keys=True) + "\n" for ex in examples)


def build_datasheet(
    examples: List[AdviceExample],
    scenarios: List[str],
    n_trials: int,
    generation_seed: int,
    reward_preset: str,
    name: str,
    scale_note: str,
) -> Datasheet:
    """Build the dataset-level provenance + statistics record."""
    n_decision = sum(1 for e in examples if e.kind == "decision")
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
        created_utc=datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
    )


def write_dataset(
    out_path: str,
    scenarios: List[str],
    n_per_scenario: int,
    n_trials: int,
    generation_seed: int,
    reward_preset: str = DEFAULT_REWARD_PRESET,
    datasheet_path: Optional[str] = None,
    scale_note: str = "pipeline-validation scale",
    include_refusals: bool = True,
    workers: int = 1,
) -> Datasheet:
    """Generate a dataset, write the JSONL and datasheet, and return the datasheet."""
    examples = generate_examples(
        scenarios, n_per_scenario, n_trials, generation_seed, reward_preset, include_refusals, workers
    )
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
    )
    if datasheet_path is None:
        datasheet_path = out_path.rsplit(".", 1)[0] + ".datasheet.json"
    with open(datasheet_path, "w") as fh:
        json.dump(datasheet.model_dump(mode="json"), fh, indent=2, sort_keys=True)
        fh.write("\n")
    return datasheet


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate simulator-verified adviser data.")
    parser.add_argument("--scenarios", default=",".join(DEFAULT_SCENARIOS), help="Comma-separated household scenarios.")
    parser.add_argument("--per-scenario", type=int, default=25, help="Households per scenario.")
    parser.add_argument("--n-trials", type=int, default=24, help="Monte Carlo trials per candidate.")
    parser.add_argument("--seed", type=int, default=20, help="Generation master seed.")
    parser.add_argument("--reward-preset", default=DEFAULT_REWARD_PRESET)
    parser.add_argument("--out", default="slm/data/dataset.jsonl", help="Output JSONL path.")
    parser.add_argument("--datasheet", default=None, help="Datasheet path (defaults next to --out).")
    parser.add_argument("--scale-note", default="pipeline-validation scale")
    parser.add_argument("--no-refusals", action="store_true", help="Skip refusal examples.")
    parser.add_argument("--workers", type=int, default=1, help="Process-pool size for scoring (1 = sequential).")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = _parse_args(argv)
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    unknown = [s for s in scenarios if s not in HOUSEHOLD_SCENARIOS]
    if unknown:
        raise SystemExit(f"Unknown scenarios: {unknown}; known: {sorted(HOUSEHOLD_SCENARIOS)}")
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
    )
    print(
        f"Wrote {datasheet.n_examples} examples "
        f"({datasheet.n_decision_examples} decisions, {datasheet.n_refusal_examples} refusals) to {args.out}"
    )


if __name__ == "__main__":
    main()
