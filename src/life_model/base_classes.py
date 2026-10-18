# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, Optional

from .deprecated_names import deprecated_arguments
from .economy import annual_to_monthly
from .ledger import FlowKind
from .limits import federal_retirement_age
from .model import LifeModelAgent, snap_money

if TYPE_CHECKING:
    from .people.person import Person


class TaxTreatment(Enum):
    """How a tax-advantaged account's contributions and withdrawals are taxed."""

    PRETAX = "pretax"  # Traditional 401k/IRA: deduct on contribute, ordinary income on withdraw.
    ROTH = "roth"  # Roth 401k/IRA: no deduction; qualified withdrawals tax/penalty-free.
    HSA = "hsa"  # HSA: deduct on contribute; tax-free for medical, taxed + penalty otherwise.


class FinancialAccount(LifeModelAgent, ABC):
    """Abstract base class for all financial accounts with balances.

    Provides uniform balance storage, deposit/withdraw validation, and balance-history tracking so
    subclasses don't reimplement these. Subclasses with a *derived* balance (e.g. the 401k, whose
    balance is pretax + roth) override the ``balance`` property; the setter must either work or
    raise — it must never silently discard a write.

    ``beneficiary`` is an optional per-account designation: at the owner's death the account is
    routed to that (surviving) beneficiary instead of the residual estate — the way real
    retirement accounts and payable-on-death accounts pass by designation, not by will. A
    predeceased beneficiary falls back to the residual-estate path. Designation changes *who*
    receives the account, not the estate-tax base (see ``Person._transfer_estate``). Subclasses
    that don't expose the keyword can have ``account.beneficiary`` assigned directly.
    """

    #: Whether the balance is the household's (counted in net worth and the conservation check).
    #: False for a donor-advised fund, whose money has been given away.
    IN_NET_WORTH: ClassVar[bool] = True
    #: The model stat (``LifeModel.EXTRA_STATS`` name) that reports this account's year-end balance.
    BALANCE_STAT: ClassVar[str | None] = None

    def collect_stats(self):
        """Report the year-end balance in :attr:`BALANCE_STAT`, when the account type has one."""
        if self.BALANCE_STAT is not None:
            setattr(self, self.BALANCE_STAT, self.balance)

    def __init__(self, person: "Person", balance: float = 0, *, beneficiary: Optional["Person"] = None):
        super().__init__(person.model)
        self.person = person
        self._balance = float(balance)
        self.beneficiary = beneficiary
        self.stat_balance_history = []
        if self.IN_NET_WORTH:
            self.model.ledger.post_opening(self, self._balance)

    @property
    def owner(self) -> "Person":
        """The account's owner (the same person as ``person``)."""
        return self.person

    @owner.setter
    def owner(self, value: "Person") -> None:
        self.person = value

    @property
    def balance(self) -> float:
        """Current account balance."""
        return self._balance

    @balance.setter
    def balance(self, value: float) -> None:
        # Monthly flows add twelfths; drop the floating-point residue (see ``snap_money``).
        self._balance = snap_money(value)

    def get_balance(self) -> float:
        """Get current account balance"""
        return self.balance

    def deposit(self, amount: float) -> bool:
        """Deposit amount into account. Returns success status.

        Negative amounts raise ``ValueError``; zero is a no-op that succeeds.
        """
        if amount < 0:
            raise ValueError("Deposit amount cannot be negative")
        self.balance += amount
        return True

    def withdraw(self, amount: float) -> float:
        """Withdraw amount from account. Returns actual amount withdrawn.

        Non-positive amounts withdraw nothing; a request larger than the balance withdraws the
        whole balance.
        """
        if amount <= 0:
            return 0.0
        amount_withdrawn = min(self.balance, amount)
        self.balance -= amount_withdrawn
        return amount_withdrawn

    def record_balance_history(self) -> None:
        """Append the year-end balance to ``stat_balance_history`` (one entry per simulated year)."""
        self.stat_balance_history.append(self.balance)

    def on_year_end(self):
        """Track the year-end balance."""
        self.record_balance_history()


#: Deprecated loan argument names (Plan 27 D8) and their canonical replacements.
LOAN_RENAMES = {
    "person": "owner",
    "loan_amount": "original_amount",
    "yearly_interest_rate": "rate_pct",
    "length_years": "term_years",
    "principal": "current_balance",
    "monthly_payment": "payment_monthly",
}


class Loan(LifeModelAgent, ABC):
    """Abstract base class for amortizing loans.

    The ABC owns amortization: :meth:`make_payment` applies a single **monthly** payment (loans
    compound and amortize monthly) with all the clamps — interest is charged on the current
    principal, principal never goes negative, and extra principal that exceeds the balance simply
    pays the loan off. The tax unit services each loan once a month (:meth:`service_month`) with the
    month's bills; ``interest_paid_this_year`` accumulates the year's interest (reset at each year
    start) for the interest deductions and stats. :meth:`make_yearly_payment` (twelve payments at
    once) remains for direct callers. Concrete subclasses supply only rate/term/identification and
    register themselves; they do not re-implement payment math.

    Terms are in months (Plan 27 D7): ``term_months`` is canonical and ``term_years`` is sugar for
    ``term_months / 12`` (the ``length_years`` attribute). A loan already in progress is entered the way
    its statement shows it — an ``origination`` month (or ``payments_made``), the ``remaining_months``,
    the ``current_balance`` and the payment — and :func:`~life_model.debt.terms.resolve_loan_terms` fills in
    the rest and rejects inputs that contradict each other. ``extra_principal_monthly`` is paid with
    every scheduled payment. ``schedule="statement"`` trusts a current balance above the original schedule
    (a loan behind on its payments) and amortizes from it.
    """

    @deprecated_arguments(LOAN_RENAMES)
    def __init__(
        self,
        owner: "Person",
        *,
        original_amount: float | None = None,
        rate_pct: float | None = None,
        term_years: float | None = None,
        current_balance: float | None = None,
        payment_monthly: float | None = None,
        term_months: int | None = None,
        origination=None,
        payments_made: int | None = None,
        remaining_months: int | None = None,
        extra_principal_monthly: float = 0.0,
        schedule: str = "contract",
    ):
        super().__init__(owner.model)
        self.person = owner
        self._set_terms(
            schedule=schedule,
            as_of=(self.model.year, self.model.month),
            loan_amount=original_amount,
            yearly_interest_rate=rate_pct,
            length_years=term_years,
            principal=current_balance,
            monthly_payment=payment_monthly,
            term_months=term_months,
            origination=origination,
            payments_made=payments_made,
            remaining_months=remaining_months,
            extra_principal_monthly=extra_principal_monthly,
        )

        # Interest actually charged over the current year, captured as the year is amortized so the
        # itemized deduction / interest stats aren't understated by reading the post-payment principal.
        self.interest_paid_this_year = 0.0

        # Statistics tracking. The per-payment histories record one entry per *monthly* period; the
        # yearly histories record one aggregated entry per simulated year (convenient for plotting
        # against the yearly simulation timeline).
        self.stat_principal_payment_history = []
        self.stat_interest_payment_history = []
        self.stat_balance_history = []
        self.stat_yearly_principal_payment_history = []
        self.stat_yearly_interest_payment_history = []
        # A loan taken out mid-run financed something outside the balance sheet (a car, tuition).
        self.model.ledger.post_opening(self, self.principal, liability=True)

    #: How resolution errors name the arguments (the constructor's names).
    TERM_NAMES: ClassVar[dict[str, str]] = {"monthly_payment": "payment_monthly"}

    def _set_terms(
        self,
        *,
        as_of: tuple[int, int] | None,
        loan_amount: float | None,
        yearly_interest_rate: float | None,
        length_years: float | None,
        principal: float | None,
        monthly_payment: float | None,
        term_months: int | None,
        origination,
        payments_made: int | None,
        remaining_months: int | None,
        extra_principal_monthly: float = 0.0,
        schedule: str = "contract",
    ) -> None:
        """Resolve and store the loan's terms (see :func:`~life_model.debt.terms.resolve_loan_terms`;
        ``schedule="statement"`` trusts the statement's balance over the original schedule)."""
        from .debt.terms import resolve_loan_terms

        if yearly_interest_rate is None:
            raise TypeError(f"{type(self).__name__} needs an interest rate")
        if term_months is None and length_years is not None:
            term_months = round(length_years * 12)
        elif term_months is not None and length_years is not None and round(length_years * 12) != term_months:
            raise ValueError(f"length_years={length_years} and term_months={term_months} disagree")
        if extra_principal_monthly < 0:
            raise ValueError("extra_principal_monthly must not be negative")
        terms = resolve_loan_terms(
            rate_pct=yearly_interest_rate,
            as_of=as_of,
            original_amount=loan_amount,
            term_months=term_months,
            origination=origination,
            payments_made=payments_made,
            remaining_months=remaining_months,
            current_balance=principal,
            monthly_payment=monthly_payment,
            names=self.TERM_NAMES,
            schedule=schedule,
        )
        #: Which inputs define the schedule: ``"contract"`` (the original terms) or ``"statement"``.
        self.schedule = schedule
        self.loan_amount = terms.original_amount
        self.yearly_interest_rate = yearly_interest_rate
        self.term_months = terms.term_months
        self.principal = terms.current_balance
        self.monthly_payment = terms.monthly_payment
        #: Scheduled payments made so far (counts on with every payment in the run).
        self.payments_made = terms.payments_made
        #: Origination ``(year, month)`` when known (None: unknown).
        self.origination = terms.origination
        #: Extra principal paid with every scheduled payment (Plan 27 D7).
        self.extra_principal_monthly = float(extra_principal_monthly)

    @property
    def length_years(self) -> float:
        """The term in years (``term_months / 12``; an int for a whole number of years)."""
        years = self.term_months / 12
        return int(years) if years == int(years) else years

    @length_years.setter
    def length_years(self, value: float) -> None:
        self.term_months = round(value * 12)

    @property
    def remaining_months(self) -> int:
        """Scheduled payments left to maturity (a prepaid loan pays off sooner)."""
        return max(0, self.term_months - self.payments_made)

    def refinance(
        self,
        rate_pct: float,
        *,
        term_months: int | None = None,
        term_years: float | None = None,
        costs: float = 0.0,
        finance_costs: bool = False,
        cash_out: float = 0.0,
    ) -> float:
        """Refinance (Plan 27 D7): a new loan at ``rate_pct`` for the current balance (plus ``cash_out``,
        and ``costs`` when ``finance_costs``), amortized over the new term from this month.

        Closing ``costs`` not financed are paid now through the household waterfall; ``cash_out`` is
        paid to the owner. Returns the new principal.
        """
        from .ledger import FlowKind
        from .model import Event, EventKind

        if term_months is None:
            if term_years is None:
                raise ValueError("refinance needs term_months or term_years")
            term_months = round(term_years * 12)
        if costs < 0 or cash_out < 0:
            raise ValueError("refinance costs and cash_out must not be negative")
        name = getattr(self, "name", None) or type(self).__name__
        cause = f"refinance of {name}"
        ledger = self.model.ledger
        old_principal = self.principal
        if cash_out > 0:
            self._pay_cash_out(cash_out, cause)
        if costs > 0:
            if finance_costs:
                ledger.post(
                    costs,
                    FlowKind.DEBT_SERVICE,
                    from_account=self,
                    sink="refinance closing costs",
                    cause=cause,
                    agent=self.person,
                )
            else:
                from .people.tax_unit import TaxUnit

                unpaid = TaxUnit.for_member(self.person).pay_bills(
                    costs, kind=FlowKind.DEBT_SERVICE, sink="refinance closing costs", cause=cause
                )
                self.person.add_debt(unpaid, kind=FlowKind.DEBT_SERVICE, sink="refinance closing costs", cause=cause)
        new_principal = old_principal + cash_out + (costs if finance_costs else 0.0)
        self._on_refinance(old_principal, new_principal)
        self.principal = new_principal
        self.loan_amount = new_principal
        self.yearly_interest_rate = rate_pct
        self.term_months = int(term_months)
        self.payments_made = 0
        self.origination = (self.model.year, self.model.month)
        self.monthly_payment = self.calculate_monthly_payment()
        self.model.event_log.add(
            Event(
                EventKind.REFINANCED,
                person=self.person,
                amount=new_principal,
                account=self,
                cause=cause,
                message=f"{self.person.name} refinanced {name}: ${new_principal:,.0f} at {rate_pct:g}% for "
                f"{term_months} months (${self.monthly_payment:,.2f}/month)",
            )
        )
        return new_principal

    def _on_refinance(self, old_principal: float, new_principal: float) -> None:
        """Hook for subclasses (a mortgage keeps its grandfathered acquisition debt)."""

    def _pay_cash_out(self, amount: float, cause: str) -> None:
        """Pay a refinance's cash-out to the owner (borrowed from this loan)."""
        from .ledger import FlowKind

        self.person.receive_cash(amount, source=cause, kind=FlowKind.BORROW, from_account=self, cause=cause)

    @property
    def monthly_interest_rate(self) -> float:
        """Per-month interest rate as a fraction (e.g. 6% APR -> 0.005)."""
        return self.yearly_interest_rate / (100 * 12)

    def calculate_monthly_payment(self) -> float:
        """Fully-amortizing monthly payment using the standard loan formula.

        Guards the zero-interest case (avoids division by zero) and a zero-length term.
        """
        from .debt.terms import amortizing_payment

        return amortizing_payment(self.loan_amount, self.yearly_interest_rate, self.term_months)

    def get_interest_amount(self, period: str = "month") -> float:
        """Interest accrued on the current principal for one period.

        Args:
            period: ``"month"`` (default) for a single month's interest — the period the loan
                actually amortizes over — or ``"year"`` for a full year's simple interest.
        """
        annual = self.principal * (self.yearly_interest_rate / 100)
        if period == "year":
            return annual
        if period == "month":
            return annual / 12
        raise ValueError(f"Unknown period {period!r}; expected 'month' or 'year'")

    def make_payment(self, payment_amount: float, extra_to_principal: float = 0) -> float:
        """Apply a single monthly payment.

        Interest is charged on the current principal first; the remainder plus any
        ``extra_to_principal`` reduces the principal. The principal is clamped at zero (paying
        more than the balance simply pays the loan off), and if a payment doesn't cover the
        month's interest the shortfall is added to the principal (negative amortization).

        Returns:
            float: The total cash actually paid this month (interest + principal).
        """
        if payment_amount < 0:
            raise ValueError("Payment amount cannot be negative")
        if extra_to_principal < 0:
            raise ValueError("Extra principal payment cannot be negative")

        monthly_interest = self.get_interest_amount("month")
        actual_interest_payment = min(payment_amount, monthly_interest)
        available_for_principal = payment_amount - actual_interest_payment
        total_principal_payment = available_for_principal + extra_to_principal
        principal_payment = min(total_principal_payment, self.principal)

        unpaid_interest = monthly_interest - actual_interest_payment
        self.principal = max(0.0, self.principal - principal_payment + unpaid_interest)
        if self.principal < 0.005:
            # The last scheduled payment leaves only floating-point residue: the loan is paid off.
            principal_payment += self.principal
            self.principal = 0.0
        self.payments_made = getattr(self, "payments_made", 0) + 1

        self.stat_principal_payment_history.append(principal_payment)
        self.stat_interest_payment_history.append(actual_interest_payment)

        return actual_interest_payment + principal_payment

    def make_yearly_payment(self, monthly_payment: float | None = None, extra_to_principal: float = 0) -> float:
        """Amortize one simulated year as twelve monthly payments.

        ``extra_to_principal`` is applied once (in the first month). Payments stop early once the
        loan is paid off. ``interest_paid_this_year`` is updated to the interest charged across the
        year.

        Returns:
            float: Total cash paid across the year.
        """
        if monthly_payment is None:
            monthly_payment = self.monthly_payment
        total_paid = 0.0
        interest_this_year = 0.0
        principal_this_year = 0.0
        for month in range(12):
            if self.principal <= 0:
                break
            extra = extra_to_principal if month == 0 else 0.0
            total_paid += self.make_payment(monthly_payment, extra)
            interest_this_year += self.stat_interest_payment_history[-1]
            principal_this_year += self.stat_principal_payment_history[-1]
        self.interest_paid_this_year = interest_this_year
        self.stat_yearly_principal_payment_history.append(principal_this_year)
        self.stat_yearly_interest_payment_history.append(interest_this_year)
        return total_paid

    def service_year(self) -> float:
        """Service this loan for one simulated year at its scheduled payment (twelve payments)."""
        return self.make_yearly_payment(self.monthly_payment)

    def service_month(self) -> float:
        """Make this month's scheduled payment (none once the loan is paid off).

        Called by the tax unit with the month's bills. Returns the cash paid; the interest charged is
        added to ``interest_paid_this_year``.
        """
        if self.principal <= 0:
            return 0.0
        paid = self.make_payment(self.monthly_payment, self.extra_principal_monthly)
        self._record_month(self.stat_principal_payment_history[-1], self.stat_interest_payment_history[-1])
        return paid

    def _record_month(self, principal: float, interest: float) -> None:
        """Add a month's principal and interest to the year's running totals."""
        self.interest_paid_this_year += interest
        self._principal_paid_this_year = getattr(self, "_principal_paid_this_year", 0.0) + principal

    def on_year_start(self):
        # The year's interest accumulates from zero (the deduction and stats read it at year end).
        self.interest_paid_this_year = 0.0
        self._principal_paid_this_year = 0.0

    def on_year_end(self):
        """Track the year's payments and the year-end balance."""
        self.stat_yearly_principal_payment_history.append(getattr(self, "_principal_paid_this_year", 0.0))
        self.stat_yearly_interest_payment_history.append(self.interest_paid_this_year)
        self.stat_balance_history.append(self.principal)


class Investment(FinancialAccount, ABC):
    """Abstract base class for investment accounts with growth.

    Growth is applied **monthly** at the month's rate: the economy's monthly return for the
    account's asset class, or, with an explicit annual ``growth_rate`` (an APY), its monthly
    equivalent ``(1 + rate)^(1/12) - 1``. Twelve months at a constant rate therefore compound to
    exactly the annual rate, and every ``Investment`` subclass grows identically given the same
    rate. Money that arrives mid-year grows only from its month on. Subclasses that need a
    different growth model override :meth:`calculate_monthly_growth`.
    """

    # Apply growth before the month's bills are paid (0) so withdrawals see the grown balance.
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"step": -10}

    # Maps an account's asset class to the economy rate that drives its return.
    _ASSET_CLASS_RATES: ClassVar[dict[str, str]] = {
        "equity": "equity_return",
        "bond": "bond_return",
        "cash": "cash_yield",
    }

    def __init__(
        self,
        person: "Person",
        balance: float = 0,
        growth_rate: float | None = None,
        asset_class: str = "equity",
        *,
        beneficiary: Optional["Person"] = None,
        allocation: "dict[str, float] | None" = None,
        expense_ratio_pct: float = 0.0,
    ):
        super().__init__(person, balance, beneficiary=beneficiary)
        # An explicit growth_rate overrides the economy; None defers to the economy's
        # return for this account's asset class, re-read each year so path/stochastic economies flow
        # through to account growth.
        self._growth_rate_override = growth_rate
        if asset_class not in self._ASSET_CLASS_RATES:
            raise ValueError(f"Unknown asset_class {asset_class!r}; expected one of {list(self._ASSET_CLASS_RATES)}")
        self.asset_class = asset_class
        #: Target allocation as fractions by asset class (Plan 27 D5), or None (one ``asset_class``).
        self.allocation: dict[str, float] | None = None
        # The allocation's current (drifted) weights; reset to the target at each year end.
        self._weights: dict[str, float] = {}
        self.set_allocation(allocation)
        if expense_ratio_pct < 0:
            raise ValueError("expense_ratio_pct must be non-negative")
        #: Annual fund expense ratio (percent), netted out of the return a twelfth a month.
        self.expense_ratio_pct = float(expense_ratio_pct)
        self.stat_growth_history = []

    def set_allocation(self, allocation: "dict[str, float] | None") -> None:
        """Set the target asset allocation (percent by asset class, e.g. ``{"equity": 70, "bond": 30}``;
        must sum to 100). The account then grows at the blend of the economy's returns for those classes,
        drifting with them during the year and rebalanced to the target at each year end. None reverts to
        the single ``asset_class``."""
        if allocation is None:
            self.allocation = None
            self._weights = {}
            return
        unknown = set(allocation) - set(self._ASSET_CLASS_RATES)
        if unknown:
            raise ValueError(f"Unknown asset classes {sorted(unknown)}; expected {list(self._ASSET_CLASS_RATES)}")
        if any(value < 0 for value in allocation.values()):
            raise ValueError("allocation percentages must be non-negative")
        total = sum(allocation.values())
        if abs(total - 100.0) > 1e-6:
            raise ValueError(f"allocation must sum to 100 percent, got {total:g}")
        self.allocation = {name: value / 100 for name, value in allocation.items() if value > 0}
        self._weights = dict(self.allocation)

    @property
    def allocation_pct(self) -> "dict[str, float] | None":
        """The target allocation in percent (None without one)."""
        return None if self.allocation is None else {k: v * 100 for k, v in self.allocation.items()}

    @property
    def growth_rate(self) -> float:
        """Annual growth rate (percent): the explicit override if set, else the economy's return (the
        target allocation's blend), net of the expense ratio."""
        if self._growth_rate_override is not None:
            return self._growth_rate_override - self.expense_ratio_pct
        economy = self.model.economy
        if self.allocation is not None:
            gross = sum(
                w * economy.rate(self._ASSET_CLASS_RATES[c], self.model.year) for c, w in self.allocation.items()
            )
        else:
            gross = economy.rate(self._ASSET_CLASS_RATES[self.asset_class], self.model.year)
        return gross - self.expense_ratio_pct

    @growth_rate.setter
    def growth_rate(self, value: float | None) -> None:
        self._growth_rate_override = value

    @property
    def monthly_growth_rate(self) -> float:
        """This month's growth rate (percent): the monthly equivalent of the explicit annual override,
        else the economy's monthly return for the asset class (or the allocation's current blend), less a
        twelfth of the expense ratio."""
        fee = self.expense_ratio_pct / 12
        if self._growth_rate_override is not None:
            return annual_to_monthly(self._growth_rate_override) - fee
        economy = self.model.economy
        if self._weights:
            return sum(w * economy.monthly_rate(self._ASSET_CLASS_RATES[c]) for c, w in self._weights.items()) - fee
        return economy.monthly_rate(self._ASSET_CLASS_RATES[self.asset_class]) - fee

    def _drift_allocation(self) -> None:
        """Let the allocation's weights drift with this month's class returns (call once a month, after
        the growth is applied). A no-op without an allocation or with an explicit growth rate."""
        if not self._weights or self._growth_rate_override is not None:
            return
        economy = self.model.economy
        grown = {c: w * (1 + economy.monthly_rate(self._ASSET_CLASS_RATES[c]) / 100) for c, w in self._weights.items()}
        total = sum(grown.values())
        if total > 0:
            self._weights = {c: v / total for c, v in grown.items()}

    def rebalance(self) -> None:
        """Rebalance to the target allocation (done at each year end)."""
        if self.allocation is not None:
            self._weights = dict(self.allocation)

    def calculate_growth(self) -> float:
        """A year of growth on the current balance at the annual rate (``balance * rate``): an
        estimate for display; the engine grows the balance monthly (:meth:`calculate_monthly_growth`)."""
        return self.balance * (self.growth_rate / 100)

    def calculate_monthly_growth(self) -> float:
        """This month's growth on the current balance."""
        return self.balance * (self.monthly_growth_rate / 100)

    def apply_growth(self):
        """Apply this month's growth to the balance."""
        growth = self.calculate_monthly_growth()
        self.balance += growth
        self.stat_growth_history.append(growth)
        self._post_growth(growth)
        self._drift_allocation()
        return growth

    def _post_growth(self, growth: float) -> None:
        """Post a month's market growth of this account to the ledger."""
        if self.IN_NET_WORTH:
            self.model.ledger.post(growth, FlowKind.GROWTH, to_account=self, source="market", agent=self.person)

    def step(self):
        """Apply the month's growth."""
        self.apply_growth()

    def on_year_end(self):
        """Track the year-end balance and rebalance to the target allocation."""
        super().on_year_end()
        self.rebalance()


class TaxAdvantagedAccount(Investment, ABC):
    """Base class for tax-advantaged accounts (IRAs, HSA).

    Adds a year-indexed contribution limit hook, year-to-date contribution tracking (reset in
    post_step), contribution-vs-earnings basis tracking (for Roth withdrawal ordering and HSA/529
    penalty math), a :class:`TaxTreatment`, an early-withdrawal usability gate, and an RMD
    participation flag.
    """

    #: How this account is taxed. Subclasses set this.
    tax_treatment: TaxTreatment = TaxTreatment.ROTH
    #: Whether the account participates in required minimum distributions.
    is_rmd_eligible: bool = False
    #: Accounts of the same owner with the same non-None group share one annual contribution limit
    #: (e.g. "ira": Roth and Traditional IRAs share the single IRA limit).
    limit_group: ClassVar[str | None] = None

    def __init__(
        self,
        person: "Person",
        balance: float = 0,
        growth_rate: float | None = None,
        asset_class: str = "equity",
        *,
        beneficiary: Optional["Person"] = None,
        basis: float | None = None,
        allocation: "dict[str, float] | None" = None,
        expense_ratio_pct: float = 0.0,
    ):
        super().__init__(
            person,
            balance,
            growth_rate,
            asset_class,
            beneficiary=beneficiary,
            allocation=allocation,
            expense_ratio_pct=expense_ratio_pct,
        )
        # Contributions made this year (reset at year end).
        self.contributions_ytd = 0.0
        # Cumulative contribution basis still in the account. Without ``basis`` (Plan 27 D1: the
        # statement's contribution total) the opening balance is treated as basis rather than earnings;
        # growth accrues to earnings, not basis.
        if basis is not None and not 0 <= basis <= balance + 1e-9:
            raise ValueError(f"basis {basis:,.2f} must be between 0 and the balance {balance:,.2f}")
        self.contribution_basis = float(balance) if basis is None else float(basis)

    @abstractmethod
    def annual_contribution_limit(self) -> float:
        """The contribution limit for the owner this year (year- and age-indexed)."""

    def remaining_contribution_room(self) -> float:
        """Contribution room left this year (net of any contributions to sibling accounts that
        share the same limit, e.g. Roth + Traditional IRA)."""
        used = self.contributions_ytd + self.sibling_contributions_ytd()
        return max(0.0, self.annual_contribution_limit() - used)

    def sibling_contributions_ytd(self) -> float:
        """Contributions made this year to the owner's other accounts in the same ``limit_group``.

        Zero when the account's limit is not shared (``limit_group`` is None).
        """
        if self.limit_group is None:
            return 0.0
        return sum(
            account.contributions_ytd
            for account in self.person.all_tax_advantaged_accounts
            if account is not self and account.limit_group == self.limit_group
        )

    def contribute(
        self, amount: float, *, from_account=None, source: str = "contribution from outside the model"
    ) -> float:
        """Contribute up to the remaining annual limit. Returns the amount actually contributed.

        The money comes from ``from_account`` (a household account label or agent, already debited
        by the caller) when given; otherwise it is posted as new money from ``source``.
        """
        if amount <= 0:
            return 0.0
        actual = min(amount, self.remaining_contribution_room())
        if actual > 0:
            self.balance += actual
            self.contributions_ytd += actual
            self.contribution_basis += actual
            self.model.ledger.post(
                actual,
                FlowKind.CONTRIBUTION,
                from_account=from_account,
                to_account=self,
                source=None if from_account is not None else source,
                agent=self.person,
            )
        return actual

    @property
    def earnings(self) -> float:
        """Portion of the balance that is investment earnings (balance minus basis)."""
        return max(0.0, self.balance - self.contribution_basis)

    def withdraw(self, amount: float) -> float:
        """Withdraw, drawing down contribution basis before earnings (Roth ordering)."""
        withdrawn = super().withdraw(amount)
        self.contribution_basis -= min(self.contribution_basis, withdrawn)
        return withdrawn

    def reset_annual_contributions(self):
        """Reset annual contribution tracking (called at year end)."""
        self.contributions_ytd = 0.0

    @property
    def is_useable(self) -> bool:
        """Whether funds can be withdrawn without an early-withdrawal penalty (exact age >= 59.5)."""
        return self.person.age_years_fractional >= federal_retirement_age(self.model.config)

    def on_year_end(self):
        """Track the year-end balance and reset the annual contribution counter."""
        super().on_year_end()
        self.reset_annual_contributions()


class RetirementAccount(Investment, ABC):
    """Abstract base class for retirement accounts (401k)."""

    STATS_OWNED = frozenset({"stat_useable_balance"})

    def __init__(
        self,
        person: "Person",
        balance: float = 0,
        growth_rate: float | None = None,
        asset_class: str = "equity",
        *,
        beneficiary: Optional["Person"] = None,
        allocation: "dict[str, float] | None" = None,
        expense_ratio_pct: float = 0.0,
    ):
        super().__init__(
            person,
            balance,
            growth_rate,
            asset_class,
            beneficiary=beneficiary,
            allocation=allocation,
            expense_ratio_pct=expense_ratio_pct,
        )
        self.stat_useable_balance = 0

    @property
    def is_useable(self) -> bool:
        """Whether funds can be withdrawn without penalty (exact age >= 59.5)."""
        return self.person.age_years_fractional >= federal_retirement_age(self.model.config)

    def collect_stats(self):
        """Year-end useable balance (re-read every year, so it never goes stale)."""
        super().collect_stats()
        self.stat_useable_balance = self.balance if self.is_useable else 0


class Benefit(LifeModelAgent, ABC):
    """Abstract base class for benefits that provide periodic payments"""

    def __init__(self, person: "Person", company: str):
        super().__init__(person.model)
        self.person = person
        self.company = company

    @abstractmethod
    def get_annual_benefit(self) -> float:
        """Calculate annual benefit amount"""

    @abstractmethod
    def is_eligible(self) -> bool:
        """Check if person is eligible to receive benefits"""
