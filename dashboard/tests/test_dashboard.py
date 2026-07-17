#!/usr/bin/env python3
"""
Test the dashboard components

This module tests that the dashboard components work correctly
without needing to run the full Solara server.

The ``dashboard/`` directory is placed on ``sys.path`` by ``conftest.py`` so ``import app``
resolves no matter where the suite is launched from.
"""

import app
import pytest
from app import PERSON_DEFAULTS, DashboardLifeModel, param_value


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
    assert "Year" in df.columns
    assert "Income" in df.columns
    assert "Bank Balance" in df.columns


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
    final_balance_single = df_single["Bank Balance"].iloc[-1]
    final_balance_couple = df_couple["Bank Balance"].iloc[-1]

    assert final_balance_single > 0
    assert final_balance_couple > 0
    assert final_balance_couple > final_balance_single


def test_module_imports_and_builds_model():
    """Importing the module builds a runnable model and the SolaraViz page (smoke test)."""
    assert app.model is not None
    assert len(app.model.agents) > 0
    assert app.page is not None


def test_disabled_person_yields_single_person_at_import_defaults():
    """Unchecking a person via the checkbox spec yields a one-person model.

    Regression: the checkbox spec is a dict ({"value": False}); the model must read its inner
    value rather than treating the truthy dict as "enabled".
    """
    model = DashboardLifeModel(
        start_year=2023,
        end_year=2025,
        john_enabled={"label": "Include John", "type": "Checkbox", "value": True},
        jane_enabled={"label": "Include Jane", "type": "Checkbox", "value": False},
    )
    persons = [a for a in model.agents if a.__class__.__name__ == "Person"]
    assert len(persons) == 1


def test_param_spec_and_fallback_defaults_agree():
    """Each person's control spec default equals the fallback default (single source of truth).

    This invariant keeps import-time and post-slider construction in agreement: they read the
    control-spec default and the code fallback independently, so a mismatch (e.g. an ``enabled``
    flag or salary) would make the two construction paths diverge.
    """
    for prefix, name in (("john", "John"), ("jane", "Jane")):
        specs = app._person_param_specs(prefix, name)
        defaults = PERSON_DEFAULTS[prefix]
        for field, value in defaults.items():
            key = f"{prefix}_{field}"
            if key in specs:
                assert param_value(specs[key]) == value, f"{key} spec/default mismatch"


def test_model_stops_at_end_year():
    """The running flag clears at end_year so the SolaraViz Play loop halts."""
    model = DashboardLifeModel(start_year=2023, end_year=2025, jane_enabled=False)
    assert model.running
    model.run()
    assert not model.running
    # Stepping past the end is a no-op.
    years_before = list(model.simulated_years)
    model.step()
    assert model.simulated_years == years_before


def test_scenario_changes_outcomes():
    """The scenario selection visibly changes results (high_tax vs low_tax bank divergence)."""
    common = dict(start_year=2023, end_year=2033, john_enabled=True, jane_enabled=False, john_salary=120000)

    high = DashboardLifeModel(scenario="high_tax", **common)
    low = DashboardLifeModel(scenario="low_tax", **common)
    high.run()
    low.run()

    high_balance = high.datacollector.get_model_vars_dataframe()["Bank Balance"].iloc[-1]
    low_balance = low.datacollector.get_model_vars_dataframe()["Bank Balance"].iloc[-1]
    assert low_balance > high_balance


def test_scenario_default_label_uses_packaged_defaults():
    """The '(default)' dropdown label maps to scenario=None (packaged defaults)."""
    model = DashboardLifeModel(start_year=2023, end_year=2024, scenario=app.SCENARIO_DEFAULT_LABEL)
    assert model is not None
    assert app._scenario_value(app.SCENARIO_DEFAULT_LABEL) is None


def test_state_dropdown_maps_to_person_state():
    """The state dropdown sets Person.state; DEFAULT maps to None (config default pack)."""
    assert app.model_params["state"]["value"] == "DEFAULT"
    assert "CA" in app.model_params["state"]["values"]
    assert app._state_value("DEFAULT") is None
    assert app._state_value("CA") == "CA"

    from life_model.people.person import Person

    model = DashboardLifeModel(start_year=2023, end_year=2024, jane_enabled=False, state="CA")
    (person,) = [a for a in model.agents if isinstance(a, Person)]
    assert person.state == "CA"

    default_model = DashboardLifeModel(start_year=2023, end_year=2024, jane_enabled=False)
    (default_person,) = [a for a in default_model.agents if isinstance(a, Person)]
    assert default_person.state is None


def test_state_selection_changes_state_tax():
    """A no-income-tax state (TX) pays less total tax than the DEFAULT flat rate."""
    common = dict(start_year=2023, end_year=2033, john_enabled=True, jane_enabled=False, john_salary=120000)
    tx = DashboardLifeModel(state="TX", **common)
    default = DashboardLifeModel(state="DEFAULT", **common)
    tx.run()
    default.run()
    tx_balance = tx.datacollector.get_model_vars_dataframe()["Bank Balance"].iloc[-1]
    default_balance = default.datacollector.get_model_vars_dataframe()["Bank Balance"].iloc[-1]
    assert tx_balance > default_balance


def test_start_year_slider_allows_2023():
    """The Start Year slider minimum permits reproducing documented 2023-based examples."""
    start_slider = app.model_params["start_year"]
    assert start_slider.min <= 2023


def test_csv_export_matches_dataframe(single_person_model):
    """The results tab CSV export contains the same rows/columns as the yearly stats."""
    df = single_person_model.datacollector.get_model_vars_dataframe()
    csv = df.to_csv(index=False)
    header = csv.splitlines()[0].split(",")
    assert list(df.columns) == header
    # One header line + one line per simulated year.
    assert len(csv.strip().splitlines()) == len(df) + 1


def test_healthcare_toggle_default_off_and_opt_in():
    """The healthcare toggle defaults off (no healthcare agents); enabling it attaches them."""

    def build(**extra):
        return DashboardLifeModel(
            start_year=2023,
            end_year=2024,
            john_enabled=True,
            jane_enabled=False,
            john_age=64,
            **extra,
        )

    # Default off: no healthcare agents anywhere, and the param spec's default is False.
    assert app.model_params["healthcare_enabled"]["value"] is False
    model_off = build()
    assert model_off.registries.medical_costs.get_all_items() == []
    assert model_off.registries.medicare.get_all_items() == []
    assert model_off.registries.long_term_care.get_all_items() == []

    # Toggled on: each enabled person gets the three healthcare agents.
    model_on = build(healthcare_enabled=True)
    assert len(model_on.registries.medical_costs.get_all_items()) == 1
    assert len(model_on.registries.medicare.get_all_items()) == 1
    assert len(model_on.registries.long_term_care.get_all_items()) == 1
    model_on.run()
    df = model_on.datacollector.get_model_vars_dataframe()
    assert (df["Medical Costs"] > 0).all()
