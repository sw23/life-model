# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Templated counterfactual rationales.

The rationale is a pure function of the stored :class:`~slm.schema.ScoredCandidate` records: it
compares the chosen plan against the default plan (or, for the default, the strongest alternative) and cites the success-rate and
median-terminal-wealth figures straight from the scoring run. Its wording follows the
:func:`~slm.scoring.decision_basis`: a clear winner is called the strongest lever, statistically
indistinguishable options are called equivalent, and ``NO_LEVER`` says no lever is sufficient. Because every number is copied from
a stored score, faithfulness is guaranteed at data time — the generator test recomputes the exact
string from the stored scores, and the eval harness re-derives the same numbers from a fresh
scoring run (numeric-faithfulness gate).
"""

import re

from .schema import ScoredCandidate
from .scoring import argmax_candidate, decision_basis, label_decision
from .strategies import DEFAULT_PLAN, NO_LEVER, STRATEGY_BY_NAME


def _pct(success_rate: float) -> int:
    """Success rate as an integer percentage (the form cited in text)."""
    return round(success_rate * 100)


def _title(name: str) -> str:
    return STRATEGY_BY_NAME[name].title


def runner_up(scored: list[ScoredCandidate], chosen: str) -> ScoredCandidate:
    """The comparison the rationale cites: the default plan when ``chosen`` changes a lever off it
    (the counterfactual "what if you changed nothing"), else the best other candidate."""
    others = [c for c in scored if c.decision != chosen]
    default = next((c for c in others if c.decision == DEFAULT_PLAN.name), None)
    if default is not None:
        return default
    return argmax_candidate(others)


def rationale_of(scored: list[ScoredCandidate]) -> str:
    """Convenience: the rationale for the label of ``scored``."""
    return build_rationale(scored, label_decision(scored))


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


def _runner_phrase(runner: ScoredCandidate) -> str:
    who = "the default plan" if runner.decision == DEFAULT_PLAN.name else "the strongest alternative"
    return f"{who}, {_title(runner.decision)} ({runner.decision})"


def _equivalent_rationale(chosen: ScoredCandidate, runner: ScoredCandidate) -> str:
    delta_wealth = chosen.net_worth_p50 - runner.net_worth_p50
    direction = "above" if delta_wealth >= 0 else "below"
    return (
        f"Over {chosen.n_trials} shared Monte Carlo trials, no lever change is proven better beyond simulation "
        f"noise on the simulator's retirement-security objective for this household: "
        f"{_title(chosen.decision)} ({chosen.decision}) stays solvent to end of life "
        f"in {_pct(chosen.success_rate)}% of trials versus {_pct(runner.success_rate)}% for "
        f"{_runner_phrase(runner)}, and its median terminal net worth of "
        f"${chosen.net_worth_p50:,.0f} is ${abs(delta_wealth):,.0f} {direction} the alternative's "
        f"${runner.net_worth_p50:,.0f}. It is recommended because no change has evidence behind it, but the "
        f"alternative is a reasonable choice too. These are simulator Monte Carlo outputs under stated "
        f"assumptions, not guarantees."
    )


def build_rationale(scored: list[ScoredCandidate], chosen_name: str) -> str:
    """Build the counterfactual rationale for ``chosen_name`` from the stored scores."""
    if chosen_name == NO_LEVER:
        return _no_lever_rationale(scored)
    chosen = next(c for c in scored if c.decision == chosen_name)
    runner = runner_up(scored, chosen_name)
    if chosen_name == label_decision(scored) and decision_basis(scored) == "equivalent":
        return _equivalent_rationale(chosen, runner)
    delta_wealth = chosen.net_worth_p50 - runner.net_worth_p50
    direction = "above" if delta_wealth >= 0 else "below"
    if chosen_name != label_decision(scored):
        lead = (
            f"Over {chosen.n_trials} shared Monte Carlo trials, {_title(chosen_name)} ({chosen_name}) "
            f"is not the plan the simulator's evidence supports here"
        )
    elif chosen_name == DEFAULT_PLAN.name:
        lead = (
            f"Over {chosen.n_trials} shared Monte Carlo trials, the default plan, {_title(chosen_name)} "
            f"({chosen_name}), beats every single-lever change beyond simulation noise on the simulator's "
            f"retirement-security objective (solvency first, then wealth left at the end of life)"
        )
    else:
        lead = (
            f"Over {chosen.n_trials} shared Monte Carlo trials, {_title(chosen_name)} ({chosen_name}) "
            f"improves on the default plan beyond simulation noise on the simulator's retirement-security "
            f"objective (solvency first, then wealth left at the end of life)"
        )
    return (
        f"{lead}: it keeps the household solvent to end of life in {_pct(chosen.success_rate)}% of trials, "
        f"versus {_pct(runner.success_rate)}% for {_runner_phrase(runner)}. Its median terminal net worth is "
        f"${chosen.net_worth_p50:,.0f}, ${abs(delta_wealth):,.0f} {direction} the alternative's "
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
