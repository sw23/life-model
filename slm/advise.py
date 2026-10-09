# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tool-loop adviser: draft -> simulate -> revise.

The distilled model answers directly (mode a). The **tool-loop** (mode b) wraps any
:class:`~slm.adviser.AdviserModel` and puts a live simulator behind its advice: the model drafts a
decision, ``slm`` scores every candidate with a fresh Monte Carlo run, the scoreboard is fed back
for up to a fixed iteration budget, and — because ``trust_simulation`` is on by default — the loop
never ships a decision the simulator shows is dominated by more than a margin, and it always
rewrites the rationale from the fresh simulation numbers. "Dominated" means outside the top set:
worse than the best on paired trials beyond Monte Carlo noise. That sidesteps hallucinated figures
entirely: the shipped numbers are, by construction, the simulator's.

Crucially the tool-loop is *itself* an ``AdviserModel`` (``generate(messages) -> text``), so it
drops into the identical eval harness as the distilled model — the evaluation compares
distilled-only vs tool-loop on the same held-out set. It reconstructs the scoring household from
the rendered household text (the serializer round-trips every field), so it needs nothing beyond
the messages it is handed. Scoring uses seeds derived from the household text, so a given household
always yields the same tool-loop answer (deterministic end-to-end, including under the stub).
"""

import zlib
from dataclasses import dataclass

import numpy as np

from life_model.people.person import GenderAtBirth

from .adviser import AdviserModel, Messages
from .prompts import format_decision_answer, parse_decision
from .rationales import build_rationale
from .scoring import argmax_candidate, label_decision, score_household
from .serializer import parse_household
from .strategies import NO_LEVER, STRATEGY_BY_NAME

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
    # If the drafted decision is outside the simulator's top set (worse than the best beyond Monte
    # Carlo noise on paired trials) and its mean return trails the best by more than this, adopt the
    # simulator's label instead (the simulator-grounded correction).
    dominance_margin: float = 0.0
    trust_simulation: bool = True


def _user_text(messages: Messages) -> str:
    return "\n".join(m["content"] for m in messages if m.get("role") == "user")


def _household_from_text(text: str) -> dict:
    """Reconstruct a scoring-ready household config from rendered household text."""
    parsed = parse_household(text)
    household: dict = {
        "person_start_age": parsed["person_start_age"],
        "person_retirement_age": parsed["person_retirement_age"],
        "person_gender": _GENDER_BY_NAME[parsed["person_gender"].lower()],
        "initial_salary": float(parsed["initial_salary"]),
        "initial_bank_balance": float(parsed["initial_bank_balance"]),
        "initial_spending": float(parsed["initial_spending"]),
        "children_ages": list(parsed["children_ages"]),
        "models_healthcare": parsed["models_healthcare"],
        "employer_match_rate": float(parsed["employer_match_rate"]),
        "employer_match_cap": float(parsed["employer_match_cap"]),
        "initial_401k_pretax": float(parsed["initial_401k_pretax"]),
        "initial_401k_roth": float(parsed["initial_401k_roth"]),
        "initial_brokerage": float(parsed["initial_brokerage"]),
        "ss_claim_age": parsed["ss_claim_age"],
        "retirement_spending_ratio": float(parsed["retirement_spending_ratio"]),
    }
    if parsed["economy_scenario"] is not None:
        household["economy_scenario"] = parsed["economy_scenario"]
    return household


class ToolLoopAdviser:
    """An ``AdviserModel`` that grounds a wrapped model's advice in a live Monte Carlo run."""

    def __init__(self, model: AdviserModel, config: ToolLoopConfig | None = None):
        self.model = model
        self.config = config or ToolLoopConfig()

    def _trial_seeds(self, household_text: str) -> list[int]:
        # Seeds derived from the household text (stable) so the tool's scoring is deterministic and
        # independent of any eval seed the household is later re-scored under.
        base = (self.config.seed ^ zlib.crc32(household_text.encode())) & 0x7FFFFFFF
        seq = np.random.SeedSequence(base)
        return [int(child.generate_state(1)[0]) for child in seq.spawn(self.config.n_trials)]

    def _scoreboard_message(self, scored) -> dict[str, str]:
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
        label = label_decision(scored)

        # Draft, then revise up to the iteration budget, feeding the scoreboard back each round.
        convo: list[dict[str, str]] = list(messages)
        decision = parse_decision(self.model.generate(convo))
        for _ in range(self.config.max_iters):
            board = self._scoreboard_message(scored)
            convo = convo + [board]
            revised = parse_decision(self.model.generate(convo))
            if revised is not None:
                decision = revised

        # Simulator-grounded correction: never ship a decision the simulator shows is dominated by
        # more than the margin, nor a no_plan_lever the simulator contradicts (some lever is viable);
        # fall back to the simulated label.
        if self.config.trust_simulation:
            if decision == NO_LEVER:
                if label != NO_LEVER:
                    decision = label
            elif (
                decision is None
                or decision not in by_name
                or (
                    not by_name[decision].in_top_set
                    and by_name[argmax].mean_return - by_name[decision].mean_return > self.config.dominance_margin
                )
            ):
                decision = label
        elif decision is None:
            decision = label

        # Ship the fresh simulation's own numbers, so the rationale is faithful by construction.
        rationale = build_rationale(scored, decision)
        return format_decision_answer(decision, rationale)
