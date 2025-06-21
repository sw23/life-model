#!/usr/bin/env python3
"""
Test the dashboard components

This module tests that the dashboard components work correctly
without needing to run the full Solara server.
"""

import sys
import os
import pytest

# Add the dashboard directory to Python path for imports
dashboard_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'dashboard')
if dashboard_path not in sys.path:
    sys.path.insert(0, dashboard_path)

# Import dashboard modules - these need to be after the path setup
try:
    from dashboard import (create_financial_model, plot_financial_overview,
                           plot_balance_comparison, plot_retirement_savings, plot_taxes_and_income,
                           DashboardLifeModel, create_dashboard)  # noqa: E402
except ImportError as e:
    pytest.skip(f"Dashboard imports not available: {e}", allow_module_level=True)


@pytest.fixture
def basic_model():
    """Create a basic financial model for testing."""
    params = {
        'start_year': 2023,
        'end_year': 2027,
        'john_enabled': True,
        'john_age': 30,
        'john_retirement_age': 65,
        'john_salary': 60000,
        'john_spending': 15000,
        'john_bank_balance': 25000,
        'jane_enabled': True,
        'jane_age': 28,
        'jane_retirement_age': 65,
        'jane_salary': 55000,
        'jane_spending': 18000,
        'jane_bank_balance': 20000,
        'spending_increase': 3.0,
        'salary_increase': 2.5,
    }

    model = create_financial_model(params)
    model.run()
    return model


@pytest.fixture
def single_person_model():
    """Create a single person model for testing."""
    params = {
        'start_year': 2023,
        'end_year': 2025,
        'john_enabled': True,
        'jane_enabled': False,
        'john_age': 45,
        'john_salary': 75000,
    }

    model = create_financial_model(params)
    model.run()
    return model


@pytest.fixture
def couple_model():
    """Create a couple model for testing."""
    params = {
        'start_year': 2023,
        'end_year': 2025,
        'john_enabled': True,
        'jane_enabled': True,
        'john_age': 35,
        'jane_age': 33,
        'john_salary': 80000,
        'jane_salary': 70000,
    }

    model = create_financial_model(params)
    model.run()
    return model


def test_model_creation():
    """Test that we can create and run a model."""
    params = {
        'start_year': 2023,
        'end_year': 2027,
        'john_enabled': True,
        'john_age': 30,
        'john_retirement_age': 65,
        'john_salary': 60000,
        'john_spending': 15000,
        'john_bank_balance': 25000,
        'jane_enabled': True,
        'jane_age': 28,
        'jane_retirement_age': 65,
        'jane_salary': 55000,
        'jane_spending': 18000,
        'jane_bank_balance': 20000,
        'spending_increase': 3.0,
        'salary_increase': 2.5,
    }

    model = create_financial_model(params)
    assert model is not None
    assert len(model.agents) > 0

    # Run the simulation
    model.run()
    assert len(model.simulated_years) == 5  # 2023-2027 is 5 years

    # Check data
    df = model.datacollector.get_model_vars_dataframe()
    assert not df.empty
    assert df.shape[0] == 5  # 5 years of data
    assert 'Year' in df.columns
    assert 'Income' in df.columns
    assert 'Bank Balance' in df.columns


def test_chart_generation(basic_model):
    """Test chart generation."""
    model = basic_model

    # Test financial overview chart
    chart1 = plot_financial_overview(model)
    assert chart1 is not None
    # Verify chart can be serialized
    json_data1 = chart1.to_json()
    assert len(json_data1) > 0

    # Test balance comparison chart
    chart2 = plot_balance_comparison(model)
    assert chart2 is not None
    json_data2 = chart2.to_json()
    assert len(json_data2) > 0

    # Test retirement savings chart
    chart3 = plot_retirement_savings(model)
    assert chart3 is not None
    json_data3 = chart3.to_json()
    assert len(json_data3) > 0

    # Test taxes and income chart
    chart4 = plot_taxes_and_income(model)
    assert chart4 is not None
    json_data4 = chart4.to_json()
    assert len(json_data4) > 0


def test_parameter_variations(single_person_model, couple_model):
    """Test different parameter combinations."""
    model_single = single_person_model
    model_couple = couple_model

    # Verify models were created with correct number of agents
    assert len(model_single.agents) < len(model_couple.agents)

    # Compare results
    df_single = model_single.datacollector.get_model_vars_dataframe()
    df_couple = model_couple.datacollector.get_model_vars_dataframe()

    assert not df_single.empty
    assert not df_couple.empty

    # Both models should have the same number of years
    assert len(df_single) == len(df_couple)

    # Couple should generally have higher income and bank balance
    final_balance_single = df_single['Bank Balance'].iloc[-1]
    final_balance_couple = df_couple['Bank Balance'].iloc[-1]

    assert final_balance_single > 0
    assert final_balance_couple > 0
    assert final_balance_couple > final_balance_single


def test_empty_model_charts():
    """Test that charts handle models without data gracefully."""
    # Create a model but don't run it
    params = {
        'start_year': 2023,
        'end_year': 2025,
        'john_enabled': True,
        'john_age': 30,
        'john_salary': 50000,
    }

    model = create_financial_model(params)
    # Don't run the model to test empty data handling

    # All chart functions should handle empty data gracefully
    chart1 = plot_financial_overview(model)
    assert chart1 is not None

    chart2 = plot_balance_comparison(model)
    assert chart2 is not None

    chart3 = plot_retirement_savings(model)
    assert chart3 is not None

    chart4 = plot_taxes_and_income(model)
    assert chart4 is not None


def test_dashboard_life_model_steps_attribute():
    """Test that DashboardLifeModel has the steps attribute required by SolaraViz."""
    # Test that the class has the steps attribute (required by SolaraViz)
    assert hasattr(DashboardLifeModel, 'steps'), \
        "DashboardLifeModel class should have steps attribute for SolaraViz compatibility"

    # Test that an instance also has the steps attribute
    model = DashboardLifeModel()
    assert hasattr(model, 'steps'), "DashboardLifeModel instance should have steps attribute"
    assert model.steps == 0, "Initial steps should be 0"


def test_solara_viz_dashboard_creation():
    """Test that the SolaraViz dashboard can be created without errors."""
    # This should not raise an AttributeError: 'type object has no attribute steps'
    dashboard = create_dashboard()
    assert dashboard is not None, "Dashboard should be created successfully"
