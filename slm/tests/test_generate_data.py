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

from slm.generate_data import build_datasheet, examples_to_jsonl, generate_examples
from slm.prompts import OUT_OF_SCOPE_DOMAINS, is_refusal, parse_decision
from slm.rationales import build_rationale
from slm.schema import AdviceExample
from slm.strategies import STRATEGY_NAMES

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
        assert ex.chosen_decision in STRATEGY_NAMES
        recomputed = build_rationale(ex.scored_alternatives, ex.chosen_decision)
        assert recomputed == ex.rationale


def test_chosen_is_argmax_success_rate(examples):
    for ex in examples:
        if ex.kind != "decision":
            continue
        chosen = next(c for c in ex.scored_alternatives if c.decision == ex.chosen_decision)
        best_rate = max(c.success_rate for c in ex.scored_alternatives)
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
    assert ds.n_refusal_examples == 3 * len(OUT_OF_SCOPE_DOMAINS)
    assert ds.simulator_commit and ds.config_hash
