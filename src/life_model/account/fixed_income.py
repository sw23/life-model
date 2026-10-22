# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Fixed-income holdings: CDs, Treasuries, I bonds and bond funds.

A :class:`FixedIncomeHolding` is not cash (the waterfall spends a bank account like checking, and its
interest is ordinary income); it keeps each instrument's own rules:

* **cd**: interest at ``rate_pct`` (an APR) credited monthly to the CD (ordinary interest, taxable when
  credited); at ``maturity`` the balance moves to the owner's bank. An early withdrawal forfeits
  ``early_withdrawal_penalty_months`` of interest on the amount withdrawn, deductible above the line
  (IRC §62(a)(9), Schedule 1 line 18).
* **treasury**: a note or bond held to maturity at face; the coupon (``rate_pct`` a year) is paid to the
  bank a twelfth a month as Treasury interest (federally taxable, exempt from state tax, 31 U.S.C.
  §3124); the face comes back at ``maturity``. A sale before maturity is at face (rate risk is not
  modeled).
* **i_bond**: the composite rate ``fixed + 2 x semiannual inflation + fixed x semiannual inflation``
  (``rate_pct`` is the fixed rate; the semiannual inflation rate is half the economy's annual inflation)
  resets every six months from the issue month and never goes below zero; interest accrues monthly and
  its federal tax is deferred to redemption (state-exempt). An I bond cannot be cashed in its first 12
  months, a redemption within five years forfeits the last three months of interest, and it stops
  earning at 30 years (TreasuryDirect).
* **bond_fund**: total return at the economy's bond return (or ``growth_pct``); ``rate_pct`` is the
  distribution yield, carved out of that return and paid monthly as interest (``tax_exempt`` for a
  municipal fund, ``state_tax_exempt`` for a Treasury fund), reinvested by default. Basis is the
  average cost (Treas. Reg. §1.1012-1(e)); a sale realizes the gain, long-term once the holding is a
  year old.

``reserve=True`` (the default) keeps a holding out of the household waterfall until every other source
is exhausted (the ``reserve`` step); ``reserve=False`` puts it in the ``fixed_income`` step, right after
the bank.
"""

from typing import TYPE_CHECKING, ClassVar

from ..base_classes import FinancialAccount
from ..economy import annual_to_monthly
from ..ledger import FlowKind
from ..model import Event, month_index, parse_year_month
from ..tax.income import IncomeType

if TYPE_CHECKING:
    from ..people.person import Person

#: Instrument kinds.
FIXED_INCOME_KINDS = ("cd", "treasury", "i_bond", "bond_fund")

# vintage: 2026, source: TreasuryDirect, "I bonds" and "I bonds interest rates" (fetched 2026-10-18):
# cashable after 12 months; cashed before 5 years loses the last 3 months of interest; earns for 30 years;
# the composite rate never goes below zero and changes every 6 months from the issue date.
I_BOND_LOCK_MONTHS = 12
I_BOND_PENALTY_YEARS = 5
I_BOND_PENALTY_MONTHS = 3
I_BOND_MATURITY_YEARS = 30


def _parse_month(value: "str | int | None") -> "tuple[int, int] | None":
    if value is None:
        return None
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        return int(value), 12
    return parse_year_month(value)


class FixedIncomeHolding(FinancialAccount):
    """A CD, Treasury, I bond or bond fund (see the module docstring for each kind's rules)."""

    BALANCE_STAT = "stat_fixed_income_balance"
    STATS_OWNED = frozenset({"stat_fixed_income_balance"})
    # Interest accrues with the other accounts' growth, before the month's bills (0).
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"step": -10}

    def __init__(
        self,
        owner: "Person",
        *,
        kind: str,
        face: float,
        rate_pct: float,
        maturity: "str | int | None" = None,
        purchased: "str | int | None" = None,
        state_tax_exempt: bool | None = None,
        tax_exempt: bool = False,
        early_withdrawal_penalty_months: int = 0,
        reserve: bool = True,
        name: str | None = None,
        reinvest: bool | None = None,
        accrued_interest: float = 0.0,
        cost_basis: float | None = None,
        growth_pct: float | None = None,
    ):
        """A fixed-income holding.

        Args:
            owner: The owner.
            kind: ``"cd"``, ``"treasury"``, ``"i_bond"`` or ``"bond_fund"``.
            face: The current value from the statement (a CD's or I bond's current value, a Treasury's
                face, a fund's market value).
            rate_pct: The CD's APR, the Treasury's coupon, the I bond's fixed rate, or the fund's
                distribution yield (percent a year).
            maturity: ``"YYYY-MM"`` (or a year: its December) the CD or Treasury matures; None never
                matures (an I bond matures 30 years after ``purchased``).
            purchased: ``"YYYY-MM"`` the holding was bought (the I bond's issue month: the lock, the
                five-year penalty and its rate resets; a fund's holding period). Defaults to the first
                simulated month.
            state_tax_exempt: Interest exempt from state tax (default True for Treasuries and I bonds).
            tax_exempt: Interest exempt from federal tax (a municipal bond fund).
            early_withdrawal_penalty_months: A CD's penalty for early withdrawal, in months of interest.
            reserve: Drawn by the household waterfall only after every other source (default True).
            name: A label (the issuer or fund).
            reinvest: Whether interest stays in the holding (default: True for a CD, bond fund and I
                bond; a Treasury's coupon is paid to the bank).
            accrued_interest: An I bond's interest included in ``face`` (its federal tax is deferred to
                redemption). For a CD: interest earned before the model's start that ``face`` (the principal
                on the statement) does not include, added to the holding's value and taxed when it is paid
                (at maturity or an early redemption). Defaults to 0.
            cost_basis: A bond fund's cost basis (defaults to ``face``: no embedded gain).
            growth_pct: A bond fund's total return (percent a year); None follows the economy's bond return.
        """
        if kind not in FIXED_INCOME_KINDS:
            raise ValueError(f"Unknown fixed-income kind {kind!r}; expected one of {FIXED_INCOME_KINDS}")
        if face < 0 or rate_pct < -100:
            raise ValueError("face must be non-negative")
        if early_withdrawal_penalty_months < 0:
            raise ValueError("early_withdrawal_penalty_months must be non-negative")
        if accrued_interest < 0:
            raise ValueError("accrued_interest must be non-negative")
        # A CD's interest accrued before the start is not in the statement's face: it is part of the value.
        super().__init__(owner, face + (accrued_interest if kind == "cd" else 0.0))
        self.kind = kind
        self.rate_pct = float(rate_pct)
        self.name = name or {"cd": "CD", "treasury": "Treasury", "i_bond": "I bond", "bond_fund": "Bond fund"}[kind]
        self.company = self.name
        model = self.model
        self.purchased = _parse_month(purchased) or (model.year, model.month)
        if kind == "i_bond" and maturity is None:
            self.maturity: tuple[int, int] | None = (
                self.purchased[0] + I_BOND_MATURITY_YEARS,
                self.purchased[1],
            )
        else:
            self.maturity = _parse_month(maturity)
        self.state_tax_exempt = kind in ("treasury", "i_bond") if state_tax_exempt is None else state_tax_exempt
        self.tax_exempt = tax_exempt
        self.early_withdrawal_penalty_months = early_withdrawal_penalty_months
        self.reserve = reserve
        self.reinvest = (kind != "treasury") if reinvest is None else reinvest
        #: An I bond's interest not yet taxed (deferred to redemption).
        self.accrued_interest = float(accrued_interest)
        #: A bond fund's average-cost basis.
        self.cost_basis = float(face if cost_basis is None else cost_basis)
        self._growth_override = growth_pct
        self.matured = False
        #: An I bond's interest by month (for the three-month forfeiture), most recent last.
        self._recent_interest: list[float] = []
        self._i_bond_rate: float | None = None
        self.stat_fixed_income_balance = 0.0
        self.model.registries.fixed_income.register(owner, self)

    # --- helpers ---

    @property
    def months_held(self) -> int:
        return month_index(self.model.year, self.model.month) - month_index(*self.purchased)

    @property
    def income_type(self) -> IncomeType:
        if self.tax_exempt:
            return IncomeType.TAX_EXEMPT_INTEREST
        if self.state_tax_exempt:
            return IncomeType.TREASURY_INTEREST
        return IncomeType.INTEREST

    def _post_interest(self, amount: float, *, to_account=None) -> None:
        """Post ``amount`` of interest (to this holding, or to ``to_account``) and tax it now."""
        if amount == 0:
            return
        self.model.ledger.post(
            amount, FlowKind.INTEREST, to_account=to_account or self, source=self.name, agent=self.person
        )
        self.person.income.add(self.income_type, amount, source=f"{self.kind}_interest")

    def i_bond_composite_rate(self) -> float:
        """The I bond's composite rate (percent a year) for the current six-month period."""
        semiannual_inflation = self.model.economy.inflation(self.model.year) / 2 / 100
        fixed = self.rate_pct / 100
        return max(0.0, fixed + 2 * semiannual_inflation + fixed * semiannual_inflation) * 100

    @property
    def is_mature_now(self) -> bool:
        return self.maturity is not None and (self.model.year, self.model.month) >= self.maturity

    # --- monthly ---

    def step(self):
        """This month's interest (and maturity)."""
        if self.matured or self.balance <= 0:
            return
        handler = getattr(self, f"_step_{self.kind}")
        handler()
        if self.is_mature_now:
            self.mature()

    def _step_cd(self) -> None:
        # An APR credited (and compounded) monthly.
        interest = self.balance * self.rate_pct / 12 / 100
        if self.reinvest:
            self._post_interest(interest)
            self.balance += interest
        else:
            self._post_interest(interest, to_account=self.person.cash_destination)
            self.person.receive_cash(interest, post=False)

    def _step_treasury(self) -> None:
        coupon = self.balance * self.rate_pct / 12 / 100
        if self.reinvest:
            self._post_interest(coupon)
            self.balance += coupon
        else:
            destination = self.person.cash_destination
            self._post_interest(coupon, to_account=destination)
            self.person.receive_cash(coupon, post=False)

    def _step_i_bond(self) -> None:
        if self.months_held >= I_BOND_MATURITY_YEARS * 12:
            return
        if self._i_bond_rate is None or self.months_held % 6 == 0:
            self._i_bond_rate = self.i_bond_composite_rate()
        # Semiannual compounding, accrued monthly: (1 + rate / 2)^(1/6) - 1 a month.
        monthly = (1 + self._i_bond_rate / 100 / 2) ** (1 / 6) - 1
        interest = self.balance * monthly
        self.balance += interest
        self.accrued_interest += interest
        self._recent_interest = [*self._recent_interest[-(I_BOND_PENALTY_MONTHS - 1) :], interest]
        # The value rises now; the federal tax waits for redemption (no income-ledger entry yet).
        self.model.ledger.post(interest, FlowKind.INTEREST, to_account=self, source=self.name, agent=self.person)

    def _step_bond_fund(self) -> None:
        total = (
            annual_to_monthly(self._growth_override)
            if self._growth_override is not None
            else self.model.economy.monthly_rate("bond_return")
        )
        distribution = self.balance * self.rate_pct / 12 / 100
        price_change = self.balance * total / 100 - distribution
        self.balance += price_change
        self.model.ledger.post(price_change, FlowKind.GROWTH, to_account=self, source="market", agent=self.person)
        if self.reinvest:
            self._post_interest(distribution)
            self.balance += distribution
            self.cost_basis += distribution
        else:
            destination = self.person.cash_destination
            self._post_interest(distribution, to_account=destination)
            self.person.receive_cash(distribution, post=False)

    def mature(self) -> None:
        """Pay the holding out to the owner's bank at maturity (an I bond's deferred interest is taxed)."""
        amount = self.balance
        if self.kind in ("i_bond", "cd") and self.accrued_interest > 0:
            self.person.income.add(self.income_type, self.accrued_interest, source=f"{self.kind}_interest")
            self.accrued_interest = 0.0
        self.balance = 0.0
        self.matured = True
        if amount > 0:
            self.person.receive_cash(
                amount, kind=FlowKind.TRANSFER, from_account=self, cause=f"{self.name} matured", source=self.name
            )
            self.model.event_log.add(Event(f"{self.person.name}'s {self.name} matured: ${amount:,.0f} to the bank"))

    # --- redemption ---

    @property
    def redeemable(self) -> float:
        """What can be cashed now (an I bond is locked for its first 12 months)."""
        if self.matured:
            return 0.0
        if self.kind == "i_bond" and self.months_held < I_BOND_LOCK_MONTHS:
            return 0.0
        return self.balance

    def redeem(self, amount: float) -> float:
        """Cash up to ``amount`` of the holding's value early: posts the CD penalty (and its deduction),
        the I bond's forfeited interest and deferred interest, or the fund's realized gain. Returns the
        cash the owner receives (the caller moves and posts it as a transfer from this holding)."""
        take = min(amount, self.redeemable)
        if take <= 0:
            return 0.0
        fraction = take / self.balance if self.balance > 0 else 1.0
        self.balance -= take
        lost = 0.0
        if self.kind == "cd" and self.accrued_interest > 0:
            interest = self.accrued_interest * fraction
            self.accrued_interest -= interest
            self.person.income.add(self.income_type, interest, source="cd_interest")
        if self.kind == "cd" and not self.is_mature_now and self.early_withdrawal_penalty_months:
            lost = min(take, take * self.rate_pct / 12 / 100 * self.early_withdrawal_penalty_months)
            if lost > 0:
                self.person.income.add_deduction(lost, source="early_withdrawal_penalty")
        elif self.kind == "i_bond":
            interest = self.accrued_interest * fraction
            if self.months_held < I_BOND_PENALTY_YEARS * 12:
                lost = min(take, sum(self._recent_interest) * fraction)
            self.accrued_interest -= interest
            if interest - lost > 0:
                self.person.income.add(self.income_type, interest - lost, source="i_bond_interest")
        elif self.kind == "bond_fund":
            basis = self.cost_basis * fraction
            self.cost_basis -= basis
            gain = take - basis
            if gain != 0:
                long_term = self.months_held >= 12
                income_type = IncomeType.LONG_TERM_CAPITAL_GAIN if long_term else IncomeType.SHORT_TERM_CAPITAL_GAIN
                self.person.income.add(income_type, gain, source="bond_fund_sale")
        if lost > 0:
            self.model.ledger.post(
                lost,
                FlowKind.PENALTY,
                from_account=self,
                sink=f"{self.name}: early withdrawal",
                cause=f"{self.name} early withdrawal penalty",
                agent=self.person,
            )
        return take - lost

    def buy(self, amount: float) -> None:
        """Add ``amount`` to the holding (a sweep's purchase; the caller debits and posts the transfer)."""
        if amount <= 0:
            return
        if self.matured:
            self.matured = False
            self.purchased = (self.model.year, self.model.month)
        self.balance += amount
        self.cost_basis += amount

    def collect_stats(self):
        self.stat_fixed_income_balance = self.balance

    def _repr_html_(self):
        return f"{self.name} ({self.kind}) balance: ${self.balance:,.2f} at {self.rate_pct:g}%"
