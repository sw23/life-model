# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Adviser eval-harness tests (acceptance):

* the oracle adviser (always argmax) scores >= every heuristic on outcome quality — validating
  the harness end-to-end without any model;
* the numeric-faithfulness gate accepts true numbers and rejects fabricated ones;
* the refusal metric detects trained scope discipline;
* the report is schema-shaped and deterministic under seed.

Kept small (fewer households/trials) so it runs in CI without the slow marker.
"""

import pytest

from slm.adviser import StubAdviserModel
from slm.evaluate_adviser import AdviserEvaluator, format_report
from slm.faithfulness import is_faithful
from slm.generate_data import _sample_households, _trial_seeds
from slm.rationales import build_rationale, rationale_of
from slm.scoring import argmax_candidate, score_household


@pytest.fixture(scope="module")
def evaluator():
    # One scenario, no held-out economy overlay, tiny counts: keeps the harness cheap for CI.
    return AdviserEvaluator(scenarios=["basic"], n_per_scenario=3, n_trials=4, master_seed=777, held_out_scenario=None)


@pytest.fixture(scope="module")
def oracle_report(evaluator):
    return evaluator.run(evaluator.build_oracle(), include_oracle=True)


@pytest.fixture(scope="module")
def stub_report(evaluator):
    return evaluator.run(StubAdviserModel(fixed_decision="contribution_waterfall"), include_oracle=False)


def test_oracle_beats_all_heuristics(oracle_report):
    cond = oracle_report["conditions"]["held_out_seeds"]
    # The oracle emits each household's argmax, so its mean success is >= every heuristic's.
    assert cond["adviser_beats_best_heuristic"] is True
    for stats in cond["heuristics"].values():
        assert cond["adviser_mean_success_rate"] >= stats["mean_success_rate"] - 1e-9


def test_oracle_block_reports_beats_all(oracle_report):
    assert oracle_report["oracle"]["held_out_seeds"]["oracle_beats_all_heuristics"] is True


def test_parse_and_refusal_rates(stub_report):
    # The stub always emits a parseable in-scope decision, and always refuses out-of-scope prompts.
    assert stub_report["conditions"]["held_out_seeds"]["parse_rate"] == 1.0
    assert stub_report["refusals"]["refusal_rate"] == 1.0


def test_report_is_deterministic(evaluator, stub_report):
    b = evaluator.run(StubAdviserModel(fixed_decision="contribution_waterfall"), include_oracle=False)
    a = {k: v for k, v in stub_report.items() if k != "created_utc"}
    b = {k: v for k, v in b.items() if k != "created_utc"}
    assert a == b
    assert isinstance(format_report(stub_report), str)


def test_faithfulness_accepts_true_numbers_rejects_fabrications():
    household = _sample_households(["basic"], 1, 999)[0][1]
    seeds = _trial_seeds(999, 0, 6)
    scored = score_household(household, seeds, "retirement_security")
    chosen = argmax_candidate(scored).decision

    true_rationale = build_rationale(scored, chosen)
    assert is_faithful(true_rationale, scored, chosen)

    # A fabricated success rate (impossible 137%) must fail the gate.
    fabricated = true_rationale + " Also, success is 137% and terminal wealth is $999,999,999."
    assert not is_faithful(fabricated, scored, chosen)


def test_rationale_of_matches_build_rationale():
    household = _sample_households(["basic"], 1, 5)[0][1]
    seeds = _trial_seeds(5, 0, 4)
    scored = score_household(household, seeds, "retirement_security")
    chosen = argmax_candidate(scored).decision
    assert rationale_of(scored) == build_rationale(scored, chosen)
