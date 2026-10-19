# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""What a run produced, in one object: :class:`RunResult` (returned by ``LifeModel.run()``).

A result bundles the yearly model frame, the per-agent frame (with ``Year``, ``Name``, ``Type`` and
``Owner`` columns), every tax return, the cash-flow ledger, every typed event, the per-year and
per-month balance-sheet summaries, the monthly model frame (``LifeModel(collect="month")``), the
seed and (optionally) the household spec the model was built from. It
exports to JSON, CSV or Parquet, loads back, converts to real (start-year) dollars and explains a
year in prose.

Frames are built lazily from the model on first use, so ``run()`` stays cheap for callers that
ignore its return value.
"""

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from .ledger import LEDGER_COLUMNS
from .tax.return_record import TaxReturn, TaxReturns

if TYPE_CHECKING:
    from .checks import ConservationRecord
    from .model import LifeModel

#: Columns of :attr:`RunResult.balance_sheets`.
BALANCE_SHEET_COLUMNS = ("year", "opening_net_worth", "closing_net_worth", "inflows", "outflows")
#: Columns of :attr:`RunResult.monthly_balance_sheets`.
MONTHLY_BALANCE_SHEET_COLUMNS = ("year", "month", "opening_net_worth", "closing_net_worth", "inflows", "outflows")
#: Ledger kinds that are income (inflows shown under "Income" by :meth:`RunResult.explain`).
_INCOME_KINDS = (
    "wage",
    "bonus",
    "vest",
    "business_income",
    "interest",
    "dividend",
    "benefit",
    "match",
    "gift",
    "inheritance",
)


def _require_parquet() -> None:
    try:
        import pyarrow  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError(
            "Parquet export needs pyarrow, an optional dependency: pip install 'life-model[parquet]' "
            "(or pip install pyarrow). JSON and CSV exports need nothing extra."
        ) from exc


def _money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


class RunResult:
    """The outputs of one simulation run (see the module docstring).

    Attributes are DataFrames except :attr:`tax_returns` (``{(year, unit_id): TaxReturn}``) and the
    metadata (:attr:`seed`, :attr:`spec`, :attr:`deflators`, :attr:`real`).
    """

    def __init__(
        self,
        *,
        model_frame: pd.DataFrame | None = None,
        agent_frame: pd.DataFrame | None = None,
        tax_returns: "dict[tuple[int, int], TaxReturn] | None" = None,
        ledger: pd.DataFrame | None = None,
        events: pd.DataFrame | None = None,
        balance_sheets: pd.DataFrame | None = None,
        monthly_frame: pd.DataFrame | None = None,
        monthly_balance_sheets: pd.DataFrame | None = None,
        seed: int | None = None,
        spec: Any | None = None,
        deflators: dict[int, float] | None = None,
        money_columns: "tuple[str, ...] | list[str]" = (),
        real: bool = False,
    ):
        self._model: LifeModel | None = None
        self._model_frame = model_frame
        self._agent_frame = agent_frame
        self.tax_returns: TaxReturns = TaxReturns(tax_returns or {})
        self._ledger = ledger
        self._events = events
        self._balance_sheets = balance_sheets
        self._monthly_frame = monthly_frame
        self._monthly_balance_sheets = monthly_balance_sheets
        self.seed = seed
        #: The household spec the model was built from (a :class:`~life_model.spec.schema.HouseholdSpec`), when known.
        self.spec = spec
        #: Cumulative inflation factor per simulated year (start year = 1.0).
        self.deflators: dict[int, float] = dict(deflators or {})
        #: Titles of the money columns of the model and agent frames.
        self.money_columns: tuple[str, ...] = tuple(money_columns)
        #: True when money is in start-year dollars (see :meth:`real_dollars`).
        self.real = real

    @classmethod
    def from_model(cls, model: "LifeModel", *, spec: Any | None = None) -> "RunResult":
        """A result reading ``model`` (frames are built on first use)."""
        from .model import MoneyStat

        result = cls(
            tax_returns=model.tax_returns,
            seed=model.initial_seed if model.initial_seed is not None else getattr(model, "_seed", None),
            spec=spec,
            deflators={year: model.economy.cumulative_inflation(year) for year in model.simulated_years},
            money_columns=[s.title for s in (*model.STATS, *model.EXTRA_STATS) if isinstance(s, MoneyStat)],
        )
        result._model = model
        return result

    # ------------------------------------------------------------------
    # Frames (lazy from the model)
    # ------------------------------------------------------------------

    @property
    def model_frame(self) -> pd.DataFrame | None:
        """Yearly model-level stats (one row per year; ``None`` when the model did not collect data)."""
        if self._model_frame is None and self._model is not None and self._model.datacollector is not None:
            self._model_frame = self._model.datacollector.get_model_vars_dataframe().reset_index(drop=True)
        return self._model_frame

    @property
    def agent_frame(self) -> pd.DataFrame | None:
        """Per-agent stats, one row per agent per year, with ``Year``, ``Step`` and ``AgentID`` columns."""
        if self._agent_frame is None and self._model is not None and self._model.datacollector is not None:
            frame = self._model.datacollector.get_agent_vars_dataframe().reset_index()
            years = self.model_frame["Year"].tolist() if self.model_frame is not None else []
            frame.insert(0, "Year", [int(years[int(step) - 1]) for step in frame["Step"]])
            frame["Step"] = frame["Step"].astype(int)
            self._agent_frame = frame
        return self._agent_frame

    @property
    def ledger(self) -> pd.DataFrame:
        """The cash-flow ledger, one row per entry (see :mod:`life_model.ledger`)."""
        if self._ledger is None:
            if self._model is not None:
                self._ledger = self._model.ledger.to_frame()
            else:
                self._ledger = pd.DataFrame(columns=list(LEDGER_COLUMNS))
        return self._ledger

    @property
    def events(self) -> pd.DataFrame:
        """Every logged event (detail kinds included)."""
        if self._events is None:
            from .model import EVENT_COLUMNS

            if self._model is not None:
                self._events = self._model.event_log.to_frame()
            else:
                self._events = pd.DataFrame(columns=list(EVENT_COLUMNS))
        return self._events

    @property
    def balance_sheets(self) -> pd.DataFrame:
        """Per-year opening/closing net worth and ledger inflows/outflows (the conservation check's
        inputs)."""
        if self._balance_sheets is None:
            rows = []
            if self._model is not None:
                from .checks import conservation_records

                for record in conservation_records(self._model):
                    rows.append(
                        {
                            "year": record.year,
                            "opening_net_worth": record.opening_net_worth,
                            "closing_net_worth": record.closing_net_worth,
                            "inflows": record.inflows,
                            "outflows": record.outflows,
                        }
                    )
            self._balance_sheets = pd.DataFrame(rows, columns=list(BALANCE_SHEET_COLUMNS))
        return self._balance_sheets

    @property
    def monthly_frame(self) -> pd.DataFrame | None:
        """Model-level stats at each month end, with ``Year`` and ``Month`` columns (balances at the
        month end, flows year to date), when the model was built with ``collect="month"``; else
        None. Its December rows equal :attr:`model_frame`."""
        model = self._model
        if self._monthly_frame is None and model is not None and model.collect == "month" and model.datacollector:
            self._monthly_frame = model.monthly_frame()
        return self._monthly_frame

    @property
    def monthly_balance_sheets(self) -> pd.DataFrame:
        """Per-month opening/closing net worth and ledger inflows/outflows (the monthly conservation
        check's inputs)."""
        if self._monthly_balance_sheets is None:
            rows = []
            if self._model is not None:
                from .checks import conservation_records

                for record in conservation_records(self._model, monthly=True):
                    rows.append(
                        {
                            "year": record.year,
                            "month": record.month,
                            "opening_net_worth": record.opening_net_worth,
                            "closing_net_worth": record.closing_net_worth,
                            "inflows": record.inflows,
                            "outflows": record.outflows,
                        }
                    )
            self._monthly_balance_sheets = pd.DataFrame(rows, columns=list(MONTHLY_BALANCE_SHEET_COLUMNS))
        return self._monthly_balance_sheets

    @property
    def years(self) -> list[int]:
        if self.model_frame is not None:
            return [int(y) for y in self.model_frame["Year"]]
        return sorted(self.deflators)

    def tax_returns_frame(self) -> pd.DataFrame:
        """One row per return with its scalar lines (``TaxReturn.summary_row``)."""
        rows = [self.tax_returns[key].summary_row() for key in sorted(self.tax_returns)]
        return pd.DataFrame(rows)

    def conservation(self) -> "list[ConservationRecord]":
        """The money-conservation check's yearly records, always in **nominal** dollars (works on a
        loaded result too).

        Conservation is a statement about nominal money: a year's change in net worth equals its
        ledger flows. In start-year dollars it does not hold, because inflation erodes the opening
        balance without any ledger flow (the real opening balance is in the prior year's dollars), so
        a real-dollar result re-inflates its balance sheets with :attr:`deflators` before checking.
        """
        from .checks import ConservationRecord

        records = []
        start = min(self.deflators) if self.deflators else None
        for row in self.balance_sheets.itertuples():
            year = int(row.year)
            closing_factor = opening_factor = 1.0
            if self.real:
                # Undo _deflate_balance_sheets: closing and flows in the year's dollars, opening in the
                # prior year's.
                closing_factor = self.deflators.get(year, 1.0)
                opening_factor = self.deflators.get(year - 1, 1.0) if start is not None and year > start else 1.0
            records.append(
                ConservationRecord(
                    year=year,
                    opening_net_worth=float(row.opening_net_worth) * opening_factor,
                    closing_net_worth=float(row.closing_net_worth) * closing_factor,
                    inflows=float(row.inflows) * closing_factor,
                    outflows=float(row.outflows) * closing_factor,
                )
            )
        return records

    def __repr__(self) -> str:
        years = self.years
        span = f"{years[0]}-{years[-1]}" if years else "no years"
        dollars = "real" if self.real else "nominal"
        return (
            f"RunResult({span}, {len(self.tax_returns)} tax returns, {len(self.ledger)} ledger entries, "
            f"{len(self.events)} events, seed={self.seed}, {dollars} dollars)"
        )

    # ------------------------------------------------------------------
    # Real dollars
    # ------------------------------------------------------------------

    def real_dollars(self) -> "RunResult":
        """A copy with every money amount deflated by the economy's cumulative inflation to
        start-year dollars: money columns of both frames, ledger and event amounts, tax returns and
        balance sheets. Rates, years and identifiers are unchanged. Idempotent."""
        if self.real:
            return self
        deflator = self.deflators

        def deflate(frame: pd.DataFrame | None, columns, year_column: str) -> pd.DataFrame | None:
            if frame is None:
                return None
            frame = frame.copy()
            factors = frame[year_column].map(lambda y: deflator.get(int(y), 1.0) if pd.notna(y) else 1.0)
            for column in columns:
                if column in frame.columns:
                    frame[column] = pd.to_numeric(frame[column], errors="coerce") / factors.astype(float)
            return frame

        return RunResult(
            model_frame=deflate(self.model_frame, self.money_columns, "Year"),
            agent_frame=deflate(self.agent_frame, self.money_columns, "Year"),
            tax_returns={
                key: tax_return.scaled(deflator.get(key[0], 1.0)) for key, tax_return in self.tax_returns.items()
            },
            ledger=deflate(self.ledger, ["amount"], "year"),
            events=deflate(self.events, ["amount"], "year"),
            balance_sheets=self._deflate_balance_sheets(),
            monthly_frame=deflate(self.monthly_frame, self.money_columns, "Year"),
            monthly_balance_sheets=deflate(
                self.monthly_balance_sheets, ["opening_net_worth", "closing_net_worth", "inflows", "outflows"], "year"
            ),
            seed=self.seed,
            spec=self.spec,
            deflators=self.deflators,
            money_columns=self.money_columns,
            real=True,
        )

    def _deflate_balance_sheets(self) -> pd.DataFrame:
        frame = self.balance_sheets.copy()
        if frame.empty:
            return frame
        years = frame["year"].astype(int)
        start = min(self.deflators) if self.deflators else None
        closing = years.map(lambda y: self.deflators.get(y, 1.0))
        # The opening balance of year Y is the closing balance of Y-1, in Y-1 dollars.
        opening = years.map(lambda y: self.deflators.get(y - 1, 1.0) if start is not None and y > start else 1.0)
        frame["closing_net_worth"] = frame["closing_net_worth"] / closing
        frame["opening_net_worth"] = frame["opening_net_worth"] / opening
        frame["inflows"] = frame["inflows"] / closing
        frame["outflows"] = frame["outflows"] / closing
        return frame

    # ------------------------------------------------------------------
    # Exports
    # ------------------------------------------------------------------

    def _meta(self) -> dict[str, Any]:
        spec = self.spec
        if spec is not None and hasattr(spec, "model_dump"):
            spec = spec.model_dump(mode="json")
        elif spec is not None and not isinstance(spec, (dict, list, str, int, float, bool)):
            spec = repr(spec)
        return {
            "seed": self.seed,
            "real": self.real,
            "deflators": {str(year): factor for year, factor in self.deflators.items()},
            "money_columns": list(self.money_columns),
            "spec": spec,
            "tax_returns": [self.tax_returns[key].to_dict() for key in sorted(self.tax_returns)],
        }

    @staticmethod
    def _records(frame: pd.DataFrame | None) -> list[dict] | None:
        if frame is None:
            return None
        return json.loads(frame.to_json(orient="records"))

    def to_json(self, path: "str | os.PathLike") -> Path:
        """Write the whole result as one JSON document. Returns the path."""
        path = Path(path)
        document = {
            **self._meta(),
            "model_frame": self._records(self.model_frame),
            "agent_frame": self._records(self.agent_frame),
            "ledger": self._records(self.ledger),
            "events": self._records(self.events),
            "balance_sheets": self._records(self.balance_sheets),
            "monthly_frame": self._records(self.monthly_frame),
            "monthly_balance_sheets": self._records(self.monthly_balance_sheets),
        }
        path.write_text(json.dumps(document))
        return path

    def _tables(self) -> dict[str, pd.DataFrame | None]:
        return {
            "model": self.model_frame,
            "agents": self.agent_frame,
            "ledger": self.ledger,
            "events": self.events,
            "balance_sheets": self.balance_sheets,
            "monthly_balance_sheets": self.monthly_balance_sheets,
            "monthly": self.monthly_frame,
            "tax_returns": self.tax_returns_frame(),
        }

    def to_csv(self, directory: "str | os.PathLike") -> Path:
        """Write one CSV per table (``model.csv``, ``agents.csv``, ``ledger.csv``, ``events.csv``,
        ``balance_sheets.csv``, ``monthly_balance_sheets.csv``, ``tax_returns.csv``, and ``monthly.csv``
        when collected) plus ``meta.json``. Returns the directory."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        for name, frame in self._tables().items():
            if frame is not None:
                frame.to_csv(directory / f"{name}.csv", index=False)
        (directory / "meta.json").write_text(json.dumps(self._meta()))
        return directory

    def to_parquet(self, directory: "str | os.PathLike") -> Path:
        """Write one Parquet file per table plus ``meta.json`` (needs pyarrow: the ``parquet``
        extra). :meth:`load` reads it back. Returns the directory."""
        _require_parquet()
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        for name, frame in self._tables().items():
            if frame is not None:
                frame.to_parquet(directory / f"{name}.parquet", index=False)
        (directory / "meta.json").write_text(json.dumps(self._meta()))
        return directory

    @classmethod
    def load(cls, directory: "str | os.PathLike") -> "RunResult":
        """Read a result written by :meth:`to_parquet` (or, best effort, :meth:`to_csv`)."""
        directory = Path(directory)
        meta = json.loads((directory / "meta.json").read_text())
        parquet = (directory / "ledger.parquet").exists()
        if parquet:
            _require_parquet()

        def read(name: str) -> pd.DataFrame | None:
            path = directory / f"{name}.{'parquet' if parquet else 'csv'}"
            if not path.exists():
                return None
            return pd.read_parquet(path) if parquet else pd.read_csv(path)

        tax_returns = {}
        for record in meta.get("tax_returns", []):
            tax_return = TaxReturn.from_dict(record)
            tax_returns[(tax_return.year, tax_return.unit_id)] = tax_return
        return cls(
            model_frame=read("model"),
            agent_frame=read("agents"),
            tax_returns=tax_returns,
            ledger=read("ledger"),
            events=read("events"),
            balance_sheets=read("balance_sheets"),
            monthly_frame=read("monthly"),
            monthly_balance_sheets=read("monthly_balance_sheets"),
            seed=meta.get("seed"),
            spec=meta.get("spec"),
            deflators={int(year): factor for year, factor in meta.get("deflators", {}).items()},
            money_columns=meta.get("money_columns", ()),
            real=meta.get("real", False),
        )

    # ------------------------------------------------------------------
    # Explain
    # ------------------------------------------------------------------

    def explain(self, year: int) -> str:
        """A markdown account of ``year``: income by source, bills by category, how they were paid
        (the waterfall, with every forced sale and pre-tax withdrawal and its cause), each tax
        return's summary, the change in net worth, and every event."""
        ledger = self.ledger
        rows = ledger[ledger["year"] == year]
        dollars = "start-year dollars" if self.real else "nominal dollars"
        lines = [f"# {year}", "", f"All amounts in {dollars}.", ""]

        inflows = rows[rows["from_account"].isna() & rows["to_account"].notna()]
        outflows = rows[rows["from_account"].notna() & rows["to_account"].isna()]
        transfers = rows[rows["from_account"].notna() & rows["to_account"].notna()]
        people = {}
        if not self.events.empty:
            people = dict(zip(self.events["person_id"], self.events["person"], strict=False))
        for frame in (self.agent_frame,):
            if frame is not None and "Type" in frame.columns:
                persons = frame[frame["Type"] == "Person"]
                people.update(dict(zip(persons["AgentID"], persons["Name"], strict=False)))

        def who(agent_id) -> str:
            if agent_id is None or (isinstance(agent_id, float) and pd.isna(agent_id)):
                return ""
            name = people.get(agent_id) or people.get(int(agent_id))
            return f" ({name})" if name else ""

        def grouped(frame: pd.DataFrame, by: list[str]) -> list[tuple]:
            if frame.empty:
                return []
            frame = frame.fillna({column: "" for column in by})
            summed = frame.groupby(by, sort=False)["amount"].sum().reset_index()
            return [tuple(row) for row in summed.itertuples(index=False)]

        lines.append("## Income")
        income = inflows[inflows["kind"].isin(_INCOME_KINDS)]
        for kind, source, agent_id, amount in grouped(income, ["kind", "source", "agent_id"]):
            lines.append(f"- {kind.replace('_', ' ')} from {source}{who(agent_id)}: {_money(amount)}")
        if income.empty:
            lines.append("- none")
        growth = inflows[~inflows["kind"].isin(_INCOME_KINDS)]
        if not growth.empty:
            lines += ["", "## Growth and other inflows"]
            for kind, source, amount in grouped(growth, ["kind", "source"]):
                lines.append(f"- {kind.replace('_', ' ')} ({source}): {_money(amount)}")

        lines += ["", "## Bills"]
        bills = outflows[~outflows["kind"].isin(["tax", "penalty"])]
        for kind, sink, amount in grouped(bills, ["kind", "sink"]):
            lines.append(f"- {kind.replace('_', ' ')}: {sink}: {_money(amount)}")
        principal = transfers[transfers["kind"].isin(["debt_service", "housing"])]
        for kind, cause, amount in grouped(principal, ["kind", "cause"]):
            lines.append(f"- {kind.replace('_', ' ')}: {cause}: {_money(amount)}")
        if bills.empty and principal.empty:
            lines.append("- none")
        taxes = outflows[outflows["kind"].isin(["tax", "penalty"])]
        if not taxes.empty:
            lines.append(f"- taxes: {_money(taxes['amount'].sum())} (see the returns below)")

        def name_of(frame: pd.DataFrame, column: str) -> pd.Series:
            names = frame[column] if column in frame.columns else pd.Series([None] * len(frame), index=frame.index)
            labels = frame["to_account" if column == "to_name" else "from_account"]
            return names.where(names.notna() & (names != ""), labels).fillna("")

        lines += ["", "## How they were paid"]
        events = self.events[self.events["year"] == year]
        drawn = 0.0
        for kind in ("forced_sale", "pretax_withdrawal", "withdrawal"):
            for event in events[events["kind"] == kind].itertuples():
                drawn += float(event.amount or 0.0)
                lines.append(f"- {event.message}")
        # Accounts that paid bills directly (no waterfall event): 529 plans funding college costs, HSAs
        # reimbursing medical costs. Their withdrawals land in the bank the bills are paid from.
        funded = transfers[
            transfers["kind"].isin(["withdrawal"])
            & transfers["from_account"].fillna("").str.match(r"^(Plan529|HealthSavingsAccount):")
            & transfers["to_account"].fillna("").str.match(r"^(BankAccount|Cash):")
        ]
        if not funded.empty:
            funded = funded.assign(_from=name_of(funded, "from_name"))
            for source, cause, amount in grouped(funded, ["_from", "cause"]):
                why = f" ({cause})" if cause else ""
                drawn += amount
                lines.append(f"- from {source}{why}: {_money(amount)}")
        borrowed = rows[(rows["kind"] == "borrow") & rows["from_account"].fillna("").str.startswith("Debt:")]
        # A return's balance due (or refund) accrued in December is settled in April of the next year.
        accrued = taxes[taxes["from_account"].fillna("").str.startswith(("TaxDue:", "TaxRefund:"))]["amount"].sum()
        settled = transfers[
            (transfers["kind"] == "tax")
            & transfers["to_account"].fillna("").str.startswith("TaxDue:")
            & transfers["cause"].fillna("").str.contains("balance due")
        ]["amount"].sum()
        paid_total = bills["amount"].sum() + taxes["amount"].sum() + principal["amount"].sum() - accrued + settled
        new_debt = borrowed["amount"].sum()
        cash = paid_total - drawn - new_debt
        lines.append(f"- from cash on hand (income and bank balances): {_money(cash)}")
        if new_debt:
            lines.append(f"- carried as new debt: {_money(new_debt)}")
        refunded = transfers[
            (transfers["kind"] == "tax") & transfers["from_account"].fillna("").str.startswith("TaxRefund:")
        ]["amount"].sum()
        if settled:
            lines.append(f"- last year's balance due, paid in April: {_money(settled)}")
        if refunded:
            lines.append(f"- last year's refund, received in April: {_money(refunded)}")
        if accrued > 0:
            lines.append(f"- this year's balance due, payable next April: {_money(accrued)}")
        elif accrued < 0:
            lines.append(f"- this year's refund, due next April: {_money(-accrued)}")
        contributions = transfers[transfers["kind"].isin(["contribution", "rmd"])]
        if not contributions.empty:
            lines += ["", "## Savings moves"]
            contributions = contributions.assign(_to=name_of(contributions, "to_name"))
            for kind, cause, target, amount in grouped(contributions, ["kind", "cause", "_to"]):
                label = cause or ("required minimum distribution" if kind == "rmd" else "contribution")
                lines.append(f"- {kind}: {label} → {target}: {_money(amount)}")

        returns = [r for (y, _), r in sorted(self.tax_returns.items()) if y == year]
        lines += ["", "## Tax returns"]
        for r in returns:
            lines.append(f"### {', '.join(r.member_names)} ({r.filing_status.replace('_', ' ').lower()}, {r.state})")
            lines.append(
                f"- total income {_money(r.total_income)}, adjustments {_money(r.total_adjustments)}, "
                f"AGI {_money(r.agi)}"
            )
            lines.append(
                f"- {r.deduction_taken} deduction {_money(r.deduction)} → taxable income {_money(r.taxable_income)}"
            )
            credits = ", ".join(f"{k.replace('_', ' ')} {_money(v)}" for k, v in r.credits.items()) or "none"
            penalties = ", ".join(f"{k.replace('_', ' ')} {_money(v)}" for k, v in r.penalties.items()) or "none"
            lines.append(
                f"- federal: ordinary {_money(r.ordinary_tax)} + preferential {_money(r.preferential_tax)} + NIIT "
                f"{_money(r.niit)} − credits ({credits}) + penalties ({penalties}) = {_money(r.federal_tax)}"
            )
            lines.append(
                f"- state {_money(r.state_tax)}, Social Security {_money(r.social_security_tax)}, Medicare "
                f"{_money(r.medicare_tax)}; total {_money(r.total_tax)}"
            )
            lines.append(f"- marginal rate {r.marginal_rate:.0f}%, effective federal rate {r.effective_rate:.1f}%")
            if getattr(r, "settled_in_april", False):
                due = (
                    f"balance due {_money(r.amount_owed)}"
                    if r.amount_owed
                    else f"refund {_money(r.overpayment)}"
                    if r.overpayment
                    else "nothing due"
                )
                penalty = (
                    f" (with a {_money(r.estimated_tax_penalty)} estimated tax penalty)"
                    if r.estimated_tax_penalty
                    else ""
                )
                lines.append(
                    f"- paid during the year: federal withholding {_money(r.federal_income_tax_withheld)}, estimated "
                    f"payments {_money(r.estimated_tax_payments)}; {due}{penalty}, settled in April {r.year + 1}"
                )
        if not returns:
            lines.append("- none")

        sheet = self.balance_sheets
        sheet = sheet[sheet["year"] == year]
        if not sheet.empty:
            row = sheet.iloc[0]
            change = row["closing_net_worth"] - row["opening_net_worth"]
            lines += [
                "",
                "## Net worth",
                (
                    f"- {_money(row['opening_net_worth'])} → {_money(row['closing_net_worth'])} ({_money(change)}): "
                    f"inflows {_money(row['inflows'])}, outflows {_money(row['outflows'])}"
                ),
            ]

        lines += ["", "## Events"]
        for event in events.itertuples():
            lines.append(f"- [{event.kind}] {event.message}")
        if events.empty:
            lines.append("- none")
        return "\n".join(lines) + "\n"
