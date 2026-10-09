# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""A tabular reference adviser: gradient-boosted trees on the structured household fields.

It reads the same facts the language model reads (parsed back out of the rendered household text)
and predicts each plan lever with one classifier per dimension, trained on the dataset's labels.
It answers with no rationale numbers, so it measures decision quality only. Its job in the eval is
a learnability bar: if a language model cannot match a small tabular model given the same facts,
the gap is in the language model, not in the labels.

Optional dependency: scikit-learn (soft import; only this module needs it).
"""

import numpy as np

from .adviser import Messages, _user_text
from .prompts import format_decision_answer, format_refusal_answer
from .schema import AdviceExample
from .serializer import parse_household
from .strategies import DIMENSIONS, NO_LEVER, Plan

_MENU_MARKER = "Decision menu"
_ECONOMIES = (None, "boom", "high_inflation", "deflation", "conservative", "aggressive", "recession")


def household_features(h: dict) -> list[float]:
    """Numeric features of a parsed household (the fields the rendered text states)."""
    salary = max(float(h["initial_salary"]), 1.0)
    economy = h.get("economy_scenario")
    return [
        float(h["person_start_age"]),
        float(h["person_retirement_age"]),
        salary,
        float(h["initial_bank_balance"]),
        float(h["initial_spending"]),
        float(h["initial_spending"]) / salary,
        float(h.get("employer_match_rate", 0.0)),
        float(h.get("employer_match_cap", 0.0)),
        float(h.get("initial_401k_pretax", 0.0)),
        float(h.get("initial_401k_roth", 0.0)),
        float(h.get("initial_brokerage", 0.0)),
        float(h.get("retirement_spending_ratio", 1.0)),
        float(len(h.get("children_ages", []))),
        float(_ECONOMIES.index(economy) if economy in _ECONOMIES else 0),
    ]


class TabularAdviser:
    """An ``AdviserModel`` backed by per-lever gradient-boosted classifiers."""

    def __init__(self, rows: list[AdviceExample], max_iter: int = 200, seed: int = 0):
        from sklearn.ensemble import HistGradientBoostingClassifier

        decisions = [r for r in rows if r.kind == "decision" and r.chosen_decision != NO_LEVER]
        X = np.array([household_features(parse_household(r.household_text)) for r in decisions])
        self.models = {}
        for dim in DIMENSIONS:
            y = [getattr(Plan.parse(r.chosen_decision), dim.name) for r in decisions]
            self.models[dim.name] = HistGradientBoostingClassifier(max_iter=max_iter, random_state=seed).fit(X, y)

    def generate(self, messages: Messages) -> str:
        user = _user_text(messages)
        if _MENU_MARKER not in user:
            return format_refusal_answer("That topic is outside what the life-model simulator prices.")
        x = np.array([household_features(parse_household(user))])
        plan = Plan(**{name: str(model.predict(x)[0]) for name, model in self.models.items()})
        return format_decision_answer(plan.name, "Tabular baseline (no rationale).")
