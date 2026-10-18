# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Shared marginal-bracket engine.

Both federal and state income taxes are computed as a sum over half-open marginal segments. This
single helper is the one place that logic lives so federal and state can never silently drift.
:func:`~life_model.tax.federal.federal_income_tax` and the state pack engine both
call it; they are property-tested against each other.
"""

from collections.abc import Sequence

Bracket = Sequence[int | float]

#: One marginal segment a taxable amount reached: ``(lower, upper, rate_percent, amount, tax)``, where
#: ``amount`` is the income taxed in ``[lower, upper)`` and ``tax`` is ``amount * rate / 100``.
BracketSlice = tuple[float, float, float, float, float]


def apply_brackets(income: float, brackets: "list[Bracket]") -> float:
    """Apply progressive tax brackets to ``income``.

    Brackets are treated as half-open marginal segments ``[prev_upper, upper)`` where ``upper`` is
    each row's second column (the last row uses ``inf``). Using the upper bound as the segment
    boundary — rather than the row's own ``start`` (``prev_upper + 1``) — closes the $1 gaps the old
    ``[start, end]`` rows left between brackets. The result is not rounded; callers
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


def bracket_slices(income: float, brackets: "list[Bracket]") -> list[BracketSlice]:
    """The marginal segments ``income`` reaches, with the tax charged in each.

    Walks the brackets exactly as :func:`apply_brackets` does (same segment bounds, same arithmetic,
    same order), so ``sum(tax for *_, tax in bracket_slices(x, b)) == apply_brackets(x, b)``. Used to
    show a return's per-bracket breakdown; it never feeds back into the tax computed.
    """
    slices: list[BracketSlice] = []
    prev_upper = 0.0
    for _start, upper, percent in brackets:
        if income <= prev_upper:
            break
        amount_in_bracket = min(income, upper) - prev_upper
        tax = amount_in_bracket * (percent / 100)
        slices.append((float(prev_upper), float(upper), float(percent), float(amount_in_bracket), tax))
        prev_upper = upper
    return slices
