# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The ``AdviserModel`` interface abstraction and deterministic stubs (Plan 20 D5, task 1).

The whole pipeline talks to a model through one tiny protocol — ``generate(messages) -> text`` —
so a local SLM, a local MLX model, and a hosted API model are interchangeable on the same eval
harness. CI never loads weights: the schema/scoring/eval/tool-loop tests all run against the
deterministic stubs here. Real backends (HF/MLX/API) live in :mod:`slm.backends` behind lazy
imports so importing this module never pulls in torch or transformers.
"""

from typing import Dict, List, Optional, Protocol, runtime_checkable

from .prompts import format_decision_answer, format_refusal_answer
from .strategies import STRATEGY_NAMES, decision_space

Messages = List[Dict[str, str]]

# Marker the user turn carries when (and only when) it is an in-scope decision request. The
# stubs use its presence/absence to decide whether to answer or refuse, mirroring what a trained
# model learns from the system prompt.
_MENU_MARKER = "Decision menu"


@runtime_checkable
class AdviserModel(Protocol):
    """Minimal model interface: map a chat message list to an assistant text response."""

    def generate(self, messages: Messages) -> str:
        """Return the assistant's text response to ``messages`` (system + user turns)."""
        ...


def _user_text(messages: Messages) -> str:
    """Concatenate the user turns (the only content the stubs inspect)."""
    return "\n".join(m["content"] for m in messages if m.get("role") == "user")


class StubAdviserModel:
    """Deterministic stub: emit a fixed in-scope decision, or refuse out-of-scope requests.

    A request is treated as in-scope iff its user turn contains the decision menu marker (the
    same signal the system prompt keys refusals off). In scope it returns ``fixed_decision``
    (default: the first strategy) with a fixed rationale; out of scope it refuses. Used to drive
    the full pipeline end-to-end in CI without any weights.
    """

    def __init__(self, fixed_decision: Optional[str] = None, rationale: str = "Stubbed rationale."):
        self.fixed_decision = fixed_decision or STRATEGY_NAMES[0]
        if self.fixed_decision not in decision_space():
            raise ValueError(f"unknown strategy {self.fixed_decision!r}")
        self.rationale = rationale

    def generate(self, messages: Messages) -> str:
        if _MENU_MARKER in _user_text(messages):
            return format_decision_answer(self.fixed_decision, self.rationale)
        return format_refusal_answer("That topic is outside what the life-model simulator prices.")


class ScriptedAdviserModel:
    """Deterministic stub that answers from a household-text -> decision map.

    Given a mapping from a household's rendered text (or any unique substring of it) to the
    decision to emit, it returns the decision for whichever key appears in the user turn. This is
    how the eval harness builds an *oracle* adviser: score every candidate per household, map each
    household to its argmax, and drive it through the identical generate → parse → execute path as
    any real model. Out-of-scope requests (no menu, no matching key) refuse.
    """

    def __init__(self, decision_by_household: Dict[str, str], rationale: str = "Oracle argmax."):
        self.decision_by_household = dict(decision_by_household)
        self.rationale = rationale

    def generate(self, messages: Messages) -> str:
        user = _user_text(messages)
        if _MENU_MARKER in user:
            for key, decision in self.decision_by_household.items():
                if key in user:
                    return format_decision_answer(decision, self.rationale)
        return format_refusal_answer("That topic is outside what the life-model simulator prices.")
