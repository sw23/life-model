# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Serializer tests: rendered text faithfully reflects structured state (round-trip)."""

from slm.schema import HouseholdProfile
from slm.serializer import parse_household, render_household


def _profile(**overrides) -> HouseholdProfile:
    base = dict(
        scenario="mid_career",
        person_start_age=35,
        person_retirement_age=62,
        person_gender="Female",
        initial_salary=80000,
        initial_bank_balance=30000,
        initial_spending=50000,
    )
    base.update(overrides)
    return HouseholdProfile(**base)


def test_render_is_deterministic():
    p = _profile()
    assert render_household(p) == render_household(p)


def test_round_trip_recovers_all_fields():
    p = _profile(initial_salary=123456, initial_bank_balance=2000, initial_spending=45678)
    recovered = parse_household(render_household(p))
    assert recovered["scenario"] == p.scenario
    assert recovered["person_start_age"] == p.person_start_age
    assert recovered["person_retirement_age"] == p.person_retirement_age
    assert recovered["person_gender"].lower() == p.person_gender.lower()
    assert recovered["initial_salary"] == round(p.initial_salary)
    assert recovered["initial_spending"] == round(p.initial_spending)
    assert recovered["initial_bank_balance"] == round(p.initial_bank_balance)
    assert recovered["economy_scenario"] is None


def test_round_trip_recovers_economy_scenario():
    p = _profile(economy_scenario="recession")
    assert parse_household(render_household(p))["economy_scenario"] == "recession"


def test_round_trip_recovers_children_and_healthcare():
    p = _profile(children_ages=[2, 5, 11], models_healthcare=True)
    recovered = parse_household(render_household(p))
    assert recovered["children_ages"] == [2, 5, 11]
    assert recovered["models_healthcare"] is True


def test_round_trip_defaults_no_children_no_healthcare():
    recovered = parse_household(render_household(_profile()))
    assert recovered["children_ages"] == []
    assert recovered["models_healthcare"] is False


def test_children_and_healthcare_surfaced_in_text():
    text = render_household(_profile(children_ages=[4], models_healthcare=True))
    assert "1 child (age 4)" in text
    assert "Healthcare costs" in text and "are modeled" in text
    no_kids = render_household(_profile())
    assert "no children" in no_kids
    assert "not modeled" in no_kids


def test_text_mentions_key_facts():
    text = render_household(_profile())
    assert "mid_career" in text
    assert "retire at age 62" in text
    assert "$80,000" in text


def test_economy_scenario_surfaced():
    text = render_household(_profile(economy_scenario="recession"))
    assert "recession" in text
