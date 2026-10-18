# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The model's append-only cash-flow ledger and the household balance sheet it reconciles with.

Every movement of money the simulation makes is posted once, as a :class:`LedgerEntry` on
``model.ledger`` (a :class:`CashFlowLedger`), at the point where the economic event happens (a
paycheck, a sale, a bill, a tax payment), not at the account primitives (``deposit``/``withdraw``),
which are building blocks of those events.

**Endpoints.** An entry moves ``amount`` *from* one endpoint *to* another. An endpoint inside the
household balance sheet is an *account label* (``from_account`` / ``to_account``): an agent label
such as ``"BankAccount:12"`` (see :func:`account_label`), or a person's pseudo-accounts
``"Cash:<id>"`` (cash held with no bank account) and ``"Debt:<id>"`` (unpaid bills carried as
debt). An endpoint outside it is a free-text counterparty (``source`` / ``sink``: ``"Acme"``,
``"IRS"``, ``"market"``). So an entry is

* an **inflow** (external ``source`` → household account): raises net worth by ``amount``;
* an **outflow** (household account → external ``sink``): lowers net worth by ``amount``;
* a **transfer** (household account → household account): no effect on net worth.

For a liability account (a loan, ``Debt:<id>``), money *to* it pays it down and money *from* it is
new borrowing, so the same rules hold. Amounts are normally positive; a correction (a payroll
true-up after a pay cut) may be negative.

**Conservation.** Because external flows are posted where they happen and balances are measured
independently (:func:`household_balance_sheet`), the year's change in net worth must equal the
year's net external flow. :mod:`life_model.checks` asserts it; any difference is money the
simulation created or destroyed without saying so.

**Time.** Entries carry the ``year`` and ``month`` they were posted in and the ``stage`` that posted
them.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

    from .model import LifeModel


class FlowKind(str, Enum):
    """What a ledger entry is. The plan's list, plus ``borrow``, ``forfeit``, ``opening_balance`` and
    ``other``."""

    WAGE = "wage"  #: Salary paid by an employer.
    BONUS = "bonus"  #: Bonus paid by an employer.
    VEST = "vest"  #: Stock compensation vesting (to cash or a brokerage account).
    INTEREST = "interest"  #: Interest earned (bank accounts).
    DIVIDEND = "dividend"  #: Dividends paid into an account.
    GROWTH = "growth"  #: Market growth of an account or asset (negative in a down year).
    CONTRIBUTION = "contribution"  #: Money put into a savings account (from pay, the bank, or an employer).
    MATCH = "match"  #: Employer 401k match (negative when forfeited).
    WITHDRAWAL = "withdrawal"  #: Money taken out of a savings account into cash.
    RMD = "rmd"  #: A required minimum distribution.
    SALE = "sale"  #: A taxable sale (brokerage holdings, a home).
    TAX = "tax"  #: Income, payroll and estate taxes (negative for a refund).
    PENALTY = "penalty"  #: Additional taxes (early-withdrawal penalties).
    SPENDING = "spending"  #: Living expenses and one-time expenses.
    HOUSING = "housing"  #: Rent, mortgage payments, property tax, insurance, upkeep, purchase costs.
    DEBT_SERVICE = "debt_service"  #: Loan payments and the interest charged on debt.
    PREMIUM = "premium"  #: Insurance premiums (and whole-life cash value credited from them).
    BENEFIT = "benefit"  #: Social Security, pensions, insurance payouts, debt relief.
    TRANSFER = "transfer"  #: Money moved between household accounts.
    GIFT = "gift"  #: Charity, trust funding, and gifts received.
    INHERITANCE = "inheritance"  #: Assets passing at a death.
    BORROW = "borrow"  #: New debt: unpaid bills carried forward, policy loans.
    FORFEIT = "forfeit"  #: Value surrendered to a counterparty (unvested match, annuity reserve at death).
    OPENING_BALANCE = "opening_balance"  #: An account or asset that enters the simulation mid-run.
    OTHER = "other"  #: Unclassified external flows (e.g. ``receive_cash`` from user code).


#: One-line meaning of every :class:`FlowKind` (rendered into docs/outputs.md).
FLOW_KIND_DOCS: dict[str, str] = {
    "wage": "Salary paid by an employer.",
    "bonus": "Bonus paid by an employer.",
    "vest": "Stock compensation vesting (to cash or a brokerage account).",
    "interest": "Interest earned (bank accounts).",
    "dividend": "Dividends paid into an account.",
    "growth": "Market growth of an account or asset (negative in a down year).",
    "contribution": "Money put into a savings account (from pay, the bank, or an employer).",
    "match": "Employer 401k match (negative when forfeited).",
    "withdrawal": "Money taken out of a savings account into cash.",
    "rmd": "A required minimum distribution.",
    "sale": "A taxable sale (brokerage holdings, a home).",
    "tax": "Income, payroll and estate taxes (negative for a refund).",
    "penalty": "Additional taxes (early-withdrawal penalties).",
    "spending": "Living expenses and one-time expenses.",
    "housing": "Rent, mortgage payments, property tax, insurance, upkeep, purchase costs.",
    "debt_service": "Loan payments and the interest charged on debt.",
    "premium": "Insurance premiums (and whole-life cash value credited from them).",
    "benefit": "Social Security, pensions, insurance payouts, debt relief.",
    "transfer": "Money moved between household accounts.",
    "gift": "Charity, trust funding, and gifts received.",
    "inheritance": "Assets passing at a death.",
    "borrow": "New debt: unpaid bills carried forward, policy loans.",
    "forfeit": "Value surrendered to a counterparty (unvested match, annuity reserve at death).",
    "opening_balance": "An account or asset that enters the simulation mid-run.",
    "other": "Unclassified external flows (e.g. ``receive_cash`` from user code).",
}


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One posted movement of money (see the module docstring for the endpoint rules)."""

    #: Position in the ledger (0-based, strictly increasing).
    seq: int
    year: int
    #: Month within the year (1-12) the entry was posted in.
    month: int | None
    #: The model stage that posted it (``pre_step``, ``events``, ``step``, ``post_step``), or None.
    stage: str | None
    #: A :class:`FlowKind` value.
    kind: str
    amount: float
    #: Household account the money left (None when it came from outside: see ``source``).
    from_account: str | None
    #: Household account the money went to (None when it left the household: see ``sink``).
    to_account: str | None
    #: External counterparty the money came from (inflows).
    source: str | None
    #: External counterparty the money went to (outflows).
    sink: str | None
    #: Why it happened, in words (``"fund 2031 bills + taxes"``, ``"estate of Bob"``).
    cause: str | None
    #: The person the flow belongs to (agent ``unique_id``), when there is one.
    agent_id: int | None

    @property
    def is_inflow(self) -> bool:
        return self.from_account is None and self.to_account is not None

    @property
    def is_outflow(self) -> bool:
        return self.from_account is not None and self.to_account is None

    @property
    def is_transfer(self) -> bool:
        return self.from_account is not None and self.to_account is not None

    @property
    def net_worth_effect(self) -> float:
        """How much this entry changes household net worth (0 for a transfer)."""
        if self.is_inflow:
            return self.amount
        if self.is_outflow:
            return -self.amount
        return 0.0


#: Column order of :meth:`CashFlowLedger.to_frame`.
LEDGER_COLUMNS = (
    "seq",
    "year",
    "month",
    "stage",
    "kind",
    "amount",
    "from_account",
    "to_account",
    "source",
    "sink",
    "cause",
    "agent_id",
    "from_name",
    "to_name",
)


def account_label(account: Any) -> str | None:
    """The ledger label of a household account: an agent becomes ``"<Class>:<unique_id>"``; a
    string is already a label; None stays None."""
    if account is None or isinstance(account, str):
        return account
    return f"{type(account).__name__}:{account.unique_id}"


def cash_label(person: Any) -> str:
    """Label of the cash a person holds outside any bank account (``person.cash``)."""
    return f"Cash:{person.unique_id}"


def debt_label(person: Any) -> str:
    """Label of a person's unpaid-bills debt (``person.debt``), a liability."""
    return f"Debt:{person.unique_id}"


def describe_account(account: Any) -> str:
    """A readable name for an account agent: ``"John's BankAccount (Chase)"``."""
    owner = getattr(account, "person", None) or getattr(account, "owner", None) or getattr(account, "grantor", None)
    owner_name = getattr(owner, "name", None)
    detail = (
        getattr(account, "company", None)
        or getattr(account, "name", None)
        or getattr(account, "fund_name", None)
        or getattr(account, "card_name", None)
        or getattr(account, "school_name", None)
    )
    text = type(account).__name__
    if detail:
        text += f" ({detail})"
    return f"{owner_name}'s {text}" if owner_name else text


class CashFlowLedger:
    """Append-only record of every money movement in a model (``model.ledger``)."""

    def __init__(self, model: "LifeModel"):
        self.model = model
        self.entries: list[LedgerEntry] = []
        #: Readable names of the account labels seen (``label -> "John's BankAccount (Chase)"``).
        self.names: dict[str, str] = {}
        self._causes: list[str] = []
        self._suppress_opening = 0

    # ------------------------------------------------------------------
    # Posting
    # ------------------------------------------------------------------

    def _label(self, account: Any) -> str | None:
        label = account_label(account)
        if label is not None and label not in self.names and not isinstance(account, str):
            self.names[label] = describe_account(account)
        return label

    def name_label(self, label: str, name: str) -> None:
        """Give a pseudo-account label (``Cash:``/``Debt:``) a readable name."""
        self.names.setdefault(label, name)

    def post(
        self,
        amount: float,
        kind: "FlowKind | str",
        *,
        from_account: Any = None,
        to_account: Any = None,
        source: str | None = None,
        sink: str | None = None,
        cause: str | None = None,
        agent: Any = None,
    ) -> LedgerEntry | None:
        """Append an entry. ``from_account``/``to_account`` take an account agent or label; leave the
        external side None and name the counterparty in ``source``/``sink``. Zero amounts are not
        recorded. Returns the entry (or None)."""
        if amount == 0:
            return None
        from_label = self._label(from_account)
        to_label = self._label(to_account)
        if from_label is None and to_label is None:
            raise ValueError("A ledger entry needs at least one household account (from_account or to_account)")
        if cause is None and self._causes:
            cause = self._causes[-1]
        agent_id = getattr(agent, "unique_id", agent)
        entry = LedgerEntry(
            seq=len(self.entries),
            year=self.model.year,
            month=getattr(self.model, "month", None),
            stage=getattr(self.model, "current_stage", None),
            kind=kind.value if isinstance(kind, FlowKind) else str(kind),
            amount=float(amount),
            from_account=from_label,
            to_account=to_label,
            source=None if from_label is not None else (source or "external"),
            sink=None if to_label is not None else (sink or "external"),
            cause=cause,
            agent_id=agent_id,
        )
        self.entries.append(entry)
        return entry

    @property
    def current_cause(self) -> str | None:
        """The innermost :meth:`caused_by` cause, if any."""
        return self._causes[-1] if self._causes else None

    def describe(self, label: str) -> str:
        """A readable name for ``label`` (looked up among the model's agents if never posted)."""
        if label in self.names:
            return self.names[label]
        for agent in self.model.agents:
            if account_label(agent) == label:
                return describe_account(agent)
        return label

    @contextmanager
    def caused_by(self, cause: str) -> Iterator[None]:
        """Entries posted inside the block without their own ``cause`` get this one."""
        self._causes.append(cause)
        try:
            yield
        finally:
            self._causes.pop()

    @contextmanager
    def moving_balances(self) -> Iterator[None]:
        """Accounts constructed inside the block are funded by money the caller moves (and posts)
        itself, so their opening balance is not posted as new money."""
        self._suppress_opening += 1
        try:
            yield
        finally:
            self._suppress_opening -= 1

    def post_opening(self, account: Any, value: float, *, liability: bool = False, cause: str | None = None) -> None:
        """Post the opening balance of an account, asset or liability created while the model is
        running (by a life event, say). Accounts set up before a run, or inside
        :meth:`moving_balances`, post nothing. A liability's opening balance is an outflow (a
        purchase financed by the new debt)."""
        if value == 0 or self._suppress_opening or getattr(self.model, "current_stage", None) is None:
            return
        owner = getattr(account, "person", None) or getattr(account, "owner", None) or getattr(account, "grantor", None)
        if liability:
            self.post(
                value,
                FlowKind.OPENING_BALANCE,
                from_account=account,
                sink="purchase financed by new debt",
                cause=cause or f"{describe_account(account)} opened",
                agent=owner,
            )
        else:
            self.post(
                value,
                FlowKind.OPENING_BALANCE,
                to_account=account,
                source="opening balance",
                cause=cause or f"{describe_account(account)} opened",
                agent=owner,
            )

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[LedgerEntry]:
        return iter(self.entries)

    def between(self, start: int, end: int | None = None) -> list[LedgerEntry]:
        """Entries with ``start <= seq < end``."""
        return self.entries[start:end]

    def for_year(self, year: int) -> list[LedgerEntry]:
        return [entry for entry in self.entries if entry.year == year]

    @staticmethod
    def net_flow(entries: "list[LedgerEntry]") -> float:
        """Net external flow (inflows minus outflows) of ``entries``."""
        return sum(entry.net_worth_effect for entry in entries)

    def to_records(self, start: int = 0, end: int | None = None) -> list[dict[str, Any]]:
        """Entries ``[start, end)`` as dicts (with the accounts' readable names)."""
        records = []
        for entry in self.entries[start:end]:
            record = asdict(entry)
            record["from_name"] = self.names.get(entry.from_account) if entry.from_account else None
            record["to_name"] = self.names.get(entry.to_account) if entry.to_account else None
            records.append(record)
        return records

    def to_frame(self) -> "pd.DataFrame":
        """The ledger as a tidy DataFrame, one row per entry (columns: :data:`LEDGER_COLUMNS`)."""
        import pandas as pd

        return pd.DataFrame(self.to_records(), columns=list(LEDGER_COLUMNS))


# ----------------------------------------------------------------------
# Balance sheet
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class BalanceSheet:
    """Household assets and liabilities at one moment.

    ``lines`` maps account labels to signed values (assets positive, liabilities negative);
    ``owners`` maps each label to its owner's ``unique_id``.
    """

    lines: dict[str, float]
    owners: dict[str, int]

    @property
    def net_worth(self) -> float:
        return sum(self.lines.values())

    @property
    def assets(self) -> float:
        return sum(value for value in self.lines.values() if value > 0)

    @property
    def liabilities(self) -> float:
        return -sum(value for value in self.lines.values() if value < 0)

    def owner_total(self, owner_id: int) -> float:
        return sum(value for label, value in self.lines.items() if self.owners.get(label) == owner_id)


def balance_sheet_lines(agent: Any) -> list[tuple[str, float, Any]]:
    """``(label, signed value, owner)`` for each household balance-sheet line ``agent`` carries.

    Included: bank, brokerage, 401k, IRAs, HSAs, 529 plans, inherited IRAs, annuities (accumulation
    balance plus annuitized reserve, while active), revocable trusts, homes (unsold), whole-life cash
    value net of policy loans (active policies), cash held outside banks; liabilities: mortgages,
    car/student loans, credit cards, unpaid-bills debt. Excluded: donor-advised funds and
    irrevocable trusts (no longer the household's), unvested stock, pensions and Social Security
    (income streams, not balances).
    """
    from .base_classes import FinancialAccount, Loan
    from .debt.credit_card import RevolvingDebt
    from .estate.trust import Trust, TrustType
    from .housing.home import Home
    from .insurance.annuity import Annuity
    from .insurance.life_insurance import LifeInsurance
    from .people.person import Person

    if isinstance(agent, Person):
        return [
            (cash_label(agent), agent.cash, agent),
            (debt_label(agent), -agent.debt, agent),
        ]
    if isinstance(agent, FinancialAccount):
        if not agent.IN_NET_WORTH:
            return []
        return [(account_label(agent), agent.balance, agent.person)]
    if isinstance(agent, (Loan, RevolvingDebt)):
        return [(account_label(agent), -agent.principal, agent.person)]
    if isinstance(agent, Home):
        return [(account_label(agent), 0.0 if agent.sold else agent.home_value, agent.person)]
    if isinstance(agent, Annuity):
        value = agent.balance + agent.annuitized_reserve if agent.is_active else 0.0
        return [(account_label(agent), value, agent.person)]
    if isinstance(agent, Trust):
        if agent.trust_type != TrustType.REVOCABLE:
            return []
        return [(account_label(agent), agent.balance, agent.grantor)]
    if isinstance(agent, LifeInsurance):
        value = agent.cash_value - agent.outstanding_loan_balance if agent.is_active else 0.0
        return [(account_label(agent), value, agent.person)]
    return []


def household_balance_sheet(model: "LifeModel") -> BalanceSheet:
    """Every living person's assets and liabilities (see :func:`balance_sheet_lines`).

    A line counts only while its owner is a living person still in the model, so whatever a
    decedent leaves behind un-inherited drops out (and must be posted as leaving).
    """
    from .people.person import Person

    living = {agent.unique_id for agent in model.agents if isinstance(agent, Person) and not agent.is_deceased}
    lines: dict[str, float] = {}
    owners: dict[str, int] = {}
    for agent in model.agents:
        for label, value, owner in balance_sheet_lines(agent):
            owner_id = getattr(owner, "unique_id", None)
            if owner_id not in living:
                continue
            lines[label] = lines.get(label, 0.0) + value
            owners[label] = owner_id
    return BalanceSheet(lines=lines, owners=owners)


def owned_lines(model: "LifeModel", owner: Any) -> list[tuple[str, float, Any]]:
    """The balance-sheet lines ``owner`` holds right now (alive or not)."""
    return [
        (label, value, agent)
        for agent in model.agents
        for label, value, line_owner in balance_sheet_lines(agent)
        if line_owner is owner and value != 0
    ]
