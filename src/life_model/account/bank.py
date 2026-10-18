# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import html
from typing import ClassVar

from .._compat import legacy_signature
from ..base_classes import FinancialAccount
from ..economy import annual_to_monthly
from ..ledger import FlowKind
from ..model import compound_interest
from ..people.person import Person
from ..tax.income import IncomeType

#: ``compounding`` choices and the number of compounding periods per year each means.
COMPOUNDING_PERIODS = {"monthly": 12, "annual": 1}


class BankAccount(FinancialAccount):
    """A cash account (checking/savings) paying interest.

    ``interest_rate`` is a nominal annual rate (APR, percent) compounded ``compounding`` times a
    year, so the effective yield (APY) is ``(1 + APR / n) ** n - 1``: a 5% APR compounded monthly
    yields 5.116%; pass ``compounding="annual"`` when the rate you have is an APY.

    Interest accrues monthly in the ``step`` stage before the month's bills are paid (priority -10,
    like investment growth): ``APR / 12`` a month when compounded monthly, ``(1 + APY)^(1/12) - 1``
    when the rate is an annual-compounding APY. It is posted to the owner's income ledger as ordinary
    :attr:`~life_model.tax.income.IncomeType.INTEREST` income (net investment income for the §1411
    surtax), so it is taxed with the year's return. Year-end statistics are taken in
    ``collect_stats``.
    """

    STATS_OWNED = frozenset({"stat_useable_balance"})

    # Accrue interest before tax-unit settlement (0) so the interest is on this year's return.
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"step": -10}

    @legacy_signature(("owner", "company", "type", "balance", "interest_rate"), {"interest_rate": "interest_pct"})
    def __init__(
        self,
        owner: Person,
        *,
        company: str = "Bank",
        type: str = "Bank",
        balance: float = 0,
        interest_pct: float | None = None,
        compounding: str | None = None,
        reserve: bool = False,
    ):
        """Class modeling bank accounts

        Args:
            owner (Person): Person that owns the Bank Account.
            company (str): Company at which the bank account belongs.
            type (str, optional): Type of account. Defaults to 'Bank'.
            balance (float, optional): Balance of account. Defaults to 0.
            interest_pct (float, optional): Nominal annual interest rate (APR, percent); deprecated
                alias ``interest_rate``. Defers to the economy's cash yield each year if None.
            compounding (str, optional): ``"monthly"`` or ``"annual"`` compounding of
                ``interest_pct``. Defaults to the configured ``accounts.bank.compound_rate`` (monthly).
            reserve (bool, optional): An emergency reserve (Plan 27 D2/D4): income is not deposited here
                and the household waterfall draws it only after every other source (the ``reserve``
                step). Defaults to False.

        Every argument after ``owner`` is keyword-only (positional use is deprecated, Plan 27 D8).
        """
        interest_rate = interest_pct
        super().__init__(owner, balance)
        self.company = company
        self.type = type
        #: Whether this is an emergency reserve (drawn last by the waterfall, never receives income).
        self.reserve = reserve
        bank_config = self.model.config.accounts.bank
        # An explicit interest_rate overrides the economy; None defers to the
        # economy's cash yield, re-read each year.
        self._interest_rate_override = interest_rate
        if compounding is None:
            self.compound_rate = bank_config.compound_rate
        elif compounding in COMPOUNDING_PERIODS:
            self.compound_rate = COMPOUNDING_PERIODS[compounding]
        else:
            raise ValueError(f"Unknown compounding {compounding!r}; expected one of {list(COMPOUNDING_PERIODS)}")

        self.stat_total_interest = 0
        self.stat_useable_balance = 0

        # Register with the model registry
        self.model.registries.bank_accounts.register(owner, self)

    @property
    def interest_rate(self) -> float:
        """Annual interest rate (APR, percent): the explicit override if set, else the economy's yield."""
        if self._interest_rate_override is not None:
            return self._interest_rate_override
        return self.model.economy.cash_yield(self.model.year)

    @interest_rate.setter
    def interest_rate(self, value: float | None) -> None:
        self._interest_rate_override = value

    def _repr_html_(self):
        return f"{self.type} account at {html.escape(self.company)} balance: ${self.balance:,}"

    @property
    def monthly_interest_rate(self) -> float:
        """This month's interest rate (percent): a twelfth of the APR when compounded monthly, else the
        monthly equivalent of the annual rate."""
        if self.compound_rate == 12:
            return self.interest_rate / 12
        return annual_to_monthly(compound_interest(100, self.interest_rate, self.compound_rate))

    def step(self):
        # Apply this month's interest and record it as ordinary income for the year's return.
        interest = self.balance * self.monthly_interest_rate / 100
        self.balance += interest
        self.stat_total_interest += interest
        self.model.ledger.post(interest, FlowKind.INTEREST, to_account=self, source=self.company, agent=self.person)
        if interest != 0:
            self.person.income.add(IncomeType.INTEREST, interest, source="bank_interest")

    def collect_stats(self):
        # Year-end statistics, after the month's bills and the year's taxes were paid.
        self.stat_useable_balance = self.balance
