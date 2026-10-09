# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Numeric-faithfulness gates (metric family 2).

The anti-hallucination check: every number an adviser cites in its rationale must match a figure
re-derived from a fresh scoring run of the household within tolerance. A rationale that cites *no*
numbers is vacuously faithful (it claims nothing false); a rationale that cites an invented figure
fails. This is a pure function of text + scores, so it is unit-testable without any model.

Two gates, for two questions:

* :func:`is_faithful` — **exact**: the numbers match *this* scoring run (1-point / 2% tolerance).
  An answer generated from a scoring run (the dataset rationale, the tool-loop's live run) must
  pass it against that run; that is faithfulness by construction.
* :func:`is_consistent` — **within Monte Carlo noise** of an independent scoring run: each cited
  percentage within two binomial standard errors (at least 2 points) and each cited dollar figure
  within three standard errors of the median. A distilled model never sees the eval's seeds, so
  exact agreement with them measures seed luck; consistency is the anti-hallucination check that
  can actually be passed.
"""

import math

from .rationales import cited_dollars, cited_percentages, faithfulness_targets
from .schema import ScoredCandidate

# Tolerances: percentages within 1 point, dollars within 2% (or $1, whichever is larger) of a
# re-derived target — loose enough to absorb Monte Carlo re-scoring noise, tight enough to catch
# fabricated numbers.
PCT_TOLERANCE = 1
DOLLAR_TOLERANCE_FRACTION = 0.02


def _matches(value: float, targets: list[int], tol: float) -> bool:
    return any(abs(value - t) <= tol for t in targets)


def is_faithful(
    rationale: str,
    scored: list[ScoredCandidate],
    chosen: str,
    pct_tolerance: int = PCT_TOLERANCE,
    dollar_tolerance_fraction: float = DOLLAR_TOLERANCE_FRACTION,
) -> bool:
    """Whether every number cited in ``rationale`` matches a re-derived scoring figure."""
    target_pcts, target_dollars = faithfulness_targets(scored, chosen)
    for pct in cited_percentages(rationale):
        if not _matches(pct, target_pcts, pct_tolerance):
            return False
    for dollars in cited_dollars(rationale):
        tol = max(1.0, dollar_tolerance_fraction * max(abs(d) for d in target_dollars + [1]))
        if not _matches(dollars, target_dollars, tol):
            return False
    return True


def _median_se(c: ScoredCandidate) -> float:
    """Approximate standard error of a median from the p10-p90 spread (normal approximation)."""
    sigma = max(c.net_worth_p90 - c.net_worth_p10, 0.0) / 2.5631
    return 1.2533 * sigma / math.sqrt(max(c.n_trials, 1))


def is_consistent(rationale: str, scored: list[ScoredCandidate], chosen: str) -> bool:
    """Whether every number cited in ``rationale`` is within Monte Carlo noise of ``scored``."""
    target_pcts, target_dollars = faithfulness_targets(scored, chosen)
    n = max(c.n_trials for c in scored)
    for pct in cited_percentages(rationale):
        ok = False
        for t in target_pcts:
            p = min(max(t / 100.0, 0.0), 1.0)
            tol = max(2.0, 200.0 * math.sqrt(p * (1 - p) / n) + 1.0)
            ok = ok or abs(pct - t) <= tol
        if not ok:
            return False
    dollar_tol = max(1000.0, 3.0 * math.sqrt(2.0) * max(_median_se(c) for c in scored))
    for dollars in cited_dollars(rationale):
        if not _matches(dollars, target_dollars, dollar_tol):
            return False
    return True
