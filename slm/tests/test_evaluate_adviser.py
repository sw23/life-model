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
from slm.scoring import argmax_candidate, decision_basis, label_decision, score_household
from slm.strategies import NO_LEVER


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


def test_no_lever_answer_runs_the_default_plan(evaluator):
    # An always-abstaining adviser is scored as the default plan, so abstaining cannot game outcomes.
    abstain = evaluator.run(StubAdviserModel(fixed_decision=NO_LEVER), include_oracle=False)
    default = evaluator.run(StubAdviserModel(fixed_decision="contribution_waterfall"), include_oracle=False)
    a, d = abstain["conditions"]["held_out_seeds"], default["conditions"]["held_out_seeds"]
    assert a["parse_rate"] == 1.0 and a["abstain_rate"] == 1.0
    assert a["adviser_mean_success_rate"] == d["adviser_mean_success_rate"]
    assert a["label_agreement_rate"] == a["label_abstain_rate"]


def test_no_lever_rationale_is_faithful():
    # Find a household with no viable lever and check its rationale passes the numeric gate.
    for seed in range(40):
        household = _sample_households(["low_earner"], 1, seed)[0][1]
        household["initial_spending"] = household["initial_salary"] * 1.2  # spends more than it earns
        scored = score_household(household, _trial_seeds(seed, 0, 4), "retirement_security")
        if decision_basis(scored) == "no_viable":
            assert label_decision(scored) == NO_LEVER
            rationale = build_rationale(scored, NO_LEVER)
            assert "no strategy on the menu keeps this household solvent" in rationale
            assert is_faithful(rationale, scored, NO_LEVER)
            assert not is_faithful(rationale + " Success is 97%.", scored, NO_LEVER)
            return
    pytest.fail("no insolvent household found")


def test_strategy_titles_are_not_cited_numbers():
    # "Accumulate then 4%-rule drawdown" names a strategy; its 4% is not a claimed success rate.
    from slm.rationales import cited_percentages

    text = "Accumulate then 4%-rule drawdown (four_percent_drawdown) is solvent in 50% of trials."
    assert cited_percentages(text) == [50]


def test_oracle_has_zero_regret_and_full_top_set_agreement(oracle_report):
    cond = oracle_report["conditions"]["held_out_seeds"]
    assert cond["adviser_regret"]["mean_regret"] == pytest.approx(0.0)
    assert cond["top_set_agreement_rate"] == 1.0
    for block in cond["constant_policy_regret"].values():
        assert block["mean_regret"] >= -1e-9
        assert 0.0 <= block["normalized_regret"] <= 1.0
    # The oracle is never worse than any constant answer.
    assert cond["adviser_vs_best_constant"]["mean_regret_advantage"] >= -1e-9


def test_constant_adviser_regret_equals_its_policy_row(stub_report):
    cond = stub_report["conditions"]["held_out_seeds"]
    row = cond["constant_policy_regret"]["contribution_waterfall"]
    assert cond["adviser_regret"]["mean_regret"] == pytest.approx(row["mean_regret"])
    assert "adviser regret" in format_report(stub_report)
