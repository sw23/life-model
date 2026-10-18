# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Declarative household specification (``HouseholdSpec``).

A ``HouseholdSpec`` is plain data (YAML or JSON) describing a household: its people, their jobs,
accounts, debts, housing, insurance, Social Security, healthcare, giving, children and spending,
the marriages between them, and dated life events. :func:`life_model.spec.builder.build_model`
turns a spec into a ready-to-run :class:`~life_model.model.LifeModel`; the core constructors stay
the low-level API underneath.

Conventions (enforced by the field types and :mod:`life_model.spec.validate`):

* **Units.** Every rate field ends in ``_pct`` and is a percentage: ``4.5`` means 4.5%. A value in
  ``(0, 1)`` on a field whose typical magnitude is above 1 produces a "did you mean 4.5?" warning.
* **Periods.** Every flow states its period: ``*_annual`` (per year) or ``*_monthly`` (per month).
  Balances, prices and one-time amounts are plain dollars at the as-of date.
* **Signs.** Money is never negative: debts are entered as positive balances.
* **Growth.** Fields typed ``GrowthPct`` take a percentage or the string ``"economy"``, which
  follows the simulation economy (inflation, wage growth, the account's asset-class return or home
  appreciation) and therefore varies under stochastic and path economies.
* **Strictness.** Every model forbids unknown keys, so a typo fails loudly.
* **Not yet supported.** Fields marked ``x-not-yet-supported`` in the JSON Schema (and "NOT YET
  SUPPORTED" in their description) are declared so statements can be written down today, but the
  engine cannot simulate them yet; the validator rejects a spec that sets one. A later plan flips a
  field on by removing its marker and teaching the builder and extractor to map it.
"""

from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Version of the spec format written by :func:`life_model.spec.io.dump`.
SPEC_VERSION = 1

#: JSON Schema keys carried in ``json_schema_extra`` (also read by the validator and docs script).
NYS_KEY = "x-not-yet-supported"
UNIT_KEY = "x-unit"
CORE_KEY = "x-core"
ABOVE_ONE_KEY = "x-typical-above-one"


def spec_field(
    default: Any = ...,
    *,
    description: str,
    unit: str | None = None,
    core: str | None = None,
    not_yet_supported: str | None = None,
    typical_above_one: bool = False,
    **kwargs: Any,
) -> Any:
    """A ``pydantic.Field`` carrying the spec metadata (unit, core mapping, support status).

    Args:
        default: Field default (``...`` for required).
        description: Human/LLM-facing description; should state unit and period.
        unit: Unit label (``percent``, ``USD``, ``USD/year``, ``USD/month``, ``year``, ``age``...).
        core: The core constructor argument the field maps to (``Class.argument``).
        not_yet_supported: When set, the plan that will add engine support. The validator rejects
            any non-default value for the field until the marker is removed.
        typical_above_one: For ``_pct`` fields whose real-world values are normally above 1
            (growth, contribution, interest rates): a value in ``(0, 1)`` triggers a warning.
    """
    extra: dict[str, Any] = {}
    if unit is not None:
        extra[UNIT_KEY] = unit
    if core is not None:
        extra[CORE_KEY] = core
    if not_yet_supported is not None:
        extra[NYS_KEY] = not_yet_supported
        description = f"{description} NOT YET SUPPORTED ({not_yet_supported}): rejected by the validator."
    if typical_above_one:
        extra[ABOVE_ONE_KEY] = True
    return Field(default, description=description, json_schema_extra=extra or None, **kwargs)


class SpecModel(BaseModel):
    """Base for every spec model: unknown keys are errors, and assignment re-validates."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    #: Set on a model class that the engine cannot simulate yet (the plan that will add it).
    NOT_YET_SUPPORTED: ClassVar[str | None] = None
    #: The core class this model is built into (documentation only).
    CORE_CLASS: ClassVar[str | None] = None


# --- Unit types ---------------------------------------------------------------------------------

#: A percentage (4.5 = 4.5%).
Percent = Annotated[float, Field(ge=-100, le=1000)]
#: A non-negative percentage.
NonNegativePercent = Annotated[float, Field(ge=0, le=1000)]
#: A percentage or ``"economy"`` (follow the simulation economy's matching rate).
GrowthPct = Percent | Literal["economy"]
#: Dollars; never negative (debts are entered as positive balances).
NonNegativeMoney = Annotated[float, Field(ge=0)]
#: An age in whole years.
Age = Annotated[int, Field(ge=0, le=119)]
#: A (possibly fractional) age such as a retirement age of 59.5.
AgeFloat = Annotated[float, Field(ge=0, le=119)]
#: A calendar year.
Year = Annotated[int, Field(ge=1900, le=2200)]
#: A spec identifier (referenced by other entries).
# (Character class written so docutils does not read "..._]" as a hyperlink reference.)
Identifier = Annotated[str, Field(pattern=r"^[-0-9A-Z_a-z]+$", min_length=1, max_length=64)]
#: A ``YYYY-MM`` calendar month.
YearMonth = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


def _id_field(what: str) -> Any:
    return spec_field(
        None,
        description=f"Optional identifier for this {what}, unique across the spec. Required when another entry "
        "references it (a 401k's job, an event's target, a relative event's anchor).",
    )


# --- Meta and economy ---------------------------------------------------------------------------


class Meta(SpecModel):
    """Run metadata: the simulated period, seed, named scenario and state defaults."""

    CORE_CLASS = "LifeModel"

    name: str = spec_field(description="Short name of the household.", min_length=1)
    description: str | None = spec_field(None, description="Free-text description.")
    as_of: str | None = spec_field(
        None,
        description="Date the balances were read from statements (YYYY-MM or YYYY-MM-DD). Informational.",
        pattern=r"^\d{4}-(0[1-9]|1[0-2])(-\d{2})?$",
    )
    start_year: Year = spec_field(description="First simulated year.", unit="year", core="LifeModel.start_year")
    end_year: Year | None = spec_field(
        None,
        description="Last simulated year (inclusive). Defaults to start_year + 50.",
        unit="year",
        core="LifeModel.end_year",
    )
    start: YearMonth | None = spec_field(
        None,
        description="First simulated month (YYYY-MM), in start_year: a model started in October simulates "
        "three months of its first year. Defaults to January of start_year.",
        unit="YYYY-MM",
        core="LifeModel.start",
    )
    seed: int | None = spec_field(
        None, description="Random seed (stochastic economy and mortality draws).", core="LifeModel.seed"
    )
    scenario: str | None = spec_field(
        None,
        description="Named economic/regulatory scenario from life_model.config.scenarios (e.g. 'recession').",
        core="LifeModel.scenario",
    )
    default_state: str | None = spec_field(
        None,
        description="Two-letter state of residence for people without their own 'state'. Must have a state "
        "tax pack (unknown codes are errors, never a silent flat 6%).",
        core="config.tax.state.default_state",
    )


class StochasticEconomy(SpecModel):
    """Distribution parameters for ``mode: stochastic`` (all optional; percentages)."""

    CORE_CLASS = "config.economy.stochastic"

    equity_mean_pct: Percent | None = spec_field(None, description="Mean equity return.", unit="percent")
    equity_vol_pct: NonNegativePercent | None = spec_field(None, description="Equity volatility.", unit="percent")
    bond_mean_pct: Percent | None = spec_field(None, description="Mean bond return.", unit="percent")
    bond_vol_pct: NonNegativePercent | None = spec_field(None, description="Bond volatility.", unit="percent")
    inflation_mean_pct: Percent | None = spec_field(None, description="Mean inflation.", unit="percent")
    inflation_vol_pct: NonNegativePercent | None = spec_field(None, description="Inflation volatility.", unit="percent")
    cash_yield_mean_pct: Percent | None = spec_field(None, description="Mean cash yield.", unit="percent")
    cash_yield_vol_pct: NonNegativePercent | None = spec_field(
        None, description="Cash yield volatility.", unit="percent"
    )
    home_appreciation_mean_pct: Percent | None = spec_field(None, description="Mean home appreciation.", unit="percent")
    home_appreciation_vol_pct: NonNegativePercent | None = spec_field(
        None, description="Home appreciation volatility.", unit="percent"
    )
    wage_growth_mean_pct: Percent | None = spec_field(None, description="Mean wage growth.", unit="percent")
    wage_growth_vol_pct: NonNegativePercent | None = spec_field(
        None, description="Wage growth volatility.", unit="percent"
    )
    equity_bond_correlation: float | None = spec_field(
        None, description="Equity/bond correlation (-1..1, unitless).", ge=-1, le=1
    )
    equity_inflation_correlation: float | None = spec_field(
        None, description="Equity/inflation correlation (-1..1, unitless).", ge=-1, le=1
    )
    bond_inflation_correlation: float | None = spec_field(
        None, description="Bond/inflation correlation (-1..1, unitless).", ge=-1, le=1
    )


EconomyRate = Literal[
    "inflation_pct",
    "wage_growth_pct",
    "equity_return_pct",
    "bond_return_pct",
    "cash_yield_pct",
    "home_appreciation_pct",
]


class Economy(SpecModel):
    """Overrides of the packaged economy (config ``economy``); unset fields keep the defaults.

    Same shape as the config block, with ``_pct`` names for the rates.
    """

    CORE_CLASS = "config.economy"

    mode: Literal["fixed", "path", "stochastic"] | None = spec_field(
        None,
        description="'fixed' constants every year, 'path' per-year overrides, 'stochastic' seeded random draws.",
    )
    inflation_pct: Percent | None = spec_field(
        None, description="Annual inflation.", unit="percent", typical_above_one=True
    )
    wage_growth_pct: Percent | None = spec_field(
        None, description="Annual wage growth.", unit="percent", typical_above_one=True
    )
    equity_return_pct: Percent | None = spec_field(
        None, description="Annual equity return.", unit="percent", typical_above_one=True
    )
    bond_return_pct: Percent | None = spec_field(
        None, description="Annual bond return.", unit="percent", typical_above_one=True
    )
    cash_yield_pct: Percent | None = spec_field(None, description="Annual cash yield.", unit="percent")
    home_appreciation_pct: Percent | None = spec_field(
        None, description="Annual home appreciation.", unit="percent", typical_above_one=True
    )
    paths: dict[EconomyRate, dict[int, float]] | None = spec_field(
        None,
        description="Path mode: per-rate, per-year percentages, e.g. {equity_return_pct: {2027: -10}}.",
    )
    stochastic: StochasticEconomy | None = spec_field(None, description="Stochastic-mode distribution overrides.")


# --- Timing -------------------------------------------------------------------------------------


class Relative(SpecModel):
    """A time relative to another event."""

    after: Identifier = spec_field(description="Id of the anchor event.")
    years: int = spec_field(0, description="Years after the anchor event (may be 0).", unit="years", ge=0)


class At(SpecModel):
    """When an event happens: exactly one of ``year``, ``age`` or ``relative``, plus an optional
    ``month``.

    Shorthand: an integer is a year (``at: 2030``); ``"2030-07"`` is July 2030.

    Age timing resolves through ``Person.get_year_at_age`` (the engine's own age semantics), so
    the builder needs no age arithmetic of its own; see :mod:`life_model.spec.events`.
    """

    year: Year | None = spec_field(None, description="Calendar year.", unit="year")
    age: Age | None = spec_field(None, description="Age (whole years) of the event's person.", unit="age")
    person: Identifier | None = spec_field(
        None, description="Whose age 'age' refers to. Defaults to the event's person."
    )
    relative: Relative | None = spec_field(None, description="Relative to another event.")
    month: int | None = spec_field(
        None,
        description="Month (1-12) the event happens in, within the resolved year. Defaults to the first simulated "
        "month of that year (January), or for 'age' to the month the person reaches that age (their birth month).",
        unit="month",
        core="LifeEvent.month",
        ge=1,
        le=12,
    )

    @model_validator(mode="before")
    @classmethod
    def _shorthand(cls, data: Any) -> Any:
        if isinstance(data, bool):
            return data
        if isinstance(data, int):
            return {"year": data}
        if isinstance(data, str):
            parts = data.split("-")
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                return {"year": int(parts[0]), "month": int(parts[1])}
            if data.isdigit():
                return {"year": int(data)}
        return data

    @model_validator(mode="after")
    def _exactly_one(self) -> "At":
        chosen = [name for name in ("year", "age", "relative") if getattr(self, name) is not None]
        if len(chosen) != 1:
            raise ValueError(f"'at' needs exactly one of year, age or relative (got {chosen or 'none'})")
        if self.person is not None and self.age is None:
            raise ValueError("'at.person' is only meaningful with 'at.age'")
        return self


# --- Spending, jobs ------------------------------------------------------------------------------


class SpendingCategory(SpecModel):
    """A categorized spending line (Plan 27 D6)."""

    amount_annual: NonNegativeMoney = spec_field(description="Annual amount.", unit="USD/year")
    growth_pct: GrowthPct = spec_field("economy", description="Annual growth.", unit="percent")
    essential: bool = spec_field(True, description="Essential (vs discretionary) spending.")


class Spending(SpecModel):
    """A person's living spending (everything except housing, debts, taxes and modeled costs)."""

    CORE_CLASS = "Spending"

    amount_annual: NonNegativeMoney = spec_field(
        description="Base living spending per year.", unit="USD/year", core="Spending.base"
    )
    growth_pct: GrowthPct = spec_field(
        0.0,
        description="Yearly increase; 'economy' follows inflation. The core default 0 means spending never "
        "rises (the validator warns).",
        unit="percent",
        core="Spending.yearly_increase",
        typical_above_one=True,
    )
    categories: dict[str, SpendingCategory] | None = spec_field(
        None,
        description="Categorized spending lines on top of the base amount.",
        not_yet_supported="Plan 27 D6",
    )
    schedule: list[tuple[int, float]] | None = spec_field(
        None,
        description="(age, percent of prior spending) steps, e.g. a retirement spending smile.",
        not_yet_supported="Plan 27 D6",
    )


class Payroll(SpecModel):
    """Pre-tax payroll deductions (Plan 27 D3; the dependent-care FSA is supported since Plan 31)."""

    CORE_CLASS = "PayrollDeductions"

    health_premium_monthly: NonNegativeMoney = spec_field(
        0.0, description="Health premium.", unit="USD/month", not_yet_supported="Plan 27 D3"
    )
    dental_vision_monthly: NonNegativeMoney = spec_field(
        0.0, description="Dental/vision.", unit="USD/month", not_yet_supported="Plan 27 D3"
    )
    fsa_annual: NonNegativeMoney = spec_field(
        0.0, description="Health FSA.", unit="USD/year", not_yet_supported="Plan 27 D3"
    )
    dependent_care_fsa_annual: NonNegativeMoney = spec_field(
        0.0,
        description="Dependent-care FSA election (W-2 box 10): excluded from wages and FICA up to the Form 2441 "
        "limit ($5,000; $7,500 from 2026), and it reduces the expenses the dependent care credit can use.",
        unit="USD/year",
        core="PayrollDeductions.dependent_care_fsa_annual",
    )
    hsa_employee_annual: NonNegativeMoney = spec_field(
        0.0, description="Employee HSA.", unit="USD/year", not_yet_supported="Plan 27 D3"
    )
    hsa_employer_annual: NonNegativeMoney = spec_field(
        0.0, description="Employer HSA.", unit="USD/year", not_yet_supported="Plan 27 D3"
    )
    commuter_monthly: NonNegativeMoney = spec_field(
        0.0, description="Commuter benefit.", unit="USD/month", not_yet_supported="Plan 27 D3"
    )


class StockGrant(SpecModel):
    """An existing (already granted, partly unvested) equity grant (Plan 27 D1)."""

    grant_year: Year = spec_field(description="Year granted.", unit="year")
    value: NonNegativeMoney = spec_field(description="Grant value at grant.", unit="USD")
    vesting_schedule_pct: list[NonNegativePercent] = spec_field(
        description="Percent vesting each year.", unit="percent"
    )


class StockOption(SpecModel):
    """A stock option exercised in a planned year (Plan 31): an NSO's spread is wages; an ISO exercised and
    held puts its spread into AMT (Form 6251 line 2i), and the minimum tax credit follows in later years."""

    CORE_CLASS = "StockOption"

    kind: Literal["iso", "nso"] = spec_field(description="Incentive (ISO) or nonqualified (NSO) option.")
    exercise_year: Year = spec_field(description="Year the option is exercised.", unit="year")
    exercise_cost: NonNegativeMoney = spec_field(
        description="Strike price times shares (cash paid at exercise).", unit="USD", core="StockOption.exercise_cost"
    )
    value: NonNegativeMoney = spec_field(
        description="Market value of the shares at the start year; revalued by the plan's stock growth to the "
        "exercise year (set growth_pct 0 to exercise at exactly this value).",
        unit="USD",
        core="StockOption.value",
    )
    sell_at_exercise: bool = spec_field(
        False,
        description="Cashless same-day sale (for an ISO a disqualifying disposition: ordinary income, no AMT). "
        "Otherwise the shares are held in the person's first brokerage account.",
        core="StockOption.sell_at_exercise",
    )


class StockPlan(SpecModel):
    """RSU compensation attached to a job."""

    CORE_CLASS = "StockPlan"

    signon_value: NonNegativeMoney = spec_field(
        0.0, description="Sign-on grant issued in the plan's first year.", unit="USD", core="StockPlan.signon_value"
    )
    refresher_value: NonNegativeMoney = spec_field(
        0.0, description="Each annual refresher grant.", unit="USD", core="StockPlan.refresher_value"
    )
    refresher_start_year: int = spec_field(
        1,
        description="Years after the plan starts before the first refresher.",
        unit="years",
        core="StockPlan.refresher_start_year",
        ge=0,
    )
    refresher_growth_pct: Percent = spec_field(
        0.0,
        description="Yearly growth of the refresher value.",
        unit="percent",
        core="StockPlan.refresher_growth_percent",
    )
    vesting_schedule_pct: list[NonNegativePercent] | None = spec_field(
        None,
        description="Percent of each refresher grant vesting 1, 2, ... years after grant (must sum to 100). "
        "Defaults to the configured preset.",
        unit="percent",
        core="StockPlan.schedule",
    )
    signon_vesting_schedule_pct: list[NonNegativePercent] | None = spec_field(
        None,
        description="Vesting schedule of the sign-on grant (defaults to vesting_schedule_pct).",
        unit="percent",
        core="StockPlan.signon_schedule",
    )
    disposition: Literal["sell", "hold"] = spec_field(
        "sell",
        description="Sell vested shares, or hold them in the first brokerage account.",
        core="StockPlan.disposition",
    )
    growth_pct: GrowthPct = spec_field(
        "economy",
        description="Company stock growth; 'economy' follows the equity return.",
        unit="percent",
        core="StockPlan.growth_rate",
        typical_above_one=True,
    )
    existing_grants: list[StockGrant] | None = spec_field(
        None, description="Grants made before the start year with unvested shares.", not_yet_supported="Plan 27 D1"
    )
    espp_discount_pct: NonNegativePercent | None = spec_field(
        None, description="ESPP purchase discount.", unit="percent", not_yet_supported="Plan 27 PR B"
    )
    options: list[StockOption] = spec_field(
        default_factory=list, description="Stock options (ISO / NSO) to exercise.", core="StockPlan.options"
    )

    @field_validator("vesting_schedule_pct", "signon_vesting_schedule_pct")
    @classmethod
    def _sums_to_100(cls, value: list[float] | None) -> list[float] | None:
        if value is not None and (not value or abs(sum(value) - 100.0) > 1e-4):
            raise ValueError(f"vesting schedule must sum to 100 percent, got {sum(value) if value else 0}")
        return value


class Job(SpecModel):
    """A W-2 job: base salary, raises and bonus. A 401k is a separate ``kind: 401k`` account."""

    CORE_CLASS = "Job + Salary"

    id: Identifier | None = _id_field("job")
    company: str = spec_field(description="Employer name.", core="Job.company")
    role: str = spec_field("Employee", description="Job title.", core="Job.role")
    salary_annual: NonNegativeMoney = spec_field(description="Base salary.", unit="USD/year", core="Salary.base")
    raise_pct: GrowthPct = spec_field(
        0.0,
        description="Yearly raise; 'economy' follows wage growth. The core default 0 means the salary never "
        "rises (the validator warns).",
        unit="percent",
        core="Salary.yearly_increase",
        typical_above_one=True,
    )
    bonus_pct: NonNegativePercent = spec_field(
        0.0, description="Yearly bonus as a percent of base salary.", unit="percent", core="Salary.yearly_bonus"
    )
    stock_plan: StockPlan | None = spec_field(None, description="RSU plan attached to this job.")
    start_year: Year | None = spec_field(
        None, description="First year the job pays.", unit="year", not_yet_supported="Plan 27 D3"
    )
    end_year: Year | None = spec_field(
        None, description="Last year the job pays.", unit="year", not_yet_supported="Plan 27 D3"
    )
    bonus_fixed_annual: NonNegativeMoney | None = spec_field(
        None, description="Fixed-dollar bonus.", unit="USD/year", not_yet_supported="Plan 27 D3"
    )
    raises: list[tuple[int, float]] | None = spec_field(
        None, description="(year, raise percent) schedule.", not_yet_supported="Plan 27 D3"
    )
    payroll: Payroll | None = spec_field(
        None,
        description="Pre-tax payroll deductions (the dependent-care FSA; the others are Plan 27 D3).",
        core="Job.payroll",
    )


# --- Accounts ------------------------------------------------------------------------------------

_ALLOCATION_DESC = "Asset allocation in percent by asset class, e.g. {equity: 70, bond: 30}."


class MatchTier(SpecModel):
    """One tier of an employer match: ``match_pct`` of deferrals on the next ``up_to_pay_pct`` of pay."""

    match_pct: NonNegativePercent = spec_field(description="Employer dollars per 100 deferred.", unit="percent")
    up_to_pay_pct: NonNegativePercent = spec_field(description="Width of the tier, percent of pay.", unit="percent")


class BankAccount(SpecModel):
    """A checking or savings account. Income is deposited into the person's primary bank account."""

    CORE_CLASS = "BankAccount"

    kind: Literal["bank"]
    id: Identifier | None = _id_field("account")
    company: str = spec_field("Bank", description="Bank name.", core="BankAccount.company")
    type: str = spec_field(
        "Checking", description="Account type label (Checking, Savings, ...).", core="BankAccount.type"
    )
    balance: NonNegativeMoney = spec_field(
        0.0, description="Balance at the as-of date.", unit="USD", core="BankAccount.balance"
    )
    interest_pct: Annotated[float, Field(ge=0, le=1000)] | Literal["economy"] = spec_field(
        "economy",
        description="Annual interest rate (APR, compounded per 'compounding'); 'economy' (the core default) "
        "follows the economy's cash yield. Interest is taxed as ordinary income.",
        unit="percent",
        core="BankAccount.interest_rate",
    )
    primary: bool = spec_field(
        False,
        description="Receives income and pays bills first. Exactly one per person when they have several "
        "bank accounts; otherwise the first in canonical order is primary.",
    )
    compounding: Literal["monthly", "annual"] | None = spec_field(
        None,
        description="How interest_pct compounds: 'monthly' (an APR) or 'annual' (enter an APY). Defaults to the "
        "configured convention.",
        core="BankAccount.compounding",
    )
    reserve: bool = spec_field(
        False, description="Emergency reserve not drawn for ordinary bills.", not_yet_supported="Plan 27 D2/D4"
    )


class FixedIncomeAccount(SpecModel):
    """A CD, Treasury, I-bond or bond fund holding (Plan 27 D2).

    Until it lands, statements with these are often entered as a bank account named "Bonds"; the
    validator warns about that stand-in because it is spent like checking.
    """

    NOT_YET_SUPPORTED = "Plan 27 D2"
    CORE_CLASS = "FixedIncomeHolding (Plan 27)"

    kind: Literal["fixed_income"]
    id: Identifier | None = _id_field("account")
    instrument: Literal["cd", "treasury", "i_bond", "bond_fund"] = spec_field(description="Instrument type.")
    face: NonNegativeMoney = spec_field(description="Face value / current value.", unit="USD")
    rate_pct: Percent = spec_field(description="Coupon or yield.", unit="percent")
    maturity: YearMonth | None = spec_field(None, description="Maturity month.", unit="YYYY-MM")
    state_tax_exempt: bool = spec_field(False, description="Interest exempt from state tax (Treasuries).")
    early_withdrawal_penalty_months: int = spec_field(0, description="CD penalty in months of interest.", ge=0)
    reserve: bool = spec_field(True, description="Not drawn by the waterfall unless all else is exhausted.")


class TaxLot(SpecModel):
    """One brokerage tax lot."""

    value: NonNegativeMoney = spec_field(description="Market value at the as-of date.", unit="USD")
    cost_basis: NonNegativeMoney = spec_field(description="Cost basis.", unit="USD")
    acquired_year: Year | None = spec_field(
        None, description="Year acquired (long-term once held a year). Defaults to the start year.", unit="year"
    )


class BrokerageAccount(SpecModel):
    """A taxable brokerage account.

    Enter either ``balance`` (one lot with no embedded gain) or ``lots``. Lots with embedded gains
    are built through the undocumented core workaround ``BrokerageAccount.deposit_with_basis``
    (one call per lot on an account opened empty); Plan 27 D1 adds a ``lots=`` constructor argument.
    """

    CORE_CLASS = "BrokerageAccount"

    kind: Literal["brokerage"]
    id: Identifier | None = _id_field("account")
    company: str = spec_field("Brokerage", description="Brokerage name.", core="BrokerageAccount.company")
    balance: NonNegativeMoney | None = spec_field(
        None,
        description="Balance, seeded as one lot with basis equal to the balance (no embedded gain). Mutually "
        "exclusive with lots.",
        unit="USD",
        core="BrokerageAccount.balance",
    )
    lots: list[TaxLot] | None = spec_field(
        None,
        description="Opening tax lots (value, cost basis, acquired year), built via deposit_with_basis.",
        core="BrokerageAccount.deposit_with_basis",
    )
    growth_pct: GrowthPct = spec_field(
        "economy",
        description="Total annual return; 'economy' follows the equity return (and varies under stochastic runs).",
        unit="percent",
        core="BrokerageAccount.growth_rate",
        typical_above_one=True,
    )
    dividend_yield_pct: NonNegativePercent | None = spec_field(
        None,
        description="Qualified-dividend yield carved out of the return; defaults to the configured yield.",
        unit="percent",
        core="BrokerageAccount.dividend_yield",
    )
    allocation_pct: dict[str, float] | None = spec_field(
        None, description=_ALLOCATION_DESC, unit="percent", not_yet_supported="Plan 27 D5"
    )
    expense_ratio_pct: NonNegativePercent | None = spec_field(
        None, description="Fund expense ratio.", unit="percent", not_yet_supported="Plan 27 D5"
    )
    reinvest_dividends: bool = spec_field(
        True, description="False pays dividends to the bank instead.", not_yet_supported="Plan 27 item 1"
    )

    @model_validator(mode="after")
    def _balance_or_lots(self) -> "BrokerageAccount":
        if self.balance is not None and self.lots is not None:
            raise ValueError("give either 'balance' or 'lots', not both")
        return self


class Job401k(SpecModel):
    """A 401(k) at one of the person's jobs (pre-tax and Roth buckets)."""

    CORE_CLASS = "Job401kAccount"

    kind: Literal["401k"]
    id: Identifier | None = _id_field("account")
    job: Identifier | None = spec_field(
        None,
        description="Id of the person's job offering the plan. A standalone (old-employer) plan without a job "
        "is NOT YET SUPPORTED (Plan 27 D3).",
        core="Job401kAccount.job",
    )
    pretax_balance: NonNegativeMoney = spec_field(
        0.0, description="Pre-tax balance.", unit="USD", core="Job401kAccount.pretax_balance"
    )
    roth_balance: NonNegativeMoney = spec_field(
        0.0, description="Roth balance.", unit="USD", core="Job401kAccount.roth_balance"
    )
    pretax_contrib_pct: NonNegativePercent = spec_field(
        0.0,
        description="Pre-tax deferral, percent of plan pay (base salary, plus bonus with match_on_bonus).",
        unit="percent",
        core="Job401kAccount.pretax_contrib_percent",
        typical_above_one=True,
    )
    roth_contrib_pct: NonNegativePercent = spec_field(
        0.0,
        description="Roth deferral, percent of plan pay (base salary, plus bonus with match_on_bonus).",
        unit="percent",
        core="Job401kAccount.roth_contrib_percent",
        typical_above_one=True,
    )
    growth_pct: GrowthPct = spec_field(
        "economy",
        description="Annual return; 'economy' follows the equity return.",
        unit="percent",
        core="Job401kAccount.average_growth",
        typical_above_one=True,
    )
    match_tiers: list[MatchTier] | None = spec_field(
        None,
        description="The employer match as the plan states it, tier by tier over the deferral rate: "
        "[{match_pct: 100, up_to_pay_pct: 3}, {match_pct: 50, up_to_pay_pct: 2}] is 100% of the first 3% of pay "
        "deferred plus 50% of the next 2%.",
        core="Job401kAccount.match_tiers",
    )
    match_on_bonus: bool = spec_field(
        False,
        description="Plan pay includes the bonus (deferral percentages and match tiers apply to salary + bonus).",
        core="Job401kAccount.match_on_bonus",
    )
    match_vesting_years: int = spec_field(
        0,
        description="Cliff vesting of employer money (0 = immediately vested); unvested match is forfeited if "
        "the job ends first.",
        unit="years",
        core="Job401kAccount.match_vesting_years",
        ge=0,
    )
    company_match_pct: NonNegativePercent = spec_field(
        0.0,
        description="DEPRECATED (the validator warns): core's legacy match, this percent OF THE DEFERRAL capped at "
        "this percent of pay (6 with a 6% deferral on $100k matches $360). Use match_tiers; a dollar-for-dollar "
        "match up to 6% of pay is [{match_pct: 100, up_to_pay_pct: 6}]. Mutually exclusive with match_tiers.",
        unit="percent",
        core="Job401kAccount.company_match_percent",
        typical_above_one=True,
    )
    after_tax_balance: NonNegativeMoney | None = spec_field(
        None, description="After-tax (non-Roth) bucket.", unit="USD", not_yet_supported="Plan 27 D3"
    )
    roth_basis: NonNegativeMoney | None = spec_field(
        None, description="Roth contribution basis.", unit="USD", not_yet_supported="Plan 27 D3"
    )
    allocation_pct: dict[str, float] | None = spec_field(
        None, description=_ALLOCATION_DESC, unit="percent", not_yet_supported="Plan 27 D5"
    )

    @model_validator(mode="after")
    def _one_match_formula(self) -> "Job401k":
        if self.match_tiers is not None and self.company_match_pct:
            raise ValueError("give either match_tiers or the deprecated company_match_pct, not both")
        return self


class TraditionalIRA(SpecModel):
    """A traditional IRA (pre-tax; RMDs apply)."""

    CORE_CLASS = "TraditionalIRA"

    kind: Literal["traditional_ira"]
    id: Identifier | None = _id_field("account")
    balance: NonNegativeMoney = spec_field(0.0, description="Balance.", unit="USD", core="TraditionalIRA.balance")
    growth_pct: GrowthPct = spec_field(
        "economy",
        description="Annual return; 'economy' follows the equity return.",
        unit="percent",
        core="TraditionalIRA.growth_rate",
        typical_above_one=True,
    )
    contribution_limit_annual: NonNegativeMoney | None = spec_field(
        None,
        description="Override of the annual contribution limit (shared across IRAs).",
        unit="USD/year",
        core="TraditionalIRA.contribution_limit",
    )
    nondeductible_basis: NonNegativeMoney | None = spec_field(
        None, description="Form 8606 after-tax basis.", unit="USD", not_yet_supported="Plan 27 D1"
    )


class RothIRA(SpecModel):
    """A Roth IRA. The whole opening balance is treated as contribution basis (Plan 27 item 3)."""

    CORE_CLASS = "RothIRA"

    kind: Literal["roth_ira"]
    id: Identifier | None = _id_field("account")
    balance: NonNegativeMoney = spec_field(0.0, description="Balance.", unit="USD", core="RothIRA.balance")
    growth_pct: GrowthPct = spec_field(
        "economy",
        description="Annual return; 'economy' follows the equity return.",
        unit="percent",
        core="RothIRA.growth_rate",
        typical_above_one=True,
    )
    contribution_limit_annual: NonNegativeMoney | None = spec_field(
        None,
        description="Override of the annual contribution limit (shared across IRAs).",
        unit="USD/year",
        core="RothIRA.contribution_limit",
    )
    contribution_basis: NonNegativeMoney | None = spec_field(
        None, description="Contribution basis (withdrawable any time).", unit="USD", not_yet_supported="Plan 27 D1"
    )
    conversion_basis: NonNegativeMoney | None = spec_field(
        None, description="Conversion basis.", unit="USD", not_yet_supported="Plan 27 D1"
    )


class HealthSavingsAccount(SpecModel):
    """A health savings account."""

    CORE_CLASS = "HealthSavingsAccount"

    kind: Literal["hsa"]
    id: Identifier | None = _id_field("account")
    coverage: Literal["individual", "family"] = spec_field(
        "individual", description="HDHP coverage tier (sets the limit).", core="HealthSavingsAccount.hsa_type"
    )
    balance: NonNegativeMoney = spec_field(0.0, description="Balance.", unit="USD", core="HealthSavingsAccount.balance")
    growth_pct: GrowthPct = spec_field(
        "economy",
        description="Annual return; 'economy' follows the equity return.",
        unit="percent",
        core="HealthSavingsAccount.growth_rate",
        typical_above_one=True,
    )
    employer_contribution_annual: NonNegativeMoney | None = spec_field(
        None,
        description="Employer contribution per year (continues after retirement until Plan 27 D3). Defaults to "
        "the configured amount.",
        unit="USD/year",
        core="HealthSavingsAccount.employer_contribution",
    )
    contribution_limit_annual: NonNegativeMoney | None = spec_field(
        None,
        description="Override of the annual contribution limit.",
        unit="USD/year",
        core="HealthSavingsAccount.contribution_limit",
    )
    basis: NonNegativeMoney | None = spec_field(
        None, description="Contribution basis.", unit="USD", not_yet_supported="Plan 27 D1"
    )


class Plan529(SpecModel):
    """A 529 education savings plan."""

    CORE_CLASS = "Plan529"

    kind: Literal["529"]
    id: Identifier | None = _id_field("account")
    beneficiary: Identifier | None = spec_field(
        None, description="Id of one of the owner's children.", core="Plan529.beneficiary"
    )
    balance: NonNegativeMoney = spec_field(0.0, description="Balance.", unit="USD", core="Plan529.balance")
    plan_state: str = spec_field("NY", description="Sponsoring state (informational in core).", core="Plan529.state")
    growth_pct: GrowthPct = spec_field(
        "economy",
        description="Annual return; 'economy' follows the equity return.",
        unit="percent",
        core="Plan529.growth_rate",
        typical_above_one=True,
    )
    contribution_limit_annual: NonNegativeMoney | None = spec_field(
        None, description="Annual limit override.", unit="USD/year", core="Plan529.annual_contribution_limit"
    )
    lifetime_contribution_limit: NonNegativeMoney | None = spec_field(
        None, description="Lifetime limit override.", unit="USD", core="Plan529.lifetime_contribution_limit"
    )
    basis: NonNegativeMoney | None = spec_field(
        None, description="Contribution basis.", unit="USD", not_yet_supported="Plan 27 D1"
    )


class InheritedPretaxAccount(SpecModel):
    """An inherited pre-tax account drawn down under the SECURE Act 10-year rule."""

    CORE_CLASS = "InheritedPretaxAccount"

    kind: Literal["inherited_pretax"]
    id: Identifier | None = _id_field("account")
    balance: NonNegativeMoney = spec_field(description="Balance.", unit="USD", core="InheritedPretaxAccount.balance")
    decedent_name: str = spec_field(description="Name of the decedent.", core="InheritedPretaxAccount.decedent_name")
    years: int = spec_field(
        10, description="Distribution window.", unit="years", core="InheritedPretaxAccount.years", ge=1
    )


class Pension(SpecModel):
    """A defined-benefit pension: a flat benefit, or the accrual formula (multiplier x service x salary)."""

    CORE_CLASS = "Pension"

    kind: Literal["pension"]
    id: Identifier | None = _id_field("account")
    company: str = spec_field(description="Plan sponsor.", core="Pension.company")
    vesting_years: int = spec_field(
        description="Years of service to vest.", unit="years", core="Pension.vesting_years", ge=0
    )
    benefit_annual: NonNegativeMoney = spec_field(
        0.0,
        description="Flat annual benefit (ignored when the formula is given).",
        unit="USD/year",
        core="Pension.benefit_amount",
    )
    start_age: AgeFloat | None = spec_field(
        None, description="Benefit start age (defaults to the retirement age).", unit="age", core="Pension.start_age"
    )
    cola_pct: NonNegativePercent = spec_field(
        0.0, description="Annual cost-of-living adjustment once in pay.", unit="percent", core="Pension.cola_percent"
    )
    survivor_pct: NonNegativePercent = spec_field(
        0.0,
        description="Share continued to a surviving spouse (50 = joint-and-50%).",
        unit="percent",
        core="Pension.survivor_percent",
        typical_above_one=True,
        le=100,
    )
    years_of_service: int | None = spec_field(
        None,
        description="Credited service (defaults to vesting_years).",
        unit="years",
        core="Pension.years_of_service",
        ge=0,
    )
    benefit_multiplier_pct: NonNegativePercent | None = spec_field(
        None,
        description="Percent of final salary accrued per year of service (with final_salary_annual).",
        unit="percent",
        core="Pension.benefit_multiplier",
    )
    final_salary_annual: NonNegativeMoney | None = spec_field(
        None, description="Final(-average) salary for the formula.", unit="USD/year", core="Pension.final_salary"
    )
    job: Identifier | None = spec_field(
        None,
        description="Id of the owner's sponsoring job. Defaults to the owner's job whose company equals 'company' "
        "(if any).",
        core="Pension.job",
    )
    accrues_service: bool = spec_field(
        True,
        description="A year of service (and vesting) accrues for each year the sponsoring job books payroll; a "
        "formula benefit's final salary follows that job.",
        core="Pension.accrues_service",
    )
    early_retirement_reduction_pct: NonNegativePercent | None = spec_field(
        None, description="Reduction per year before normal age.", unit="percent", not_yet_supported="Plan 27 item 5"
    )
    lump_sum_option: bool = spec_field(False, description="Lump-sum election.", not_yet_supported="Plan 27 item 5")

    @model_validator(mode="after")
    def _formula_pair(self) -> "Pension":
        if (self.benefit_multiplier_pct is None) != (self.final_salary_annual is None):
            raise ValueError("benefit_multiplier_pct and final_salary_annual must be given together")
        return self


class Annuity(SpecModel):
    """An annuity contract."""

    CORE_CLASS = "Annuity"

    kind: Literal["annuity"]
    id: Identifier | None = _id_field("account")
    annuity_type: Literal["fixed", "variable", "immediate", "deferred"] = spec_field(
        description="Contract type.", core="Annuity.annuity_type"
    )
    balance: NonNegativeMoney = spec_field(
        0.0, description="Contract value.", unit="USD", core="Annuity.initial_balance"
    )
    interest_pct: Percent | None = spec_field(
        None,
        description="Crediting rate; defaults to the configured rate.",
        unit="percent",
        core="Annuity.interest_rate",
        typical_above_one=True,
    )
    payout_type: Literal["life_only", "life_with_period_certain", "joint_and_survivor", "lump_sum"] = spec_field(
        "life_only", description="Payout option.", core="Annuity.payout_type"
    )
    payout_start_age: Age | None = spec_field(
        None,
        description="Age the contract annuitizes. Unset: an immediate annuity pays now, a deferred one at the "
        "configured age, and a fixed or variable one stays in accumulation.",
        unit="age",
        core="Annuity.payout_start_age",
    )
    payout_monthly: NonNegativeMoney | None = spec_field(
        None, description="Fixed monthly payout (computed when unset).", unit="USD/month", core="Annuity.monthly_payout"
    )
    period_certain_years: int | None = spec_field(
        None,
        description="Guaranteed years for period certain.",
        unit="years",
        core="Annuity.period_certain_years",
        ge=0,
    )
    surrender_charge_years: int | None = spec_field(
        None, description="Years surrender charges apply.", unit="years", core="Annuity.surrender_charge_years", ge=0
    )
    surrender_charge_pct: NonNegativePercent | None = spec_field(
        None, description="Surrender charge rate.", unit="percent", core="Annuity.surrender_charge_rate"
    )
    joint_annuitant: Identifier | None = spec_field(
        None, description="Person id of the second life (joint_and_survivor).", core="Annuity.joint_annuitant"
    )
    survivor_pct: NonNegativePercent = spec_field(
        100.0,
        description="Share continued to the joint annuitant.",
        unit="percent",
        core="Annuity.survivor_percent",
        le=100,
    )
    basis: NonNegativeMoney | None = spec_field(
        None, description="Cost basis of an existing contract.", unit="USD", not_yet_supported="Plan 27 D1"
    )
    purchase_year: Year | None = spec_field(
        None, description="Year purchased (surrender clock).", unit="year", not_yet_supported="Plan 27 D1"
    )
    qualified: bool | None = spec_field(
        None, description="Held in a qualified (pre-tax) plan.", not_yet_supported="Plan 27 D1"
    )


class DonorAdvisedFund(SpecModel):
    """A donor-advised fund."""

    CORE_CLASS = "DonorAdvisedFund"

    kind: Literal["daf"]
    id: Identifier | None = _id_field("account")
    name: str = spec_field("DAF", description="Fund name.", core="DonorAdvisedFund.fund_name")
    balance: NonNegativeMoney = spec_field(0.0, description="Balance.", unit="USD", core="DonorAdvisedFund.balance")
    growth_pct: Percent = spec_field(
        7.0, description="Annual return.", unit="percent", core="DonorAdvisedFund.growth_rate", typical_above_one=True
    )
    management_fee_pct: NonNegativePercent = spec_field(
        0.6, description="Annual fee.", unit="percent", core="DonorAdvisedFund.management_fee"
    )
    distribution_pct: NonNegativePercent = spec_field(
        5.0,
        description="Share granted to charity each year.",
        unit="percent",
        core="DonorAdvisedFund.distribution_rate",
        typical_above_one=True,
    )


class Trust(SpecModel):
    """A revocable or irrevocable trust; the owning person is the grantor."""

    CORE_CLASS = "Trust"

    kind: Literal["trust"]
    id: Identifier | None = _id_field("account")
    trust_type: Literal["revocable", "irrevocable"] = spec_field(description="Trust type.", core="Trust.trust_type")
    beneficiaries: list[Identifier] = spec_field(
        default_factory=list, description="Person ids of the beneficiaries.", core="Trust.beneficiaries"
    )
    name: str = spec_field("Trust", description="Display name.", core="Trust.name")
    balance: NonNegativeMoney = spec_field(
        0.0, description="Initial corpus (not a gift).", unit="USD", core="Trust.balance"
    )
    growth_pct: GrowthPct = spec_field(
        "economy",
        description="Annual return; 'economy' follows the asset class.",
        unit="percent",
        core="Trust.growth_rate",
        typical_above_one=True,
    )
    asset_class: Literal["equity", "bond", "cash"] = spec_field(
        "equity", description="Asset class.", core="Trust.asset_class"
    )


Account = Annotated[
    BankAccount
    | FixedIncomeAccount
    | BrokerageAccount
    | Job401k
    | TraditionalIRA
    | RothIRA
    | HealthSavingsAccount
    | Plan529
    | InheritedPretaxAccount
    | Pension
    | Annuity
    | DonorAdvisedFund
    | Trust,
    Field(discriminator="kind"),
]


def _string_kind(item: Any) -> Any:
    """YAML reads ``kind: 529`` as an integer; the discriminator needs the string."""
    if isinstance(item, dict) and isinstance(item.get("kind"), int) and not isinstance(item.get("kind"), bool):
        return {**item, "kind": str(item["kind"])}
    return item


# --- Debts ---------------------------------------------------------------------------------------

_LOAN_WORKAROUND = (
    "A loan already in progress is entered as original_amount plus the current balance; the builder "
    "passes loan_amount=original_amount, principal=balance (the undocumented core workaround), so the "
    "payment follows the original amortization and the loan pays off over its remaining term. Plan 27 "
    "D1/D7 adds origination dates and months."
)


class CarLoan(SpecModel):
    __doc__ = f"An auto loan. {_LOAN_WORKAROUND}"

    CORE_CLASS = "CarLoan"

    kind: Literal["car"]
    id: Identifier | None = _id_field("debt")
    name: str = spec_field("Car", description="Vehicle (make/model).", core="CarLoan.name")
    original_amount: NonNegativeMoney = spec_field(
        description="Amount originally borrowed.", unit="USD", core="CarLoan.loan_amount"
    )
    balance: NonNegativeMoney | None = spec_field(
        None, description="Current principal (defaults to original_amount).", unit="USD", core="CarLoan.principal"
    )
    rate_pct: NonNegativePercent = spec_field(
        description="APR.", unit="percent", core="CarLoan.yearly_interest_rate", typical_above_one=True
    )
    term_years: int = spec_field(
        description="Original term in whole years.", unit="years", core="CarLoan.length_years", ge=0
    )
    payment_monthly: NonNegativeMoney | None = spec_field(
        None, description="Monthly payment (computed when unset).", unit="USD/month", core="CarLoan.monthly_payment"
    )
    term_months: int | None = spec_field(
        None, description="Term in months (66, 75, ...).", unit="months", not_yet_supported="Plan 27 D7"
    )
    origination: YearMonth | None = spec_field(
        None, description="Origination month.", unit="YYYY-MM", not_yet_supported="Plan 27 D1"
    )
    payments_made: int | None = spec_field(None, description="Payments already made.", not_yet_supported="Plan 27 D1")
    extra_principal_monthly: NonNegativeMoney | None = spec_field(
        None, description="Extra principal each month.", unit="USD/month", not_yet_supported="Plan 27 D7"
    )


class StudentLoan(SpecModel):
    __doc__ = f"A student loan. {_LOAN_WORKAROUND}"

    CORE_CLASS = "StudentLoan"

    kind: Literal["student"]
    id: Identifier | None = _id_field("debt")
    loan_type: Literal["federal_subsidized", "federal_unsubsidized", "private", "plus"] = spec_field(
        description="Loan program.", core="StudentLoan.loan_type"
    )
    school: str = spec_field("School", description="School name.", core="StudentLoan.school_name")
    original_amount: NonNegativeMoney = spec_field(
        description="Amount originally borrowed.", unit="USD", core="StudentLoan.loan_amount"
    )
    balance: NonNegativeMoney | None = spec_field(
        None, description="Current principal (defaults to original_amount).", unit="USD", core="StudentLoan.principal"
    )
    rate_pct: NonNegativePercent = spec_field(
        description="Interest rate.", unit="percent", core="StudentLoan.yearly_interest_rate", typical_above_one=True
    )
    term_years: int = spec_field(
        description="Original term in whole years.", unit="years", core="StudentLoan.length_years", ge=0
    )
    payment_monthly: NonNegativeMoney | None = spec_field(
        None, description="Monthly payment (computed when unset).", unit="USD/month", core="StudentLoan.monthly_payment"
    )
    in_deferment: bool = spec_field(False, description="In deferment (no payments).", core="StudentLoan.in_deferment")
    repayment_plan: Literal["standard", "repayment_assistance_plan"] = spec_field(
        "standard",
        description="Standard amortization or the income-driven RAP (federal only).",
        core="StudentLoan.repayment_plan",
    )
    deferment_until: Year | None = spec_field(
        None, description="Last deferment year.", unit="year", not_yet_supported="Plan 27 item 12"
    )
    qualifying_payments: int | None = spec_field(
        None, description="Prior forgiveness-qualifying payments.", not_yet_supported="Plan 27 D1"
    )
    term_months: int | None = spec_field(
        None, description="Term in months.", unit="months", not_yet_supported="Plan 27 D7"
    )
    payments_made: int | None = spec_field(None, description="Payments already made.", not_yet_supported="Plan 27 D1")


class CreditCard(SpecModel):
    """A credit card (revolving debt). New charges from spending are not modeled (Plan 27 item 12)."""

    CORE_CLASS = "CreditCard"

    kind: Literal["credit_card"]
    id: Identifier | None = _id_field("debt")
    name: str = spec_field("Card", description="Card issuer.", core="CreditCard.card_name")
    credit_limit: NonNegativeMoney = spec_field(description="Credit limit.", unit="USD", core="CreditCard.credit_limit")
    balance: NonNegativeMoney = spec_field(
        0.0, description="Current balance owed.", unit="USD", core="CreditCard.current_balance"
    )
    rate_pct: NonNegativePercent | None = spec_field(
        None,
        description="APR (configured default when unset).",
        unit="percent",
        core="CreditCard.yearly_interest_rate",
        typical_above_one=True,
    )
    minimum_payment_pct: NonNegativePercent | None = spec_field(
        None,
        description="Minimum payment, percent of balance.",
        unit="percent",
        core="CreditCard.minimum_payment_percent",
    )
    card_type: Literal["visa", "mastercard", "american_express", "discover", "store_card"] | None = spec_field(
        None, description="Card network.", core="CreditCard.card_type"
    )
    payment_strategy: Literal["minimum", "full_balance", "fixed"] = spec_field(
        "minimum", description="How the balance is paid down each month.", core="CreditCard.payment_strategy"
    )
    payment_monthly: NonNegativeMoney = spec_field(
        0.0, description="Monthly payment for the 'fixed' strategy.", unit="USD/month", core="CreditCard.fixed_payment"
    )


Debt = Annotated[CarLoan | StudentLoan | CreditCard, Field(discriminator="kind")]


# --- Housing -------------------------------------------------------------------------------------


class Mortgage(SpecModel):
    __doc__ = (
        "The mortgage on a home. "
        + _LOAN_WORKAROUND.replace("the loan pays off", "the mortgage pays off")
        + " start_year is stored by core but not yet used for amortization (Plan 27 item 11)."
    )

    CORE_CLASS = "Mortgage"

    original_amount: NonNegativeMoney = spec_field(
        description="Amount originally borrowed.", unit="USD", core="Mortgage.loan_amount"
    )
    balance: NonNegativeMoney | None = spec_field(
        None, description="Current principal (defaults to original_amount).", unit="USD", core="Mortgage.principal"
    )
    rate_pct: NonNegativePercent = spec_field(
        description="Interest rate.", unit="percent", core="Mortgage.yearly_interest_rate", typical_above_one=True
    )
    term_years: int = spec_field(
        description="Original term (30, 15, ...).", unit="years", core="Mortgage.length_years", ge=0
    )
    start_year: Year | None = spec_field(
        None,
        description="Year the loan was originated (defaults to the start year).",
        unit="year",
        core="Mortgage.start_date",
    )
    payment_monthly: NonNegativeMoney | None = spec_field(
        None,
        description="Principal and interest per month (computed when unset; exclude escrow).",
        unit="USD/month",
        core="Mortgage.monthly_payment",
    )
    origination: YearMonth | None = spec_field(
        None, description="Origination month.", unit="YYYY-MM", not_yet_supported="Plan 27 D1"
    )
    remaining_months: int | None = spec_field(
        None, description="Months remaining.", unit="months", not_yet_supported="Plan 27 D1"
    )
    escrow_monthly: NonNegativeMoney | None = spec_field(
        None, description="Escrow included in the statement payment.", unit="USD/month", not_yet_supported="Plan 27 D1"
    )
    extra_principal_monthly: NonNegativeMoney | None = spec_field(
        None, description="Extra principal each month.", unit="USD/month", not_yet_supported="Plan 27 D7"
    )


class HomeExpenses(SpecModel):
    """Recurring costs of owning a home."""

    CORE_CLASS = "HomeExpenses"

    property_tax_pct: NonNegativePercent = spec_field(
        description="Property tax per year, percent of market value.",
        unit="percent",
        core="HomeExpenses.property_tax_percent",
    )
    insurance_pct: NonNegativePercent = spec_field(
        description="Homeowner's insurance per year, percent of market value.",
        unit="percent",
        core="HomeExpenses.home_insurance_percent",
    )
    maintenance_annual: NonNegativeMoney = spec_field(
        0.0, description="Maintenance.", unit="USD/year", core="HomeExpenses.maintenance_amount"
    )
    maintenance_growth_pct: Percent = spec_field(
        0.0, description="Yearly increase of maintenance.", unit="percent", core="HomeExpenses.maintenance_increase"
    )
    improvement_annual: NonNegativeMoney = spec_field(
        0.0, description="Improvements (added to cost basis).", unit="USD/year", core="HomeExpenses.improvement_amount"
    )
    improvement_growth_pct: Percent = spec_field(
        0.0, description="Yearly increase of improvements.", unit="percent", core="HomeExpenses.improvement_increase"
    )
    hoa_monthly: NonNegativeMoney = spec_field(
        0.0,
        description="HOA dues per month (core stores the annual amount).",
        unit="USD/month",
        core="HomeExpenses.hoa_amount",
    )
    hoa_growth_pct: Percent = spec_field(
        0.0, description="Yearly increase of HOA dues.", unit="percent", core="HomeExpenses.hoa_increase"
    )


class Home(SpecModel):
    """An owned home (optionally with a mortgage)."""

    CORE_CLASS = "Home"

    kind: Literal["home"]
    id: Identifier | None = _id_field("home")
    name: str = spec_field("Home", description="Name of the house.", core="Home.name")
    purchase_price: NonNegativeMoney = spec_field(
        description="Purchase price; also the starting market value and cost basis in core (Plan 27 item 10).",
        unit="USD",
        core="Home.purchase_price",
    )
    value_growth_pct: GrowthPct = spec_field(
        "economy",
        description="Yearly appreciation; 'economy' follows home appreciation.",
        unit="percent",
        core="Home.value_yearly_increase",
        typical_above_one=True,
    )
    down_payment: NonNegativeMoney = spec_field(0.0, description="Down payment.", unit="USD", core="Home.down_payment")
    purchase: bool = spec_field(
        False,
        description="True: bought at the start (down payment and closing costs are paid from the owner's accounts). "
        "False: already owned, no cash changes hands.",
        core="Home.purchase",
    )
    mortgage: Mortgage | None = spec_field(None, description="The mortgage, if any.")
    expenses: HomeExpenses = spec_field(description="Recurring ownership costs.")
    current_value: NonNegativeMoney | None = spec_field(
        None,
        description="Market value today (distinct from purchase price).",
        unit="USD",
        not_yet_supported="Plan 27 D1",
    )
    cost_basis: NonNegativeMoney | None = spec_field(
        None, description="Section 121 cost basis.", unit="USD", not_yet_supported="Plan 27 D1"
    )
    purchase_year: Year | None = spec_field(
        None, description="Year purchased.", unit="year", not_yet_supported="Plan 27 D1"
    )


class Rental(SpecModel):
    """A rented apartment."""

    CORE_CLASS = "Apartment"

    kind: Literal["rental"]
    id: Identifier | None = _id_field("rental")
    name: str = spec_field("Apartment", description="Name of the rental.", core="Apartment.name")
    rent_monthly: NonNegativeMoney = spec_field(
        description="Monthly rent.", unit="USD/month", core="Apartment.monthly_rent"
    )
    rent_growth_pct: GrowthPct = spec_field(
        5.0,
        description="Yearly rent increase; 'economy' follows inflation. The core default is 5 (the validator warns "
        "when it is left unset).",
        unit="percent",
        core="Apartment.yearly_increase",
        typical_above_one=True,
    )


Housing = Annotated[Home | Rental, Field(discriminator="kind")]


# --- Insurance -----------------------------------------------------------------------------------


class LifeInsurance(SpecModel):
    """A term or whole life policy (``premium_schedule`` maps to ``PremiumIncreaseType``)."""

    CORE_CLASS = "LifeInsurance"

    kind: Literal["life"]
    id: Identifier | None = _id_field("policy")
    policy: Literal["term", "whole"] = spec_field(description="Policy type.", core="LifeInsurance.policy_type")
    death_benefit: NonNegativeMoney = spec_field(
        description="Death benefit.", unit="USD", core="LifeInsurance.death_benefit"
    )
    premium_monthly: NonNegativeMoney = spec_field(
        description="Monthly premium.", unit="USD/month", core="LifeInsurance.monthly_premium"
    )
    term_years: int | None = spec_field(
        None, description="Term length (term policies).", unit="years", core="LifeInsurance.term_years", ge=1
    )
    premium_schedule: Literal["level", "age_banded", "yearly_increase"] = spec_field(
        "level",
        description="'level' fixed premium; 'age_banded' core's configured age multipliers; 'yearly_increase' "
        "grows by premium_increase_pct.",
        core="LifeInsurance.premium_increase_rate",
    )
    premium_increase_pct: NonNegativePercent | None = spec_field(
        None,
        description="Yearly premium increase for premium_schedule 'yearly_increase'.",
        unit="percent",
        core="LifeInsurance.premium_increase_rate",
    )
    cash_value_growth_pct: Percent | None = spec_field(
        None, description="Whole-life cash value growth.", unit="percent", core="LifeInsurance.cash_value_growth_rate"
    )
    loan_interest_pct: NonNegativePercent | None = spec_field(
        None, description="Policy loan interest.", unit="percent", core="LifeInsurance.loan_interest_rate"
    )
    max_missed_payments: int | None = spec_field(
        None, description="Missed payments before lapse.", core="LifeInsurance.max_missed_payments", ge=0
    )
    beneficiary: Identifier | None = spec_field(
        None, description="Person id of the designated beneficiary.", core="LifeInsurance.beneficiary"
    )
    issue_year: Year | None = spec_field(None, description="Year issued.", unit="year", not_yet_supported="Plan 27 D1")
    cash_value: NonNegativeMoney | None = spec_field(
        None, description="Existing cash value.", unit="USD", not_yet_supported="Plan 27 D1"
    )
    loan_balance: NonNegativeMoney | None = spec_field(
        None, description="Existing policy loan.", unit="USD", not_yet_supported="Plan 27 D1"
    )
    group: bool = spec_field(False, description="Employer group life.", not_yet_supported="Plan 27 item 13")

    @model_validator(mode="after")
    def _schedule(self) -> "LifeInsurance":
        if self.premium_schedule == "yearly_increase" and not self.premium_increase_pct:
            raise ValueError("premium_schedule 'yearly_increase' needs a positive premium_increase_pct")
        if self.premium_schedule != "yearly_increase" and self.premium_increase_pct is not None:
            raise ValueError("premium_increase_pct is only used with premium_schedule 'yearly_increase'")
        return self


class GeneralInsurance(SpecModel):
    """A general insurance policy (premium-only in core except for claims)."""

    CORE_CLASS = "Insurance"

    kind: Literal["health", "disability", "umbrella", "ltc", "auto", "home", "renters", "flood", "earthquake"]
    id: Identifier | None = _id_field("policy")
    company: str = spec_field("Insurer", description="Insurer.", core="Insurance.company")
    premium_annual: NonNegativeMoney = spec_field(
        description="Annual premium.", unit="USD/year", core="Insurance.annual_premium"
    )
    coverage_amount: NonNegativeMoney = spec_field(
        description="Coverage limit.", unit="USD", core="Insurance.coverage_amount"
    )
    deductible: NonNegativeMoney = spec_field(0.0, description="Deductible.", unit="USD", core="Insurance.deductible")
    coverage_start_age: Age | None = spec_field(
        None, description="Coverage start age (immediate when unset).", unit="age", core="Insurance.coverage_start_age"
    )
    coverage_end_age: Age | None = spec_field(
        None, description="Coverage end age (lifetime when unset).", unit="age", core="Insurance.coverage_end_age"
    )
    premium_increase_pct: NonNegativePercent | None = spec_field(
        None,
        description="Yearly premium increase (configured default when unset).",
        unit="percent",
        core="Insurance.premium_increase_rate",
    )
    max_claims_per_year: int | None = spec_field(
        None, description="Claims allowed per year.", core="Insurance.max_claims_per_year", ge=0
    )
    oop_max_annual: NonNegativeMoney | None = spec_field(
        None, description="Health out-of-pocket maximum.", unit="USD/year", not_yet_supported="Plan 27 D9"
    )
    coinsurance_pct: NonNegativePercent | None = spec_field(
        None, description="Health coinsurance.", unit="percent", not_yet_supported="Plan 27 D9"
    )


Insurance = Annotated[LifeInsurance | GeneralInsurance, Field(discriminator="kind")]


# --- Social Security, healthcare, giving, children ---------------------------------------------


class SocialSecurity(SpecModel):
    """Social Security retirement benefits from an earnings record."""

    CORE_CLASS = "SocialSecurity"

    claim_age: AgeFloat | None = spec_field(
        None,
        description="Claiming age (62-70); defaults to the retirement age, which must then be at least 62.",
        unit="age",
        core="SocialSecurity.withdrawal_start_age",
    )
    earnings_history: dict[int, NonNegativeMoney] | None = spec_field(
        None,
        description="Covered earnings by year from the SSA statement, e.g. {2019: 47000, 2020: 48000}.",
        unit="USD/year",
        core="SocialSecurity.income_history",
    )
    assumed_career_start_age: Age | None = spec_field(
        None,
        description="Synthesize the earnings record instead: a flat real career at the first job's salary from "
        "this age to the year before start_year, indexed by the average wage index and capped at each year's "
        "wage base (years before 1978 dropped). Mutually exclusive with earnings_history.",
        unit="age",
    )
    pia_override_monthly: NonNegativeMoney | None = spec_field(
        None, description="PIA from the SSA statement.", unit="USD/month", not_yet_supported="Plan 27 D10"
    )
    spousal_benefit: bool = spec_field(False, description="Model the spousal benefit.", not_yet_supported="Plan 27 D10")

    @field_validator("earnings_history")
    @classmethod
    def _sorted_history(cls, value: dict[int, float] | None) -> dict[int, float] | None:
        return None if value is None else dict(sorted(value.items()))

    @model_validator(mode="after")
    def _one_history(self) -> "SocialSecurity":
        if self.earnings_history is not None and self.assumed_career_start_age is not None:
            raise ValueError("give either earnings_history or assumed_career_start_age, not both")
        return self


class Healthcare(SpecModel):
    """Opt-in healthcare cost agents."""

    medical_costs: bool = spec_field(False, description="Age-banded out-of-pocket medical costs.", core="MedicalCosts")
    medicare: bool = spec_field(
        False, description="Medicare premiums and IRMAA from the eligibility age.", core="Medicare"
    )
    long_term_care: bool = spec_field(False, description="Long-term-care hazard and costs.", core="LongTermCare")


class Donation(SpecModel):
    """A recurring charitable donation."""

    CORE_CLASS = "Donation"

    kind: Literal["donation"]
    id: Identifier | None = _id_field("donation")
    charity: str = spec_field(description="Charity name.", core="Donation.charity_name")
    amount_annual: NonNegativeMoney = spec_field(
        description="Amount given each time (every frequency_years).", unit="USD/year", core="Donation.annual_amount"
    )
    donation_type: Literal["cash", "stock", "property", "other", "qcd"] = spec_field(
        "cash",
        description="What is given: 'cash'; 'stock' (appreciated long-term shares from the person's brokerage "
        "accounts, deducted at fair market value up to 30% of AGI with no capital gain; any shortfall in cash); "
        "'qcd' (a qualified charitable distribution from the person's traditional IRAs from age 70½, up to the "
        "year's limit: not income, counts toward the RMD, not deductible; cash before then); 'property' and "
        "'other' are deducted like cash.",
        core="Donation.donation_type",
    )
    tax_deductible: bool = spec_field(True, description="Deductible.", core="Donation.tax_deductible")
    frequency_years: int = spec_field(
        1, description="Give every N years.", unit="years", core="Donation.frequency_years", ge=1
    )
    start_year: Year | None = spec_field(
        None, description="First year (defaults to start).", unit="year", core="Donation.start_year"
    )
    end_year: Year | None = spec_field(
        None, description="Last year (defaults to model end).", unit="year", core="Donation.end_year"
    )


Giving = Annotated[Donation, Field(discriminator="kind")]


class Child(SpecModel):
    """A child dependent: age-banded costs, the Child Tax Credit, 529 beneficiary."""

    CORE_CLASS = "Child"

    id: Identifier | None = _id_field("child")
    name: str = spec_field(description="Child's name.", core="Child.name")
    birth_year: Year = spec_field(
        description="Birth year (future years are planned births).", unit="year", core="Child.birth_year"
    )
    cost_override_annual: NonNegativeMoney | None = spec_field(
        None, description="Per-child cost instead of the config bands.", unit="USD/year", not_yet_supported="Plan 27 D6"
    )
    care_expenses_annual: NonNegativeMoney = spec_field(
        0.0,
        description="Dependent care (after-school care, day camp) paid while the child is under 13, on top of the "
        "age-band cost, in start-year dollars. The childcare band's cost (under 6) already counts as care "
        "expenses for the dependent care credit.",
        unit="USD/year",
        core="Child.care_expenses_annual",
    )
    interest_annual: NonNegativeMoney = spec_field(
        0.0,
        description="The child's own interest income (a custodial account, not part of the household's "
        "balances), reported by the parents on Form 8814 (kiddie tax).",
        unit="USD/year",
        core="Child.interest_annual",
    )
    dividends_annual: NonNegativeMoney = spec_field(
        0.0,
        description="The child's own qualified dividends (same as interest_annual).",
        unit="USD/year",
        core="Child.dividends_annual",
    )


# --- Plan 27 / Plan 31 person-level policies ----------------------------------------------------


class ContributionPlan(SpecModel):
    """A recurring contribution (Plan 27 D4)."""

    account: Identifier = spec_field(description="Target account id.")
    amount_annual: NonNegativeMoney | None = spec_field(None, description="Dollars per year.", unit="USD/year")
    pay_pct: NonNegativePercent | None = spec_field(None, description="Percent of pay.", unit="percent")
    source: Literal["bank", "payroll"] = spec_field("bank", description="Where the money comes from.")


class SavingsPolicy(SpecModel):
    """Surplus sweep above a cash floor (Plan 27 D4)."""

    cash_floor: NonNegativeMoney = spec_field(description="Cash kept in the bank.", unit="USD")
    sweep_to: Identifier = spec_field(description="Account receiving the surplus.")


class SelfEmployment(SpecModel):
    """Self-employment income (Plan 31): a sole proprietorship built as ``Job(kind="self_employed")``.

    The net profit (gross receipts less expenses) is paid to the bank like wages, taxed as Schedule C income
    with self-employment tax (Schedule SE, sharing the Social Security wage base with W-2 wages), half of it
    deducted, the SEP / solo 401(k) contribution deducted, and the qualified business income deduction.
    Withholding and estimated payments are not modeled yet (the tax is settled with the year, Plan 31 D3).
    A ``kind: 401k`` account whose ``job`` is this entry's ``id`` is a solo 401(k).
    """

    CORE_CLASS = "Job (kind='self_employed')"

    id: Identifier | None = _id_field("business (a solo 401k account names it as its job)")
    business: str = spec_field(description="Business name.", core="Job.company")
    net_profit_annual: NonNegativeMoney | None = spec_field(
        None,
        description="Schedule C net profit (line 31). Give it, or gross_receipts_annual and expenses_annual.",
        unit="USD/year",
        core="Salary.base",
    )
    gross_receipts_annual: NonNegativeMoney | None = spec_field(
        None, description="Gross receipts (Schedule C line 1).", unit="USD/year", core="Salary.base"
    )
    expenses_annual: NonNegativeMoney = spec_field(
        0.0,
        description="Business expenses (Schedule C line 28); they grow with the receipts.",
        unit="USD/year",
        core="Job.expenses_annual",
    )
    growth_pct: GrowthPct = spec_field(
        0.0, description="Yearly growth of the receipts; 'economy' follows wage growth.", unit="percent"
    )
    sep_ira_contrib_pct: NonNegativePercent = spec_field(
        0.0,
        description="Employer plan rate of the SEP (or the solo 401(k)'s profit sharing), at most 25: the owner "
        "contributes rate / (1 + rate) of net profit less half of SE tax (Pub. 560), within the year's limits.",
        unit="percent",
        core="Job.plan_contribution_percent",
        le=25,
    )
    sep_account: Identifier | None = spec_field(
        None,
        description="Id of the traditional_ira receiving the SEP contribution (default: the person's first "
        "traditional IRA, or a new one).",
        core="Job.sep_account",
    )
    sstb: bool = spec_field(False, description="A specified service trade or business (§199A(d)(2)).", core="Job.sstb")

    @model_validator(mode="after")
    def _profit_or_receipts(self) -> "SelfEmployment":
        if (self.net_profit_annual is None) == (self.gross_receipts_annual is None):
            raise ValueError("give either net_profit_annual, or gross_receipts_annual (with expenses_annual)")
        if self.net_profit_annual is not None and self.expenses_annual:
            raise ValueError("expenses_annual goes with gross_receipts_annual, not net_profit_annual")
        return self

    @property
    def receipts(self) -> float:
        return self.net_profit_annual if self.net_profit_annual is not None else float(self.gross_receipts_annual or 0)


# --- People --------------------------------------------------------------------------------------


class Person(SpecModel):
    """A person and everything they own."""

    CORE_CLASS = "Person"

    id: Identifier = spec_field(description="Unique person id (referenced by relationships, events, trusts).")
    name: str = spec_field(description="Display name.", core="Person.name")
    age: Age = spec_field(
        description="Age (completed years) in the first simulated month (meta.start, else January of start_year). "
        "Without birth the birth month is taken to be January, so the person is age for the rest of the first "
        "year and age + 1 the year after.",
        unit="age",
        core="Person.age",
    )
    birth: YearMonth | None = spec_field(
        None,
        description="Birth month (YYYY-MM) for exact ages: 59.5, the retirement month, Social Security and "
        "Medicare start in the right month. Must agree with age. When missing, January is assumed (the "
        "validator warns).",
        unit="YYYY-MM",
        core="Person.birth",
    )
    gender: Literal["male", "female", "other"] = spec_field(
        "other", description="Gender at birth for the mortality table ('other' blends).", core="Person.gender"
    )
    retirement_age: AgeFloat = spec_field(
        description="Age at which every job stops.", unit="age", core="Person.retirement_age"
    )
    state: str | None = spec_field(
        None, description="Two-letter state of residence (defaults to meta.default_state).", core="Person.state"
    )
    mortality: Literal["immortal", "stochastic", "fixed_age"] = spec_field(
        "immortal", description="How death is decided each year.", core="Person.mortality_mode"
    )
    death_age: Age | None = spec_field(
        None, description="Age of death for mortality 'fixed_age'.", unit="age", core="Person.death_age"
    )
    spending: Spending = spec_field(description="Living spending.")
    jobs: list[Job] = spec_field(default_factory=list, description="Jobs (W-2).")
    accounts: list[Account] = spec_field(default_factory=list, description="Accounts, discriminated by 'kind'.")
    debts: list[Debt] = spec_field(default_factory=list, description="Debts (car, student, credit_card).")
    housing: list[Housing] = spec_field(default_factory=list, description="Homes and rentals.")
    insurance: list[Insurance] = spec_field(default_factory=list, description="Insurance policies.")
    social_security: SocialSecurity | None = spec_field(None, description="Social Security benefits.")
    healthcare: Healthcare | None = spec_field(None, description="Opt-in healthcare cost agents.")
    giving: list[Giving] = spec_field(default_factory=list, description="Charitable giving.")
    children: list[Child] = spec_field(default_factory=list, description="Child dependents.")
    self_employment: SelfEmployment | None = spec_field(None, description="Self-employment income (Schedule C).")
    contribution_plans: list[ContributionPlan] | None = spec_field(
        None, description="Recurring contributions.", not_yet_supported="Plan 27 D4"
    )
    savings_policy: SavingsPolicy | None = spec_field(
        None, description="Surplus sweep above a cash floor.", not_yet_supported="Plan 27 D4"
    )

    @model_validator(mode="before")
    @classmethod
    def _account_kinds(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("accounts"), list):
            return {**data, "accounts": [_string_kind(item) for item in data["accounts"]]}
        return data

    @model_validator(mode="after")
    def _death_age(self) -> "Person":
        if self.mortality == "fixed_age" and self.death_age is None:
            raise ValueError("mortality 'fixed_age' needs death_age")
        return self


# --- Relationships -------------------------------------------------------------------------------


class Marriage(SpecModel):
    """A marriage. The first spouse listed is the head of the joint tax unit."""

    spouses: tuple[Identifier, Identifier] = spec_field(description="The two person ids; the first is the head.")
    year: Year | None = spec_field(
        None,
        description="Year married. Unset or <= start_year: married from the start. Later years become a 'marry' event.",
        unit="year",
    )
    filing_status: Literal["joint", "separate"] = spec_field(
        "joint", description="Married filing jointly or separately.", core="Person.filing_status"
    )


class Relationships(SpecModel):
    """Relationships between people."""

    marriages: list[Marriage] = spec_field(default_factory=list, description="Marriages.")


# --- Events --------------------------------------------------------------------------------------


class EventBase(SpecModel):
    """Common event fields."""

    id: Identifier | None = spec_field(None, description="Event id (needed to anchor relative events).")
    at: At = spec_field(description="When the event happens: {year}, {age} or {relative: {after, years}}.")
    person: Identifier = spec_field(description="Person the event applies to.")
    name: str | None = spec_field(None, description="Description shown in the event list.")


class MarryEvent(EventBase):
    """Marry another person in the household (``person`` becomes the head)."""

    action: Literal["marry"]
    spouse: Identifier = spec_field(description="Person id of the spouse.")
    filing_status: Literal["joint", "separate"] = spec_field("joint", description="Filing status after marrying.")


class DivorceEvent(EventBase):
    """Divorce (backlog)."""

    NOT_YET_SUPPORTED = "backlog (divorce)"

    action: Literal["divorce"]
    spouse: Identifier = spec_field(description="Person id of the spouse.")


class RetireEvent(EventBase):
    """Retire: every job stops and the retirement age becomes the current age."""

    action: Literal["retire"]


class ChangeJobEvent(EventBase):
    """Change a job: new salary, stop (quit / layoff with optional severance), or start a new job."""

    action: Literal["change_job"]
    job: Identifier | None = spec_field(None, description="Id of the existing job to change or stop.")
    salary_annual: NonNegativeMoney | None = spec_field(None, description="New base salary.", unit="USD/year")
    stop: bool = spec_field(False, description="Stop the job (quit or layoff).")
    severance: NonNegativeMoney = spec_field(
        0.0, description="One-time severance paid as wages on stopping.", unit="USD"
    )
    new_job: Job | None = spec_field(None, description="A job that starts at this time.")


class MoveEvent(EventBase):
    """Move: change state of residence, end a rental, and/or buy or sell a home."""

    action: Literal["move"]
    state: str | None = spec_field(None, description="New two-letter state (applies to the person and their spouse).")
    end_rental: Identifier | None = spec_field(None, description="Id of a rental that ends.")
    sell_home: Identifier | None = spec_field(None, description="Id of a home that is sold.")
    buy_home: Home | None = spec_field(None, description="A home bought now (always paid from accounts).")
    new_rental: Rental | None = spec_field(None, description="A rental that starts now.")


class BuyHomeEvent(EventBase):
    """Buy a home: down payment and closing costs are paid from the person's accounts."""

    action: Literal["buy_home"]
    home: Home = spec_field(description="The home bought ('purchase' is forced true).")


class SellHomeEvent(EventBase):
    """Sell a home: pay off the mortgage, realize the equity, tax the gain above the exclusion."""

    action: Literal["sell_home"]
    home: Identifier = spec_field(description="Id of the home.")
    selling_cost_pct: NonNegativePercent | None = spec_field(
        None, description="Selling costs (configured default when unset).", unit="percent"
    )


class OneTimeExpenseEvent(EventBase):
    """A one-time expense added to that year's spending."""

    action: Literal["one_time_expense"]
    amount: NonNegativeMoney = spec_field(description="Amount (one time).", unit="USD")


class RecurringExpenseEvent(EventBase):
    """An expense added every year from ``at`` through ``until`` (inclusive)."""

    action: Literal["recurring_expense"]
    amount_annual: NonNegativeMoney = spec_field(description="Amount per year.", unit="USD/year")
    until: At | None = spec_field(None, description="Last year (inclusive); the end of the simulation when unset.")


class ChangeSpendingEvent(EventBase):
    """Change base spending: a new annual amount, or a percent change."""

    action: Literal["change_spending"]
    amount_annual: NonNegativeMoney | None = spec_field(None, description="New base spending.", unit="USD/year")
    change_pct: Percent | None = spec_field(None, description="Percent change (-20 = cut by a fifth).", unit="percent")

    @model_validator(mode="after")
    def _one_of(self) -> "ChangeSpendingEvent":
        if (self.amount_annual is None) == (self.change_pct is None):
            raise ValueError("change_spending needs exactly one of amount_annual or change_pct")
        return self


class AddAccountEvent(EventBase):
    """Open an account."""

    action: Literal["add_account"]
    account: Account = spec_field(description="The account opened.")

    @model_validator(mode="before")
    @classmethod
    def _account_kind(cls, data: Any) -> Any:
        if isinstance(data, dict) and "account" in data:
            return {**data, "account": _string_kind(data["account"])}
        return data


class ContributeEvent(EventBase):
    """A one-time contribution from the bank into an account.

    Tax-advantaged accounts take at most their remaining annual room (the rest stays in the bank);
    the tax treatment is whatever the account's own ``contribute()`` applies. Recurring
    contributions are Plan 27 D4 (``contribution_plans``).
    """

    action: Literal["contribute"]
    account: Identifier = spec_field(description="Target account id.")
    amount: NonNegativeMoney = spec_field(description="Amount (one time).", unit="USD")


class ConvertToRothEvent(EventBase):
    """Roth conversion (Plan 27)."""

    NOT_YET_SUPPORTED = "Plan 27 item 3"

    action: Literal["convert_to_roth"]
    amount: NonNegativeMoney = spec_field(description="Amount converted.", unit="USD")
    source: Identifier | None = spec_field(None, description="Source account id.")


class ClaimSocialSecurityEvent(EventBase):
    """Claim Social Security (sets the claiming age; the person needs social_security)."""

    action: Literal["claim_social_security"]


class DieEvent(EventBase):
    """Death at a given time (sets fixed-age mortality)."""

    action: Literal["die"]


Event = Annotated[
    MarryEvent
    | DivorceEvent
    | RetireEvent
    | ChangeJobEvent
    | MoveEvent
    | BuyHomeEvent
    | SellHomeEvent
    | OneTimeExpenseEvent
    | RecurringExpenseEvent
    | ChangeSpendingEvent
    | AddAccountEvent
    | ContributeEvent
    | ConvertToRothEvent
    | ClaimSocialSecurityEvent
    | DieEvent,
    Field(discriminator="action"),
]

#: Every event action name, in schema order.
EVENT_ACTIONS: tuple[str, ...] = (
    "marry",
    "divorce",
    "retire",
    "change_job",
    "move",
    "buy_home",
    "sell_home",
    "one_time_expense",
    "recurring_expense",
    "change_spending",
    "add_account",
    "contribute",
    "convert_to_roth",
    "claim_social_security",
    "die",
)


#: Payment sources of the household waterfall (``people.tax_unit.DEFAULT_WITHDRAWAL_ORDER``).
WithdrawalSource = Literal["bank", "brokerage", "roth_basis", "pretax", "roth_earnings"]


# --- Top level -----------------------------------------------------------------------------------

from .actuals import ActualsByYear  # (imported here: actuals reads the unit types defined above)


class HouseholdSpec(SpecModel):
    """A complete household: metadata, optional economy overrides, people, relationships, events."""

    spec_version: Literal[1] = spec_field(SPEC_VERSION, description="Spec format version.")
    meta: Meta = spec_field(description="Run metadata.")
    economy: Economy | None = spec_field(None, description="Economy overrides.")
    people: list[Person] = spec_field(description="The people in the household (one family).", min_length=1)
    relationships: Relationships = spec_field(default_factory=Relationships, description="Marriages.")
    withdrawal_order: list[WithdrawalSource] | None = spec_field(
        None,
        description="Household payment waterfall: the order sources are drawn to pay bills and taxes, across "
        "every member. Each source exactly once, starting with 'bank'. Defaults to bank, brokerage, roth_basis, "
        "pretax, roth_earnings.",
        core="Family.withdrawal_order",
    )
    events: list[Event] = spec_field(default_factory=list, description="Dated life events.")
    actuals: ActualsByYear | None = spec_field(
        None,
        description="What the household's real documents say, by tax year (filed 1040 lines, W-2s, 1099s, "
        "statement balances): read by 'life-model reconcile' and the backtest, ignored by the builder. Keep real "
        "documents in my-models/ (git-ignored).",
    )

    @field_validator("withdrawal_order")
    @classmethod
    def _valid_order(cls, value: list[str] | None) -> list[str] | None:
        if value is not None:
            from ..people.tax_unit import validate_withdrawal_order

            validate_withdrawal_order(value)
        return value

    def person(self, person_id: str) -> Person:
        """The person with ``person_id`` (``KeyError`` when absent)."""
        for person in self.people:
            if person.id == person_id:
                return person
        raise KeyError(person_id)


def json_schema() -> dict[str, Any]:
    """The JSON Schema of :class:`HouseholdSpec` (for tool-use definitions)."""
    return HouseholdSpec.model_json_schema()
