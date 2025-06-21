"""
Mesa Dashboard for Life Model Financial Simulation

This module provides a Solara-based interactive dashboard for the life_model
financial simulation package. Users can configure family parameters, run
simulations, and visualize financial projections.

Based on the ExampleSimulation.ipynb notebook.
"""

import solara
from mesa.visualization import SolaraViz
import altair as alt
import pandas as pd

from life_model.model import LifeModel
from life_model.family import Family
from life_model.person import Person, Spending
from life_model.account.bank import BankAccount
from life_model.job import Job, Salary


class DashboardLifeModel(LifeModel):
    """LifeModel wrapper for dashboard with parameter initialization."""

    # Class-level steps attribute for SolaraViz compatibility
    steps = 0

    def __init__(self, start_year=2023, end_year=2050, john_enabled=True,
                 john_age=44, john_retirement_age=60, john_salary=50000,
                 john_spending=12000, john_bank_balance=20000,
                 jane_enabled=False, jane_age=45, jane_retirement_age=60,
                 jane_salary=65000, jane_spending=12000, jane_bank_balance=30000,
                 spending_increase=5.0, salary_increase=1.0,
                 john_job_enabled=True, jane_job_enabled=True,
                 john_company="Company A", john_role="Manager", john_bonus=1,
                 jane_company="Company B", jane_role="Developer", jane_bonus=1,
                 bank_interest_rate=0.5, seed=None):
        """Initialize the model with dashboard parameters."""
        super().__init__(
            start_year=start_year,
            end_year=end_year,
            seed=seed
        )

        # Create family
        family = Family(self)

        # Create people
        if john_enabled:
            john = Person(
                family=family,
                name='John',
                age=john_age,
                retirement_age=john_retirement_age,
                spending=Spending(
                    model=self,
                    base=john_spending,
                    yearly_increase=spending_increase
                )
            )

            # Add bank account for John
            BankAccount(
                owner=john,
                company='Bank',
                type='Checking',
                balance=john_bank_balance,
                interest_rate=bank_interest_rate
            )

            # Add job for John
            if john_job_enabled:
                Job(
                    owner=john,
                    company=john_company,
                    role=john_role,
                    salary=Salary(
                        model=self,
                        base=john_salary,
                        yearly_increase=salary_increase,
                        yearly_bonus=john_bonus
                    )
                )

        if jane_enabled:
            jane = Person(
                family=family,
                name='Jane',
                age=jane_age,
                retirement_age=jane_retirement_age,
                spending=Spending(
                    model=self,
                    base=jane_spending,
                    yearly_increase=spending_increase
                )
            )

            # Add bank account for Jane
            BankAccount(
                owner=jane,
                company='Credit Union',
                type='Checking',
                balance=jane_bank_balance,
                interest_rate=bank_interest_rate
            )

            # Add job for Jane
            if jane_job_enabled:
                Job(
                    owner=jane,
                    company=jane_company,
                    role=jane_role,
                    salary=Salary(
                        model=self,
                        base=jane_salary,
                        yearly_increase=salary_increase,
                        yearly_bonus=jane_bonus
                    )
                )


def plot_financial_overview(model: LifeModel) -> alt.Chart:
    """Create a financial overview chart."""
    if not hasattr(model, 'datacollector') or model.datacollector is None:
        return alt.Chart(pd.DataFrame()).mark_text().encode(
            text=alt.value("Run simulation to see results")
        )

    # Get model data
    df = model.datacollector.get_model_vars_dataframe()

    if df.empty:
        return alt.Chart(pd.DataFrame()).mark_text().encode(
            text=alt.value("No data available")
        )

    # Create a melted dataframe for better visualization
    financial_columns = ['Income', 'Bank Balance', '401k Balance', 'Debt', 'Spending']
    available_columns = [col for col in financial_columns if col in df.columns]

    if not available_columns:
        return alt.Chart(pd.DataFrame()).mark_text().encode(
            text=alt.value("No financial data available")
        )

    # Melt the dataframe
    df_melted = df[['Year'] + available_columns].melt(
        id_vars=['Year'],
        value_vars=available_columns,
        var_name='Category',
        value_name='Amount'
    )

    # Create the chart
    chart = alt.Chart(df_melted).mark_line(point=True).encode(
        x=alt.X('Year:O', title='Year'),
        y=alt.Y('Amount:Q', title='Amount ($)', scale=alt.Scale(type='linear')),
        color=alt.Color('Category:N', title='Financial Category'),
        tooltip=['Year:O', 'Category:N', 'Amount:Q']
    ).properties(
        title='Financial Overview',
        width=600,
        height=400
    )

    return chart


def plot_balance_comparison(model: LifeModel) -> alt.Chart:
    """Create a balance comparison chart."""
    if not hasattr(model, 'datacollector') or model.datacollector is None:
        return alt.Chart(pd.DataFrame()).mark_text().encode(
            text=alt.value("Run simulation to see results")
        )

    df = model.datacollector.get_model_vars_dataframe()

    if df.empty or 'Bank Balance' not in df.columns:
        return alt.Chart(pd.DataFrame()).mark_text().encode(
            text=alt.value("No balance data available")
        )

    # Create bars for balances
    chart = alt.Chart(df).mark_bar().encode(
        x=alt.X('Year:O', title='Year'),
        y=alt.Y('Bank Balance:Q', title='Bank Balance ($)'),
        tooltip=['Year:O', 'Bank Balance:Q']
    ).properties(
        title='Bank Balance Over Time',
        width=600,
        height=300
    )

    return chart


def plot_retirement_savings(model: LifeModel) -> alt.Chart:
    """Create a retirement savings chart."""
    if not hasattr(model, 'datacollector') or model.datacollector is None:
        return alt.Chart(pd.DataFrame()).mark_text().encode(
            text=alt.value("Run simulation to see results")
        )

    df = model.datacollector.get_model_vars_dataframe()

    if df.empty:
        return alt.Chart(pd.DataFrame()).mark_text().encode(
            text=alt.value("No data available")
        )

    # Create retirement-focused chart
    retirement_columns = ['401k Balance', '401k Contrib', '401k Match']
    available_columns = [col for col in retirement_columns if col in df.columns]

    if not available_columns:
        return alt.Chart(pd.DataFrame()).mark_text().encode(
            text=alt.value("No retirement data available")
        )

    # Create multiple charts
    charts = []

    # 401k Balance over time
    if '401k Balance' in df.columns:
        balance_chart = alt.Chart(df).mark_area(
            opacity=0.7,
            color='green'
        ).encode(
            x=alt.X('Year:O', title='Year'),
            y=alt.Y('401k Balance:Q', title='401k Balance ($)'),
            tooltip=['Year:O', '401k Balance:Q']
        )
        charts.append(balance_chart)

    # Contributions over time
    contrib_columns = ['401k Contrib', '401k Match']
    contrib_available = [col for col in contrib_columns if col in df.columns]

    if contrib_available:
        df_contrib = df[['Year'] + contrib_available].melt(
            id_vars=['Year'],
            value_vars=contrib_available,
            var_name='Type',
            value_name='Amount'
        )

        contrib_chart = alt.Chart(df_contrib).mark_bar().encode(
            x=alt.X('Year:O', title='Year'),
            y=alt.Y('Amount:Q', title='Contribution ($)'),
            color=alt.Color('Type:N', title='Contribution Type'),
            tooltip=['Year:O', 'Type:N', 'Amount:Q']
        )
        charts.append(contrib_chart)

    if charts:
        if len(charts) > 1:
            final_chart = alt.vconcat(*charts).resolve_scale(
                color='independent'
            ).properties(
                title='Retirement Savings Overview'
            )
        else:
            final_chart = charts[0].properties(
                title='Retirement Savings Overview',
                width=600,
                height=300
            )
        return final_chart
    else:
        return alt.Chart(pd.DataFrame()).mark_text().encode(
            text=alt.value("No retirement data to display")
        )


def plot_taxes_and_income(model: LifeModel) -> alt.Chart:
    """Create a taxes and income breakdown chart."""
    if not hasattr(model, 'datacollector') or model.datacollector is None:
        return alt.Chart(pd.DataFrame()).mark_text().encode(
            text=alt.value("Run simulation to see results")
        )

    df = model.datacollector.get_model_vars_dataframe()

    if df.empty:
        return alt.Chart(pd.DataFrame()).mark_text().encode(
            text=alt.value("No data available")
        )

    # Income and tax columns
    income_tax_columns = ['Income', 'Taxes', 'Federal Taxes', 'State Taxes', 'SS Taxes', 'Medicare Taxes']
    available_columns = [col for col in income_tax_columns if col in df.columns]

    if len(available_columns) < 2:
        return alt.Chart(pd.DataFrame()).mark_text().encode(
            text=alt.value("Insufficient tax/income data")
        )

    # Create income vs total taxes chart
    income_chart = alt.Chart(df).mark_line(
        point=True,
        color='blue'
    ).encode(
        x=alt.X('Year:O', title='Year'),
        y=alt.Y('Income:Q', title='Amount ($)'),
        tooltip=['Year:O', 'Income:Q']
    )

    if 'Taxes' in df.columns:
        taxes_chart = alt.Chart(df).mark_line(
            point=True,
            color='red',
            strokeDash=[5, 5]
        ).encode(
            x=alt.X('Year:O', title='Year'),
            y=alt.Y('Taxes:Q', title='Amount ($)'),
            tooltip=['Year:O', 'Taxes:Q']
        )

        combined_chart = income_chart + taxes_chart
    else:
        combined_chart = income_chart

    final_chart = combined_chart.properties(
        title='Income vs. Taxes Over Time',
        width=600,
        height=350
    )

    return final_chart


# Model parameters for the dashboard
model_params = {
    "start_year": {
        "type": "SliderInt",
        "value": 2023,
        "label": "Start Year",
        "min": 2020,
        "max": 2030,
        "step": 1,
    },
    "end_year": {
        "type": "SliderInt",
        "value": 2050,
        "label": "End Year",
        "min": 2025,
        "max": 2070,
        "step": 1,
    },
    "john_enabled": {
        "type": "Checkbox",
        "value": True,
        "label": "Include John",
    },
    "john_age": {
        "type": "SliderInt",
        "value": 44,
        "label": "John's Age",
        "min": 20,
        "max": 70,
        "step": 1,
    },
    "john_retirement_age": {
        "type": "SliderInt",
        "value": 60,
        "label": "John's Retirement Age",
        "min": 50,
        "max": 70,
        "step": 1,
    },
    "john_salary": {
        "type": "SliderInt",
        "value": 50000,
        "label": "John's Salary ($)",
        "min": 30000,
        "max": 150000,
        "step": 5000,
    },
    "john_spending": {
        "type": "SliderInt",
        "value": 12000,
        "label": "John's Annual Spending ($)",
        "min": 5000,
        "max": 50000,
        "step": 1000,
    },
    "john_bank_balance": {
        "type": "SliderInt",
        "value": 20000,
        "label": "John's Initial Bank Balance ($)",
        "min": 0,
        "max": 100000,
        "step": 5000,
    },
    "jane_enabled": {
        "type": "Checkbox",
        "value": False,
        "label": "Include Jane",
    },
    "jane_age": {
        "type": "SliderInt",
        "value": 45,
        "label": "Jane's Age",
        "min": 20,
        "max": 70,
        "step": 1,
    },
    "jane_retirement_age": {
        "type": "SliderInt",
        "value": 60,
        "label": "Jane's Retirement Age",
        "min": 50,
        "max": 70,
        "step": 1,
    },
    "jane_salary": {
        "type": "SliderInt",
        "value": 65000,
        "label": "Jane's Salary ($)",
        "min": 30000,
        "max": 150000,
        "step": 5000,
    },
    "jane_spending": {
        "type": "SliderInt",
        "value": 12000,
        "label": "Jane's Annual Spending ($)",
        "min": 5000,
        "max": 50000,
        "step": 1000,
    },
    "jane_bank_balance": {
        "type": "SliderInt",
        "value": 30000,
        "label": "Jane's Initial Bank Balance ($)",
        "min": 0,
        "max": 100000,
        "step": 5000,
    },
    "spending_increase": {
        "type": "SliderFloat",
        "value": 5.0,
        "label": "Annual Spending Increase (%)",
        "min": 0.0,
        "max": 10.0,
        "step": 0.5,
    },
    "salary_increase": {
        "type": "SliderFloat",
        "value": 1.0,
        "label": "Annual Salary Increase (%)",
        "min": 0.0,
        "max": 5.0,
        "step": 0.1,
    },
}


def ensure_model_run(model):
    """Ensure the model has been run and has data."""
    if hasattr(model, 'simulated_years') and len(model.simulated_years) == 0:
        # Model hasn't been run yet, run it
        model.run()
    return model


def create_chart_component(plot_function):
    """Create a Solara component that wraps our plot functions."""
    @solara.component
    def ChartComponent(model):
        # Ensure model is run
        model = ensure_model_run(model)

        # Generate the chart
        chart = plot_function(model)

        # Return the chart as a Solara component
        return solara.display(chart)

    return ChartComponent


def create_dashboard():
    """Create and run the financial simulation dashboard."""

    # Create visualization components using our custom wrapper
    components = [
        create_chart_component(plot_financial_overview),
        create_chart_component(plot_balance_comparison),
        create_chart_component(plot_retirement_savings),
        create_chart_component(plot_taxes_and_income),
    ]

    # Create the SolaraViz dashboard
    viz = SolaraViz(
        model=DashboardLifeModel,
        components=components,
        model_params=model_params,
        name="Life Model Financial Simulation Dashboard",
        play_interval=500,
    )

    return viz


def main():
    """Main function to run the dashboard."""
    dashboard = create_dashboard()
    # Note: dashboard.run() would be called in a Solara app context
    return dashboard


if __name__ == "__main__":
    main()
