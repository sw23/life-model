# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Per-person income ledger.

Tracks a person's income for the current simulated year as a list of typed entries, keeping the
two tax bases separate:

* **Ordinary taxable income** — the income tax base. Includes wages, pre-tax retirement
  distributions (401k/IRA withdrawals and RMDs), interest, and other ordinary income.
* **FICA wages** — the payroll tax base. Earned income only; the full gross salary including
  pre-tax 401k deferrals, but not retirement distributions or other unearned income.

Income producers append typed entries via :meth:`IncomeLedger.add`; nothing writes a raw scalar.
The tax computation reads ``ordinary_taxable`` (income tax base) and ``fica_wages`` (payroll tax
base) off the ledger, so income tax and payroll tax each see the correct base.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List


class IncomeType(Enum):
    """Category of an income entry, which determines how it is taxed."""

    WAGES = "wages"  # Earned income: subject to both income tax and FICA.
    PRETAX_DISTRIBUTION = "pretax_distribution"  # 401k/IRA withdrawals & RMDs: ordinary income, no FICA.
    SS_BENEFIT = "ss_benefit"  # Social Security benefits: taxed under provisional-income rules (future).
    PENSION = "pension"  # Defined-benefit pension income: ordinary, no FICA (retirees pay no payroll tax).
    INTEREST = "interest"  # Interest income: ordinary, no FICA.
    ORDINARY = "ordinary"  # Generic ordinary income: no FICA.
    # Gains on assets held one year or less are taxed at ordinary rates; the separate member exists
    # so reporting and loss-character tracking can tell them apart from other ordinary income.
    SHORT_TERM_CAPITAL_GAIN = "short_term_capital_gain"
    LONG_TERM_CAPITAL_GAIN = "long_term_capital_gain"  # Held over a year: preferential 0/15/20% rates.
    QUALIFIED_DIVIDEND = "qualified_dividend"  # Taxed at the same preferential rates as long-term gains.


#: Income types taxed under the preferential capital-gains rate schedule rather than the ordinary
#: brackets. These are excluded from :attr:`IncomeLedger.ordinary_taxable` and surfaced separately
#: as :attr:`IncomeLedger.preferential_income` so the stacking computation can see both bases.
#: Short-term gains are deliberately absent — they are taxed at ordinary rates.
PREFERENTIAL_TYPES = frozenset({IncomeType.LONG_TERM_CAPITAL_GAIN, IncomeType.QUALIFIED_DIVIDEND})

#: Income types that make up net investment income for the §1411 surtax: interest, dividends, and
#: capital gains. Defined by inclusion rather than by subtracting excluded categories, so a new
#: income type is outside the NIIT base until it is deliberately added here. Wages, Social Security,
#: and retirement-plan distributions are statutorily excluded.
NET_INVESTMENT_TYPES = frozenset(
    {
        IncomeType.INTEREST,
        IncomeType.QUALIFIED_DIVIDEND,
        IncomeType.SHORT_TERM_CAPITAL_GAIN,
        IncomeType.LONG_TERM_CAPITAL_GAIN,
    }
)


@dataclass
class IncomeEntry:
    """A single income event for the year."""

    #: The category of income.
    income_type: IncomeType
    #: The ordinary-taxable portion this entry contributes (income tax base).
    amount: float
    #: The FICA-subject wages this entry contributes (payroll tax base). Non-zero only for
    #: :attr:`IncomeType.WAGES`; it can differ from ``amount`` because pre-tax 401k deferrals
    #: reduce ordinary income but are still FICA wages.
    fica_wages: float = 0.0


class IncomeLedger:
    """Accumulates a person's income entries for the current simulated year."""

    def __init__(self):
        self.entries: List[IncomeEntry] = []

    def add(self, income_type: IncomeType, amount: float, fica_wages: float = 0.0) -> None:
        """Append an income entry."""
        self.entries.append(IncomeEntry(income_type, amount, fica_wages))

    def add_wages(self, ordinary_amount: float, fica_wages: float) -> None:
        """Append earned income.

        Args:
            ordinary_amount: Wages included in ordinary taxable income (gross minus pre-tax deferrals).
            fica_wages: Wages subject to FICA (the full gross, including pre-tax deferrals).
        """
        self.add(IncomeType.WAGES, ordinary_amount, fica_wages)

    def clear(self) -> None:
        """Reset the ledger for the next year (mirrors the old ``taxable_income = 0``)."""
        self.entries.clear()

    @property
    def ordinary_taxable(self) -> float:
        """Total ordinary taxable income (the ordinary-rate tax base).

        Preferential income (long-term gains, qualified dividends) is excluded — it is taxed on its
        own rate schedule and is reported by :attr:`preferential_income`. Callers that want the full
        income tax base must add the two together.
        """
        return sum(e.amount for e in self.entries if e.income_type not in PREFERENTIAL_TYPES)

    @property
    def preferential_income(self) -> float:
        """Net long-term capital gains plus qualified dividends (the preferential-rate base).

        May be negative in a net capital-loss year; loss netting and the $3,000 ordinary offset are
        applied at settlement, so this is a raw figure rather than a clamped one.
        """
        return sum(e.amount for e in self.entries if e.income_type in PREFERENTIAL_TYPES)

    @property
    def net_investment_income(self) -> float:
        """Net investment income for the §1411 surtax base (never negative)."""
        return max(0.0, sum(e.amount for e in self.entries if e.income_type in NET_INVESTMENT_TYPES))

    @property
    def fica_wages(self) -> float:
        """Total FICA-subject wages (payroll tax base)."""
        return sum(e.fica_wages for e in self.entries)

    def totals_by_type(self) -> "Dict[IncomeType, float]":
        """Taxable amount contributed by each income type, preferential types included.

        Every :class:`IncomeType` is present in the result (0.0 when absent) so callers can index
        any type unconditionally. Used by the state tax base to subtract categories a state exempts
        (pre-tax distributions, Social Security) from total income. Capital gains are *not* split
        out by default because the large majority of states tax them as ordinary income; states
        that exempt them set ``capital_gains_taxable: false`` on their pack.
        """
        totals: Dict[IncomeType, float] = {income_type: 0.0 for income_type in IncomeType}
        for entry in self.entries:
            totals[entry.income_type] += entry.amount
        return totals
