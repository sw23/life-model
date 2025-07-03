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
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'dashboard'))

from app import DashboardLifeModel  # noqa: E402


@pytest.fixture
def basic_model():
    """Create a basic financial model for testing."""
    model = DashboardLifeModel(
        start_year=2023,
        end_year=2027,
        john_enabled=True,
        john_age=30,
        john_retirement_age=65,
        john_salary=60000,
        john_spending=15000,
        john_bank_balance=25000,
        jane_enabled=True,
        jane_age=28,
        jane_retirement_age=65,
        jane_salary=55000,
        jane_spending=18000,
        jane_bank_balance=20000,
        spending_increase=3.0,
        salary_increase=2.5,
    )
    model.run()
    return model


@pytest.fixture
def single_person_model():
    """Create a single person model for testing."""
    model = DashboardLifeModel(
        start_year=2023,
        end_year=2025,
        john_enabled=True,
        jane_enabled=False,
        john_age=45,
        john_salary=75000,
    )
    model.run()
    return model


@pytest.fixture
def couple_model():
    """Create a couple model for testing."""
    model = DashboardLifeModel(
        start_year=2023,
        end_year=2025,
        john_enabled=True,
        jane_enabled=True,
        john_age=35,
        jane_age=33,
        john_salary=80000,
        jane_salary=70000,
    )
    model.run()
    return model


def test_model_creation():
    """Test that we can create and run a model."""
    model = DashboardLifeModel(
        start_year=2023,
        end_year=2027,
        john_enabled=True,
        john_age=30,
        john_retirement_age=65,
        john_salary=60000,
        john_spending=15000,
        john_bank_balance=25000,
        jane_enabled=True,
        jane_age=28,
        jane_retirement_age=65,
        jane_salary=55000,
        jane_spending=18000,
        jane_bank_balance=20000,
        spending_increase=3.0,
        salary_increase=2.5,
    )
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
