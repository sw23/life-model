# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Schema tests: strict validation, version pinning, round-trip through JSON."""

import json

import pytest
from pydantic import ValidationError

from slm.schema import (
    SCHEMA_VERSION,
    AdviceExample,
    ChatMessage,
    HouseholdProfile,
    Provenance,
    ScoredCandidate,
)


def _example() -> AdviceExample:
    household = HouseholdProfile(
        scenario="basic",
        person_start_age=30,
        person_retirement_age=65,
        person_gender="Male",
        initial_salary=60000,
        initial_bank_balance=10000,
        initial_spending=35000,
    )
    return AdviceExample(
        example_id="basic-0001",
        kind="decision",
        household=household,
        household_text="Household profile ...",
        question="Which strategy?",
        decision_space=["contribution_waterfall", "age_glide"],
        chosen_decision="contribution_waterfall",
        scored_alternatives=[
            ScoredCandidate(
                decision="contribution_waterfall",
                success_rate=0.82,
                mean_return=30.0,
                net_worth_p10=100.0,
                net_worth_p50=200.0,
                net_worth_p90=300.0,
                n_trials=8,
            )
        ],
        rationale="Success 82%.",
        messages=[
            ChatMessage(role="system", content="s"),
            ChatMessage(role="user", content="u"),
            ChatMessage(role="assistant", content="DECISION: contribution_waterfall"),
        ],
        provenance=Provenance(
            generation_seed=7,
            simulator_commit="abc123",
            config_hash="deadbeef",
            n_trials=8,
            reward_preset="retirement_security",
        ),
    )


def test_schema_version_is_two():
    # v2: compositional plan decisions, paired gaps/gains, retirement-income household context.
    assert SCHEMA_VERSION == 2
    assert _example().schema_version == 2


def test_v1_rows_rejected():
    row = _example().model_dump()
    row["schema_version"] = 1
    with pytest.raises(ValidationError):
        AdviceExample(**row)


def test_extra_key_forbidden():
    with pytest.raises(ValidationError):
        HouseholdProfile(
            scenario="basic",
            person_start_age=30,
            person_retirement_age=65,
            person_gender="Male",
            initial_salary=1,
            initial_bank_balance=1,
            initial_spending=1,
            bogus_key=1,
        )


def test_success_rate_bounds():
    with pytest.raises(ValidationError):
        ScoredCandidate(
            decision="x",
            success_rate=1.5,
            mean_return=0.0,
            net_worth_p10=0.0,
            net_worth_p50=0.0,
            net_worth_p90=0.0,
            n_trials=1,
        )


def test_json_round_trip_is_stable():
    ex = _example()
    dumped = ex.model_dump(mode="json")
    reloaded = AdviceExample.model_validate(dumped)
    # Byte-identical canonical JSON on re-dump — the property generate_data relies on.
    assert json.dumps(dumped, sort_keys=True) == json.dumps(reloaded.model_dump(mode="json"), sort_keys=True)


def test_refusal_example_has_no_household():
    ex = AdviceExample(
        example_id="refuse-crypto-0",
        kind="refusal",
        question="Should I buy Bitcoin?",
        rationale="Out of scope.",
        out_of_scope=True,
        messages=[ChatMessage(role="assistant", content="REFUSE: out of scope")],
    )
    assert ex.household is None
    assert ex.out_of_scope is True


# --- Plan 25: HouseholdProfile is a projection of the HouseholdSpec ---------------------------


def test_profile_round_trips_through_the_household_spec():
    from slm.generate_data import _to_profile
    from slm.households import SLM_SCENARIOS, sample_households

    for scenario, household, _ in sample_households(list(SLM_SCENARIOS), 3, generation_seed=4):
        profile = _to_profile(scenario, household)
        spec = profile.to_household_spec()
        again = HouseholdProfile.from_household_spec(
            spec,
            scenario=profile.scenario,
            retirement_spending_ratio=profile.retirement_spending_ratio,
            employer_match_rate=profile.employer_match_rate,
            employer_match_cap=profile.employer_match_cap,
        )
        assert again == profile


def test_profile_spec_is_the_household_the_scoring_env_builds():
    from deepqlearning.envs.financial.scenarios import household_spec
    from slm.generate_data import _to_profile
    from slm.households import SLM_SCENARIOS, sample_households

    for scenario, household, _ in sample_households(list(SLM_SCENARIOS), 2, generation_seed=9):
        profile = _to_profile(scenario, household)
        expected = household_spec(household, {"household_scenario": scenario})
        assert profile.to_household_spec() == expected


def test_profile_without_social_security_projects_without_it():
    profile = HouseholdProfile(
        scenario="basic",
        person_start_age=30,
        person_retirement_age=65,
        person_gender="Female",
        initial_salary=50000,
        initial_bank_balance=1000,
        initial_spending=30000,
    )
    spec = profile.to_household_spec()
    assert spec.people[0].social_security is None
    assert HouseholdProfile.from_household_spec(spec, scenario="basic") == profile


def test_sample_dataset_text_is_rendered_from_the_spec():
    """The committed sample's household text is byte-identical to rendering its profile's spec."""
    from pathlib import Path

    from slm.serializer import render_household

    path = Path(__file__).resolve().parents[1] / "data" / "sample_dataset.jsonl"
    rows = [AdviceExample.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()]
    decisions = [row for row in rows if row.household is not None]
    assert decisions
    for row in decisions:
        assert render_household(row.household) == row.household_text
