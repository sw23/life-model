# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Alternative minimum tax (IRC §55-§56; Form 6251) and the minimum tax credit (§53; Form 8801).

A parallel computation on the same return inputs (Plan 31 D2): alternative minimum taxable income is
taxable income plus the senior deduction (2025+), plus the standard deduction or the itemized SALT,
plus the incentive-stock-option spread, less the §68 reduction (§56(b)(1)(E): §68 does not apply to
AMT). The exemption phases out at the year's rate; the tentative minimum tax uses 26%/28% with Form
6251 Part III's capital-gain rates; AMT is the excess over the regular tax.

Only deferral items (the ISO spread here) create a minimum tax credit: Form 8801 Part I refigures the
year's AMT on exclusion items alone, and the rest carries forward, usable in a later year up to the
regular tax (after other nonrefundable credits) less that year's tentative minimum tax.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .federal import FilingStatus

if TYPE_CHECKING:
    from ..config.models import AMTYear


@dataclass(frozen=True)
class AMTInputs:
    """What Form 6251 reads from the regular return."""

    #: Form 1040 line 11 minus line 14 (may be negative).
    taxable_income: float
    #: Schedule 1-A senior deduction (added back from 2025, Form 6251 line 1a).
    senior_deduction: float = 0.0
    #: Line 2a: the standard deduction taken, or the itemized taxes (Schedule A line 7).
    deduction_addback: float = 0.0
    #: Line 2i: the bargain element of incentive stock options exercised and held (a deferral item).
    iso_adjustment: float = 0.0
    #: The §68 reduction of itemized deductions, which AMT does not apply (a negative adjustment).
    itemized_limitation: float = 0.0
    #: Qualified dividends plus net long-term gain taxed at preferential rates (QDCGT worksheet line 4).
    preferential_income: float = 0.0
    #: Regular taxable income taxed at ordinary rates (QDCGT worksheet line 5).
    regular_taxable_ordinary: float = 0.0
    #: Line 10: regular tax (Form 1040 line 16).
    regular_tax: float = 0.0


@dataclass(frozen=True)
class AMTResult:
    amti: float = 0.0
    exemption: float = 0.0
    taxable_excess: float = 0.0
    #: Line 9: tentative minimum tax.
    tentative_minimum_tax: float = 0.0
    #: Line 11: alternative minimum tax.
    amt: float = 0.0


def _by_status(params: "AMTYear", filing_status: FilingStatus) -> tuple[float, float, float]:
    """(exemption, phase-out start, 28% breakpoint) for the status."""
    # "A joint return or a surviving spouse" (IRC §55(d)(1)(A), (d)(2)(A)).
    if filing_status.joint_rates:
        return params.exemption_joint, params.phaseout_start_joint, params.breakpoint
    if filing_status == FilingStatus.MARRIED_FILING_SEPARATELY:
        return params.exemption_separate, params.phaseout_start_separate, params.breakpoint_separate
    return params.exemption_single, params.phaseout_start_single, params.breakpoint


def _rate_tax(amount: float, breakpoint: float, params: "AMTYear") -> float:
    """Form 6251 line 7 / 18 / 39: 26% up to the breakpoint, 28% above (less 2% of the breakpoint)."""
    amount = max(0.0, amount)
    if amount <= breakpoint:
        return amount * params.low_rate / 100
    return amount * params.high_rate / 100 - breakpoint * (params.high_rate - params.low_rate) / 100


def alternative_minimum_tax(
    inputs: AMTInputs,
    filing_status: FilingStatus,
    params: "AMTYear | None",
    capital_gains_brackets: "list | None" = None,
    *,
    include_deferral_items: bool = True,
) -> AMTResult:
    """Form 6251 for one return (``include_deferral_items=False`` is Form 8801 Part I).

    Args:
        inputs: The regular return's figures (:class:`AMTInputs`).
        filing_status: The return's filing status.
        params: The year's AMT parameters (None: no AMT).
        capital_gains_brackets: The year's preferential brackets ``[[lower, upper, rate], ...]`` (their
            0% and 15% tops are Part III lines 19 and 25).
        include_deferral_items: False refigures the tax on exclusion items only (the ISO spread out).
    """
    if params is None:
        return AMTResult()
    amti = (
        inputs.taxable_income
        + inputs.senior_deduction
        + inputs.deduction_addback
        - inputs.itemized_limitation
        + (inputs.iso_adjustment if include_deferral_items else 0.0)
    )
    exemption_full, phaseout_start, breakpoint = _by_status(params, filing_status)
    exemption = max(0.0, exemption_full - params.phaseout_rate / 100 * max(0.0, amti - phaseout_start))
    excess = max(0.0, amti - exemption)
    preferential = max(0.0, inputs.preferential_income)
    if preferential > 0 and excess > 0 and capital_gains_brackets:
        tmt = _part_iii(
            excess, preferential, inputs.regular_taxable_ordinary, breakpoint, params, capital_gains_brackets
        )
    else:
        tmt = _rate_tax(excess, breakpoint, params)
    return AMTResult(
        amti=amti,
        exemption=exemption,
        taxable_excess=excess,
        tentative_minimum_tax=tmt,
        amt=max(0.0, tmt - inputs.regular_tax),
    )


def _part_iii(
    line12: float,
    line13: float,
    regular_ordinary: float,
    breakpoint: float,
    params: "AMTYear",
    brackets: list,
) -> float:
    """Form 6251 Part III (lines 12-40) without unrecaptured §1250 gain or the Schedule D Tax Worksheet."""
    zero_top = brackets[0][1]
    fifteen_top = brackets[1][1]
    line16 = min(line12, line13)
    line17 = line12 - line16
    line18 = _rate_tax(line17, breakpoint, params)
    line20 = max(0.0, regular_ordinary)
    line21 = max(0.0, zero_top - line20)
    line22 = min(line12, line13)
    line23 = min(line21, line22)
    line24 = line22 - line23
    line28 = line21 + line20
    line29 = max(0.0, fifteen_top - line28)
    line30 = min(line24, line29)
    line31 = line30 * 0.15
    line32 = line23 + line30
    line34 = 0.0
    if abs(line32 - line12) > 1e-9:
        line33 = line22 - line32
        line34 = line33 * 0.20
    line38 = line18 + line31 + line34
    line39 = _rate_tax(line12, breakpoint, params)
    return min(line38, line39)


def minimum_tax_credit_generated(amt: AMTResult, exclusion_only: AMTResult, regular_tax: float) -> float:
    """Form 8801 lines 15-18: the year's AMT less the net minimum tax on exclusion items."""
    net_on_exclusions = max(0.0, exclusion_only.tentative_minimum_tax - regular_tax)
    return max(0.0, amt.amt - net_on_exclusions)


def minimum_tax_credit_allowed(
    carryforward: float, regular_tax_after_credits: float, tentative_minimum_tax: float
) -> float:
    """Form 8801 lines 21-25: the carryforward, up to the regular tax (less other nonrefundable credits)
    over this year's tentative minimum tax."""
    return max(0.0, min(carryforward, regular_tax_after_credits - tentative_minimum_tax))


def capital_gains_tops(brackets: list) -> tuple[float, float]:
    """The 0% and 15% tops of a preferential schedule (for callers and tests)."""
    return brackets[0][1], brackets[1][1]


__all__ = [
    "AMTInputs",
    "AMTResult",
    "alternative_minimum_tax",
    "capital_gains_tops",
    "minimum_tax_credit_allowed",
    "minimum_tax_credit_generated",
]
