# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Numeric-faithfulness gate (Plan 20 D4, metric family 2).

The anti-hallucination check: every number an adviser cites in its rationale must match a figure
re-derived from a fresh scoring run of the household within tolerance. A rationale that cites *no*
numbers is vacuously faithful (it claims nothing false); a rationale that cites an invented figure
fails. This is a pure function of text + scores, so it is unit-testable without any model.
"""

from typing import List

from .rationales import cited_dollars, cited_percentages, faithfulness_targets
from .schema import ScoredCandidate

# Tolerances: percentages within 1 point, dollars within 2% (or $1, whichever is larger) of a
# re-derived target — loose enough to absorb Monte Carlo re-scoring noise, tight enough to catch
# fabricated numbers.
PCT_TOLERANCE = 1
DOLLAR_TOLERANCE_FRACTION = 0.02


def _matches(value: float, targets: List[int], tol: float) -> bool:
    return any(abs(value - t) <= tol for t in targets)


def is_faithful(
    rationale: str,
    scored: List[ScoredCandidate],
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
