# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Templated counterfactual rationales (Plan 20 D2, task 2).

The rationale is a pure function of the stored :class:`~slm.schema.ScoredCandidate` records: it
compares the chosen (argmax) lever against the next-best one and cites the success-rate and
median-terminal-wealth figures straight from the scoring run. Because every number is copied from
a stored score, faithfulness is guaranteed at data time — the generator test recomputes the exact
string from the stored scores, and the eval harness re-derives the same numbers from a fresh
scoring run (numeric-faithfulness gate, D4).
"""

import re
from typing import List, Tuple

from .schema import ScoredCandidate
from .scoring import argmax_candidate
from .strategies import STRATEGY_BY_NAME


def _pct(success_rate: float) -> int:
    """Success rate as an integer percentage (the form cited in text)."""
    return int(round(success_rate * 100))


def _title(name: str) -> str:
    return STRATEGY_BY_NAME[name].title


def runner_up(scored: List[ScoredCandidate], chosen: str) -> ScoredCandidate:
    """The best candidate other than ``chosen`` (same deterministic ordering as the argmax)."""
    others = [c for c in scored if c.decision != chosen]
    return argmax_candidate(others)


def build_rationale(scored: List[ScoredCandidate], chosen_name: str) -> str:
    """Build the counterfactual rationale for ``chosen_name`` from the stored scores."""
    chosen = next(c for c in scored if c.decision == chosen_name)
    runner = runner_up(scored, chosen_name)
    delta_wealth = chosen.net_worth_p50 - runner.net_worth_p50
    direction = "above" if delta_wealth >= 0 else "below"
    return (
        f"Over {chosen.n_trials} shared Monte Carlo trials, {_title(chosen_name)} "
        f"({chosen_name}) is the strongest plan-level lever here: it keeps the household solvent "
        f"to end of life in {_pct(chosen.success_rate)}% of trials, versus "
        f"{_pct(runner.success_rate)}% for the next-best option, {_title(runner.decision)} "
        f"({runner.decision}). Its median terminal net worth is ${chosen.net_worth_p50:,.0f}, "
        f"${abs(delta_wealth):,.0f} {direction} the next-best lever's "
        f"${runner.net_worth_p50:,.0f}. These are simulator Monte Carlo outputs under stated "
        f"assumptions, not guarantees."
    )


_PCT_RE = re.compile(r"(\d+)%")
_DOLLAR_RE = re.compile(r"\$([\d,]+)")


def cited_percentages(rationale: str) -> List[int]:
    """Every integer percentage cited in a rationale (for the faithfulness gate)."""
    return [int(m) for m in _PCT_RE.findall(rationale)]


def cited_dollars(rationale: str) -> List[int]:
    """Every whole-dollar figure cited in a rationale (for the faithfulness gate)."""
    return [int(m.replace(",", "")) for m in _DOLLAR_RE.findall(rationale)]


def faithfulness_targets(scored: List[ScoredCandidate], chosen_name: str) -> Tuple[List[int], List[int]]:
    """The (percentages, dollars) a faithful rationale for ``chosen_name`` should cite.

    Used by the eval harness (D4): re-derive these from a fresh scoring run and confirm the
    adviser's rationale cites matching numbers within tolerance.
    """
    chosen = next(c for c in scored if c.decision == chosen_name)
    runner = runner_up(scored, chosen_name)
    delta = abs(chosen.net_worth_p50 - runner.net_worth_p50)
    pcts = [_pct(chosen.success_rate), _pct(runner.success_rate)]
    dollars = [int(round(chosen.net_worth_p50)), int(round(delta)), int(round(runner.net_worth_p50))]
    return pcts, dollars
