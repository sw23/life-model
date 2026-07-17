# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tool-loop adviser tests:

* the tool-loop is an AdviserModel (drops into the eval harness),
* it is deterministic end-to-end under the stub,
* it grounds the shipped rationale in a fresh simulation (faithful by construction),
* trust_simulation corrects a stub that always picks a dominated lever,
* out-of-scope requests defer to the wrapped model's refusal.
"""

from slm.advise import ToolLoopAdviser, ToolLoopConfig, _household_from_text
from slm.adviser import AdviserModel, StubAdviserModel
from slm.faithfulness import is_faithful
from slm.generate_data import _sample_households, _to_profile
from slm.prompts import build_messages, build_refusal_messages, is_refusal, parse_decision
from slm.scoring import argmax_candidate, score_household
from slm.serializer import render_household

_HH_TEXT = None


def _household_text():
    global _HH_TEXT
    if _HH_TEXT is None:
        scenario, household, _ = _sample_households(["basic"], 1, 42)[0]
        _HH_TEXT = render_household(_to_profile(scenario, household))
    return _HH_TEXT


def test_tool_loop_is_adviser_model():
    loop = ToolLoopAdviser(StubAdviserModel(), ToolLoopConfig(n_trials=4, max_iters=1))
    assert isinstance(loop, AdviserModel)


def test_tool_loop_is_deterministic():
    loop = ToolLoopAdviser(StubAdviserModel(fixed_decision="age_glide"), ToolLoopConfig(n_trials=4, max_iters=1))
    messages = build_messages(_household_text())
    assert loop.generate(messages) == loop.generate(messages)


def test_tool_loop_output_parses_and_is_faithful():
    loop = ToolLoopAdviser(StubAdviserModel(fixed_decision="age_glide"), ToolLoopConfig(n_trials=6, max_iters=1))
    text = loop.generate(build_messages(_household_text()))
    decision = parse_decision(text)
    assert decision is not None
    # The shipped rationale cites the fresh simulation's own numbers for the chosen decision.
    household = _household_from_text(_household_text())
    loop_seeds = loop._trial_seeds(build_messages(_household_text())[1]["content"])
    scored = score_household(household, loop_seeds, "retirement_security")
    assert is_faithful(text, scored, decision)


def test_trust_simulation_corrects_dominated_pick():
    # A stub that always picks the weak "save_25_percent"-like lever is corrected to
    # the simulator's best when trust_simulation is on.
    loop = ToolLoopAdviser(
        StubAdviserModel(fixed_decision="max_roth_401k"),
        ToolLoopConfig(n_trials=8, max_iters=1, trust_simulation=True),
    )
    text = loop.generate(build_messages(_household_text()))
    decision = parse_decision(text)
    household = _household_from_text(_household_text())
    seeds = loop._trial_seeds(build_messages(_household_text())[1]["content"])
    scored = score_household(household, seeds, "retirement_security")
    best = argmax_candidate(scored)
    chosen = next(c for c in scored if c.decision == decision)
    # The shipped decision is never worse than the simulator's best on success rate.
    assert chosen.success_rate >= best.success_rate - 1e-9


def test_tool_loop_defers_refusal_to_model():
    loop = ToolLoopAdviser(StubAdviserModel(), ToolLoopConfig(n_trials=4, max_iters=1))
    text = loop.generate(build_refusal_messages("Should I buy Bitcoin?"))
    assert is_refusal(text)
    assert parse_decision(text) is None


def test_household_reconstructed_from_text():
    scenario, household, _ = _sample_households(["high_earner"], 1, 3)[0]
    text = render_household(_to_profile(scenario, household))
    recon = _household_from_text(text)
    assert recon["initial_salary"] == round(household["initial_salary"])
    assert recon["person_start_age"] == household["person_start_age"]
