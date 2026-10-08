# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Data-generation tests (acceptance):

* same seed -> byte-identical JSONL,
* every rationale number is reproducible from the stored scoring results,
* refusal examples are generated for out-of-scope queries,
* schema validation holds for every emitted row.

Kept small (one scenario, few households, few trials) so it runs in CI without the slow marker.
"""

import json

import pytest

from slm.generate_data import _balance_labels, build_datasheet, examples_to_jsonl, generate_examples
from slm.households import MAX_CHILD_SHARE_OF_SPENDING, SLM_SCENARIOS, TRAIN_ECONOMIES, sample_households
from slm.prompts import OUT_OF_SCOPE_DOMAINS, REFUSAL_TRAIN_PHRASINGS, is_refusal, parse_decision
from slm.rationales import build_rationale
from slm.schema import AdviceExample
from slm.scoring import NO_VIABLE_MAX_SUCCESS, decision_basis
from slm.strategies import NO_LEVER, STRATEGY_NAMES, answer_space

SCEN = ["basic"]


@pytest.fixture(scope="module")
def examples():
    return generate_examples(SCEN, n_per_scenario=3, n_trials=4, generation_seed=20)


def test_same_seed_byte_identical(examples):
    again = generate_examples(SCEN, n_per_scenario=3, n_trials=4, generation_seed=20)
    assert examples_to_jsonl(again) == examples_to_jsonl(examples)


def test_different_seed_differs(examples):
    other = generate_examples(SCEN, n_per_scenario=3, n_trials=4, generation_seed=21)
    assert examples_to_jsonl(other) != examples_to_jsonl(examples)


def test_rationale_reproducible_from_stored_scores(examples):
    # Every rationale is a pure function of the stored scored_alternatives (faithfulness by
    # construction): recomputing it from the stored scores reproduces the stored string exactly.
    for ex in examples:
        if ex.kind != "decision":
            continue
        assert ex.chosen_decision in answer_space()
        recomputed = build_rationale(ex.scored_alternatives, ex.chosen_decision)
        assert recomputed == ex.rationale


def test_chosen_is_argmax_success_rate_or_no_lever(examples):
    for ex in examples:
        if ex.kind != "decision":
            continue
        best_rate = max(c.success_rate for c in ex.scored_alternatives)
        assert ex.decision_basis == decision_basis(ex.scored_alternatives)
        if ex.chosen_decision == NO_LEVER:
            # no_plan_lever exactly when even the best lever is (almost) never solvent.
            assert ex.decision_basis == "no_viable" and best_rate <= NO_VIABLE_MAX_SUCCESS
            continue
        assert ex.decision_basis != "no_viable"
        chosen = next(c for c in ex.scored_alternatives if c.decision == ex.chosen_decision)
        assert chosen.success_rate == best_rate


def test_decision_examples_parse_and_are_in_scope(examples):
    for ex in examples:
        if ex.kind != "decision":
            continue
        assistant = ex.messages[-1].content
        assert parse_decision(assistant) == ex.chosen_decision
        assert not is_refusal(assistant)
        assert ex.decision_space == list(STRATEGY_NAMES)


def test_refusals_generated_for_every_out_of_scope_domain(examples):
    refusals = [ex for ex in examples if ex.kind == "refusal"]
    assert refusals, "expected refusal examples"
    domains = {ex.example_id.split("-")[1] for ex in refusals}
    assert domains == set(OUT_OF_SCOPE_DOMAINS)
    for ex in refusals:
        assert ex.out_of_scope is True
        assert is_refusal(ex.messages[-1].content)
        assert parse_decision(ex.messages[-1].content) is None


def test_every_row_schema_valid_via_jsonl(examples):
    for line in examples_to_jsonl(examples).splitlines():
        AdviceExample.model_validate(json.loads(line))


def test_datasheet_counts_match(examples):
    ds = build_datasheet(
        examples, SCEN, n_trials=4, generation_seed=20, reward_preset="retirement_security", name="t", scale_note="test"
    )
    assert ds.n_examples == len(examples)
    assert ds.n_decision_examples + ds.n_refusal_examples == len(examples)
    assert ds.n_refusal_examples == len(REFUSAL_TRAIN_PHRASINGS) * len(OUT_OF_SCOPE_DOMAINS)
    assert ds.simulator_commit and ds.config_hash
    assert sum(ds.label_counts.values()) == ds.n_decision_examples
    assert sum(ds.decision_basis_counts.values()) == ds.n_decision_examples


def test_refusal_wording_varies(examples):
    answers = {ex.messages[-1].content for ex in examples if ex.kind == "refusal"}
    questions = {ex.question for ex in examples if ex.kind == "refusal"}
    n = len(REFUSAL_TRAIN_PHRASINGS) * len(OUT_OF_SCOPE_DOMAINS)
    assert len(questions) == n
    # Each topic rotates through the refusal reasons, so every topic gets several distinct answers.
    assert len(answers) == 3 * len(OUT_OF_SCOPE_DOMAINS)


def test_children_fit_inside_the_spending_budget():
    for scenario, household, _ in sample_households(list(SLM_SCENARIOS), 40, 3):
        start_age = household["person_start_age"]
        assert all(0 <= age <= min(17, start_age - 20) for age in household["children_ages"])
        base = household["initial_spending"]
        # Base spending is what remains after child costs; children take at most half the total.
        child_costs = sum(12000 if a < 6 else 8000 for a in household["children_ages"])
        assert child_costs <= MAX_CHILD_SHARE_OF_SPENDING * (base + child_costs) + 0.01, scenario


def test_training_economies_exclude_the_held_out_recession():
    assert "recession" not in TRAIN_ECONOMIES
    drawn = {h.get("economy_scenario") for _, h, _ in sample_households(list(SLM_SCENARIOS), 30, 4)}
    assert "recession" not in drawn and None in drawn and len(drawn) > 2


def test_older_households_are_sampled():
    ages = [h["person_start_age"] for _, h, _ in sample_households(["late_career", "pre_retiree"], 20, 5)]
    assert min(ages) >= 46 and max(ages) >= 55


def test_balance_caps_every_label(examples):
    decisions = [e for e in examples if e.kind == "decision"]
    # Relabel copies so one label dominates, then cap it.
    skewed = [
        e.model_copy(update={"example_id": f"x-{i}", "chosen_decision": "max_roth_401k" if i % 5 else "age_glide"})
        for i, e in enumerate(decisions * 10)
    ]
    kept, dropped = _balance_labels(skewed, max_share=0.5)
    counts = {label: sum(e.chosen_decision == label for e in kept) for label in {e.chosen_decision for e in kept}}
    assert dropped == len(skewed) - len(kept) > 0
    assert max(counts.values()) <= 0.5 * len(kept) + 1
    assert counts["age_glide"] == sum(e.chosen_decision == "age_glide" for e in skewed)  # minority untouched
