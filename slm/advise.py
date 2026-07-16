# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tool-loop adviser: draft -> simulate -> revise (Plan 20 D1b, task 6).

The distilled model answers directly (mode a). The **tool-loop** (mode b) wraps any
:class:`~slm.adviser.AdviserModel` and puts a live simulator behind its advice: the model drafts a
decision, ``slm`` scores every candidate with a fresh Monte Carlo run, the scoreboard is fed back
for up to a fixed iteration budget, and — because ``trust_simulation`` is on by default — the loop
never ships a decision the simulator shows is dominated by more than a margin, and it always
rewrites the rationale from the fresh simulation numbers. That sidesteps hallucinated figures
entirely: the shipped numbers are, by construction, the simulator's.

Crucially the tool-loop is *itself* an ``AdviserModel`` (``generate(messages) -> text``), so it
drops into the identical Plan 20 eval harness as the distilled model — the evaluation compares
distilled-only vs tool-loop on the same held-out set. It reconstructs the scoring household from
the rendered household text (the serializer round-trips every field), so it needs nothing beyond
the messages it is handed. Scoring uses seeds derived from the household text, so a given household
always yields the same tool-loop answer (deterministic end-to-end, including under the stub).
"""

import zlib
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from life_model.people.person import GenderAtBirth

from .adviser import AdviserModel, Messages
from .prompts import format_decision_answer, parse_decision
from .rationales import build_rationale
from .scoring import argmax_candidate, score_household
from .serializer import parse_household
from .strategies import STRATEGY_BY_NAME

_MENU_MARKER = "Decision menu"

_GENDER_BY_NAME = {
    "male": GenderAtBirth.MALE,
    "female": GenderAtBirth.FEMALE,
    "other": GenderAtBirth.OTHER,
}


@dataclass
class ToolLoopConfig:
    """Tool-loop hyperparameters."""

    max_iters: int = 2
    n_trials: int = 16
    reward_preset: str = "retirement_security"
    seed: int = 0
    # If the drafted decision's success rate is more than this below the simulator's best, adopt
    # the simulator's best instead (the simulator-grounded correction).
    dominance_margin: float = 0.0
    trust_simulation: bool = True


def _user_text(messages: Messages) -> str:
    return "\n".join(m["content"] for m in messages if m.get("role") == "user")


def _household_from_text(text: str) -> Dict:
    """Reconstruct a scoring-ready household config from rendered household text."""
    parsed = parse_household(text)
    household: Dict = {
        "person_start_age": parsed["person_start_age"],
        "person_retirement_age": parsed["person_retirement_age"],
        "person_gender": _GENDER_BY_NAME[parsed["person_gender"].lower()],
        "initial_salary": float(parsed["initial_salary"]),
        "initial_bank_balance": float(parsed["initial_bank_balance"]),
        "initial_spending": float(parsed["initial_spending"]),
    }
    if parsed["economy_scenario"] is not None:
        household["economy_scenario"] = parsed["economy_scenario"]
    return household


class ToolLoopAdviser:
    """An ``AdviserModel`` that grounds a wrapped model's advice in a live Monte Carlo run."""

    def __init__(self, model: AdviserModel, config: Optional[ToolLoopConfig] = None):
        self.model = model
        self.config = config or ToolLoopConfig()

    def _trial_seeds(self, household_text: str) -> List[int]:
        # Seeds derived from the household text (stable) so the tool's scoring is deterministic and
        # independent of any eval seed the household is later re-scored under.
        base = (self.config.seed ^ zlib.crc32(household_text.encode())) & 0x7FFFFFFF
        seq = np.random.SeedSequence(base)
        return [int(child.generate_state(1)[0]) for child in seq.spawn(self.config.n_trials)]

    def _scoreboard_message(self, scored) -> Dict[str, str]:
        lines = ["Simulator Monte Carlo results (success rate, median terminal net worth):"]
        for c in sorted(scored, key=lambda s: s.success_rate, reverse=True):
            title = STRATEGY_BY_NAME[c.decision].title
            lines.append(f"- {c.decision} ({title}): success {c.success_rate:.0%}, median ${c.net_worth_p50:,.0f}")
        lines.append("Reconsider and give your final DECISION and RATIONALE.")
        return {"role": "user", "content": "\n".join(lines)}

    def generate(self, messages: Messages) -> str:
        user = _user_text(messages)
        # Out-of-scope / non-decision requests: defer to the wrapped model (its refusal behavior).
        if _MENU_MARKER not in user:
            return self.model.generate(messages)

        household = _household_from_text(user)
        seeds = self._trial_seeds(user)
        scored = score_household(household, seeds, self.config.reward_preset)
        by_name = {c.decision: c for c in scored}
        argmax = argmax_candidate(scored).decision

        # Draft, then revise up to the iteration budget, feeding the scoreboard back each round.
        convo: List[Dict[str, str]] = list(messages)
        decision = parse_decision(self.model.generate(convo))
        for _ in range(self.config.max_iters):
            board = self._scoreboard_message(scored)
            convo = convo + [board]
            revised = parse_decision(self.model.generate(convo))
            if revised is not None:
                decision = revised

        # Simulator-grounded correction: never ship a decision the simulator shows is dominated by
        # more than the margin; fall back to the simulated best.
        if self.config.trust_simulation:
            if decision is None or decision not in by_name:
                decision = argmax
            elif by_name[decision].success_rate < by_name[argmax].success_rate - self.config.dominance_margin:
                decision = argmax
        elif decision is None:
            decision = argmax

        # Ship the fresh simulation's own numbers, so the rationale is faithful by construction.
        rationale = build_rationale(scored, decision)
        return format_decision_answer(decision, rationale)
