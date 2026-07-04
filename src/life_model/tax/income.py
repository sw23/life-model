# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Per-person income ledger.

The engine historically tracked a single ``person.taxable_income`` scalar, which conflated two
distinct concepts: **FICA (payroll) wages**, which are earned income only, and **ordinary
taxable income**, which also includes pre-tax retirement distributions. That conflation is the
root cause of several FICA bugs (payroll tax levied on 401k/RMD distributions; the FICA base
understating pre-tax deferrals). The ledger keeps the two separate so income tax and payroll tax
each see the right base.

Income producers append typed entries; nothing writes a raw scalar. The tax computation reads
``ordinary_taxable`` (income tax base) and ``fica_wages`` (payroll tax base) off the ledger.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List


class IncomeType(Enum):
    """Category of an income entry, which determines how it is taxed."""

    WAGES = "wages"  # Earned income: subject to both income tax and FICA.
    PRETAX_DISTRIBUTION = "pretax_distribution"  # 401k/IRA withdrawals & RMDs: ordinary income, no FICA.
    SS_BENEFIT = "ss_benefit"  # Social Security benefits: taxed under provisional-income rules (future).
    INTEREST = "interest"  # Interest income: ordinary, no FICA.
    ORDINARY = "ordinary"  # Generic ordinary income: no FICA.


@dataclass
class IncomeEntry:
    """A single income event for the year.

    Attributes:
        income_type: The category of income.
        amount: The ordinary-taxable portion this entry contributes (income tax base).
        fica_wages: The FICA-subject wages this entry contributes (payroll tax base). Non-zero
            only for :attr:`IncomeType.WAGES`; note it can differ from ``amount`` because pre-tax
            401k deferrals reduce ordinary income but are still FICA wages.
    """

    income_type: IncomeType
    amount: float
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
        """Total ordinary taxable income (income tax base)."""
        return sum(e.amount for e in self.entries)

    @property
    def fica_wages(self) -> float:
        """Total FICA-subject wages (payroll tax base)."""
        return sum(e.fica_wages for e in self.entries)
