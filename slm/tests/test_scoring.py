# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Paired, return-based scoring: gaps to the best, the top set, the label basis, adaptive trials."""

import numpy as np
import pytest

from slm.faithfulness import is_consistent, is_faithful
from slm.generate_data import _sample_households, _trial_seeds
from slm.rationales import build_rationale
from slm.schema import ScoredCandidate
from slm.scoring import (
    argmax_candidate,
    decision_basis,
    paired_bootstrap_ci,
    score_household,
    top_set,
)


def _candidate(name, mean_return, *, success=1.0, in_top_set=True, gap_low=0.0, n=32):
    return ScoredCandidate(
        decision=name,
        success_rate=success,
        mean_return=mean_return,
        net_worth_p10=100000.0,
        net_worth_p50=200000.0,
        net_worth_p90=300000.0,
        n_trials=n,
        gap_ci_low=gap_low,
        in_top_set=in_top_set,
    )


def test_paired_bootstrap_ci_brackets_the_mean_and_is_deterministic():
    diffs = np.random.default_rng(1).normal(0.5, 1.0, 64)
    low, high = paired_bootstrap_ci(diffs)
    assert low < diffs.mean() < high
    assert paired_bootstrap_ci(diffs) == (low, high)
    assert paired_bootstrap_ci(np.zeros(10)) == (0.0, 0.0)


def test_argmax_is_by_mean_return_not_success():
    scored = [_candidate("a", 10.0, success=1.0), _candidate("b", 12.0, success=0.9)]
    assert argmax_candidate(scored).decision == "b"


def test_basis_clear_only_when_no_alternative_in_top_set():
    clear = [_candidate("a", 12.0), _candidate("b", 10.0, in_top_set=False, gap_low=0.5)]
    tied = [_candidate("a", 12.0), _candidate("b", 11.9, in_top_set=True, gap_low=-0.1)]
    assert decision_basis(clear) == "clear"
    assert decision_basis(tied) == "equivalent"
    assert top_set(tied) == ["a", "b"]
    hopeless = [_candidate("a", 1.0, success=0.05), _candidate("b", 0.5, success=0.0)]
    assert decision_basis(hopeless) == "no_viable"


@pytest.fixture(scope="module")
def household():
    return _sample_households(["mid_career"], 1, 3)[0][1]


def test_scores_carry_paired_gaps(household):
    scored = score_household(household, _trial_seeds(3, 0, 8), "retirement_security")
    best = argmax_candidate(scored)
    assert best.gap_to_best == 0.0 and best.in_top_set
    for c in scored:
        assert c.gap_to_best >= 0.0
        assert c.gap_ci_low <= c.gap_to_best <= c.gap_ci_high
        assert c.in_top_set == (c.decision == best.decision or c.gap_ci_low <= 0.0)


def test_adaptive_trials_grow_only_while_equivalent(household):
    seeds = _trial_seeds(3, 0, 16)
    adaptive = score_household(household, seeds, "retirement_security", min_trials=4)
    n = adaptive[0].n_trials
    assert n in (4, 8, 16)
    if n < 16:
        assert decision_basis(adaptive) != "equivalent"
    # Scoring the same number of seeds non-adaptively gives the same numbers.
    fixed = score_household(household, seeds[:n], "retirement_security")
    assert [c.model_dump() for c in fixed] == [c.model_dump() for c in adaptive]


def test_consistency_tolerates_noise_but_not_fabrication(household):
    scored = score_household(household, _trial_seeds(3, 0, 16), "retirement_security")
    chosen = argmax_candidate(scored).decision
    rationale = build_rationale(scored, chosen)
    assert is_faithful(rationale, scored, chosen) and is_consistent(rationale, scored, chosen)
    # One point off on a percentage: not exact, but within Monte Carlo noise.
    best = argmax_candidate(scored)
    pct = round(best.success_rate * 100)
    nudged = rationale.replace(f"in {pct}% of trials", f"in {max(pct - 1, 0) if pct > 50 else pct + 1}% of trials", 1)
    assert is_consistent(nudged, scored, chosen)
    assert not is_consistent(rationale + " Success is 3% and wealth is $987,654,321.", scored, chosen)
