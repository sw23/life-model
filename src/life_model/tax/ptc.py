# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The ACA premium tax credit (IRC §36B; Form 8962; Plan 31 task 6).

Marketplace coverage is a HEALTH :class:`~life_model.insurance.general_insurance.Insurance` with
``marketplace=MarketplaceCoverage(slcsp_monthly=..., advance_monthly=...)``: the policy's premium is paid a
twelfth a month while coverage is active, net of any advance credit paid to the insurer. At settlement the
return's credit is figured on Form 8962 from the year's coverage months:

* household income (line 3): AGI plus tax-exempt interest and nontaxable Social Security;
* line 5: household income as a percent of the poverty line for the family size (the prior year's HHS
  guideline), truncated to a whole percent; above 400% the form enters 401;
* line 7: the applicable figure, linear within the year's band, rounded to 0.01% (26 CFR 1.36B-3(g));
* line 8a: the annual contribution (household income x figure, to the dollar), 8b a twelfth of it;
* lines 11/12-23: each covered month's credit, the second-lowest-cost silver plan premium less the monthly
  contribution, at most the month's premium (the annual totals when all twelve months are alike);
* lines 24-29: the credit less the advance payments: a net credit (Schedule 3 line 9, refundable) or the
  excess advance payments repaid (Schedule 2 line 1a), limited by the year's repayment table (no limit from
  2026, OBBBA §71305).

Outside the eligible range (below 100% of the poverty line; above 400% from 2026) the credit is zero and
any advance payments are repaid. A married couple filing separately gets no credit (the domestic-abuse
exceptions are not modeled).
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config.models import PremiumTaxCreditYear
    from .federal import FilingStatus


@dataclass(frozen=True)
class MarketplaceCoverage:
    """A health policy bought on the ACA marketplace (Form 1095-A's inputs).

    ``slcsp_monthly``: the second-lowest-cost silver plan premium for the people the policy covers (1095-A
    column B), in start-year dollars (it grows with the policy's premium). ``advance_monthly``: the advance
    credit paid to the insurer each month (column C): a dollar amount, ``"estimate"`` (the marketplace's
    estimate from the household's last return: the credit that income would earn), or None (no advance
    payments; the whole credit is claimed on the return).
    """

    slcsp_monthly: float
    advance_monthly: "float | str | None" = None

    def __post_init__(self):
        if self.slcsp_monthly < 0:
            raise ValueError("slcsp_monthly must be non-negative")
        if isinstance(self.advance_monthly, str) and self.advance_monthly != "estimate":
            raise ValueError("advance_monthly must be a dollar amount, 'estimate' or None")
        if isinstance(self.advance_monthly, (int, float)) and self.advance_monthly < 0:
            raise ValueError("advance_monthly must be non-negative")


def _half_up(value: float, places: int = 0) -> float:
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def fpl_percent(household_income: float, family_size: int, params: "PremiumTaxCreditYear") -> int:
    """Form 8962 line 5: household income as a whole percent of the poverty line (401 above 400%)."""
    poverty = params.poverty_line.for_family(max(1, family_size))
    if household_income > poverty * 4:
        return 401
    return int(max(0.0, household_income) * 100 // poverty) if poverty > 0 else 0


def applicable_figure(percent: float, params: "PremiumTaxCreditYear") -> float:
    """Form 8962 line 7: the applicable figure (a fraction, four decimals)."""
    rows = params.applicable_percentage
    for low, high, initial, final in rows:
        if low <= percent < high:
            value = initial + (final - initial) * (percent - low) / (high - low) if high != float("inf") else initial
            return _half_up(value, 2) / 100
    return _half_up(rows[-1][3], 2) / 100


def repayment_limit(percent: float, filing_status: "FilingStatus", params: "PremiumTaxCreditYear") -> float | None:
    """The cap on excess advance payments repaid (Form 8962 line 28), None for no limit. "Single" is the
    single filing status only; head of household and qualifying surviving spouses use the other column."""
    for low, high, single, other in params.repayment_limit:
        if low <= percent < high:
            amount = single if filing_status.name == "SINGLE" else other
            return None if amount is None else float(amount)
    return None


def premium_tax_credit(
    household_income: float,
    family_size: int,
    months: "list[tuple[float, float, float]]",
    filing_status: "FilingStatus",
    params: "PremiumTaxCreditYear",
) -> dict[str, float]:
    """Form 8962 for ``months`` of coverage (``(enrollment premium, SLCSP premium, advance payment)`` per
    covered month). Returns its figures: ``household_income``, ``fpl_percent``, ``applicable_figure``,
    ``contribution`` (8a), ``enrollment_premiums``, ``slcsp_premiums``, ``allowed`` (line 24), ``advance``
    (line 25), ``net`` (line 26: the refundable credit) and ``repayment`` (line 29)."""
    enrollment = sum(m[0] for m in months)
    slcsp = sum(m[1] for m in months)
    advance = sum(m[2] for m in months)
    percent = fpl_percent(household_income, family_size, params)
    figure = applicable_figure(percent, params)
    contribution = _half_up(max(0.0, household_income) * figure)
    eligible = (
        months
        and filing_status.name != "MARRIED_FILING_SEPARATELY"
        and percent >= params.min_fpl_pct
        and percent <= params.max_fpl_pct
    )
    allowed = 0.0
    if eligible:
        alike = len(months) == 12 and all(m[:2] == months[0][:2] for m in months)
        if alike:
            allowed = min(enrollment, max(0.0, slcsp - contribution))  # line 11
        else:
            monthly = _half_up(contribution / 12)  # line 8b
            allowed = sum(min(p, max(0.0, s - monthly)) for p, s, _ in months)  # lines 12-23
    net = max(0.0, allowed - advance)
    excess = max(0.0, advance - allowed)
    limit = repayment_limit(percent, filing_status, params)
    repayment = excess if limit is None else min(excess, limit)
    return {
        "household_income": household_income,
        "fpl_percent": float(percent),
        "applicable_figure": figure,
        "contribution": contribution,
        "enrollment_premiums": enrollment,
        "slcsp_premiums": slcsp,
        "allowed": allowed,
        "advance": advance,
        "net": net,
        "repayment": repayment,
    }


def estimated_advance_monthly(
    household_income: float,
    family_size: int,
    premium_monthly: float,
    slcsp_monthly: float,
    filing_status: "FilingStatus",
    params: "PremiumTaxCreditYear",
) -> float:
    """The marketplace's monthly advance credit for an income estimate: the credit that income would earn
    for a month of this coverage."""
    figures = premium_tax_credit(
        household_income, family_size, [(premium_monthly, slcsp_monthly, 0.0)], filing_status, params
    )
    return figures["allowed"]
