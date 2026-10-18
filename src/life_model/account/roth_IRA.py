# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from dataclasses import dataclass

from .._compat import legacy_signature
from ..base_classes import TaxAdvantagedAccount, TaxTreatment
from ..limits import federal_retirement_age
from ..people.person import Person
from ..tax.income import IncomeType

#: Years a converted amount must stay in a Roth IRA before it can come out penalty-free under 59.5
#: (IRC §408A(d)(3)(F): the 5-taxable-year period starting with the year of the conversion).
CONVERSION_SEASONING_YEARS = 5


@dataclass
class ConversionLot:
    """One Roth conversion still in the account: ``amount`` converted in ``year`` (None: an opening
    conversion basis of unknown, assumed seasoned, date), of which ``taxable`` was included in income."""

    amount: float
    year: int | None
    taxable: float

    def seasoned(self, year: int) -> bool:
        return self.year is None or year >= self.year + CONVERSION_SEASONING_YEARS


class RothIRA(TaxAdvantagedAccount):
    STATS_OWNED = frozenset({"stat_roth_ira_balance"})
    BALANCE_STAT = "stat_roth_ira_balance"
    tax_treatment = TaxTreatment.ROTH
    is_rmd_eligible = False
    limit_group = "ira"  # one IRA limit shared across Roth and Traditional

    @legacy_signature(
        ("person", "balance", "growth_rate", "contribution_limit"),
        {"person": "owner", "growth_rate": "growth_pct", "contribution_limit": "contribution_limit_annual"},
    )
    def __init__(
        self,
        owner: Person,
        *,
        balance: float = 0,
        growth_pct: float | None = None,
        contribution_limit_annual: float | None = None,
        contribution_basis: float | None = None,
        conversion_basis: float = 0.0,
        allocation: "dict[str, float] | None" = None,
        expense_ratio_pct: float = 0.0,
    ):
        """Models a Roth IRA account for a person.

        Contributions are made with after-tax dollars. Withdrawals follow the Roth ordering rules (IRC
        §408A(d)(4)): regular contributions first (always tax- and penalty-free), then conversions
        (tax-free; the taxable part of a conversion less than five years old carries the 10% additional
        tax before 59.5), then earnings (ordinary income plus the 10% additional tax before 59.5; qualified
        and tax-free from 59.5; the five-year rule for earnings is not modeled).

        Args:
            owner: The person to which this IRA belongs (deprecated alias ``person``).
            balance: Current balance in the IRA.
            growth_pct: Expected annual growth rate percentage (deprecated alias ``growth_rate``).
                Defers to the economy's equity return when None.
            contribution_limit_annual: Override for the annual contribution limit (deprecated alias
                ``contribution_limit``); the year's IRA limit plus the age-50 catch-up when None.
            contribution_basis: Regular contributions still in the account (Plan 27 D1). When None the
                whole balance less ``conversion_basis`` is treated as contributions (no earnings).
            conversion_basis: Converted amounts still in the account (assumed more than five years old).
            allocation: Target allocation in percent by asset class (Plan 27 D5).
            expense_ratio_pct: Fund expense ratio (percent a year).
        """
        if conversion_basis < 0 or conversion_basis > balance + 1e-9:
            raise ValueError("conversion_basis must be between 0 and the balance")
        if contribution_basis is None:
            contribution_basis = balance - conversion_basis
        if contribution_basis < 0 or contribution_basis + conversion_basis > balance + 1e-9:
            raise ValueError("contribution_basis + conversion_basis must be between 0 and the balance")
        super().__init__(
            owner,
            balance,
            growth_pct,
            basis=contribution_basis,
            allocation=allocation,
            expense_ratio_pct=expense_ratio_pct,
        )
        self._contribution_limit_override = contribution_limit_annual
        #: Conversions still in the account, oldest first.
        self.conversions: list[ConversionLot] = []
        if conversion_basis > 0:
            self.conversions.append(ConversionLot(conversion_basis, None, conversion_basis))
        self.model.registries.roth_iras.register(owner, self)

    @property
    def conversion_basis(self) -> float:
        """Converted amounts still in the account (tax-free on withdrawal)."""
        return sum(lot.amount for lot in self.conversions)

    @property
    def earnings(self) -> float:
        """Portion of the balance that is investment earnings (balance less both kinds of basis)."""
        return max(0.0, self.balance - self.contribution_basis - self.conversion_basis)

    def annual_contribution_limit(self) -> float:
        if self._contribution_limit_override is not None:
            return self._contribution_limit_override
        from .traditional_IRA import ira_contribution_limit

        return ira_contribution_limit(self.person, self.model.year)

    def receive_conversion(self, amount: float, taxable: float) -> None:
        """Credit a Roth conversion of ``amount`` (``taxable`` of it was included in income this year);
        the caller posts the transfer."""
        if amount <= 0:
            return
        self.balance += amount
        self.conversions.append(ConversionLot(amount, self.model.year, taxable))

    def _qualified(self) -> bool:
        return self.person.age_years_fractional >= federal_retirement_age(self.model.config)

    def withdraw(self, amount: float) -> float:
        """Withdraw in the Roth ordering: contributions, then conversions (oldest first), then earnings.

        Earnings withdrawn before the federal retirement age (59.5) are a non-qualified distribution:
        ordinary income plus the early-withdrawal additional tax; the taxable part of a conversion less
        than five years old carries the additional tax too (IRC §408A(d)(3)(F)). Both are recorded on the
        owner's income ledger.
        """
        if amount <= 0:
            return 0.0
        withdrawn = min(amount, self.balance)
        if withdrawn <= 0:
            return 0.0
        self.balance -= withdrawn
        remaining = withdrawn
        from_contributions = min(remaining, self.contribution_basis)
        self.contribution_basis -= from_contributions
        remaining -= from_contributions
        penalized = 0.0
        while remaining > 1e-12 and self.conversions:
            lot = self.conversions[0]
            take = min(remaining, lot.amount)
            taxable_share = lot.taxable * (take / lot.amount) if lot.amount > 0 else 0.0
            if not lot.seasoned(self.model.year):
                penalized += taxable_share
            lot.amount -= take
            lot.taxable -= taxable_share
            remaining -= take
            if lot.amount <= 1e-9:
                self.conversions.pop(0)
        earnings_withdrawn = max(0.0, remaining)
        config = self.model.config
        if not self._qualified():
            rate = config.retirement.early_withdrawal_penalty_rate / 100
            if earnings_withdrawn > 0:
                self.person.income.add(IncomeType.PRETAX_DISTRIBUTION, earnings_withdrawn, source="roth_ira_earnings")
                self.person.income.add_penalty(earnings_withdrawn * rate, source="roth_ira_earnings")
            if penalized > 0:
                self.person.income.add_penalty(penalized * rate, source="roth_conversion_recapture")
        return withdrawn

    def tax_free_withdrawable(self) -> float:
        """Amount that can be withdrawn right now without creating taxable income or a penalty."""
        if self._qualified():
            return self.balance
        year = self.model.year
        available = self.contribution_basis
        for lot in self.conversions:
            if not lot.seasoned(year):
                break  # conversions come out oldest first; a young one would be penalized
            available += lot.amount
        return min(self.balance, available)

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Balance: ${self.balance:,.2f}</li>"
        desc += f"<li>Growth Rate: {self.growth_rate}%</li>"
        desc += f"<li>Contribution Limit: ${self.annual_contribution_limit():,.2f}</li>"
        desc += f"<li>Contributions This Year: ${self.contributions_ytd:,.2f}</li>"
        desc += "</ul>"
        return desc
