"""
Mesa Dashboard for Life Model Financial Simulation

This module provides a Solara-based interactive dashboard for the life_model
financial simulation package. Users can configure family parameters, choose an
economic scenario, run simulations, and visualize financial projections.

Based on the ExampleSimulation.ipynb notebook.
"""

from datetime import datetime
from typing import Any

import solara
from matplotlib.figure import Figure
from mesa.visualization import Slider, SolaraViz, make_plot_component
from mesa.visualization.utils import update_counter

from life_model.config.financial_config import FinancialConfig
from life_model.config.models import DEFAULT_STATE_KEY
from life_model.config.scenarios import list_scenarios
from life_model.model import LifeModel
from life_model.people.family import Family
from life_model.spec import HouseholdSpec, populate_model

# Label used in the scenario dropdown for "use the packaged defaults" (scenario=None).
SCENARIO_DEFAULT_LABEL = "(default)"

# State-of-residence choices for the state dropdown: the packs shipped in the packaged defaults.
# DEFAULT (the legacy flat rate) stays first so it is the dropdown's default selection.
STATE_CHOICES = [DEFAULT_STATE_KEY] + sorted(
    code for code in FinancialConfig().tax.state.packs if code != DEFAULT_STATE_KEY
)

current_year = datetime.now().astimezone().year


def param_value(spec: Any) -> Any:
    """Normalize a model-parameter spec to a plain value.

    SolaraViz constructs the model two ways: at import time it passes the raw ``model_params``
    specs (``Slider`` objects and ``{"type": ..., "value": ...}`` dicts), and after a control
    changes it passes plain values. This collapses all three forms to a plain value so the model
    constructor behaves identically in every path.
    """
    if isinstance(spec, Slider):
        return spec.value
    if isinstance(spec, dict) and "value" in spec:
        return spec["value"]
    return spec


# --- Single source of truth for defaults -----------------------------------------------------
# Each person's defaults power BOTH the SolaraViz control specs (model_params) and the fallback
# values used when the model is constructed directly (import time / tests). Keeping them in one
# place is what keeps the two construction paths in agreement.

PERSON_DEFAULTS: dict[str, dict[str, Any]] = {
    "john": {
        "enabled": True,
        "age": 44,
        "retirement_age": 60,
        "company": "Company A",
        "role": "Manager",
        "bank_company": "Bank",
        "salary": 50000,
        "bonus": 0,
        "spending": 12000,
        "bank_balance": 20000,
        "retirement_enabled": True,
        "retirement_balance": 0,
        "retirement_contrib": 6,
        "company_match": 3,
        "retirement_growth": 7.0,
        "children": 0,
    },
    "jane": {
        "enabled": True,
        "age": 45,
        "retirement_age": 60,
        "company": "Company B",
        "role": "Developer",
        "bank_company": "Credit Union",
        "salary": 65000,
        "bonus": 0,
        "spending": 12000,
        "bank_balance": 30000,
        "retirement_enabled": True,
        "retirement_balance": 0,
        "retirement_contrib": 6,
        "company_match": 3,
        "retirement_growth": 7.0,
        "children": 0,
    },
}

SHARED_DEFAULTS: dict[str, Any] = {
    "start_year": current_year,
    "end_year": current_year + 50,
    "salary_increase": 2.0,
    "spending_increase": 3.0,
    "bank_interest_rate": 0.5,
    "home_enabled": False,
    "home_price": 400000,
    "mortgage_rate": 6.0,
    "mortgage_term": 30,
    # Healthcare agents (medical cost curve, Medicare, long-term care) are opt-in and default
    # off so existing dashboard runs keep producing the same numbers.
    "healthcare_enabled": False,
}


def _person_param_specs(prefix: str, name: str) -> dict[str, Any]:
    """Build the SolaraViz control specs for one person from that person's defaults."""
    d = PERSON_DEFAULTS[prefix]
    return {
        f"{prefix}_enabled": {"label": f"Include {name}", "type": "Checkbox", "value": d["enabled"]},
        f"{prefix}_age": Slider(f"{name}'s Age", d["age"], 18, 80, 1),
        f"{prefix}_retirement_age": Slider(f"{name}'s Retirement Age", d["retirement_age"], 50, 70, 1),
        f"{prefix}_salary": Slider(f"{name}'s Salary ($)", d["salary"], 30000, 150000, 5000),
        f"{prefix}_bonus": Slider(f"{name}'s Annual Bonus (%)", d["bonus"], 0, 50, 1),
        f"{prefix}_spending": Slider(f"{name}'s Annual Spending ($)", d["spending"], 5000, 50000, 1000),
        f"{prefix}_bank_balance": Slider(f"{name}'s Initial Bank Balance ($)", d["bank_balance"], 0, 100000, 5000),
        f"{prefix}_retirement_enabled": {
            "label": f"{name} has a 401k",
            "type": "Checkbox",
            "value": d["retirement_enabled"],
        },
        f"{prefix}_retirement_balance": Slider(f"{name}'s 401k Balance ($)", d["retirement_balance"], 0, 500000, 5000),
        f"{prefix}_retirement_contrib": Slider(f"{name}'s 401k Contribution (%)", d["retirement_contrib"], 0, 50, 1),
        f"{prefix}_company_match": Slider(f"{name}'s 401k Company Match (% of pay)", d["company_match"], 0, 20, 1),
        f"{prefix}_children": Slider(f"{name}'s Children", d["children"], 0, 5, 1),
    }


def _get(kwargs: dict[str, Any], key: str, default: Any) -> Any:
    """Fetch a normalized param value from the model kwargs, falling back to ``default``."""
    return param_value(kwargs.get(key, default))


def _person_spec(prefix: str, kwargs: dict[str, Any]) -> dict[str, Any] | None:
    """One person's spec entry (bank account, job, optional 401k, children), or None when disabled."""
    d = PERSON_DEFAULTS[prefix]

    def g(field: str) -> Any:
        return _get(kwargs, f"{prefix}_{field}", d[field])

    if not g("enabled"):
        return None

    name = prefix.capitalize()
    start_year = _get(kwargs, "start_year", SHARED_DEFAULTS["start_year"])
    person: dict[str, Any] = {
        "id": prefix,
        "name": name,
        "age": g("age"),
        # January of the year that makes them age at the start (the engine's default birth month).
        "birth": f"{int(start_year) - int(g('age')):04d}-01",
        "retirement_age": g("retirement_age"),
        "state": _state_value(kwargs.get("state")),
        "spending": {
            "amount_annual": g("spending"),
            "growth_pct": _get(kwargs, "spending_increase", SHARED_DEFAULTS["spending_increase"]),
        },
        "jobs": [
            {
                "id": f"{prefix}_job",
                "company": d["company"],
                "role": d["role"],
                "salary_annual": g("salary"),
                "raise_pct": _get(kwargs, "salary_increase", SHARED_DEFAULTS["salary_increase"]),
                "bonus_pct": g("bonus"),
            }
        ],
        "accounts": [
            {
                "kind": "bank",
                "company": d["bank_company"],
                "type": "Checking",
                "balance": g("bank_balance"),
                "interest_pct": _get(kwargs, "bank_interest_rate", SHARED_DEFAULTS["bank_interest_rate"]),
            }
        ],
        # Children are born at the start of the simulation; costs and the Child Tax Credit then
        # flow through the person's spending and tax unit automatically.
        "children": [
            {"id": f"{prefix}_child{i + 1:02d}", "name": f"{name}'s Child {i + 1}", "birth_year": start_year}
            for i in range(int(g("children")))
        ],
    }
    if g("retirement_enabled"):
        person["accounts"].append(
            {
                "kind": "401k",
                "job": f"{prefix}_job",
                "pretax_balance": g("retirement_balance"),
                "pretax_contrib_pct": g("retirement_contrib"),
                # "Company match (% of pay)" is a dollar-for-dollar match on deferrals up to that
                # percent of pay: one 100% tier (the deprecated company_match_pct meant a percent
                # *of the deferral*).
                "match_tiers": [{"match_pct": 100, "up_to_pay_pct": g("company_match")}]
                if g("company_match") > 0
                else None,
                "growth_pct": g("retirement_growth"),
            }
        )
    if _get(kwargs, "healthcare_enabled", SHARED_DEFAULTS["healthcare_enabled"]):
        # The medical cost curve, Medicare (premiums + IRMAA) and the long-term-care hazard model.
        person["healthcare"] = {"medical_costs": True, "medicare": True, "long_term_care": True}
    return person


def _home_spec(kwargs: dict[str, Any]) -> dict[str, Any]:
    """The mortgaged home (20% down, already owned at the start, so no cash changes hands)."""
    price = _get(kwargs, "home_price", SHARED_DEFAULTS["home_price"])
    down_payment = price * 0.20
    return {
        "kind": "home",
        "name": "Home",
        "purchase_price": price,
        "value_growth_pct": "economy",  # appreciate with the economy
        "down_payment": down_payment,
        "purchase": False,
        "mortgage": {
            "original_amount": price - down_payment,
            "rate_pct": _get(kwargs, "mortgage_rate", SHARED_DEFAULTS["mortgage_rate"]),
            "term_years": int(_get(kwargs, "mortgage_term", SHARED_DEFAULTS["mortgage_term"])),
        },
        "expenses": {
            "property_tax_pct": 1.0,
            "insurance_pct": 0.5,
            "maintenance_annual": 3000,
            "maintenance_growth_pct": 2.0,
        },
    }


def to_household_spec(**kwargs: Any) -> HouseholdSpec | None:
    """The dashboard's parameters (Sliders, checkboxes, or plain values) as a ``HouseholdSpec``.

    John and Jane are each included when enabled; when both are, they are married and file jointly
    (John heads the tax unit). The home, when enabled, belongs to John (or Jane when John is
    disabled). Returns None when nobody is enabled (a spec needs at least one person).
    """
    start_year = _get(kwargs, "start_year", SHARED_DEFAULTS["start_year"])
    people = [p for p in (_person_spec("john", kwargs), _person_spec("jane", kwargs)) if p is not None]
    if not people:
        return None
    if _get(kwargs, "home_enabled", SHARED_DEFAULTS["home_enabled"]):
        people[0]["housing"] = [_home_spec(kwargs)]
    data: dict[str, Any] = {
        "meta": {
            "name": "Dashboard household",
            "start_year": start_year,
            "end_year": _get(kwargs, "end_year", SHARED_DEFAULTS["end_year"]),
            "scenario": _scenario_value(kwargs.get("scenario")),
        },
        "people": people,
    }
    if len(people) == 2:
        data["relationships"] = {"marriages": [{"spouses": ["john", "jane"]}]}
    return HouseholdSpec.model_validate(data)


def _scenario_value(raw: Any) -> str | None:
    """Map the scenario dropdown selection to a LifeModel scenario name (or None for defaults)."""
    value = param_value(raw)
    if value in (None, SCENARIO_DEFAULT_LABEL):
        return None
    return value


def _state_value(raw: Any) -> str | None:
    """Map the state dropdown selection to a Person ``state`` (None for the DEFAULT pack)."""
    value = param_value(raw)
    if value in (None, DEFAULT_STATE_KEY):
        return None
    return value


class DashboardLifeModel(LifeModel):
    """LifeModel wrapper that builds a family from dashboard parameters through the spec builder.

    The engine steps monthly; one dashboard **Step** (and each tick of **Play**) simulates a year, so
    the yearly charts gain a point per step. Month-end rows are collected too (``collect="month"``)
    for the liquidity chart.
    """

    def __init__(self, **kwargs):
        """Initialize the model from dashboard parameters (Sliders, checkboxes, or plain values)."""
        self.household_spec = to_household_spec(**kwargs)
        super().__init__(
            end_year=_get(kwargs, "end_year", SHARED_DEFAULTS["end_year"]),
            start_year=_get(kwargs, "start_year", SHARED_DEFAULTS["start_year"]),
            scenario=_scenario_value(kwargs.get("scenario")),
            collect="month",
        )
        if self.household_spec is None:
            Family(self)  # nobody enabled: an empty family, as before
            return
        # The sliders bound every value, and a retirement age below the current age is allowed (the
        # person retires in the first year), so the build skips the validator's errors.
        populate_model(self, self.household_spec, check=False)

    def step(self):
        """Simulate one year: the engine's months through the next year end."""
        if self.is_finished:
            super().step()  # clears ``running``
            return
        year = self.year
        while not self.is_finished and self.year == year:
            super().step()


# Model parameters for the dashboard (single source: SHARED_DEFAULTS + PERSON_DEFAULTS).
model_params = {
    "scenario": {
        "label": "Economic Scenario",
        "type": "Select",
        "value": SCENARIO_DEFAULT_LABEL,
        "values": [SCENARIO_DEFAULT_LABEL] + list_scenarios(),
    },
    "state": {
        "label": "State of Residence",
        "type": "Select",
        "value": DEFAULT_STATE_KEY,
        "values": STATE_CHOICES,
    },
    "start_year": Slider("Start Year", SHARED_DEFAULTS["start_year"], 2000, current_year + 50, 1),
    "end_year": Slider("End Year", SHARED_DEFAULTS["end_year"], 2005, current_year + 150, 1),
    "salary_increase": Slider("Annual Salary Increase (%)", SHARED_DEFAULTS["salary_increase"], 0, 10, 0.5),
    "spending_increase": Slider("Annual Spending Increase (%)", SHARED_DEFAULTS["spending_increase"], 0, 10, 0.5),
    "bank_interest_rate": Slider("Bank Interest Rate (%)", SHARED_DEFAULTS["bank_interest_rate"], 0, 5, 0.1),
    "home_enabled": {"label": "Include a Home", "type": "Checkbox", "value": SHARED_DEFAULTS["home_enabled"]},
    "healthcare_enabled": {
        "label": "Model healthcare costs (medical curve, Medicare, LTC)",
        "type": "Checkbox",
        "value": SHARED_DEFAULTS["healthcare_enabled"],
    },
    "home_price": Slider("Home Price ($)", SHARED_DEFAULTS["home_price"], 100000, 1000000, 25000),
    "mortgage_rate": Slider("Mortgage Rate (%)", SHARED_DEFAULTS["mortgage_rate"], 0, 12, 0.25),
    "mortgage_term": Slider("Mortgage Term (years)", SHARED_DEFAULTS["mortgage_term"], 10, 30, 5),
    **_person_param_specs("john", "John"),
    **_person_param_specs("jane", "Jane"),
}


def post_process_financial(ax):
    """Post-process financial plots to enhance readability."""
    ax.set_xlabel("Year")
    ax.set_ylabel("Amount ($)")
    ax.grid(True)
    return ax


def post_process_balance_comparison(ax):
    """Post-process balance comparison plots."""
    ax.set_xlabel("Year")
    ax.set_ylabel("Bank Balance ($)")
    ax.grid(True)
    return ax


def post_process_retirement_savings(ax):
    """Post-process retirement savings plots."""
    ax.set_xlabel("Year")
    ax.set_ylabel("401k Balance ($)")
    ax.grid(True)
    return ax


def post_process_taxes_and_income(ax):
    """Post-process taxes and income plots."""
    ax.set_xlabel("Year")
    ax.set_ylabel("Amount ($)")
    ax.grid(True)
    return ax


# Create visualization components
financial_component = make_plot_component(
    {
        "Income": "tab:blue",
        "Bank Balance": "tab:orange",
        "401k Balance": "tab:green",
        "Debt": "tab:red",
        "Spending": "tab:purple",
    },
    post_process_financial,
)
balance_comparison_component = make_plot_component({"Bank Balance": "tab:blue"}, post_process_balance_comparison)
retirement_savings_component = make_plot_component(
    {"401k Balance": "tab:green", "401k Contrib": "tab:orange", "401k Match": "tab:purple"},
    post_process_retirement_savings,
)
taxes_and_income_component = make_plot_component(
    {"Income": "tab:blue", "Taxes": "tab:red"}, post_process_taxes_and_income
)


@solara.component
def LiquidityChart(model):
    """Cash on hand at every month end: what the yearly charts (year-end balances) cannot show, e.g. a
    bank balance that dips below zero mid-year and is carried as debt until income catches up."""
    update_counter.get()
    fig = Figure()
    ax = fig.subplots()
    rows = model.monthly_frame() if model.collect == "month" else None
    if rows is not None and not rows.empty:
        when = rows["Year"] + (rows["Month"] - 1) / 12
        ax.plot(when, rows["Bank Balance"], label="Bank Balance (month end)", color="tab:blue")
        ax.plot(when, -rows["Debt"].where(rows["Debt"] > 0, 0), label="-Debt", color="tab:red", alpha=0.5)
        ax.legend(loc="best")
    ax.set_xlabel("Year")
    ax.set_ylabel("Month-end cash ($)")
    ax.set_title("Liquidity (monthly)")
    ax.grid(True)
    solara.FigureMatplotlib(fig)


@solara.component
def ResultsTable(model):
    """Results tab: the yearly-stats DataFrame plus a CSV download of the same data."""
    df = model.datacollector.get_model_vars_dataframe()
    if df.empty:
        solara.Markdown("Run the simulation (press **Play** or **Step**) to populate results.")
        return
    solara.FileDownload(
        data=df.to_csv(index=False),
        filename="life_model_results.csv",
        label="Download results as CSV",
    )
    solara.DataFrame(df)


# The plot components live on the first tab (page 0); the results table on a second tab (page 1).
components = [
    financial_component,
    balance_comparison_component,
    retirement_savings_component,
    taxes_and_income_component,
    LiquidityChart,
    (ResultsTable, 1),
]

model = DashboardLifeModel(**model_params)

# Create the SolaraViz dashboard
page = SolaraViz(
    model,
    components=components,
    name="Life Model Financial Simulation Dashboard",
    model_params=model_params,
)

page  # noqa
