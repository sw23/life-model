"""
Mesa Dashboard for Life Model Financial Simulation

This module provides a Solara-based interactive dashboard for the life_model
financial simulation package. Users can configure family parameters, run
simulations, and visualize financial projections.

Based on the ExampleSimulation.ipynb notebook.
"""

import solara
import reacton
from mesa.visualization import SolaraViz, make_plot_component
import altair as alt
import pandas as pd
from typing import Dict, Any, List

from life_model.model import LifeModel
from life_model.family import Family
from life_model.person import Person, Spending
from life_model.account.bank import BankAccount
from life_model.job import Job, Salary


def create_financial_model(params: Dict[str, Any]) -> LifeModel:
    """Create a LifeModel based on user parameters."""
    
    # Create model
    model = LifeModel(
        start_year=params.get('start_year', 2023),
        end_year=params.get('end_year', 2050)
    )
    
    # Create family
    family = Family(model)
    
    # Create people
    if params.get('john_enabled', True):
        john = Person(
            family=family,
            name='John',
            age=params.get('john_age', 44),
            retirement_age=params.get('john_retirement_age', 60),
            spending=Spending(
                model=model,
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
        if params.get('john_job_enabled', True):
            Job(
                owner=john,
                company=params.get('john_company', 'Company A'),
                role=params.get('john_role', 'Manager'),
                salary=Salary(
                    model=model,
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
                model=model,
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
        if params.get('jane_job_enabled', True):
            Job(
                owner=jane,
                company=params.get('jane_company', 'Company B'),
                role=params.get('jane_role', 'Manager'),
                salary=Salary(
                    model=model,
                    base=params.get('jane_salary', 65000),
                    yearly_increase=params.get('salary_increase', 1),
                    yearly_bonus=params.get('jane_bonus', 2)
                )
            )
    
    return model


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


def create_dashboard():
    """Create and run the financial simulation dashboard."""
    
    # Create visualization components
    components = [
        make_plot_component(plot_financial_overview),
        make_plot_component(plot_balance_comparison),
    ]
    
    # Create the SolaraViz dashboard
    viz = SolaraViz(
        model=create_financial_model,
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