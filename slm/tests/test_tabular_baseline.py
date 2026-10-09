# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The tabular reference adviser (optional scikit-learn dependency)."""

import pytest

pytest.importorskip("sklearn")

from slm.generate_data import generate_examples
from slm.prompts import build_messages, build_refusal_messages, is_refusal, parse_decision
from slm.strategies import Plan
from slm.tabular_baseline import TabularAdviser


def test_tabular_adviser_answers_plans_and_refuses():
    rows = generate_examples(["basic", "pre_retiree"], n_per_scenario=6, n_trials=4, generation_seed=4)
    adviser = TabularAdviser(rows, max_iter=10)
    decision_row = next(r for r in rows if r.kind == "decision")
    answer = adviser.generate(build_messages(decision_row.household_text))
    assert Plan.parse(parse_decision(answer)) is not None
    assert is_refusal(adviser.generate(build_refusal_messages("Should I buy Bitcoin?")))
