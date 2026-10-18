# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Deductions that depend on a whole return: the §63(f) additional standard deduction, the OBBBA senior
deduction, the SALT cap, the charitable deduction (cash at 60% of AGI, appreciated long-term property
at fair market value up to 30%, and from 2026 the 0.5% floor and the non-itemizer deduction), and the
§68 2/37 limit on itemized deductions (2026+). Shared by the tax unit (the live settlement path) and
the single-person tax path."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .federal import FilingStatus

if TYPE_CHECKING:
    from ..config.financial_config import FinancialConfig
    from ..people.person import Person


def senior_deduction(
    members: "list[Person]", filing_status: FilingStatus, magi: float, year: int, config: "FinancialConfig"
) -> float:
    """OBBBA senior deduction for a return: ``amount`` per member at or over ``age``, each reduced by
    ``phaseout_rate`` percent of MAGI above the threshold. Zero outside 2025-2028 and on separate returns."""
    cfg = config.tax.federal.senior_deduction
    if not cfg.first_year <= year <= cfg.last_year or filing_status == FilingStatus.MARRIED_FILING_SEPARATELY:
        return 0.0
    if filing_status == FilingStatus.MARRIED_FILING_JOINTLY:
        threshold = cfg.phaseout_start_married_filing_jointly
    else:
        threshold = cfg.phaseout_start_single
    reduction = cfg.phaseout_rate / 100 * max(0.0, magi - threshold)
    per_person = max(0.0, cfg.amount - reduction)
    # 65 or older by the end of the year.
    return per_person * sum(1 for member in members if member.age_in(year) >= cfg.age)


def additional_standard_deduction(
    members: "list[Person]", filing_status: FilingStatus, config: "FinancialConfig"
) -> float:
    """IRC §63(f): the additional standard deduction for each member 65 or older at year end (the
    ``married`` amount on a joint or separate return, ``unmarried`` otherwise). Blindness is not
    modeled; a separate filer counts only themselves. Zero when the year's config has no amounts."""
    amounts = config.tax.federal.additional_standard_deduction
    if amounts is None:
        return 0.0
    # The unmarried amount is for an individual "not married and not a surviving spouse" (IRC §63(f)(3)).
    married = filing_status in (
        FilingStatus.MARRIED_FILING_JOINTLY,
        FilingStatus.MARRIED_FILING_SEPARATELY,
        FilingStatus.QUALIFYING_SURVIVING_SPOUSE,
    )
    per_person = amounts.married if married else amounts.unmarried
    age = config.tax.federal.senior_deduction.age
    # Age 65 by the end of the tax year (IRS: born before January 2 of the following year), not this month.
    return per_person * sum(1 for member in members if member.age_in(member.model.year) >= age)


def deductible_insurance_premiums(person: "Person") -> float:
    """Long-term care insurance premiums the person paid this year, up to the year's §213(d)(10) limit
    for their age (a medical expense, IRS Pub. 502, and a qualified HSA expense, §223(d)(2)(C)(ii)).
    Medicare premiums are already in the person's medical costs; other health premiums are left out
    (only some are qualified HSA expenses, and pre-tax payroll premiums are Plan 27 D3)."""
    from ..insurance.general_insurance import InsuranceType

    year = person.model.year
    limits = person.model.year_config.tax.federal.ltc_premium_limits
    total = 0.0
    for policy in person.model.registries.general_insurance_policies.get_items(person):
        paid_year, premium = getattr(policy, "premium_paid_year", (None, 0.0))
        if paid_year != year:
            continue
        if policy.insurance_type == InsuranceType.LONG_TERM_CARE and limits is not None:
            # §213(d)(10): the attained age before the close of the tax year.
            attained = person.age_in(year)
            cap = next((row.limit for row in limits if attained <= row.max_age), limits[-1].limit)
            total += min(premium, cap)
    return total


def salt_cap(filing_status: FilingStatus, magi: float, config: "FinancialConfig") -> float:
    """The return's SALT deduction cap for the year (§164(b)(6)/(7)).

    ``config`` is the year's view (``model.config_for_year``): its cap, and from 2025 (OBBBA) the
    phase-down by ``salt_phaseout_rate`` percent of MAGI over ``salt_phaseout_threshold``, not below
    ``salt_cap_floor``. A separate return gets half of the cap, the threshold and the floor (the
    floor's halving is a reading of §164(b)(7)(B), which states the floor for the full limit only).
    MAGI is AGI here (foreign-income exclusions are not modeled).
    """
    federal = config.tax.federal
    share = 0.5 if filing_status == FilingStatus.MARRIED_FILING_SEPARATELY else 1.0
    cap = federal.salt_deduction_cap * share
    threshold = federal.salt_phaseout_threshold
    if threshold is None:
        return cap
    reduced = cap - federal.salt_phaseout_rate / 100 * max(0.0, magi - threshold * share)
    return max(min(cap, federal.salt_cap_floor * share), reduced)


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


# --------------------------------------------------------------------------------------------------
# The full charitable deduction (Plan 31 task 2)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CharitableDeduction:
    """A return's charitable deduction for the year, by Pub. 526 Worksheet 2 and the OBBBA rules."""

    #: This year's cash gifts (to public charities and donor-advised funds) and the part to public
    #: charities only (what the non-itemizer deduction may use).
    cash_given: float = 0.0
    cash_to_public_charities: float = 0.0
    #: Long-term appreciated property given (deducted at fair market value) this year.
    property_given: float = 0.0
    #: Usable carryforwards.
    cash_carried: float = 0.0
    property_carried: float = 0.0
    #: After the AGI limits (Worksheet 2 lines 13 and 30).
    cash_allowed: float = 0.0
    property_allowed: float = 0.0
    #: The 0.5%-of-AGI floor (2026+), absorbed by property first, then cash (§170(b)(1)(I)).
    floor_property: float = 0.0
    floor_cash: float = 0.0
    #: Schedule A lines 11 + 12 (+ 13) after the floor: what an itemizer deducts.
    itemized: float = 0.0
    #: Form 1040 line 12f (2026+): what a non-itemizer deducts (cash to public charities, capped).
    non_itemizer: float = 0.0


def _property_carryforwards(member: "Person") -> list:
    """The member's appreciated-property carryforwards ``[(year given, amount), ...]`` (30% bucket)."""
    return member.__dict__.setdefault("charitable_property_carryforwards", [])


def _gifts(members: "list[Person]") -> tuple[float, float, float]:
    """``(cash, cash to public charities, long-term property at FMV)`` given this year."""
    cash = sum(member.charitable_deductions for member in members)
    public = 0.0
    prop = 0.0
    for member in members:
        for donation in member.donations:
            public += donation.get_tax_deduction_amount()
            prop += getattr(donation, "get_property_deduction_amount", lambda: 0.0)()
    return cash, public, prop


def charitable_deduction(
    members: "list[Person]", agi: float, filing_status: FilingStatus, config: "FinancialConfig"
) -> CharitableDeduction:
    """This year's charitable deduction for the return.

    Cash (to public charities and donor-advised funds) is limited to 60% of AGI (Worksheet 2 line 13);
    long-term appreciated property given to a public charity is deducted at fair market value, limited
    to 30% of AGI and to 50% of AGI less the year's cash gifts (lines 26-30). Usable carryforwards join
    their bucket. From 2026 the itemized amount is reduced by 0.5% of AGI (property first, then cash),
    and a non-itemizer may deduct cash to public charities up to $1,000 ($2,000 joint), floor-free.
    """
    year = members[0].model.year
    charity = config.tax.federal.charitable
    agi = max(0.0, agi)
    cash, public, prop = _gifts(members)
    cash_carried = sum(
        amount
        for member in members
        for entry_year, amount in member.charitable_carryforwards
        if _usable(entry_year, year, config)
    )
    property_carried = sum(
        amount
        for member in members
        for entry_year, amount in _property_carryforwards(member)
        if _usable(entry_year, year, config)
    )
    cash_allowed = min(cash + cash_carried, charitable_cap(agi, config))
    property_room = min(agi * charity.property_agi_limit_percent / 100, max(0.0, agi * 0.5 - cash))
    property_allowed = min(prop + property_carried, property_room)
    floor_property = floor_cash = 0.0
    if charity.floor_first_year is not None and year >= charity.floor_first_year:
        floor = agi * charity.floor_percent / 100
        floor_property = min(property_allowed, floor)
        floor_cash = min(cash_allowed, floor - floor_property)
    non_itemizer = 0.0
    if charity.non_itemizer_first_year is not None and year >= charity.non_itemizer_first_year:
        joint = filing_status == FilingStatus.MARRIED_FILING_JOINTLY
        cap = charity.non_itemizer_limit_joint if joint else charity.non_itemizer_limit_single
        non_itemizer = min(public, cap)
    return CharitableDeduction(
        cash_given=cash,
        cash_to_public_charities=public,
        property_given=prop,
        cash_carried=cash_carried,
        property_carried=property_carried,
        cash_allowed=cash_allowed,
        property_allowed=property_allowed,
        floor_property=floor_property,
        floor_cash=floor_cash,
        itemized=cash_allowed + property_allowed - floor_property - floor_cash,
        non_itemizer=non_itemizer,
    )


def itemized_limitation(itemized: float, income_before: float, top_bracket_start: float, year: int, config) -> float:
    """IRC §68 (OBBBA, 2026+): the reduction of itemized deductions, 2/37 of the lesser of the itemized
    deductions and the amount by which ``income_before`` (taxable income figured without §68, plus the
    itemized deductions) exceeds the start of the 37% bracket. Zero before the first year."""
    first = config.tax.federal.charitable.itemized_limit_first_year
    if first is None or year < first or itemized <= 0:
        return 0.0
    return 2 / 37 * min(itemized, max(0.0, income_before - top_bracket_start))


def settle_property_carryforwards(
    members: "list[Person]", allowed: float, year: int, config: "FinancialConfig", *, floor_disallowed: float = 0.0
) -> None:
    """Consume and record the appreciated-property (30%) carryforwards, like the cash ones: this year's
    gifts first, then carryforwards oldest first; the excess carries five years. From 2026, property
    disallowed by the 0.5% floor carries over only when the year already has a property carryover
    (§170(d)(1)(C))."""
    cfg = config.tax.federal.charitable
    current = sum(
        getattr(d, "get_property_deduction_amount", lambda: 0.0)() for member in members for d in member.donations
    )
    room = allowed
    used_current = min(current, room)
    room -= used_current
    remaining = []
    for member in members:
        entries = _property_carryforwards(member)
        for entry_year, amount in sorted(entries):
            if not _usable(entry_year, year, config):
                continue
            take = min(amount, room)
            room -= take
            if amount - take > 0 and year - entry_year < cfg.carryforward_years:
                remaining.append((entry_year, amount - take))
        entries.clear()
    excess = current - used_current
    if excess > 0 and cfg.carryforward_years > 0:
        remaining.append((year, excess + floor_disallowed))
    _property_carryforwards(members[0]).extend(remaining)


def settle_charitable_carryforwards(
    members: "list[Person]", agi: float, year: int, config: "FinancialConfig", *, floor_disallowed: float = 0.0
) -> None:
    """Consume carryforwards and record this year's excess, once, at the year's tax settlement.

    Current-year gifts are deducted first, then carryforwards oldest first (Treas. Reg. 1.170A-10).
    Carryforwards are used up even in a year the return takes the standard deduction, as the
    regulations require. The excess of this year's gifts over the cap carries to the next
    ``carryforward_years`` years; older entries expire. The pooled carryforward lives on the first
    member (the return's head); a carryforward does not survive its holder's death. Cash disallowed by
    the 2026+ 0.5% floor (``floor_disallowed``) joins the carryover only in a year that has one
    (§170(d)(1)(C)).
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
        remaining.append((year, excess + floor_disallowed))
    members[0].charitable_carryforwards = remaining
