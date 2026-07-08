"""
Mesa Dashboard for Life Model Financial Simulation

This module provides a Solara-based interactive dashboard for the life_model
financial simulation package. Users can configure family parameters, choose an
economic scenario, run simulations, and visualize financial projections.

Based on the ExampleSimulation.ipynb notebook.
"""

from datetime import datetime
from typing import Any, Dict, Optional

import solara
from mesa.visualization import Slider, SolaraViz, make_plot_component

from life_model.account.bank import BankAccount
from life_model.account.job401k import Job401kAccount
from life_model.config.scenarios import list_scenarios
from life_model.healthcare import LongTermCare, MedicalCosts, Medicare
from life_model.housing.home import Home, HomeExpenses, Mortgage
from life_model.model import LifeModel
from life_model.people.family import Family
from life_model.people.person import Person, Spending
from life_model.work.job import Job, Salary

# Label used in the scenario dropdown for "use the packaged defaults" (scenario=None).
SCENARIO_DEFAULT_LABEL = "(default)"

current_year = datetime.now().year


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

PERSON_DEFAULTS: Dict[str, Dict[str, Any]] = {
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
    },
}

SHARED_DEFAULTS: Dict[str, Any] = {
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
    # off so existing dashboard runs keep producing the same numbers (Plan 15).
    "healthcare_enabled": False,
}


def _person_param_specs(prefix: str, name: str) -> Dict[str, Any]:
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
        f"{prefix}_company_match": Slider(f"{name}'s 401k Company Match (%)", d["company_match"], 0, 20, 1),
    }


def _get(kwargs: Dict[str, Any], key: str, default: Any) -> Any:
    """Fetch a normalized param value from the model kwargs, falling back to ``default``."""
    return param_value(kwargs.get(key, default))


def _add_person(model: LifeModel, family: Family, prefix: str, kwargs: Dict[str, Any]) -> Optional[Person]:
    """Create a person (with bank account, job, and optional 401k) from the params, if enabled."""
    d = PERSON_DEFAULTS[prefix]

    def g(field: str) -> Any:
        return _get(kwargs, f"{prefix}_{field}", d[field])

    if not g("enabled"):
        return None

    person = Person(
        family=family,
        name=prefix.capitalize(),
        age=g("age"),
        retirement_age=g("retirement_age"),
        spending=Spending(
            model=model,
            base=g("spending"),
            yearly_increase=_get(kwargs, "spending_increase", SHARED_DEFAULTS["spending_increase"]),
        ),
    )

    BankAccount(
        owner=person,
        company=d["bank_company"],
        type="Checking",
        balance=g("bank_balance"),
        interest_rate=_get(kwargs, "bank_interest_rate", SHARED_DEFAULTS["bank_interest_rate"]),
    )

    job = Job(
        owner=person,
        company=d["company"],
        role=d["role"],
        salary=Salary(
            model=model,
            base=g("salary"),
            yearly_increase=_get(kwargs, "salary_increase", SHARED_DEFAULTS["salary_increase"]),
            yearly_bonus=g("bonus"),
        ),
    )

    if g("retirement_enabled"):
        Job401kAccount(
            job=job,
            pretax_balance=g("retirement_balance"),
            pretax_contrib_percent=g("retirement_contrib"),
            company_match_percent=g("company_match"),
            average_growth=g("retirement_growth"),
        )

    return person


def _add_home(model: LifeModel, owner: Optional[Person], kwargs: Dict[str, Any]) -> None:
    """Attach a mortgaged home to ``owner`` when the home checkbox is enabled."""
    if owner is None or not _get(kwargs, "home_enabled", SHARED_DEFAULTS["home_enabled"]):
        return

    price = _get(kwargs, "home_price", SHARED_DEFAULTS["home_price"])
    rate = _get(kwargs, "mortgage_rate", SHARED_DEFAULTS["mortgage_rate"])
    term = int(_get(kwargs, "mortgage_term", SHARED_DEFAULTS["mortgage_term"]))
    down_payment = price * 0.20

    mortgage = Mortgage(
        loan_amount=price - down_payment,
        start_date=model.start_year,
        length_years=term,
        yearly_interest_rate=rate,
    )
    expenses = HomeExpenses(
        model=model,
        property_tax_percent=1.0,
        home_insurance_percent=0.5,
        maintenance_amount=3000,
        maintenance_increase=2.0,
        improvement_amount=0,
        improvement_increase=0.0,
        hoa_amount=0,
        hoa_increase=0.0,
    )
    Home(
        person=owner,
        name="Home",
        purchase_price=price,
        value_yearly_increase=None,  # appreciate with the economy
        down_payment=down_payment,
        mortgage=mortgage,
        expenses=expenses,
        purchase=False,  # already owned at simulation start (no cash outflow)
    )


def _add_healthcare(model: LifeModel, people: "tuple[Optional[Person], ...]", kwargs: Dict[str, Any]) -> None:
    """Attach the opt-in healthcare agents to each enabled person when the toggle is on.

    Adds the age-related medical cost curve, Medicare (premiums + IRMAA), and the long-term-care
    hazard model (Plan 15). Default off for back-compat.
    """
    if not _get(kwargs, "healthcare_enabled", SHARED_DEFAULTS["healthcare_enabled"]):
        return
    for person in people:
        if person is None:
            continue
        MedicalCosts(person)
        Medicare(person)
        LongTermCare(person)


def _scenario_value(raw: Any) -> Optional[str]:
    """Map the scenario dropdown selection to a LifeModel scenario name (or None for defaults)."""
    value = param_value(raw)
    if value in (None, SCENARIO_DEFAULT_LABEL):
        return None
    return value


class DashboardLifeModel(LifeModel):
    """LifeModel wrapper that builds a family from dashboard parameters."""

    def __init__(self, **kwargs):
        """Initialize the model from dashboard parameters (Sliders, checkboxes, or plain values)."""
        super().__init__(
            end_year=_get(kwargs, "end_year", SHARED_DEFAULTS["end_year"]),
            start_year=_get(kwargs, "start_year", SHARED_DEFAULTS["start_year"]),
            scenario=_scenario_value(kwargs.get("scenario")),
        )

        family = Family(self)
        john = _add_person(self, family, "john", kwargs)
        jane = _add_person(self, family, "jane", kwargs)
        _add_home(self, john or jane, kwargs)
        _add_healthcare(self, (john, jane), kwargs)


# Model parameters for the dashboard (single source: SHARED_DEFAULTS + PERSON_DEFAULTS).
model_params = {
    "scenario": {
        "label": "Economic Scenario",
        "type": "Select",
        "value": SCENARIO_DEFAULT_LABEL,
        "values": [SCENARIO_DEFAULT_LABEL] + list_scenarios(),
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
