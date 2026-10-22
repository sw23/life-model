# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Qualified business income deduction (IRC §199A; Forms 8995 and 8995-A).

The model's businesses are sole proprietorships with no W-2 employees and no qualified property
(UBIA), so above the threshold the wage/UBIA limit is $0: a non-SSTB's deduction phases down to $0
over the phase-in range (Form 8995-A Part III), and an SSTB's QBI itself phases out (Schedule A).
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .federal import FilingStatus

if TYPE_CHECKING:
    from ..config.models import QBIYear


@dataclass(frozen=True)
class QBIDeduction:
    """The deduction and the lines it was figured from."""

    qbi: float = 0.0
    #: 20% of QBI after the above-threshold limits (Form 8995 line 5 / 8995-A line 15).
    component: float = 0.0
    #: Taxable income before the QBI deduction (line 11) and the income limit (line 14).
    taxable_income_before: float = 0.0
    income_limit: float = 0.0
    deduction: float = 0.0


def _threshold(params: "QBIYear", filing_status: FilingStatus) -> tuple[float, float]:
    if filing_status == FilingStatus.MARRIED_FILING_JOINTLY:
        return params.threshold_joint, params.phase_in_joint
    if filing_status == FilingStatus.MARRIED_FILING_SEPARATELY:
        return params.threshold_separate, params.phase_in_single
    return params.threshold_single, params.phase_in_single


def qbi_deduction(
    qbi: float,
    taxable_income_before: float,
    net_capital_gain: float,
    filing_status: FilingStatus,
    params: "QBIYear | None",
    *,
    sstb: bool = False,
    w2_wages: float = 0.0,
    ubia: float = 0.0,
) -> QBIDeduction:
    """The §199A deduction for one return with one qualified business.

    Args:
        qbi: Qualified business income: net profit less the deductible part of SE tax and the
            self-employed retirement-plan deduction attributable to the business.
        taxable_income_before: Taxable income before the QBI deduction (Form 8995 line 11).
        net_capital_gain: Net capital gain plus qualified dividends (line 12).
        filing_status: The return's status (selects the threshold).
        params: The year's §199A parameters (None: the deduction is off).
        sstb: Whether the business is a specified service trade or business.
        w2_wages: W-2 wages the business paid (0 for the model's sole proprietors).
        ubia: Unadjusted basis of qualified property (0 here).
    """
    if params is None or qbi <= 0:
        return QBIDeduction(qbi=qbi, taxable_income_before=taxable_income_before)
    rate = params.rate / 100
    threshold, phase_in = _threshold(params, filing_status)
    excess = max(0.0, taxable_income_before - threshold)
    applicable = min(1.0, excess / phase_in) if phase_in > 0 else (1.0 if excess > 0 else 0.0)
    wage_limit = max(0.5 * w2_wages, 0.25 * w2_wages + 0.025 * ubia)
    if excess <= 0:
        component = rate * qbi
    else:
        # Form 8995-A Schedule A: an SSTB counts only (1 - applicable percentage) of its QBI and wages.
        share = (1.0 - applicable) if sstb else 1.0
        tentative = rate * qbi * share
        limit = wage_limit * share
        if applicable >= 1.0:
            component = min(tentative, limit)
        elif tentative > limit:
            # Form 8995-A Part III: the reduction is the applicable percentage of the excess over the limit.
            component = tentative - (tentative - limit) * applicable
        else:
            component = tentative
    income_limit = max(0.0, taxable_income_before - max(0.0, net_capital_gain)) * rate
    deduction = max(0.0, min(component, income_limit))
    if params.minimum_deduction and qbi >= params.minimum_qbi:
        # §199A(i) (OBBBA, 2026+): at least the minimum for active QBI of at least ``minimum_qbi``.
        deduction = max(deduction, params.minimum_deduction)
    return QBIDeduction(
        qbi=qbi,
        component=component,
        taxable_income_before=taxable_income_before,
        income_limit=income_limit,
        deduction=deduction,
    )
