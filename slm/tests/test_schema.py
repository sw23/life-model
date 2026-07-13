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


def test_schema_version_is_one():
    assert SCHEMA_VERSION == 1
    assert _example().schema_version == 1


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
