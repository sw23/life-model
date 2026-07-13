# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Adviser protocol + stub tests, and the decision/refusal parsing round-trip."""

from slm.adviser import AdviserModel, ScriptedAdviserModel, StubAdviserModel
from slm.prompts import build_messages, build_refusal_messages, is_refusal, parse_decision
from slm.strategies import STRATEGY_NAMES


def test_stub_satisfies_protocol():
    assert isinstance(StubAdviserModel(), AdviserModel)


def test_stub_emits_parseable_in_scope_decision():
    model = StubAdviserModel(fixed_decision="age_glide")
    messages = build_messages("Household profile (basic scenario). ...")
    text = model.generate(messages)
    assert parse_decision(text) == "age_glide"
    assert not is_refusal(text)


def test_stub_refuses_out_of_scope():
    model = StubAdviserModel()
    text = model.generate(build_refusal_messages("Should I buy Bitcoin?"))
    assert is_refusal(text)
    assert parse_decision(text) is None


def test_stub_is_deterministic():
    model = StubAdviserModel(fixed_decision="max_roth_401k")
    messages = build_messages("Household profile (basic scenario). ...")
    assert model.generate(messages) == model.generate(messages)


def test_scripted_oracle_selects_by_household_text():
    # Two distinct households mapped to two distinct decisions.
    mapping = {
        "high_earner scenario": "max_pretax_401k",
        "low_earner scenario": "emergency_fund_first",
    }
    model = ScriptedAdviserModel(mapping)
    high = model.generate(build_messages("Household profile (high_earner scenario). ..."))
    low = model.generate(build_messages("Household profile (low_earner scenario). ..."))
    assert parse_decision(high) == "max_pretax_401k"
    assert parse_decision(low) == "emergency_fund_first"


def test_parse_decision_rejects_unknown_strategy():
    assert parse_decision("DECISION: not_a_real_strategy") is None


def test_all_strategy_names_parse():
    for name in STRATEGY_NAMES:
        assert parse_decision(f"DECISION: {name}\nRATIONALE: x") == name
