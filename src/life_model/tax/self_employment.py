# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Self-employment tax (Schedule SE) and the self-employed retirement-plan limits (Pub. 560).

Pure functions: the tax unit passes each worker's Schedule C net profit and W-2 Social Security wages
(the wage base is shared, Schedule SE lines 7-9), and the self-employed ``Job`` sizes its SEP or
solo 401(k) contribution with :func:`self_employed_plan_contribution`.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..config.financial_config import resolve_financial_config as _fin

if TYPE_CHECKING:
    from ..config.financial_config import FinancialConfig


@dataclass(frozen=True)
class SelfEmploymentTax:
    """One worker's Schedule SE (Part I) lines."""

    #: Line 3: net profit (Schedule C line 31).
    net_profit: float = 0.0
    #: Line 4a / 6: net earnings from self-employment (92.35% of the profit; 0 under $400).
    net_earnings: float = 0.0
    #: Line 10: 12.4% of the net earnings up to the wage base left after W-2 Social Security wages.
    social_security: float = 0.0
    #: Line 11: 2.9% of the net earnings.
    medicare: float = 0.0

    @property
    def total(self) -> float:
        """Line 12: self-employment tax."""
        return self.social_security + self.medicare

    @property
    def deduction(self) -> float:
        """Line 13: the deductible half (Schedule 1 line 15)."""
        return self.total / 2


def self_employment_tax(
    net_profit: float, w2_social_security_wages: float = 0.0, config: "FinancialConfig | None" = None
) -> SelfEmploymentTax:
    """Schedule SE for one worker.

    Args:
        net_profit: Schedule C net profit (a loss gives no SE tax).
        w2_social_security_wages: The worker's W-2 Social Security wages (box 3), which use up the wage
            base first (lines 8a-9).
        config: The year's config (``model.year_config``); its wage base is the year's.
    """
    fin = _fin(config)
    se = fin.tax.self_employment
    net_earnings = max(0.0, net_profit) * se.net_earnings_percent / 100
    if net_earnings < se.minimum_net_earnings:
        return SelfEmploymentTax(net_profit=net_profit)
    base_left = max(0.0, fin.tax.fica.social_security_max_income - max(0.0, w2_social_security_wages))
    return SelfEmploymentTax(
        net_profit=net_profit,
        net_earnings=net_earnings,
        social_security=min(net_earnings, base_left) * se.social_security_rate / 100,
        medicare=net_earnings * se.medicare_rate / 100,
    )


def additional_medicare_on_self_employment(
    se_net_earnings: float, medicare_wages: float, threshold: float, rate_percent: float
) -> float:
    """Form 8959 Part II: 0.9% of the return's SE net earnings over the threshold left after Medicare wages."""
    remaining_threshold = max(0.0, threshold - max(0.0, medicare_wages))
    return max(0.0, se_net_earnings - remaining_threshold) * rate_percent / 100


@dataclass(frozen=True)
class PlanContribution:
    """A self-employed person's own retirement-plan contributions for the year (Pub. 560 worksheet)."""

    #: Net earnings for the plan: net profit less the deductible half of SE tax (worksheet step 3).
    compensation: float = 0.0
    #: Employer (nonelective / SEP) contribution (steps 4-7 and the 415(c) cap).
    employer: float = 0.0
    #: Elective deferral to a solo 401(k), pre-tax part.
    elective_pretax: float = 0.0
    #: Elective deferral to a solo 401(k), Roth part (not deductible).
    elective_roth: float = 0.0

    @property
    def deductible(self) -> float:
        """Schedule 1 line 16: SEP / employer contributions plus pre-tax elective deferrals."""
        return self.employer + self.elective_pretax


def self_employed_plan_contribution(
    net_profit: float,
    se_deduction: float,
    plan_rate_percent: float,
    config: "FinancialConfig | None" = None,
    *,
    elective_pretax_wanted: float = 0.0,
    elective_roth_wanted: float = 0.0,
    elective_room: float = 0.0,
) -> PlanContribution:
    """Pub. 560's Deduction Worksheet for Self-Employed (SEP, or a solo 401(k) with deferrals).

    The employer contribution is the plan rate reduced for the self-employed (rate / (1 + rate): 25% ->
    20%) times net earnings after the SE-tax deduction (step 3), limited to the plan rate times the
    §401(a)(17) compensation limit (step 6) and, with any elective deferrals, the §415(c) limit (step 8
    and steps 9-21). Elective deferrals (a solo 401(k)) are limited to ``elective_room`` (the person's
    402(g) room, catch-up included) and to the compensation.

    Args:
        net_profit: Schedule C net profit (step 1).
        se_deduction: The deductible half of SE tax (step 2).
        plan_rate_percent: The plan's contribution rate (at most 25).
        config: The year's config.
        elective_pretax_wanted: Pre-tax deferral the owner elects (solo 401(k) only).
        elective_roth_wanted: Roth deferral the owner elects (solo 401(k) only).
        elective_room: Remaining 402(g) room for the person this year.
    """
    fin = _fin(config)
    compensation = max(0.0, net_profit - se_deduction)
    if compensation <= 0:
        return PlanContribution()
    rate = min(max(plan_rate_percent, 0.0), fin.tax.self_employment.max_plan_rate) / 100
    # Pub. 560's Rate Table for Self-Employed: rate / (1 + rate) to six decimals (10% -> 0.090909).
    reduced_rate = round(rate / (1 + rate), 6)
    employer = compensation * reduced_rate
    comp_limit = fin.tax.federal.compensation_limit
    if comp_limit is not None:
        employer = min(employer, comp_limit * rate)
    additions_limit = fin.retirement.job_401k_contrib_limit.annual_additions_limit
    room = max(0.0, min(elective_room, compensation - employer))
    pretax = min(max(elective_pretax_wanted, 0.0), room)
    roth = min(max(elective_roth_wanted, 0.0), room - pretax)
    # §415(c): employer money plus deferrals (catch-up deferrals are outside 415(c); not separated here).
    employer = max(0.0, min(employer, additions_limit - pretax - roth))
    return PlanContribution(compensation=compensation, employer=employer, elective_pretax=pretax, elective_roth=roth)
