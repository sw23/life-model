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
    common = {"start_year": 2023, "end_year": 2033, "john_enabled": True, "jane_enabled": False, "john_salary": 120000}

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
    common = {"start_year": 2023, "end_year": 2033, "john_enabled": True, "jane_enabled": False, "john_salary": 120000}
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


def test_dashboard_models_conserve_money():
    """Every dollar the dashboard's household gains or loses is on the ledger (Plan 28)."""
    from life_model.checks import assert_conservation

    for kwargs in ({}, {"home_enabled": True, "healthcare_enabled": True, "scenario": "recession"}):
        model = DashboardLifeModel(**kwargs)
        result = model.run()
        assert_conservation(model)
        assert result.model_frame["Net Worth"].notna().all()


# --- Plan 25: the dashboard builds through life_model.spec ------------------------------------


def _legacy_single_person_model(prefix, **kwargs):
    """The pre-spec dashboard construction for one person (verbatim core calls, as of the Plan 26
    merge), for parity checks."""
    from life_model.account.bank import BankAccount
    from life_model.account.job401k import Job401kAccount
    from life_model.healthcare import LongTermCare, MedicalCosts, Medicare
    from life_model.housing.home import Home, HomeExpenses, Mortgage
    from life_model.model import LifeModel
    from life_model.people.family import Family
    from life_model.people.person import Person, Spending
    from life_model.work.job import Job, Salary

    d = {**PERSON_DEFAULTS[prefix], **{k.removeprefix(f"{prefix}_"): v for k, v in kwargs.items()}}
    shared = {**app.SHARED_DEFAULTS, **kwargs}
    model = LifeModel(end_year=shared["end_year"], start_year=shared["start_year"], scenario=shared.get("scenario"))
    family = Family(model)
    person = Person(
        family=family,
        name=prefix.capitalize(),
        age=d["age"],
        retirement_age=d["retirement_age"],
        spending=Spending(model=model, base=d["spending"], yearly_increase=shared["spending_increase"]),
        state=shared.get("state"),
    )
    BankAccount(
        owner=person,
        company=d["bank_company"],
        type="Checking",
        balance=d["bank_balance"],
        interest_rate=shared["bank_interest_rate"],
    )
    job = Job(
        owner=person,
        company=d["company"],
        role=d["role"],
        salary=Salary(
            model=model, base=d["salary"], yearly_increase=shared["salary_increase"], yearly_bonus=d["bonus"]
        ),
    )
    if d["retirement_enabled"]:
        Job401kAccount(
            job=job,
            pretax_balance=d["retirement_balance"],
            pretax_contrib_percent=d["retirement_contrib"],
            # As the pre-spec dashboard wrote it after Plan 26 (fourth-wave 18ece11): a dollar-for-dollar
            # match up to the slider's percent of pay.
            match_tiers=[(100, d["company_match"])] if d["company_match"] > 0 else None,
            average_growth=d["retirement_growth"],
        )
    for i in range(int(d["children"])):
        person.add_child(f"{prefix.capitalize()}'s Child {i + 1}", birth_year=model.start_year)
    if shared["home_enabled"]:
        price = shared["home_price"]
        Home(
            person=person,
            name="Home",
            purchase_price=price,
            value_yearly_increase=None,
            down_payment=price * 0.20,
            mortgage=Mortgage(
                loan_amount=price * 0.8,
                start_date=model.start_year,
                length_years=int(shared["mortgage_term"]),
                yearly_interest_rate=shared["mortgage_rate"],
            ),
            expenses=HomeExpenses(
                model=model,
                property_tax_percent=1.0,
                home_insurance_percent=0.5,
                maintenance_amount=3000,
                maintenance_increase=2.0,
                improvement_amount=0,
                improvement_increase=0.0,
                hoa_amount=0,
                hoa_increase=0.0,
            ),
            purchase=False,
        )
    if shared["healthcare_enabled"]:
        MedicalCosts(person)
        Medicare(person)
        LongTermCare(person)
    return model


@pytest.mark.parametrize(
    "prefix, params",
    [
        ("john", {}),
        (
            "jane",
            {
                "jane_children": 2,
                "jane_bonus": 10,
                "home_enabled": True,
                "state": "CA",
                "scenario": "recession",
                "start_year": 2026,
                "end_year": 2070,
            },
        ),
        ("john", {"john_retirement_enabled": False, "healthcare_enabled": True, "start_year": 2026, "end_year": 2066}),
    ],
)
def test_single_person_dashboard_matches_legacy_construction(prefix, params):
    """One person (no marriage involved) builds exactly as the hand-written construction did."""
    other = "jane" if prefix == "john" else "john"
    model = DashboardLifeModel(**{**params, f"{other}_enabled": False})
    legacy = _legacy_single_person_model(prefix, **params)
    for m in (model, legacy):
        m.random.seed(11)  # long-term care draws from the model RNG
        m.run()
    new_df = model.datacollector.get_model_vars_dataframe()
    legacy_df = legacy.datacollector.get_model_vars_dataframe()
    assert new_df.equals(legacy_df)


def test_couple_is_married_and_files_jointly(couple_model):
    """Plan 25 D6: the dashboard's two adults are a married couple filing one joint return."""
    from life_model.people.tax_unit import TaxUnit
    from life_model.tax.federal import FilingStatus

    john, jane = couple_model.household.people["john"], couple_model.household.people["jane"]
    assert john.spouse is jane and jane.spouse is john
    assert john.filing_status == jane.filing_status == FilingStatus.MARRIED_FILING_JOINTLY
    (unit,) = TaxUnit.build_units(john.family)
    assert unit.filing_status == FilingStatus.MARRIED_FILING_JOINTLY
    assert [m.name for m in john.family.members] == ["John", "Jane"]


def test_household_spec_is_exposed_and_valid():
    from life_model.spec import validate_spec

    model = DashboardLifeModel(home_enabled=True, john_children=1)
    spec = model.household_spec
    assert [p.id for p in spec.people] == ["john", "jane"]
    assert spec.relationships.marriages[0].spouses == ("john", "jane")
    assert spec.people[0].housing[0].kind == "home"
    # The only finding on the defaults: every investment (the 401ks) is on fixed growth.
    assert [f.code for f in validate_spec(spec)] == ["fixed_growth"]


def test_nobody_enabled_builds_an_empty_family():
    model = DashboardLifeModel(john_enabled=False, jane_enabled=False)
    assert model.household_spec is None
    model.run()
