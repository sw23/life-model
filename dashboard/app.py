"""
Mesa Dashboard for Life Model Financial Simulation

This module provides a Solara-based interactive dashboard for the life_model
financial simulation package. Users can configure family parameters, run
simulations, and visualize financial projections.

Based on the ExampleSimulation.ipynb notebook.
"""

from datetime import datetime
from mesa.visualization import SolaraViz, make_plot_component, Slider
from typing import Any

from life_model.model import LifeModel
from life_model.people.family import Family
from life_model.people.person import Person, Spending
from life_model.account.bank import BankAccount
from life_model.work.job import Job, Salary


class SafeDict(dict):
    """Dictionary that tries to access 'values' first (i.e. Slider), otherwise direct value."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get(self, key, default=None) -> Any:
        """Return the value of the key, or the 'value' attribute if it exists, or default."""
        value = super().get(key, default)
        try:
            return value.value  # type: ignore
        except AttributeError:
            return value


class DashboardLifeModel(LifeModel):
    """LifeModel wrapper for dashboard with parameter initialization."""

    def __init__(self, **kwargs):
        """Initialize the model with dashboard parameters."""
        params = SafeDict(kwargs)
        super().__init__(params.get('end_year', 2050),
                         params.get('start_year', 2023))

        # Create family
        family = Family(self)

        # Create people
        if params.get('john_enabled', True):
            john = Person(
                family=family,
                name='John',
                age=params.get('john_age', 44),
                retirement_age=params.get('john_retirement_age', 60),
                spending=Spending(
                    model=self,
                    base=params.get('john_spending', 12000),
                    yearly_increase=params.get('spending_increase', 5)
                )
            )

            # Add bank account for John
            BankAccount(
                owner=john,
                company='Bank',
                type='Checking',
                balance=params.get('john_bank_balance', 20000),
                interest_rate=params.get('bank_interest_rate', 0.5)
            )

            # Add job for John
            Job(
                owner=john,
                company=params.get('john_company', 'Company A'),
                role=params.get('john_role', 'Manager'),
                salary=Salary(
                    model=self,
                    base=params.get('john_salary', 50000),
                    yearly_increase=params.get('salary_increase', 1),
                    yearly_bonus=params.get('john_bonus', 1)
                )
            )

        if params.get('jane_enabled', False):
            jane = Person(
                family=family,
                name='Jane',
                age=params.get('jane_age', 45),
                retirement_age=params.get('jane_retirement_age', 60),
                spending=Spending(
                    model=self,
                    base=params.get('jane_spending', 12000),
                    yearly_increase=params.get('spending_increase', 5)
                )
            )

            # Add bank account for Jane
            BankAccount(
                owner=jane,
                company='Credit Union',
                type='Checking',
                balance=params.get('jane_bank_balance', 30000),
                interest_rate=params.get('bank_interest_rate', 0.5)
            )

            # Add job for Jane
            Job(
                owner=jane,
                company=params.get('jane_company', 'Company B'),
                role=params.get('jane_role', 'Developer'),
                salary=Salary(
                    model=self,
                    base=params.get('jane_salary', 45000),
                    yearly_increase=params.get('salary_increase', 1),
                    yearly_bonus=params.get('jane_bonus', 1)
                )
            )


# Get current yer
current_year = datetime.now().year

# Model parameters for the dashboard
model_params = {
    "start_year": Slider("Start Year", current_year, current_year, current_year + 100),
    "end_year": Slider("End Year", current_year + 50, current_year + 5, current_year + 150),
    "john_enabled": {"label": "Include John", "type": "Checkbox", "value": True},
    "john_age": Slider("John's Age", 44, 18, 80, 1),
    "john_retirement_age": Slider("John's Retirement Age", 60, 50, 70, 1),
    "john_salary": Slider("John's Salary ($)", 50000, 30000, 150000, 5000),
    "john_spending": Slider("John's Annual Spending ($)", 12000, 5000, 50000, 1000),
    "john_bank_balance": Slider("John's Initial Bank Balance ($)", 20000, 0, 100000, 5000),
    "jane_enabled": {"label": "Include Jane", "type": "Checkbox", "value": True},
    "jane_age": Slider("Jane's Age", 45, 18, 80, 1),
    "jane_retirement_age": Slider("Jane's Retirement Age", 60, 50, 70, 1),
    "jane_salary": Slider("Jane's Salary ($)", 65000, 30000, 150000, 5000),
    "jane_spending": Slider("Jane's Annual Spending ($)", 12000, 5000, 50000, 1000),
    "jane_bank_balance": Slider("Jane's Initial Bank Balance ($)", 30000, 0, 100000, 5000),

}


def post_process_financial(ax):
    """Post-process financial plots to enhance readability."""
    # ax.set_title("Financial Overview")
    ax.set_xlabel("Year")
    ax.set_ylabel("Amount ($)")
    ax.grid(True)
    return ax


def post_process_balance_comparison(ax):
    """Post-process balance comparison plots."""
    # ax.set_title("Bank Balance Comparison")
    ax.set_xlabel("Year")
    ax.set_ylabel("Bank Balance ($)")
    ax.grid(True)
    return ax


def post_process_retirement_savings(ax):
    """Post-process retirement savings plots."""
    # ax.set_title("Retirement Savings Overview")
    ax.set_xlabel("Year")
    ax.set_ylabel("401k Balance ($)")
    ax.grid(True)
    return ax


def post_process_taxes_and_income(ax):
    """Post-process taxes and income plots."""
    # ax.set_title("Income vs. Taxes Over Time")
    ax.set_xlabel("Year")
    ax.set_ylabel("Amount ($)")
    ax.grid(True)
    return ax


# Create visualization components
financial_component = make_plot_component({'Income': 'tab:blue', 'Bank Balance': 'tab:orange',
                                           '401k Balance': 'tab:green', 'Debt': 'tab:red',
                                           'Spending': 'tab:purple'}, post_process_financial)
balance_comparison_component = make_plot_component({'Bank Balance': 'tab:blue'}, post_process_balance_comparison)
retirement_savings_component = make_plot_component({'401k Balance': 'tab:green', '401k Contrib': 'tab:orange',
                                                    '401k Match': 'tab:purple'}, post_process_retirement_savings)
taxes_and_income_component = make_plot_component({'Income': 'tab:blue',
                                                  'Taxes': 'tab:red'}, post_process_taxes_and_income)

model = DashboardLifeModel(**model_params)

# Create the SolaraViz dashboard
page = SolaraViz(
    model,
    components=[financial_component, balance_comparison_component,
                retirement_savings_component, taxes_and_income_component],
    name="Life Model Financial Simulation Dashboard",
    model_params=model_params,
)

page  # noqa