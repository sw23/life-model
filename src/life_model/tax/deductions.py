# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Deductions that depend on a whole return's AGI: the OBBBA senior deduction and the charitable
AGI limit. Shared by the tax unit (the live settlement path) and the single-person tax path."""

from typing import TYPE_CHECKING

from .federal import FilingStatus

if TYPE_CHECKING:
    from ..config.financial_config import FinancialConfig
    from ..people.person import Person


def senior_deduction(
    members: "list[Person]", filing_status: FilingStatus, magi: float, year: int, config: "FinancialConfig"
) -> float:
    """OBBBA senior deduction for a return: ``amount`` per member at or over ``age``, each reduced by
    ``phaseout_rate``% of MAGI above the threshold. Zero outside 2025-2028 and on separate returns."""
    cfg = config.tax.federal.senior_deduction
    if not cfg.first_year <= year <= cfg.last_year or filing_status == FilingStatus.MARRIED_FILING_SEPARATELY:
        return 0.0
    if filing_status == FilingStatus.MARRIED_FILING_JOINTLY:
        threshold = cfg.phaseout_start_married_filing_jointly
    else:
        threshold = cfg.phaseout_start_single
    reduction = cfg.phaseout_rate / 100 * max(0.0, magi - threshold)
    per_person = max(0.0, cfg.amount - reduction)
    return per_person * sum(1 for member in members if member.age >= cfg.age)


def charitable_cap(agi: float, config: "FinancialConfig") -> float:
    """Most cash charity a return can deduct this year (60% of AGI)."""
    return max(0.0, agi) * config.tax.federal.charitable.cash_agi_limit_percent / 100


def _usable(entry_year: int, year: int, config: "FinancialConfig") -> bool:
    """A gift's excess is usable in the ``carryforward_years`` years after the year it was given."""
    return 0 < year - entry_year <= config.tax.federal.charitable.carryforward_years


def deductible_charity(members: "list[Person]", agi: float, config: "FinancialConfig") -> float:
    """This year's deductible charity: current gifts plus unexpired carryforwards, capped."""
    year = members[0].model.year
    current = sum(member.charitable_deductions for member in members)
    carried = sum(
        amount
        for member in members
        for entry_year, amount in member.charitable_carryforwards
        if _usable(entry_year, year, config)
    )
    return min(current + carried, charitable_cap(agi, config))


def settle_charitable_carryforwards(members: "list[Person]", agi: float, year: int, config: "FinancialConfig") -> None:
    """Consume carryforwards and record this year's excess, once, at year-end settlement.

    Current-year gifts are deducted first, then carryforwards oldest first (Treas. Reg. 1.170A-10).
    Carryforwards are used up even in a year the return takes the standard deduction, as the
    regulations require. The excess of this year's gifts over the cap carries to the next
    ``carryforward_years`` years; older entries expire. The pooled carryforward lives on the first
    member (the return's head); a carryforward does not survive its holder's death.
    """
    cfg = config.tax.federal.charitable
    room = charitable_cap(agi, config)
    current = sum(member.charitable_deductions for member in members)
    used_current = min(current, room)
    room -= used_current

    remaining = []
    for member in members:
        for entry_year, amount in sorted(member.charitable_carryforwards):
            if not _usable(entry_year, year, config):
                continue  # expired before this year
            take = min(amount, room)
            room -= take
            if amount - take > 0 and year - entry_year < cfg.carryforward_years:
                remaining.append((entry_year, amount - take))
        member.charitable_carryforwards = []
    excess = current - used_current
    if excess > 0 and cfg.carryforward_years > 0:
        remaining.append((year, excess))
    members[0].charitable_carryforwards = remaining
