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


class IncomeType(Enum):
    """Category of an income entry, which determines how it is taxed."""

    WAGES = "wages"  # Earned income: subject to both income tax and FICA.
    PRETAX_DISTRIBUTION = "pretax_distribution"  # 401k/IRA withdrawals & RMDs: ordinary income, no FICA.
    # Social Security benefits. An entry's ``gross`` is the benefit received and its ``amount`` the
    # taxable portion, which the tax unit sets at settlement from the unit's provisional income.
    SS_BENEFIT = "ss_benefit"
    PENSION = "pension"  # Defined-benefit pension income: ordinary, no FICA (retirees pay no payroll tax).
    INTEREST = "interest"  # Interest income (bank accounts, corporate bonds): ordinary, no FICA.
    # US Treasury interest: federally taxable ordinary income, but exempt from state income tax
    # (31 U.S.C. §3124), so every state pack excludes it.
    TREASURY_INTEREST = "treasury_interest"
    # Tax-exempt (municipal bond) interest: excluded from federal ordinary income and the §1411
    # base, but counted in Social Security provisional income (IRC §86(b)(2)(B)). Treated as exempt
    # from state tax too (in-state bonds).
    TAX_EXEMPT_INTEREST = "tax_exempt_interest"
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

#: Income types that are not part of either income-tax base (ordinary or preferential). They are
#: still recorded, because some rules look at them (Social Security provisional income).
NON_TAXABLE_TYPES = frozenset({IncomeType.TAX_EXEMPT_INTEREST})

#: Income types that make up net investment income for the §1411 surtax: interest, dividends, and
#: capital gains. Defined by inclusion rather than by subtracting excluded categories, so a new
#: income type is outside the NIIT base until it is deliberately added here. Wages, Social Security,
#: and retirement-plan distributions are statutorily excluded.
NET_INVESTMENT_TYPES = frozenset(
    {
        IncomeType.INTEREST,
        IncomeType.TREASURY_INTEREST,
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
    #: The gross amount received, for entries whose taxable ``amount`` is a derived share of it
    #: (Social Security benefits). 0.0 for every other entry.
    gross: float = 0.0
    #: What produced the entry (e.g. ``"rmd"``, ``"annuity"``, ``"hsa_deduction"``,
    #: ``"capital_loss_deduction"``). Tax computations ignore it; the year's tax return uses it to put
    #: each entry on the right line (adjustments vs. other income, pensions vs. annuities, ...).
    source: str | None = None


class IncomeLedger:
    """Accumulates a person's income entries for the current simulated year."""

    def __init__(self):
        self.entries: list[IncomeEntry] = []
        # Additional federal tax from early-withdrawal / non-qualified-distribution penalties (e.g.
        # 10% on early pre-tax distributions, 20% on non-medical HSA distributions), by source.
        # Settled as federal tax with the year's return.
        self.penalties_by_source: dict[str, float] = {}

    @property
    def penalties(self) -> float:
        """Total additional federal tax (penalties) recorded this year."""
        return sum(self.penalties_by_source.values())

    def add(
        self, income_type: IncomeType, amount: float, fica_wages: float = 0.0, *, source: str | None = None
    ) -> None:
        """Append an income entry (``source`` labels it for the tax return; keyword-only)."""
        self.entries.append(IncomeEntry(income_type, amount, fica_wages, source=source))

    def add_social_security(self, gross: float) -> None:
        """Record Social Security benefits received (gross). The taxable portion depends on the
        whole return's provisional income, so it starts at 0 and the tax unit sets it at settlement
        (:meth:`set_taxable_social_security`)."""
        if gross > 0:
            self.entries.append(IncomeEntry(IncomeType.SS_BENEFIT, 0.0, gross=gross, source="social_security"))

    @property
    def social_security_benefits(self) -> float:
        """Gross Social Security benefits received this year."""
        return sum(e.gross for e in self.entries if e.income_type == IncomeType.SS_BENEFIT)

    @property
    def taxable_social_security(self) -> float:
        """The currently recorded taxable portion of this year's Social Security benefits."""
        return sum(e.amount for e in self.entries if e.income_type == IncomeType.SS_BENEFIT)

    def set_taxable_social_security(self, taxable: float) -> None:
        """Set the taxable portion of this year's benefits, spread over the benefit entries in
        proportion to their gross (entries without a gross, e.g. ones added directly with an
        amount, are left alone)."""
        benefit_entries = [e for e in self.entries if e.income_type == IncomeType.SS_BENEFIT and e.gross > 0]
        gross = sum(e.gross for e in benefit_entries)
        for entry in benefit_entries:
            entry.amount = taxable * entry.gross / gross if gross > 0 else 0.0

    def add_wages(self, ordinary_amount: float, fica_wages: float, *, source: str = "wages") -> None:
        """Append earned income.

        Args:
            ordinary_amount: Wages included in ordinary taxable income (gross minus pre-tax deferrals).
            fica_wages: Wages subject to FICA (the full gross, including pre-tax deferrals).
        """
        self.add(IncomeType.WAGES, ordinary_amount, fica_wages, source=source)

    def add_deduction(self, amount: float, *, source: str = "adjustment") -> None:
        """Record an above-the-line deduction (e.g. a deductible IRA or HSA contribution).

        Modeled as negative ordinary income, the same way the student-loan interest deduction is,
        so it reduces the income-tax base (and AGI) without touching FICA wages. ``source`` names
        the adjustment on the tax return (``"ira_deduction"``, ``"hsa_deduction"``, ...).
        """
        if amount > 0:
            self.add(IncomeType.ORDINARY, -amount, source=source)

    def add_penalty(self, amount: float, *, source: str = "early_withdrawal") -> None:
        """Record an additional federal tax (10% early withdrawal, 20% HSA non-medical) by source."""
        if amount > 0:
            self.penalties_by_source[source] = self.penalties_by_source.get(source, 0.0) + amount

    def clear(self) -> None:
        """Reset the ledger for the next year (mirrors the old ``taxable_income = 0``)."""
        self.entries.clear()
        self.penalties_by_source = {}

    @property
    def ordinary_taxable(self) -> float:
        """Total ordinary taxable income (the ordinary-rate tax base).

        Preferential income (long-term gains, qualified dividends) is excluded — it is taxed on its
        own rate schedule and is reported by :attr:`preferential_income`. Callers that want the full
        income tax base must add the two together.
        """
        return sum(
            e.amount
            for e in self.entries
            if e.income_type not in PREFERENTIAL_TYPES and e.income_type not in NON_TAXABLE_TYPES
        )

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
    def tax_exempt_interest(self) -> float:
        """Tax-exempt (municipal) interest received this year (outside both tax bases)."""
        return sum(e.amount for e in self.entries if e.income_type == IncomeType.TAX_EXEMPT_INTEREST)

    @property
    def fica_wages(self) -> float:
        """Total FICA-subject wages (payroll tax base)."""
        return sum(e.fica_wages for e in self.entries)

    def totals_by_type(self) -> "dict[IncomeType, float]":
        """Taxable amount contributed by each income type, preferential types included.

        Every :class:`IncomeType` is present in the result (0.0 when absent) so callers can index
        any type unconditionally. Used by the state tax base to subtract categories a state exempts
        (pre-tax distributions, Social Security) from total income. Capital gains are *not* split
        out by default because the large majority of states tax them as ordinary income; states
        that exempt them set ``capital_gains_taxable: false`` on their pack.
        """
        totals: dict[IncomeType, float] = {income_type: 0.0 for income_type in IncomeType}
        for entry in self.entries:
            totals[entry.income_type] += entry.amount
        return totals
