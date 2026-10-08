# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Templated counterfactual rationales.

The rationale is a pure function of the stored :class:`~slm.schema.ScoredCandidate` records: it
compares the chosen (argmax) lever against the next-best one and cites the success-rate and
median-terminal-wealth figures straight from the scoring run. Its wording follows the
:func:`~slm.scoring.decision_basis`: a clear winner is called the strongest lever, statistically
indistinguishable options are called equivalent, and ``NO_LEVER`` says no lever is sufficient. Because every number is copied from
a stored score, faithfulness is guaranteed at data time — the generator test recomputes the exact
string from the stored scores, and the eval harness re-derives the same numbers from a fresh
scoring run (numeric-faithfulness gate).
"""

import re

from .schema import ScoredCandidate
from .scoring import argmax_candidate, decision_basis
from .strategies import NO_LEVER, STRATEGY_BY_NAME


def _pct(success_rate: float) -> int:
    """Success rate as an integer percentage (the form cited in text)."""
    return round(success_rate * 100)


def _title(name: str) -> str:
    return STRATEGY_BY_NAME[name].title


def runner_up(scored: list[ScoredCandidate], chosen: str) -> ScoredCandidate:
    """The best candidate other than ``chosen`` (same deterministic ordering as the argmax)."""
    others = [c for c in scored if c.decision != chosen]
    return argmax_candidate(others)


def rationale_of(scored: list[ScoredCandidate]) -> str:
    """Convenience: the rationale for the argmax candidate of ``scored``."""
    return build_rationale(scored, argmax_candidate(scored).decision)


def _worst(scored: list[ScoredCandidate]) -> ScoredCandidate:
    return min(scored, key=lambda c: (c.success_rate, c.net_worth_p50))


def _no_lever_rationale(scored: list[ScoredCandidate]) -> str:
    best = argmax_candidate(scored)
    worst = _worst(scored)
    return (
        f"Over {best.n_trials} shared Monte Carlo trials, no strategy on the menu keeps this household "
        f"solvent: the best option, {_title(best.decision)} ({best.decision}), stays solvent to end of "
        f"life in only {_pct(best.success_rate)}% of trials and the weakest in {_pct(worst.success_rate)}%, "
        f"and even the best option's median terminal net worth is ${best.net_worth_p50:,.0f}. The "
        f"shortfall is spending relative to income, which none of these levers changes. These are "
        f"simulator Monte Carlo outputs under stated assumptions, not guarantees."
    )


def _equivalent_rationale(chosen: ScoredCandidate, runner: ScoredCandidate) -> str:
    delta_wealth = chosen.net_worth_p50 - runner.net_worth_p50
    direction = "above" if delta_wealth >= 0 else "below"
    return (
        f"Over {chosen.n_trials} shared Monte Carlo trials, the top options are within simulation noise "
        f"for this household: {_title(chosen.decision)} ({chosen.decision}) stays solvent to end of life "
        f"in {_pct(chosen.success_rate)}% of trials versus {_pct(runner.success_rate)}% for "
        f"{_title(runner.decision)} ({runner.decision}), and its median terminal net worth of "
        f"${chosen.net_worth_p50:,.0f} is ${abs(delta_wealth):,.0f} {direction} the alternative's "
        f"${runner.net_worth_p50:,.0f}. It is listed for that slight edge, but either is a reasonable "
        f"choice. These are simulator Monte Carlo outputs under stated assumptions, not guarantees."
    )


def build_rationale(scored: list[ScoredCandidate], chosen_name: str) -> str:
    """Build the counterfactual rationale for ``chosen_name`` from the stored scores."""
    if chosen_name == NO_LEVER:
        return _no_lever_rationale(scored)
    chosen = next(c for c in scored if c.decision == chosen_name)
    runner = runner_up(scored, chosen_name)
    if chosen_name == argmax_candidate(scored).decision and decision_basis(scored) == "equivalent":
        return _equivalent_rationale(chosen, runner)
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


def _without_titles(rationale: str) -> str:
    """Drop strategy titles, whose own numbers (the "4%" in "4%-rule") are names, not citations."""
    for strategy in STRATEGY_BY_NAME.values():
        rationale = rationale.replace(strategy.title, "")
    return rationale


def cited_percentages(rationale: str) -> list[int]:
    """Every integer percentage cited in a rationale (for the faithfulness gate)."""
    return [int(m) for m in _PCT_RE.findall(_without_titles(rationale))]


def cited_dollars(rationale: str) -> list[int]:
    """Every whole-dollar figure cited in a rationale (for the faithfulness gate)."""
    return [int(m.replace(",", "")) for m in _DOLLAR_RE.findall(_without_titles(rationale))]


def faithfulness_targets(scored: list[ScoredCandidate], chosen_name: str) -> tuple[list[int], list[int]]:
    """The (percentages, dollars) a faithful rationale for ``chosen_name`` should cite.

    Used by the eval harness: re-derive these from a fresh scoring run and confirm the
    adviser's rationale cites matching numbers within tolerance.
    """
    if chosen_name == NO_LEVER:
        best = argmax_candidate(scored)
        return [_pct(best.success_rate), _pct(_worst(scored).success_rate)], [round(best.net_worth_p50)]
    chosen = next(c for c in scored if c.decision == chosen_name)
    runner = runner_up(scored, chosen_name)
    delta = abs(chosen.net_worth_p50 - runner.net_worth_p50)
    pcts = [_pct(chosen.success_rate), _pct(runner.success_rate)]
    dollars = [round(chosen.net_worth_p50), round(delta), round(runner.net_worth_p50)]
    return pcts, dollars
