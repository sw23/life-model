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

from typing import TYPE_CHECKING, Dict, Optional

from ..config.config_manager import config as _global_config
from .brackets import apply_brackets
from .income import IncomeType

if TYPE_CHECKING:
    from ..config.financial_config import FinancialConfig
    from ..config.models import StateTaxPack
    from .federal import FilingStatus


def _fin(config: "Optional[FinancialConfig]") -> "FinancialConfig":
    return config if config is not None else _global_config.financial


def get_state_tax_rate(config: "Optional[FinancialConfig]" = None) -> float:
    """Get the configured DEFAULT flat state tax rate."""
    return _fin(config).tax.state.tax_rate


def state_income_tax(income: float, config: "Optional[FinancialConfig]" = None) -> float:
    """Calculate state income taxes due at the DEFAULT flat rate.

    Args:
        income (float): Income subject to state income taxes (a federal-style AGI base).
        config (FinancialConfig, optional): Per-model config. Defaults to the global config.

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


def state_income_tax_for_unit(
    totals_by_type: "Dict[IncomeType, float]",
    filing_status: "FilingStatus",
    state: Optional[str],
    legacy_agi_base: float,
    config: "Optional[FinancialConfig]" = None,
) -> float:
    """Compute state income tax for a tax unit resolving the resident's state pack.

    ``DEFAULT`` residents use the federal-style AGI base with the flat rate. Real state packs
    build a state taxable-income base from the income ledger totals: ordinary
    income minus exempt retirement distributions (when ``not retirement_income_taxable``) minus the
    Social Security taxable portion (when ``not ss_taxable``) minus the state standard deduction,
    then the flat rate or brackets.

    Args:
        totals_by_type: Ordinary-taxable amount per income type for the unit
            (see :meth:`~life_model.tax.income.IncomeLedger.totals_by_type`).
        filing_status: Filing status of the unit.
        state: The resident's state code (``None`` → the config default state).
        legacy_agi_base: The federal-style AGI base used for the ``DEFAULT`` flat-rate path.
        config: Per-model config. Defaults to the global config.
    """
    state_config = _fin(config).tax.state
    from ..config.models import DEFAULT_STATE_KEY

    resolved = state_config.resolve_state_code(state)
    pack = state_config.get_pack(state)

    if resolved == DEFAULT_STATE_KEY:
        # ``DEFAULT`` flat rate applied to the federal AGI base.
        return legacy_agi_base * (pack.flat_rate or 0.0) / 100

    ordinary = sum(totals_by_type.values())
    base = ordinary
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
    base -= _state_standard_deduction(pack, filing_status)
    base = max(base, 0.0)

    if pack.brackets is not None:
        return apply_brackets(base, _bracket_rows(pack, filing_status))
    return base * (pack.flat_rate or 0.0) / 100
