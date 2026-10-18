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


def _bracket_rows(pack: "StateTaxPack", filing_status: "FilingStatus"):
    """Return the bracket rows for ``filing_status`` with single-fallback."""
    brackets = pack.brackets or {}
    key = "married_filing_jointly" if filing_status.value == 2 else "single"
    return brackets.get(key, brackets["single"])


def _state_standard_deduction(pack: "StateTaxPack", filing_status: "FilingStatus") -> float:
    sd = pack.standard_deduction
    return sd.married_filing_jointly if filing_status.value == 2 else sd.single


@dataclass(frozen=True)
class StateTaxDetail:
    """How a unit's state income tax was computed (one return's state lines).

    ``method`` is ``"flat_agi"`` for the ``DEFAULT`` flat rate on the federal-style base,
    ``"flat"`` or ``"brackets"`` for a state pack.
    """

    #: Resolved state code (``DEFAULT`` for the flat-rate default state).
    state: str
    method: str
    #: Income entering the state computation before subtractions and the state deduction.
    income: float
    #: Income the state excludes (Treasury and municipal interest, exempt retirement income,
    #: Social Security, capital gains where untaxed).
    subtractions: float
    #: The state standard deduction (0 on the ``DEFAULT`` path, whose base is already post-deduction).
    deduction: float
    #: The state taxable income the rate or brackets apply to.
    taxable_income: float
    #: Flat rate (percent) when the state uses one, else None.
    flat_rate: float | None
    #: The state bracket segments reached (``(lower, upper, rate_percent, amount, tax)``).
    brackets: tuple[tuple[float, float, float, float, float], ...]
    tax: float


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


def state_income_tax_detail(
    totals_by_type: "dict[IncomeType, float]",
    filing_status: "FilingStatus",
    state: str | None,
    legacy_agi_base: float,
    config: "FinancialConfig | None" = None,
) -> StateTaxDetail:
    """:func:`state_income_tax_for_unit` with every intermediate line (the one computation of it)."""
    state_config = _fin(config).tax.state
    from ..config.models import DEFAULT_STATE_KEY

    resolved = state_config.resolve_state_code(state)
    pack = state_config.get_pack(state)

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
    subtractions = ordinary - base
    deduction = _state_standard_deduction(pack, filing_status)
    base -= deduction
    base = max(base, 0.0)

    if pack.brackets is not None:
        rows = _bracket_rows(pack, filing_status)
        return StateTaxDetail(
            state=resolved,
            method="brackets",
            income=ordinary,
            subtractions=subtractions,
            deduction=deduction,
            taxable_income=base,
            flat_rate=None,
            brackets=tuple(bracket_slices(base, rows)),
            tax=apply_brackets(base, rows),
        )
    rate = pack.flat_rate or 0.0
    return StateTaxDetail(
        state=resolved,
        method="flat",
        income=ordinary,
        subtractions=subtractions,
        deduction=deduction,
        taxable_income=base,
        flat_rate=rate,
        brackets=(),
        tax=base * rate / 100,
    )
