# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Shared marginal-bracket engine.

Both federal and state income taxes are computed as a sum over half-open marginal segments. This
single helper is the one place that logic lives so federal and state can never silently drift
(Plan 17 Risks). :func:`~life_model.tax.federal.federal_income_tax` and the state pack engine both
call it; they are property-tested against each other.
"""

from typing import List, Sequence, Union

Bracket = Sequence[Union[int, float]]


def apply_brackets(income: float, brackets: "List[Bracket]") -> float:
    """Apply progressive tax brackets to ``income``.

    Brackets are treated as half-open marginal segments ``[prev_upper, upper)`` where ``upper`` is
    each row's second column (the last row uses ``inf``). Using the upper bound as the segment
    boundary — rather than the row's own ``start`` (``prev_upper + 1``) — closes the $1 gaps the old
    ``[start, end]`` rows left between brackets. The result is not rounded (Plan 04 D3); callers
    round the final total tax bill once.

    Args:
        income: Taxable income.
        brackets: Rows of ``[lower, upper, rate_percent]`` in ascending order.

    Returns:
        The total tax owed across all marginal segments.
    """
    total_tax = 0.0
    prev_upper = 0.0
    for _start, upper, percent in brackets:
        if income <= prev_upper:
            break
        amount_in_bracket = min(income, upper) - prev_upper
        total_tax += amount_in_bracket * (percent / 100)
        prev_upper = upper
    return total_tax
