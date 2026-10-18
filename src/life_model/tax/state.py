# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""State income tax.

Two code paths coexist:

* The scalar path — :func:`state_income_tax` / :func:`get_state_tax_rate` — applies the
  ``DEFAULT`` flat rate to a federal-style AGI base. It is the path every ``DEFAULT`` resident
  uses: a single flat rate on the federal-style AGI base.
* The pack path — :func:`state_income_tax_for_unit` — resolves a per-state
  :class:`~life_model.config.models.StateTaxPack` and computes a real state taxable-income base
  (exempting retirement distributions and/or Social Security where the state does) before applying
  the pack's flat rate or brackets.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..config.financial_config import resolve_financial_config as _fin
from .brackets import apply_brackets, bracket_slices
from .income import IncomeType

if TYPE_CHECKING:
    from ..config.financial_config import FinancialConfig
    from ..config.models import StateTaxPack
    from .federal import FilingStatus


def get_state_tax_rate(config: "FinancialConfig | None" = None) -> float:
    """Get the configured DEFAULT flat state tax rate."""
    return _fin(config).tax.state.tax_rate


def state_income_tax(income: float, config: "FinancialConfig | None" = None) -> float:
    """Calculate state income taxes due at the DEFAULT flat rate.

    Args:
        income (float): Income subject to state income taxes (a federal-style AGI base).
        config (FinancialConfig, optional): Per-model config. Defaults to the packaged defaults.

    Returns:
        total_tax: Amount of tax due based on the taxable income.
    """
    return income * get_state_tax_rate(config) / 100


#: State-pack filing-status key of each federal status, with the fallbacks tried in order.
_STATUS_KEYS = {
    "SINGLE": ("single",),
    "MARRIED_FILING_JOINTLY": ("married_filing_jointly", "single"),
    "HEAD_OF_HOUSEHOLD": ("head_of_household", "single"),
    "MARRIED_FILING_SEPARATELY": ("married_filing_separately", "single"),
    # A qualifying surviving spouse files with the joint schedule where a state has one (Plan 31 D5).
    "QUALIFYING_SURVIVING_SPOUSE": ("married_filing_jointly", "single"),
}


def _status_keys(filing_status: "FilingStatus") -> tuple[str, ...]:
    return _STATUS_KEYS.get(filing_status.name, ("single",))


def _bracket_rows(pack: "StateTaxPack", filing_status: "FilingStatus"):
    """The bracket rows for ``filing_status`` (head of household and separate returns fall back to
    ``single``, a qualifying surviving spouse to the joint schedule)."""
    brackets = pack.brackets or {}
    for key in _status_keys(filing_status):
        if key in brackets:
            return brackets[key]
    return brackets["single"]


def _state_standard_deduction(pack: "StateTaxPack", filing_status: "FilingStatus") -> float:
    sd = pack.standard_deduction
    for key in _status_keys(filing_status):
        value = getattr(sd, key)
        if value is not None:
            return value
    return sd.single


def _filers(filing_status: "FilingStatus") -> int:
    """People a state personal exemption / credit counts on the return (both spouses on a joint return)."""
    return 2 if filing_status.name == "MARRIED_FILING_JOINTLY" else 1


@dataclass(frozen=True)
class StateTaxDetail:
    """How a unit's state income tax was computed (one return's state lines).

    ``method`` is ``"flat_agi"`` for the ``DEFAULT`` flat rate on the federal-style base,
    ``"flat"`` or ``"brackets"`` for a state pack, ``"part_year"`` for a year with more than one state of
    residence (each state's share in ``parts``; Plan 31 D4).
    """

    #: Resolved state code (``DEFAULT`` for the flat-rate default state).
    state: str
    method: str
    #: Income entering the state computation before subtractions and the state deduction.
    income: float
    #: Income the state excludes (Treasury and municipal interest, exempt retirement income,
    #: Social Security, capital gains where untaxed).
    subtractions: float
    #: The state standard deduction and exemptions (0 on the ``DEFAULT`` path, whose base is already
    #: post-deduction).
    deduction: float
    #: The state taxable income the rate or brackets apply to.
    taxable_income: float
    #: Flat rate (percent) when the state uses one, else None.
    flat_rate: float | None
    #: The state bracket segments reached (``(lower, upper, rate_percent, amount, tax)``).
    brackets: tuple[tuple[float, float, float, float, float], ...]
    tax: float
    #: Personal and dependent exemptions included in ``deduction`` (Plan 31).
    exemptions: float = 0.0
    #: Nonrefundable state credits (personal / dependent exemption credits) subtracted in ``tax``.
    credits: float = 0.0
    #: A part-year return: each state of residence's share (Plan 31 D4).
    parts: "tuple[StateTaxDetail, ...]" = ()


def state_income_tax_for_unit(
    totals_by_type: "dict[IncomeType, float]",
    filing_status: "FilingStatus",
    state: str | None,
    legacy_agi_base: float,
    config: "FinancialConfig | None" = None,
) -> float:
    """Compute state income tax for a tax unit resolving the resident's state pack.

    ``DEFAULT`` residents use the federal-style AGI base with the flat rate. Real state packs
    build a state taxable-income base from the income ledger totals: ordinary
    income minus exempt retirement distributions (when ``not retirement_income_taxable``) minus the
    Social Security taxable portion (when ``not ss_taxable``) minus the state standard deduction,
    then the flat rate or brackets. See :func:`state_income_tax_detail` for the breakdown.

    Args:
        totals_by_type: Ordinary-taxable amount per income type for the unit
            (see :meth:`~life_model.tax.income.IncomeLedger.totals_by_type`).
        filing_status: Filing status of the unit.
        state: The resident's state code (``None`` → the config default state).
        legacy_agi_base: The federal-style AGI base used for the ``DEFAULT`` flat-rate path.
        config: Per-model config. Defaults to the packaged defaults.
    """
    return state_income_tax_detail(totals_by_type, filing_status, state, legacy_agi_base, config).tax


def _state_base(totals_by_type: "dict[IncomeType, float]", pack: "StateTaxPack") -> tuple[float, float]:
    """``(income, base)``: the income entering the state computation and what is left after the pack's
    subtractions (before the deduction)."""
    treasury = totals_by_type.get(IncomeType.TREASURY_INTEREST, 0.0)
    ordinary = sum(totals_by_type.values())
    base = ordinary - treasury - totals_by_type.get(IncomeType.TAX_EXEMPT_INTEREST, 0.0)
    if not pack.retirement_income_taxable:
        base -= totals_by_type.get(IncomeType.PRETAX_DISTRIBUTION, 0.0)
    if not pack.ss_taxable:
        base -= totals_by_type.get(IncomeType.SS_BENEFIT, 0.0)
    if not pack.capital_gains_taxable:
        for gain_type in (
            IncomeType.SHORT_TERM_CAPITAL_GAIN,
            IncomeType.LONG_TERM_CAPITAL_GAIN,
            IncomeType.QUALIFIED_DIVIDEND,
        ):
            base -= totals_by_type.get(gain_type, 0.0)
    return ordinary, base


def _retirement_exclusion(pack: "StateTaxPack", retirees: "list[tuple[int, float]] | None") -> float:
    """The pack's partial retirement-income exclusion: up to its amount per member of the minimum age, each
    limited to that member's retirement income (``retirees``: ``(age at year end, retirement income)``)."""
    rule = pack.retirement_exclusion
    if rule is None or not retirees:
        return 0.0
    return sum(min(rule.amount, max(0.0, income)) for age, income in retirees if age >= rule.min_age)


def state_income_tax_detail(
    totals_by_type: "dict[IncomeType, float]",
    filing_status: "FilingStatus",
    state: str | None,
    legacy_agi_base: float,
    config: "FinancialConfig | None" = None,
    *,
    dependents: int = 0,
    retirees: "list[tuple[int, float]] | None" = None,
    year: int | None = None,
) -> StateTaxDetail:
    """:func:`state_income_tax_for_unit` with every intermediate line (the one computation of it).

    ``dependents`` (the return's dependents) and ``retirees`` (``(age at year end, retirement income)`` per
    member) feed the pack's dependent exemption / credit and its partial retirement exclusion. ``year``
    picks a year-keyed pack's entry (a year view of the config has already resolved it). An unknown state
    raises :class:`~life_model.config.models.UnknownStateError`.
    """
    state_config = _fin(config).tax.state
    from ..config.models import DEFAULT_STATE_KEY

    resolved = state_config.resolve_state_code(state)
    pack = state_config.get_pack(state, year)

    # Interest no state may tax (US Treasuries) and municipal interest (outside the federal base, and
    # treated as in-state, so exempt here too) never enter a state base.
    treasury = totals_by_type.get(IncomeType.TREASURY_INTEREST, 0.0)
    if resolved == DEFAULT_STATE_KEY:
        # ``DEFAULT`` flat rate applied to the federal AGI base (which includes Treasury interest).
        taxable = max(legacy_agi_base - treasury, 0.0)
        rate = pack.flat_rate or 0.0
        return StateTaxDetail(
            state=resolved,
            method="flat_agi",
            income=legacy_agi_base,
            subtractions=treasury,
            deduction=0.0,
            taxable_income=taxable,
            flat_rate=rate,
            brackets=(),
            tax=taxable * rate / 100,
        )

    ordinary, base = _state_base(totals_by_type, pack)
    base -= min(max(base, 0.0), _retirement_exclusion(pack, retirees))
    subtractions = ordinary - base
    exemptions = pack.personal_exemption * _filers(filing_status) + pack.dependent_exemption * dependents
    deduction = _state_standard_deduction(pack, filing_status) + exemptions
    base -= deduction
    base = max(base, 0.0)
    credits_available = pack.personal_credit * _filers(filing_status) + pack.dependent_credit * dependents

    if pack.brackets is not None:
        rows = _bracket_rows(pack, filing_status)
        gross = apply_brackets(base, rows)
        credits = min(gross, credits_available)
        return StateTaxDetail(
            state=resolved,
            method="brackets",
            income=ordinary,
            subtractions=subtractions,
            deduction=deduction,
            taxable_income=base,
            flat_rate=None,
            brackets=tuple(bracket_slices(base, rows)),
            tax=gross - credits,
            exemptions=exemptions,
            credits=credits,
        )
    rate = pack.flat_rate or 0.0
    gross = base * rate / 100
    credits = min(gross, credits_available)
    return StateTaxDetail(
        state=resolved,
        method="flat",
        income=ordinary,
        subtractions=subtractions,
        deduction=deduction,
        taxable_income=base,
        flat_rate=rate,
        brackets=(),
        tax=gross - credits,
        exemptions=exemptions,
        credits=credits,
    )


def part_year_state_tax_detail(
    allocations: "dict[str, dict[IncomeType, float]]",
    filing_status: "FilingStatus",
    legacy_agi_base: float,
    config: "FinancialConfig | None" = None,
    *,
    dependents: int = 0,
    retirees: "list[tuple[int, float]] | None" = None,
    final_state: str | None = None,
) -> StateTaxDetail:
    """State tax for a year with more than one state of residence (Plan 31 D4), by the income-ratio method
    of the part-year returns of California (Form 540NR) and New York (IT-203), which many states share.

    ``allocations`` maps each state of residence (in the order lived in) to the income received while
    living there: wages by the months worked there, investment and other income by residency when it was
    received. For each state: the tax as if a full-year resident on the whole year's income, times that
    state's share (its base over the whole base, both after the pack's subtractions, between 0 and 1). The
    parts' deductions, exemptions and credits are prorated by the same ratio. States with other part-year
    methods (a separate part-year computation, a proration by days) are approximated by this one.
    """
    totals: dict[IncomeType, float] = {income_type: 0.0 for income_type in IncomeType}
    for allocated in allocations.values():
        for income_type, amount in allocated.items():
            totals[income_type] += amount
    parts = []
    for code, allocated in allocations.items():
        full = state_income_tax_detail(
            totals, filing_status, code, legacy_agi_base, config, dependents=dependents, retirees=retirees
        )
        state_config = _fin(config).tax.state
        pack = state_config.get_pack(code)
        _, whole = _state_base(totals, pack)
        income, own = _state_base(allocated, pack)
        ratio = min(1.0, max(0.0, own / whole)) if whole > 0 else 0.0
        parts.append(
            StateTaxDetail(
                state=full.state,
                method=full.method,
                income=income,
                subtractions=income - own,
                deduction=full.deduction * ratio,
                taxable_income=full.taxable_income * ratio,
                flat_rate=full.flat_rate,
                brackets=tuple(
                    (lo, hi, rate, amount * ratio, tax * ratio) for lo, hi, rate, amount, tax in full.brackets
                ),
                tax=full.tax * ratio,
                exemptions=full.exemptions * ratio,
                credits=full.credits * ratio,
            )
        )
    last = parts[-1]
    state = final_state if final_state is not None else last.state
    return StateTaxDetail(
        state=state,
        method="part_year",
        income=sum(p.income for p in parts),
        subtractions=sum(p.subtractions for p in parts),
        deduction=sum(p.deduction for p in parts),
        taxable_income=sum(p.taxable_income for p in parts),
        flat_rate=None,
        brackets=(),
        tax=sum(p.tax for p in parts),
        exemptions=sum(p.exemptions for p in parts),
        credits=sum(p.credits for p in parts),
        parts=tuple(parts),
    )
