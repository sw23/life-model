# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tax credits (currently the Child Tax Credit, IRC §24 as amended by the OBBBA).

The phase-out math lives here as a pure function so it can be unit-tested against worked
examples; the tax unit (people/tax_unit.py) counts qualifying children and wires the result
into the settlement pipeline.
"""

import math
from typing import TYPE_CHECKING, Optional

from ..config.config_manager import config as _global_config
from .federal import FilingStatus

if TYPE_CHECKING:
    from ..config.financial_config import FinancialConfig


def _fin(config: "Optional[FinancialConfig]") -> "FinancialConfig":
    """Resolve the financial config to use (per-model if given, else global)."""
    return config if config is not None else _global_config.financial


def _phaseout_threshold(filing_status: FilingStatus, config: "Optional[FinancialConfig]") -> float:
    """MAGI threshold at which the CTC begins to phase out for ``filing_status``.

    Statuses without their own configured threshold (e.g. HEAD_OF_HOUSEHOLD sharing the single
    threshold) fall back to ``single``.
    """
    thresholds = _fin(config).dependents.ctc_phaseout_start
    return getattr(thresholds, filing_status.name.lower(), thresholds.single)


def child_tax_credit(
    num_qualifying_children: int,
    magi: float,
    federal_tax: float,
    filing_status: FilingStatus,
    config: "Optional[FinancialConfig]" = None,
) -> float:
    """Child Tax Credit usable this year (nonrefundable portion plus refundable portion).

    The credit starts at ``ctc_per_child`` per qualifying child and is reduced by
    ``ctc_phaseout_rate`` percent of each $1,000 (or fraction thereof — IRC §24(b)(2)) of
    modified AGI over the filing-status threshold. The nonrefundable portion is clamped at the
    federal income-tax liability; up to ``ctc_refundable_max`` per child of the remainder is
    refundable (a simplification of the §24(h)(5)/(d) additional-child-tax-credit earned-income
    formula), which can drive the unit's total federal component negative.

    Args:
        num_qualifying_children: Children who qualify (age within limit, alive parent in unit).
        magi: The unit's modified adjusted gross income (ordinary income before deductions).
        federal_tax: Federal income-tax liability before credits.
        filing_status: The unit's filing status (selects the phase-out threshold).
        config: Per-model config. Defaults to the global config.

    Returns:
        The total credit amount to record on ``TaxesDue.credits`` (>= 0).
    """
    if num_qualifying_children <= 0:
        return 0.0

    dep = _fin(config).dependents
    credit = dep.ctc_per_child * num_qualifying_children

    excess = magi - _phaseout_threshold(filing_status, config)
    if excess > 0:
        # $50-per-$1,000-or-fraction-thereof at the default 5% rate: round the excess up to the
        # next $1,000 step before applying the rate.
        steps = math.ceil(excess / 1000)
        credit -= steps * 1000 * (dep.ctc_phaseout_rate / 100)
    if credit <= 0:
        return 0.0

    nonrefundable = min(credit, max(federal_tax, 0.0))
    refundable = min(credit - nonrefundable, dep.ctc_refundable_max * num_qualifying_children)
    return nonrefundable + refundable
