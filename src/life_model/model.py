# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from collections.abc import Callable
from datetime import datetime
from enum import Enum
from math import e as const_e
from typing import TYPE_CHECKING, ClassVar

import mesa
import pandas as pd
from pandas.io.formats.style import Styler

from .config.financial_config import FinancialConfig
from .ledger import LEDGER_COLUMNS, CashFlowLedger
from .registry import ModelRegistries

if TYPE_CHECKING:
    from .results import RunResult


def compound_interest(principal: float, rate: float, num_times_applied: int = 1, elapsed_time_periods: int = 1):
    return principal * pow(1 + ((rate / 100) / num_times_applied), num_times_applied * elapsed_time_periods) - principal


def continous_interest(principal: float, rate: float, elapsed_time_periods: int = 1):
    return principal * pow(const_e, (rate / 100) * elapsed_time_periods) - principal


FMT_MONEY = "${:,.0f}"


def round_money(amount: float) -> float:
    """Round a monetary amount to whole cents to avoid float residue accumulating in balances."""
    return round(amount, 2)


def snap_money(amount: float) -> float:
    """``amount`` with floating-point residue removed: a value within a millionth of a cent of a whole
    cent becomes that cent (``99999.99999999999`` -> ``100000.0``); any other value is returned
    unchanged. Twelve monthly twelfths of a salary then add back to the salary."""
    cents = round(amount, 2)
    return cents if abs(amount - cents) < 1e-8 else amount


def parse_year_month(text: str) -> tuple[int, int]:
    """``"YYYY-MM"`` (or ``"YYYY-MM-DD"``, whose day is ignored: events fire in their month) as
    ``(year, month)``."""
    parts = str(text).split("-")
    try:
        year, month = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        raise ValueError(f"Expected a 'YYYY-MM' date, got {text!r}") from None
    if not 1 <= month <= 12:
        raise ValueError(f"Month must be 1-12 in {text!r}")
    return year, month


def month_index(year: int, month: int) -> int:
    """An absolute month number (``year * 12 + month - 1``): differences are months apart."""
    return year * 12 + month - 1


class Stat:
    def __init__(
        self,
        name: str,
        title: str | None = None,
        fmt: str | None = None,
        aggregator: Callable | None = None,
        *,
        description: str = "",
        default=0,
        flow: bool = False,
    ):
        """Stat

        Args:
            name (str): Name of stat.
            title (str, optional): Title of stat.
            fmt (str, optional): Format string for printing.
            aggregator (Callable, optional): Function to aggregate stat values. Default is sum().
            description (str, optional): What the stat measures (rendered into docs/outputs.md).
            default (optional): Model-level value when no agent owns the stat (an aggregator such as
                ``max`` has no value for an empty sequence).
            flow (bool, optional): A flow over the year (income, taxes, spending) rather than a balance
                read at year end. Flow stats accumulate month by month and are reset to 0 after each
                year's row is collected (keyword-only).
        """
        self.name = name
        self.title = title or name
        self.fmt = fmt
        self.aggregator = aggregator or sum
        self.description = description
        self.default = default
        self.flow = flow

    def model_reporter(self, model: "LifeModel"):
        """Aggregate the stat over the agents whose class declares it in ``STATS_OWNED``.

        Only owners are counted, so a stat can never be double counted by an agent type that
        merely inherited a zero, and a write to an undeclared agent cannot leak into the total. A flow
        stat also counts what agents removed earlier in the year (a decedent, a closed account)
        accumulated before they left.
        """
        values = [getattr(agent, self.name) for agent in model.agents if self.name in agent.STATS_OWNED]
        departed = getattr(model, "_departed_flows", {}).get(self.name) if self.flow else None
        if departed:
            values.append(departed)
        if not values:
            return self.default
        return self.aggregator(values)


class MoneyStat(Stat):
    def __init__(self, name: str, title: str | None = None, description: str = "", *, flow: bool = False):
        super().__init__(name, title, FMT_MONEY, description=description, flow=flow)


class EventKind(str, Enum):
    """What an :class:`Event` records. Detail kinds (:attr:`is_detail`) are the year-by-year mechanics
    (every RMD, forced sale, solver withdrawal, penalty and shortfall); they are kept on the log and in
    ``RunResult.events``/``explain`` but left out of the event log's notebook table, which shows the
    life story."""

    NOTE = "note"  #: Free-text event (what ``Event(message)`` creates).
    LIFE_EVENT_FIRED = "life_event_fired"
    RETIRED = "retired"
    RETIREMENT_AGE = "retirement_age"
    MARRIED = "married"
    DIED = "died"
    HOME_BOUGHT = "home_bought"
    HOME_SOLD = "home_sold"
    POLICY_LAPSED = "policy_lapsed"
    ANNUITIZED = "annuitized"
    INHERITANCE = "inheritance"
    FORCED_SALE = "forced_sale"
    PRETAX_WITHDRAWAL = "pretax_withdrawal"
    WITHDRAWAL = "withdrawal"
    RMD = "rmd"
    PENALTY = "penalty"
    SHORTFALL_DEBT = "shortfall_debt"

    @property
    def is_detail(self) -> bool:
        return self in _DETAIL_KINDS


#: One-line meaning of every :class:`EventKind` (rendered into docs/outputs.md).
EVENT_KIND_DOCS: dict[str, str] = {
    "note": "Free-text event (what Event(message) creates); most legacy messages.",
    "life_event_fired": "A scheduled LifeEvent fired (details: stage; the record also has name and scheduled_year).",
    "retired": "A job ended (retirement, a layoff, death).",
    "retirement_age": "A person reached the federal retirement age (59.5).",
    "married": "Two people married (details: spouse).",
    "died": "A person died.",
    "home_bought": "A home was bought (amount: price; cause: the purchase).",
    "home_sold": "A home was sold (amount: price; details: net_proceeds, taxable_gain).",
    "policy_lapsed": "A life insurance policy lapsed (cause: non-payment, or a loan above the cash value).",
    "annuitized": "An annuity converted to income payments (amount: reserve; details: monthly_payout).",
    "inheritance": "Assets passed at a death (estate, designated account, trust payout, inherited IRA done).",
    "forced_sale": "Detail: the payment waterfall sold brokerage holdings (amount, account, cause).",
    "pretax_withdrawal": "Detail: the waterfall withdrew pre-tax money (amount; details: target = the solver's size).",
    "withdrawal": "Detail: the waterfall drew Roth money.",
    "rmd": "Detail: a required minimum distribution (amount, account).",
    "penalty": "Detail: an additional tax settled with the year's return (amount; cause: its source).",
    "shortfall_debt": "Detail: bills the household could not pay, carried as debt (amount, cause).",
}

_DETAIL_KINDS = frozenset(
    {
        EventKind.FORCED_SALE,
        EventKind.PRETAX_WITHDRAWAL,
        EventKind.WITHDRAWAL,
        EventKind.RMD,
        EventKind.PENALTY,
        EventKind.SHORTFALL_DEBT,
    }
)


class Event:
    def __init__(
        self,
        kind: "EventKind | str | None" = None,
        year: int | None = None,
        person=None,
        amount: float | None = None,
        account=None,
        cause: str | None = None,
        message: str | None = None,
        **details,
    ):
        """Event

        ``Event("free text")`` (a plain string first argument) is a :attr:`EventKind.NOTE` with that
        message, as events have always been. A typed event passes an :class:`EventKind` first, plus
        what it is about; its message is generated when not given.

        Args:
            kind (EventKind | str): The event's kind, or (legacy) its message.
            year (int, optional): Year; stamped by :meth:`EventLog.add` when None.
            person (Person | str, optional): Who it is about (stored as name and agent id).
            amount (float, optional): Dollar amount involved.
            account (agent | str, optional): Account involved (stored as its ledger label and name).
            cause (str, optional): Why it happened.
            message (str, optional): Display text (generated from the fields when None).
            **details: Extra kind-specific fields (e.g. ``target`` on a pre-tax withdrawal).
        """
        if isinstance(kind, EventKind):
            self.kind = kind
        elif kind is None:
            self.kind = EventKind.NOTE
        else:
            # Legacy: Event("free text").
            self.kind = EventKind.NOTE
            message = kind if message is None else message
        self.year = year
        self.person_name: str | None = getattr(person, "name", person)
        self.person_id: int | None = getattr(person, "unique_id", None)
        self.amount = amount
        from .ledger import account_label, describe_account

        self.account: str | None = account_label(account)
        self.account_name: str | None = (
            None if account is None else account if isinstance(account, str) else describe_account(account)
        )
        self.cause = cause
        self.details = details
        self.message = message if message is not None else self._auto_message()

    def _auto_message(self) -> str:
        who = self.person_name or "Someone"
        amount = f"${self.amount:,.0f}" if self.amount is not None else ""
        account = self.account_name or "an account"
        because = f" to {self.cause}" if self.cause else ""
        target = self.details.get("target")
        if self.kind == EventKind.FORCED_SALE:
            return f"{who} sold {amount} of {account}{because}"
        if self.kind == EventKind.PRETAX_WITHDRAWAL:
            sized = f" (solver target ${target:,.0f})" if target is not None else ""
            return f"{who} withdrew {amount} pre-tax from {account}{sized}{because}"
        if self.kind == EventKind.WITHDRAWAL:
            return f"{who} withdrew {amount} from {account}{because}"
        if self.kind == EventKind.RMD:
            return f"{who} took a {amount} required minimum distribution from {account}"
        if self.kind == EventKind.PENALTY:
            return f"{who} owes {amount} of additional tax ({self.cause})"
        if self.kind == EventKind.SHORTFALL_DEBT:
            return f"{who} carried {amount} of unpaid bills as debt ({self.cause})"
        parts = [self.kind.value.replace("_", " "), who]
        if amount:
            parts.append(amount)
        if self.cause:
            parts.append(f"({self.cause})")
        return " ".join(parts)

    @property
    def is_detail(self) -> bool:
        """Whether this is a detail event (hidden from :meth:`EventLog._repr_html_`)."""
        return self.kind.is_detail

    def to_dict(self) -> dict:
        """The event as a flat dict (``details`` are serialized as a JSON string)."""
        import json

        return {
            "year": self.year,
            "kind": self.kind.value,
            "person": self.person_name,
            "person_id": self.person_id,
            "amount": self.amount,
            "account": self.account,
            "account_name": self.account_name,
            "cause": self.cause,
            "message": self.message,
            "details": json.dumps(self.details, default=str) if self.details else None,
        }

    def _repr_html_(self):
        return f"<tr><td>{self.year}</td><td>{self.message}</td></tr>\n"


#: Columns of :meth:`EventLog.to_frame` (and ``RunResult.events``).
EVENT_COLUMNS = (
    "year",
    "kind",
    "person",
    "person_id",
    "amount",
    "account",
    "account_name",
    "cause",
    "message",
    "details",
)


class EventLog:
    def __init__(self, model: "LifeModel"):
        """Event Log

        Args:
            model (LifeModel): LifeModel.
        """
        self.model = model
        self.list = []

    def _repr_html_(self):
        # The life story: detail events (RMDs, forced sales, ...) are omitted, which keeps this table
        # exactly as it was before events were typed. Use :meth:`to_frame` for everything.
        table = "<table>"
        table += "<tr><th>Year:</th><th>Event:</th></tr>\n"
        table += "".join(x._repr_html_() for x in self.list if not x.is_detail)
        table += "</table>"
        return table

    def add(self, event: Event):
        if event.year is None or event.kind == EventKind.NOTE:
            # Stamped with the year it was logged (as always for free-text events).
            event.year = self.model.year
        self.list.append(event)

    def of_kind(self, *kinds: "EventKind | str") -> list[Event]:
        """The logged events of the given kinds."""
        wanted = {EventKind(k) for k in kinds}
        return [event for event in self.list if event.kind in wanted]

    def for_year(self, year: int) -> list[Event]:
        return [event for event in self.list if event.year == year]

    def to_frame(self) -> "pd.DataFrame":
        """Every logged event (detail kinds included), one row each (columns: :data:`EVENT_COLUMNS`)."""
        return pd.DataFrame([event.to_dict() for event in self.list], columns=list(EVENT_COLUMNS))


def _optional_attribute(name: str) -> Callable:
    """Agent reporter returning ``agent.<name>``, or None for agents without it.

    Agents carry only the stats they own (``STATS_OWNED``). Mesa's string attribute reporters
    return None for a missing attribute in 3.3 but raise from 3.5, so an explicit default keeps
    per-agent collection working across the supported versions.
    """

    def reporter(agent):
        return getattr(agent, name, None)

    return reporter


def _pre_post_attribute(name: str) -> Callable:
    """Agent reporter returning the value ``agent.<name>`` had before this year's ``post_step``
    escalators ran (see ``LifeModel.add_agent_stat(..., pre_post=True)``), else None."""

    def reporter(agent):
        values = getattr(agent, "pre_post_values", None)
        if values is not None and name in values:
            return values[name]
        return None

    return reporter


def agent_name(agent) -> str | None:
    """The agent's own name for the agent frame's ``Name`` column: a person's or child's name, a
    home's, a job's or account's company, a fund's or card's name; None when it has none."""
    for attr in ("name", "company", "fund_name", "card_name", "charity_name", "school_name"):
        value = getattr(agent, attr, None)
        if isinstance(value, str):
            return value
    return None


def agent_owner_name(agent) -> str | None:
    """The name of the person an agent belongs to (``Owner`` column); a person's own name."""
    for attr in ("person", "owner", "grantor"):
        owner = getattr(agent, attr, None)
        name = getattr(owner, "name", None)
        if isinstance(name, str):
            return name
    if type(agent).__name__ == "Person":
        return agent.name
    return None


class LifeModelDataCollector(mesa.DataCollector):
    """DataCollector with a public way to add an agent-level reporter after construction.

    Mesa exposes this only through the private ``_new_agent_reporter`` (the method its own
    constructor uses); keeping the call here confines the dependency to one place, covered by
    ``test_collect_data``.
    """

    def add_agent_reporter(self, name: str, reporter) -> None:
        """Collect ``reporter`` (an attribute name or a callable on the agent) as column ``name``."""
        self._new_agent_reporter(name, reporter)

    def collect(self, model):
        """Collect a row, numbering agent records by collection (1, 2, ...) rather than Mesa's
        ``model.time``, which counts months: the agent frame's ``Step`` is the n-th collected row."""
        self._collections = getattr(self, "_collections", 0) + 1
        super().collect(model)
        for records in (self._agent_records, self._agenttype_records):
            if model.time in records and model.time != self._collections:
                records[self._collections] = records.pop(model.time)

    def _record_agents(self, model):
        number = self._collections
        return ((number, *record[1:]) for record in super()._record_agents(model))


class LifeModel(mesa.Model):
    STATS: ClassVar[list[MoneyStat]] = [
        MoneyStat(
            "stat_gross_income", "Income", "Gross income made in the year (salary, bonus, RSU vests).", flow=True
        ),
        MoneyStat("stat_bank_balance", "Bank Balance", "Bank account balances after the year's bills are paid."),
        MoneyStat("stat_brokerage_balance", "Brokerage Balance", "Taxable brokerage balances at year end."),
        MoneyStat("stat_401k_balance", "401k Balance", "401k balances (pre-tax plus Roth) at year end."),
        MoneyStat(
            "stat_useable_balance", "Useable Balance", "Balances usable without penalty (banks, 401ks past 59.5)."
        ),
        MoneyStat("stat_debt", "Debt", "Unpaid-bills debt plus outstanding loan and mortgage balances."),
        MoneyStat(
            "stat_taxes_paid",
            "Taxes",
            "All taxes paid in the year: federal, state, payroll, NIIT, net of credits.",
            flow=True,
        ),
        MoneyStat(
            "stat_money_spent", "Spending", "Living expenses plus one-time expenses charged in the year.", flow=True
        ),
        MoneyStat(
            "stat_retirement_contrib",
            "401k Contrib",
            "Employee 401k deferrals (pre-tax and Roth) in the year.",
            flow=True,
        ),
        MoneyStat("stat_retirement_match", "401k Match", "Employer 401k match in the year.", flow=True),
        MoneyStat("stat_required_min_distrib", "RMDs", "Required minimum distributions taken in the year.", flow=True),
        MoneyStat(
            "stat_housing_costs", "Housing", "Mortgage payments, home expenses and rent paid in the year.", flow=True
        ),
        MoneyStat(
            "stat_interest_paid", "Interest Paid", "Interest charged on mortgages, loans and carried debt.", flow=True
        ),
        MoneyStat("stat_ss_income", "SS Income", "Social Security benefits received in the year.", flow=True),
        MoneyStat(
            "stat_charitable_donations",
            "Charity",
            "Charitable donations (direct and DAF grants) in the year.",
            flow=True,
        ),
    ]

    EXTRA_STATS: ClassVar[list[Stat]] = [
        MoneyStat("stat_taxes_paid_federal", "Federal Taxes", "Federal income tax, including penalties.", flow=True),
        MoneyStat("stat_taxes_paid_state", "State Taxes", "State income tax.", flow=True),
        MoneyStat("stat_taxes_paid_ss", "SS Taxes", "Social Security payroll tax.", flow=True),
        MoneyStat(
            "stat_taxes_paid_medicare", "Medicare Taxes", "Medicare payroll tax (incl. the additional tax).", flow=True
        ),
        MoneyStat("stat_premium_payments", "Life Ins Premiums", "Life insurance premiums paid in the year.", flow=True),
        MoneyStat("stat_cash_value", "Life Ins Cash Value", "Whole-life cash value."),
        MoneyStat("stat_death_benefit_paid", "Death Benefits", "Life insurance death benefits paid out.", flow=True),
        MoneyStat("stat_medical_costs", "Medical Costs", "Healthcare, Medicare and long-term-care costs.", flow=True),
        MoneyStat(
            "stat_dependent_costs", "Dependent Costs", "Child and dependent costs charged in the year.", flow=True
        ),
        MoneyStat("stat_pension_income", "Pension Income", "Defined-benefit pension income received.", flow=True),
        MoneyStat("stat_taxes_paid_niit", "NIIT", "Net investment income tax.", flow=True),
        MoneyStat("stat_capital_gains", "Capital Gains", "Net capital gains realized (after loss netting).", flow=True),
        MoneyStat("stat_stock_vested", "Stock Vested", "Value of stock compensation vesting in the year.", flow=True),
        MoneyStat("stat_stock_unvested", "Stock Unvested", "Value of unvested stock grants at year end."),
        MoneyStat(
            "stat_itemized_deductions",
            "Itemized Deductions",
            "Itemized deductions claimed (0 when standard was taken).",
            flow=True,
        ),
        MoneyStat("stat_tax_credits", "Credits", "Tax credits (child tax credit, ...) claimed.", flow=True),
        MoneyStat(
            "stat_tax_penalties",
            "Penalties",
            "Additional taxes (early-withdrawal penalties); part of Federal Taxes.",
            flow=True,
        ),
        MoneyStat(
            "stat_net_worth",
            "Net Worth",
            "Assets minus liabilities at year end (the household balance sheet the conservation check uses).",
        ),
        MoneyStat("stat_traditional_ira_balance", "Traditional IRA Balance", "Traditional IRA balances at year end."),
        MoneyStat("stat_roth_ira_balance", "Roth IRA Balance", "Roth IRA balances at year end."),
        MoneyStat("stat_hsa_balance", "HSA Balance", "Health savings account balances at year end."),
        MoneyStat("stat_529_balance", "529 Balance", "529 education plan balances at year end."),
        MoneyStat("stat_inherited_ira_balance", "Inherited IRA Balance", "Inherited (10-year rule) IRA balances."),
        MoneyStat("stat_annuity_balance", "Annuity Balance", "Annuity accumulation balances plus annuitized reserves."),
        MoneyStat("stat_daf_balance", "DAF Balance", "Donor-advised fund balances (not counted in net worth)."),
        MoneyStat("stat_trust_balance", "Trust Balance", "Trust balances (only revocable trusts count in net worth)."),
        MoneyStat("stat_home_value", "Home Value", "Market value of homes owned at year end."),
        MoneyStat("stat_home_equity", "Home Equity", "Home value minus the mortgage balance."),
        MoneyStat("stat_mortgage_principal", "Mortgage Principal", "Mortgage balances at year end."),
        MoneyStat("stat_agi", "AGI", "Adjusted gross income on the year's returns.", flow=True),
        MoneyStat("stat_taxable_income", "Taxable Income", "Taxable income on the year's returns.", flow=True),
        Stat(
            "stat_marginal_rate",
            "Marginal Rate",
            "{:.0f}%",
            max,
            description="Federal ordinary bracket rate (percent) of the last taxable dollar (max across returns).",
        ),
        Stat(
            "stat_standard_deduction_taken",
            "Standard Deduction Taken",
            None,
            max,
            description="Whether a return took the standard deduction (True if any did).",
            default=False,
        ),
        MoneyStat(
            "stat_forced_sales",
            "Forced Sales",
            "Brokerage holdings the payment waterfall sold to pay bills and taxes.",
            flow=True,
        ),
        MoneyStat(
            "stat_pretax_withdrawals",
            "Pre-tax Withdrawals",
            "401k/IRA/HSA money the payment waterfall withdrew to pay bills and taxes (RMDs excluded).",
            flow=True,
        ),
    ]

    #: The ordered stages one ``step()`` (one simulated **month**) runs over every agent:
    #:
    #: * ``pre_step``: the month starts — mortality, wages and benefits arrive, RMDs.
    #: * ``events``: scheduled life events fire (``LifeEvents`` is the only default participant),
    #:   after the month's income has arrived and before its bills are paid, so an event's expense,
    #:   purchase, marriage, state or salary change applies from *this* month.
    #: * ``step``: payroll true-up, account growth and interest, then the tax units pay the month's
    #:   bills through the household waterfall.
    #: * ``post_step``: end-of-month bookkeeping.
    #:
    #: Within a stage agents run by ``STEP_PRIORITY`` (ascending), then construction order. Every
    #: ``LifeModelAgent`` has a no-op method per stage, so a new stage only needs a default method on
    #: the base class.
    STAGES: ClassVar[tuple[str, ...]] = ("pre_step", "events", "step", "post_step")
    #: Stages run once per simulated year, before the first month's ``pre_step`` (January, or the
    #: start month of a part-year first year): per-year setup such as the year's RMD amount.
    YEAR_START_STAGES: ClassVar[tuple[str, ...]] = ("on_year_start",)
    #: Stages run once per simulated year, after December's ``post_step``: tax settlement,
    #: escalators, contribution-limit resets. Data is collected after them.
    YEAR_END_STAGES: ClassVar[tuple[str, ...]] = ("on_year_end",)

    def __init__(
        self,
        end_year: int | None = None,
        start_year: int | None = None,
        seed: int | None = None,
        config: FinancialConfig | None = None,
        scenario: str | None = None,
        *,
        collect_data: bool = True,
        start: str | None = None,
        start_month: int | None = None,
        collect: str = "year",
    ):
        """LifeModel Helper Class

        The model steps one calendar **month** at a time (``step()``); a simulated year is a reporting
        cadence (``step_year()``, data collected at each year end). ``end_year`` is the last
        simulated December.

        Args:
            end_year (int, optional): Last simulated year (its December is the last month). Defaults
                to ``start_year + 50``.
            start_year (int, optional): First simulated year. Defaults to the current year.
            seed (int, optional): Random seed. Defaults to None.
            config (FinancialConfig, optional): Per-model financial configuration.
                Defaults to a fresh copy of the packaged defaults so that separate
                models can run different scenarios in the same process.
            scenario (str, optional): Name of a packaged scenario to apply. Defaults to None.
            collect_data (bool, optional): When False, skip DataCollector construction and
                per-year collection entirely (``self.datacollector`` is ``None``). Simulation
                behavior is unchanged; only the yearly stat frames are unavailable, so the
                reporting helpers (``get_yearly_stat_df``, ``add_agent_stat``) cannot be used.
                Intended for high-throughput consumers (e.g. RL rollouts) that never read the
                collected frames. Defaults to True (keyword-only).
            start (str, optional): First simulated month as ``"YYYY-MM"`` (keyword-only); sets
                ``start_year`` and ``start_month``. A model started in October simulates three months
                of its first year.
            start_month (int, optional): First simulated month (1-12) of ``start_year``
                (keyword-only). Defaults to January.
            collect (str, optional): ``"year"`` (default) collects one row per simulated year;
                ``"month"`` also collects a row per month (see :meth:`monthly_frame`). Keyword-only.
        """
        # Mesa 3.5 deprecates ``seed=`` in favor of ``rng=``; both seed ``self.random`` identically.
        super().__init__(rng=seed)
        #: The seed this model was built with (None when unseeded; see ``RunResult.seed``).
        self.initial_seed = seed
        if start is not None:
            start_year_from, start_month_from = parse_year_month(start)
            if start_year is not None and start_year != start_year_from:
                raise ValueError(f"start={start!r} conflicts with start_year={start_year}")
            if start_month is not None and start_month != start_month_from:
                raise ValueError(f"start={start!r} conflicts with start_month={start_month}")
            start_year, start_month = start_year_from, start_month_from
        if start_year is None:
            start_year = datetime.now().astimezone().year
        if start_month is None:
            start_month = 1
        if not 1 <= int(start_month) <= 12:
            raise ValueError(f"start_month must be 1-12, got {start_month}")
        if collect not in ("year", "month"):
            raise ValueError(f"collect must be 'year' or 'month', got {collect!r}")

        # Resolve per-model financial configuration.
        if config is None:
            config = FinancialConfig(scenario=scenario)
        elif scenario is not None:
            from .config.scenarios import get_scenario

            config.apply_scenario(scenario, get_scenario(scenario))
        self.config = config
        self._year_configs: dict[tuple[int, int], FinancialConfig] = {}

        # Initialize registries
        self.registries = ModelRegistries()
        if end_year is None:
            end_year = start_year + 50
        self.start_year = start_year
        self.end_year = end_year
        #: First simulated month (1-12) of ``start_year``.
        self.start_month = int(start_month)
        #: The calendar year being (or about to be) simulated.
        self.year = start_year
        #: The calendar month (1-12) being (or about to be) simulated.
        self.month = self.start_month
        #: Months simulated so far (0-based index of the current month since the start).
        self.period = 0
        #: ``"year"`` or ``"month"`` (see the ``collect`` argument).
        self.collect = collect
        self.event_log = EventLog(self)
        #: Every settled return, keyed ``(year, unit_id)``; ``tax_returns[year]`` works when the year
        #: has one return (see :class:`~life_model.tax.return_record.TaxReturns`).
        from .tax.return_record import TaxReturns

        self.tax_returns = TaxReturns()
        #: Append-only record of every money movement (see :mod:`life_model.ledger`).
        self.ledger = CashFlowLedger(self)
        #: Balance sheets around each simulated year and the ledger range posted during it, keyed by
        #: year (recorded when collecting data; read by :mod:`life_model.checks`).
        self.balance_sheets: dict = {}
        #: The same around each simulated month, keyed ``(year, month)``.
        self.month_balance_sheets: dict = {}
        self.simulated_years = []
        self._stages = list(self.STAGES)
        self._year_opening = None
        self._year_ledger_start = 0
        #: Model-level rows collected each month when ``collect="month"`` (see :meth:`monthly_frame`).
        self._monthly_rows: list[dict] = []
        # This year's flow stats of agents removed during it (see LifeModelAgent.remove).
        self._departed_flows: dict[str, float] = {}
        # Attributes snapshotted before post_step (see add_agent_stat(..., pre_post=True)).
        self._pre_post_attrs: set[str] = {"base_salary", "base_spending"}
        self._closing_sheet = None
        #: The stage currently executing (one of ``STAGES``, ``YEAR_START_STAGES`` or
        #: ``YEAR_END_STAGES``), or None outside ``step()`` (model setup, between months). Agents
        #: record it at construction (``created_in_stage``).
        self.current_stage: str | None = None

        # The economy provides the year's rates (inflation, returns, wage growth) to every other
        # agent. It is created first and steps first so its rates are cached before any consumer
        # reads them.
        from .economy import EconomyModel

        self.economy = EconomyModel(self)
        self.datacollector: LifeModelDataCollector | None = None
        if collect_data:
            self.datacollector = LifeModelDataCollector(
                model_reporters={
                    "Year": "year",
                    **{x.title: lambda model, x=x: x.model_reporter(model) for x in self.STATS},
                    **{x.title: lambda model, x=x: x.model_reporter(model) for x in self.EXTRA_STATS},
                },
                agent_reporters={
                    "Name": agent_name,
                    "Type": lambda agent: type(agent).__name__,
                    "Owner": agent_owner_name,
                    **{x.title: _optional_attribute(x.name) for x in self.STATS},
                    **{x.title: _optional_attribute(x.name) for x in self.EXTRA_STATS},
                    # This year's salary and base spending, before the year-end escalators.
                    "Salary": _pre_post_attribute("base_salary"),
                    "Spending Base": _pre_post_attribute("base_spending"),
                },
                tables={"Ledger": list(LEDGER_COLUMNS)},
            )

    @classmethod
    def stat_names(cls) -> frozenset[str]:
        """Attribute names of every model-level stat (``STATS`` and ``EXTRA_STATS``)."""
        return frozenset(stat.name for stat in (*cls.STATS, *cls.EXTRA_STATS))

    @classmethod
    def get_stat_by_name(cls, stat_name: str) -> Stat | None:
        """Returns a stat by name.

        Args:
            stat_name (str): Name of stat.

        Returns:
            Optional[Stat]: Stat.
        """
        for stat in cls.STATS:
            if stat.name == stat_name:
                return stat
        for stat in cls.EXTRA_STATS:
            if stat.name == stat_name:
                return stat
        return None

    @classmethod
    def get_stat_by_title(cls, stat_title: str) -> Stat | None:
        """Returns a stat by title.

        Args:
            stat_title (str): Title of stat.

        Returns:
            Optional[Stat]: Stat.
        """
        for stat in cls.STATS:
            if stat.title == stat_title:
                return stat
        for stat in cls.EXTRA_STATS:
            if stat.title == stat_title:
                return stat
        return None

    # ------------------------------------------------------------------
    # Time
    # ------------------------------------------------------------------

    @property
    def is_year_end(self) -> bool:
        """Whether the current month is December (the year-end stages run after it)."""
        return self.month == 12

    @property
    def is_year_start(self) -> bool:
        """Whether the current month is the first simulated month of its year (January, or the
        start month of a part-year first year)."""
        return self.month == 1 or self.period == 0

    @property
    def month_index(self) -> int:
        """The current month as an absolute month number (see :func:`month_index`)."""
        return month_index(self.year, self.month)

    def months_in_year(self, year: int | None = None) -> int:
        """How many months of ``year`` (default: the current year) the model simulates: 12, or fewer
        for a part-year first year."""
        year = self.year if year is None else year
        if year == self.start_year:
            return 13 - self.start_month
        return 12

    @property
    def first_month_of_year(self) -> int:
        """The first simulated month of the current year (``start_month`` in the first year, else 1)."""
        return self.start_month if self.year == self.start_year else 1

    @property
    def is_finished(self) -> bool:
        """Whether every month through ``end_year``'s December has been simulated."""
        return self.year > self.end_year

    def step(self):
        """Execute one step of the model: one simulated **month**.

        Monthly sequence (see ``STAGES``, and LifeModelAgent.STEP_PRIORITY for ordering within a
        stage):

        * year start (first month of a year only): flow stats reset to 0, then every agent's
          ``on_year_start``
        * ``pre_step``: mortality, wages and benefits deposited, RMDs
        * ``events``: scheduled life events fire (before the month's bills are paid)
        * ``step``: payroll true-up, account growth and interest, then the month's bills
        * ``post_step``: end-of-month bookkeeping
        * year end (December only): every agent's ``on_year_end`` (tax settlement, escalators,
          resets), then every agent's ``collect_stats`` and data collection

        The DataCollector row for year Y is collected at Y's year end (while ``self.year`` still
        equals Y), so the row for year Y contains year-Y flows and end-of-year-Y balances.

        Once the final December has been simulated ``self.running`` is cleared and further calls are
        no-ops. This lets interactive drivers (SolaraViz's Play loop, which runs while
        ``self.running``) stop at ``end_year``.
        """
        # Don't step past the configured final year.
        if self.is_finished:
            self.running = False
            return

        track = self.datacollector is not None
        if self.is_year_start:
            if self.period > 0:
                self._reset_flow_stats()
            self.simulated_years.append(self.year)
            if track:
                from .ledger import household_balance_sheet

                self._year_opening = household_balance_sheet(self)
                self._year_ledger_start = len(self.ledger)
            self._run_stages(self.YEAR_START_STAGES)
        if track:
            from .ledger import household_balance_sheet

            month_opening = household_balance_sheet(self)
            month_ledger_start = len(self.ledger)

        year_end = self.is_year_end
        self._run_stages(self.STAGES, year_end=year_end)
        if year_end:
            self._run_stages(self.YEAR_END_STAGES)
            self._collect_year_end_stats()
        elif track and self.collect == "month":
            self._collect_month_end_stats()

        if track:
            from .checks import MonthBalances, YearBalances
            from .ledger import household_balance_sheet

            closing = self._closing_sheet if year_end else household_balance_sheet(self)
            self.month_balance_sheets[(self.year, self.month)] = MonthBalances(
                year=self.year,
                month=self.month,
                opening=month_opening,
                closing=closing,
                ledger_start=month_ledger_start,
                ledger_end=len(self.ledger),
            )
            if self.collect == "month":
                self._monthly_rows.append(self._monthly_row())
            if year_end:
                self.balance_sheets[self.year] = YearBalances(
                    year=self.year,
                    opening=self._year_opening,
                    closing=closing,
                    ledger_start=self._year_ledger_start,
                    ledger_end=len(self.ledger),
                )
                # Collect after the stages so row Year=Y holds year-Y flows and balances.
                for record in self.ledger.to_records(self._year_ledger_start):
                    self.datacollector.add_table_row("Ledger", record)
                self.datacollector.collect(self)

        self._advance_month()
        self.running = not self.is_finished

    def step_year(self):
        """Simulate through the next year end: the rest of the current year's months (12, or fewer
        for a part-year first year). A no-op (that clears ``running``) once the run is finished."""
        if self.is_finished:
            self.step()
            return
        year = self.year
        while not self.is_finished and self.year == year:
            self.step()

    def _advance_month(self) -> None:
        self.period += 1
        if self.month == 12:
            self.month = 1
            self.year += 1
        else:
            self.month += 1

    def _run_stages(self, stages, *, year_end: bool = False) -> None:
        """Run ``stages`` over every agent in priority order.

        The agent list is snapshotted per stage: an agent created during a stage first runs in the
        next stage, and an agent removed during a stage (a decedent's pension, say) does not run the
        rest of it. Agents whose class still keeps the annual engine's flows (``MONTHLY = False``)
        run the monthly stages only in December, i.e. once a year as they always did.
        """
        for stage in stages:
            self.current_stage = stage
            if stage == "post_step" and year_end:
                # Escalators run at year end; snapshot what they change so reporters can show the
                # year's value (e.g. this year's salary, not next year's).
                self._snapshot_pre_post()
            agents = self.agents
            monthly_stage = stage in self.STAGES
            for agent in sorted(agents, key=lambda a: a.STEP_PRIORITY.get(stage, 0)):
                if monthly_stage and not year_end and not agent.MONTHLY:
                    continue
                if agent in agents:
                    getattr(agent, stage)()
        self.current_stage = None

    def _collect_year_end_stats(self) -> None:
        """Run every agent's :meth:`LifeModelAgent.collect_stats` and set each person's net worth from
        the household balance sheet."""
        from .ledger import household_balance_sheet
        from .people.person import Person

        flows = self._flow_stat_names()
        for agent in list(self.agents):
            agent.collect_stats()
            for name in flows & agent.STATS_OWNED:
                value = getattr(agent, name)
                if isinstance(value, float):
                    setattr(agent, name, snap_money(value))
        sheet = household_balance_sheet(self)
        for agent in self.agents:
            if isinstance(agent, Person) and not agent.is_deceased:
                agent.stat_net_worth = sheet.owner_total(agent.unique_id)
        self._closing_sheet = sheet

    def _collect_month_end_stats(self) -> None:
        """Month-end balance stats for ``collect="month"`` (the year-end hook, mid-year)."""
        self._collect_year_end_stats()

    def _monthly_row(self) -> dict:
        row = {"Year": self.year, "Month": self.month}
        for stat in (*self.STATS, *self.EXTRA_STATS):
            row[stat.title] = stat.model_reporter(self)
        return row

    def monthly_frame(self) -> pd.DataFrame:
        """Model-level stats at each month end (``collect="month"`` only): ``Year`` and ``Month``
        columns, balances at the month end and flows year to date (they reset after each year end)."""
        if self.collect != "month":
            raise ModelSetupException("Monthly rows are collected only with LifeModel(collect='month')")
        return pd.DataFrame(self._monthly_rows)

    def _reset_flow_stats(self) -> None:
        """Start the new year's flow stats (income, spending, taxes, ...) at zero, before its first
        month runs (so after ``step_year()`` an agent's flow stats still hold the year just
        simulated). Balance stats are left as they are (they are re-read at each year end)."""
        flows = self._flow_stat_names()
        for agent in self.agents:
            for name in flows & agent.STATS_OWNED:
                setattr(agent, name, 0)
        self._departed_flows = {}

    @classmethod
    def _flow_stat_names(cls) -> frozenset[str]:
        return frozenset(stat.name for stat in (*cls.STATS, *cls.EXTRA_STATS) if stat.flow)

    def _snapshot_pre_post(self) -> None:
        """Copy the attributes registered with ``add_agent_stat(..., pre_post=True)`` (and the
        built-in ``Salary``/``Spending Base`` columns) before the year-end escalators run."""
        attrs = self._pre_post_attrs
        for agent in self.agents:
            values = {attr: getattr(agent, attr) for attr in attrs if hasattr(agent, attr)}
            if values:
                agent.pre_post_values = values

    def get_year_range(self) -> range:
        """Get the inclusive range of simulated years ``[start_year, end_year]``."""
        return range(self.start_year, self.end_year + 1)

    def tax_params_for_year(self, year: int):
        """Tax parameters for ``year``, inflation-projected past the published table.

        For years beyond the last published tax year, the dollar-denominated parameters are
        indexed by the economy's realized cumulative inflation from the last published year to
        ``year`` (so a 50-year simulation doesn't apply frozen present-day brackets in 2050).
        Years within the published table are returned unchanged.
        """
        return self.config.tax_year(year, inflation_factor=self._tax_projection_factor(year))

    def _tax_projection_factor(self, year: int) -> float:
        """Cumulative realized inflation from the last published tax year to ``year`` (1.0 if the
        year is published, earlier, or the config freezes unpublished years)."""
        published_years = self.config.model.tax_years
        last_published = max(published_years) if published_years else year
        if year <= last_published or self.config.model.tax_years_projection == "frozen":
            return 1.0
        factor = 1.0
        for y in range(last_published, year):
            factor *= 1 + self.economy.inflation(y) / 100
        return factor

    def config_for_year(self, year: int) -> FinancialConfig:
        """This model's config with ``year``'s tax parameters and contribution limits in effect.

        Built from :meth:`tax_params_for_year` (published values, else the projection rule) and
        cached per year. Tax and contribution-limit code reads this instead of the static config so
        a multi-decade run applies each year's brackets, deductions, wage base and limits.
        """
        # Keyed on the underlying validated model too: applying a scenario replaces it, which must
        # invalidate views built from the old values.
        key = (year, id(self.config.model))
        cached = self._year_configs.get(key)
        if cached is None:
            factor = self._tax_projection_factor(year)
            cached = self.config.year_view(self.config.tax_year(year, inflation_factor=factor), factor)
            self._year_configs[key] = cached
        return cached

    @property
    def year_config(self) -> FinancialConfig:
        """:meth:`config_for_year` for the current simulated year."""
        return self.config_for_year(self.year)

    def run(self, *, spec=None) -> "RunResult":
        """Run the simulation over every remaining month through ``end_year``'s December.

        The number of simulated years is ``end_year - start_year + 1`` (the first may be a part
        year; see ``start``).

        Returns:
            RunResult: the run's frames, tax returns, ledger, events and seed (see
            :mod:`life_model.results`). Callers that ignore it lose nothing: the frames are built
            from the model only when read. ``spec`` (keyword-only) is recorded on the result.
        """
        while not self.is_finished:
            self.step()
        self.running = False
        return self.result(spec=spec)

    def result(self, *, spec=None) -> "RunResult":
        """The :class:`~life_model.results.RunResult` of what has been simulated so far.

        ``spec`` defaults to the household spec the model was built from (``model.household.spec``,
        set by :func:`life_model.spec.build_model`), if any.
        """
        from .results import RunResult

        if spec is None:
            spec = getattr(getattr(self, "household", None), "spec", None)
        return RunResult.from_model(self, spec=spec)

    def validate(self) -> list:
        """Check the constructed household before running it.

        Runs the household validator (:func:`life_model.spec.validate.validate_model`): errors such
        as a person without a bank account, an unknown state code or a life event dated before
        ``start_year``, and warnings such as two unmarried adults in one family, 0% spending growth
        or a percent entered as a fraction.

        Returns:
            list[Finding]: The findings (empty when nothing is wrong).
        """
        from .spec.validate import validate_model

        return validate_model(self)

    def _require_datacollector(self) -> LifeModelDataCollector:
        """Return the DataCollector, or raise clearly when built with ``collect_data=False``."""
        if self.datacollector is None:
            raise ModelSetupException(
                "This LifeModel was created with collect_data=False, so no stats were collected. "
                "Construct the model with collect_data=True (the default) to use reporting helpers."
            )
        return self.datacollector

    def add_agent_stat(self, title: str, attr_name: str, *, pre_post: bool = False):
        """Add an agent stat to the model

        Args:
            title (str): Title of the stat
            attr_name (str): Name of the attribute
            pre_post (bool, optional): Report the value the attribute had *before* the year's
                ``post_step`` (where escalators such as salary raises run), i.e. this year's value
                rather than next year's. Keyword-only; defaults to False (the value at collection).
        """
        # Agents without the attribute report None for it.
        if pre_post:
            self._pre_post_attrs.add(attr_name)
            reporter = _pre_post_attribute(attr_name)
        else:
            reporter = _optional_attribute(attr_name)
        self._require_datacollector().add_agent_reporter(title, reporter)

    def get_yearly_stat_df(
        self,
        columns: list[str] | None = None,
        extra_columns: list[str] | None = None,
        aggregate: dict[str, Callable] | None = None,
        column_formats: dict[str, str] | None = None,
        real_dollars: bool = False,
        styled: bool = True,
    ) -> "Styler | pd.DataFrame":
        """Get a DataFrame of the yearly stats

        Args:
            columns (List[str], optional): Optional list of columns to include. Defaults to None.
            extra_columns (List[str], optional): Optional list of extra columns to include. Defaults to None.
            aggregate (Dict[str, Callable], optional): Dictionary of aggregators to use. Defaults to None.
            column_formats (Dict[str, str], optional): Dictionary of column formats to use. Defaults to None.
            real_dollars (bool, optional): When True, every money column is deflated by the economy's
                cumulative inflation so values are expressed in start-year dollars. Defaults to False
                (nominal dollars).
            styled (bool, optional): Return a formatted ``Styler`` (default) or, when False, the plain
                DataFrame.

        Returns:
            Styler | pd.DataFrame: The yearly stats. ``columns`` and ``extra_columns`` are not modified.
        """
        # Get the list of columns to use (a copy: the caller's list is never mutated)
        columns = ["Year"] + [x.title for x in self.STATS] if columns is None else list(columns)
        if extra_columns is not None:
            for i, column in enumerate(extra_columns):
                columns.insert(i + 1, column)
        # Get the list of stats to use (columns are the datacollector's title-keyed names)
        stats = []
        for column_name in columns:
            stat = self.get_stat_by_title(column_name)
            if stat is not None:
                stats.append(stat)
        # Create a dataframe from the data
        df = self._require_datacollector().get_model_vars_dataframe()
        # Only keep certain columns in the data frame
        df = df[columns]
        if real_dollars:
            df = self._to_real_dollars(df)
        if aggregate is not None:
            # Aggregate the data if desired
            aggregators = {"Year": "max", **aggregate, **{x.title: x.aggregator.__name__ for x in stats}}
            df = df.aggregate(aggregators).reset_index().transpose()
            df.columns = df.iloc[0]
            df = df.drop(df.index[0])
        if not styled:
            return df
        formats = {x.title: x.fmt for x in stats if x.fmt is not None}
        if column_formats is not None:
            formats.update(column_formats)
        return df.style.format(precision=0, na_rep="MISSING", formatter=formats).hide()

    def _to_real_dollars(self, df: pd.DataFrame) -> pd.DataFrame:
        """Deflate every money column of ``df`` into start-year dollars.

        Each row's money values are divided by the economy's cumulative inflation for that row's
        year (taken from the ``Year`` column when present, otherwise inferred from the simulated
        year range). Non-money columns (e.g. ``Year``) are left untouched.
        """
        df = df.copy()
        money_titles = {s.title for s in (self.STATS + self.EXTRA_STATS) if isinstance(s, MoneyStat)}
        if "Year" in df.columns:
            years = [int(y) for y in df["Year"].tolist()]
        else:
            years = list(self.get_year_range())[: len(df)]
        deflators = [self.economy.cumulative_inflation(y) for y in years]
        for col in df.columns:
            if col in money_titles:
                df[col] = [value / deflators[i] for i, value in enumerate(df[col].tolist())]
        return df

    def format_dataframe(self, df: pd.DataFrame, extra_formats: dict[str, str] | None = None) -> Styler:
        """Format a dataframe

        Args:
            df (pd.DataFrame): DataFrame to format
            extra_formats (Dict[str, str], optional): Dictionary of formats to use. Defaults to None.

        Returns:
            Styler: Formatted DataFrame
        """
        stats = [self.get_stat_by_title(str(x)) for x in df.columns]
        stats = [x for x in stats if x is not None]
        formats = {x.title: x.fmt for x in stats if x.fmt is not None}
        formats = {**formats, **extra_formats} if extra_formats is not None else formats
        return df.style.format(precision=0, na_rep="MISSING", formatter=formats).hide()

    def aggregate_dataframe(self, df: pd.DataFrame, aggregate: dict[str, Callable] | None = None) -> pd.DataFrame:
        """Aggregate a dataframe

        Args:
            df (pd.DataFrame): DataFrame to aggregate
            aggregate (Dict[str, Callable], optional): Dictionary of aggregators to use. Defaults to None.

        Returns:
            pd.DataFrame: Aggregated DataFrame
        """
        # Aggregate the data
        stats = [self.get_stat_by_title(str(x)) for x in df.columns]
        stats = [x for x in stats if x is not None]
        aggregators = {"Year": "max", **{x.title: x.aggregator.__name__ for x in stats}}
        df = df.aggregate(aggregators).reset_index().transpose()
        df.columns = df.iloc[0]
        return df.drop(df.index[0])


class LifeModelAgent(mesa.Agent):
    # Per-stage execution priority. Within a stage, agents run in ascending priority order
    # (lower runs first); ties preserve construction order. Priorities order the agents whose
    # effects depend on each other, so the yearly sequence does not depend on construction order
    # (see LifeModel.step docstring and the shuffled-construction test):
    #   pre_step:  economy (-100), Person ages/mortality (-20), pre_step life events (-15),
    #              RMDs (-10), income and benefits (0), stock vests (5), cash consumers such as
    #              premiums and donations (10)
    #   events:    LifeEvents (0)
    #   step:      payroll true-up (-30), account growth and bank interest (-10), settlement (0)
    #   post_step: post_step life events (10)
    #   on_year_end: tax settlement (0), escalators and resets (10)
    STEP_PRIORITY: ClassVar[dict[str, int]] = {}

    #: Whether this agent type runs its ``STAGES`` methods every month. ``False`` (transitional, the
    #: annual engine's flows) runs them only in December, once a year as before.
    MONTHLY: ClassVar[bool] = False

    #: Model-level stats (``LifeModel.STATS`` / ``EXTRA_STATS`` names) this agent type reports.
    #: Declared per class and merged down the inheritance chain by ``__init_subclass__``, so a
    #: subclass lists only the stats it adds. Owned stats start at 0; model reporters sum only
    #: over owners.
    STATS_OWNED: ClassVar[frozenset[str]] = frozenset()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        declared = frozenset(cls.__dict__.get("STATS_OWNED", frozenset()))
        unknown = declared - LifeModel.stat_names()
        if unknown:
            raise TypeError(f"{cls.__name__}.STATS_OWNED names unknown model stats: {sorted(unknown)}")
        inherited = frozenset().union(*(getattr(base, "STATS_OWNED", frozenset()) for base in cls.__bases__))
        cls.STATS_OWNED = inherited | declared

    def __init__(self, model: LifeModel):
        """LifeModelAgent

        Args:
            model (LifeModel): LifeModel.
        """
        super().__init__(model)  # unique_id is now automatically assigned

        #: The model period (``LifeModel.period``, months since the start) when this agent was built.
        self.created_period: int = getattr(model, "period", 0)
        #: The model year when this agent was constructed.
        self.created_year: int = model.year
        #: The stage running when this agent was constructed (e.g. ``"events"`` for an agent built
        #: by a life event), or None when it was built outside ``LifeModel.step`` (model setup, or
        #: between years). See :attr:`created_during_this_year`.
        self.created_in_stage: str | None = getattr(model, "current_stage", None)

        # Initialize the stats this agent type owns.
        for name in self.STATS_OWNED:
            setattr(self, name, 0)

    @property
    def created_during_this_year(self) -> bool:
        """True when this agent was built *during* the current simulated year (by a life event or
        another agent mid-year), as opposed to at setup or between years.

        Agents built in the ``pre_step`` or ``events`` stage are consumed in their creation year
        (settlement pays their bills, ``Job.step`` books a new job's payroll), so they escalate at
        that year end like setup agents do; this flag is for code that does need to tell a
        brand-new agent apart (e.g. a first partial period once the engine is monthly).
        """
        return self.created_in_stage is not None and self.created_year == self.model.year

    def pre_step(self):
        """Pre-step phase. Called for all agents before the events phase."""

    def events(self):
        """Events phase. Called for all agents after pre-step and before step (see ``LifeModel.STAGES``)."""

    def step(self):
        """Step phase. Called for all agents after the events phase."""

    def post_step(self):
        """Post-step phase. Called for all agents after the step phase."""

    def remove(self):
        """Remove the agent from the model, keeping this year's flow stats (income, spending, taxes,
        ...) it accumulated in the year's model totals."""
        model = self.model
        departed = getattr(model, "_departed_flows", None)
        if departed is not None:
            for name in model._flow_stat_names() & self.STATS_OWNED:
                value = getattr(self, name, 0) or 0
                if value:
                    departed[name] = departed.get(name, 0.0) + value
        super().remove()

    def on_year_start(self):
        """Year-start phase: once per simulated year, before the first month's ``pre_step``."""

    def on_year_end(self):
        """Year-end phase: once per simulated year, after December's ``post_step`` (tax settlement,
        escalators, annual resets)."""

    def collect_stats(self):
        """Year-end hook: record end-of-year balance stats. Called for every agent after the
        year-end stages and before data collection (and at each month end with ``collect="month"``)."""


class ModelSetupException(Exception):
    """Exception raised when there is an error setting up the model."""
