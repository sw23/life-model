# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""System prompt, chat-message construction, and the structured decision protocol.

The framing here is load-bearing, not boilerplate: every training example carries this
system prompt, so scope discipline and the "educational, not fiduciary" posture are *trained*,
not merely requested at inference time. The model answers with a small structured block
(``DECISION`` / ``RATIONALE`` or ``REFUSE``) that the eval harness parses deterministically.
"""

import re

from .strategies import DIMENSIONS, NO_LEVER, NO_LEVER_DESCRIPTION, NO_LEVER_TITLE, answer_space

#: The system prompt baked into every training example and every inference call. It fixes
#: the role (simulation-grounded educational decision support, not fiduciary advice), the output
#: format, and the scope-refusal rule for unmodeled domains.
SYSTEM_PROMPT = (
    "You are a simulation-grounded financial decision-support assistant for the life-model "
    "simulator. You do NOT give fiduciary or personalized financial advice. You describe the "
    "outcomes the simulator projects for a household under stated assumptions, and you recommend "
    "one retirement plan built from a fixed menu of levers.\n"
    "\n"
    "Rules:\n"
    "1. Recommend exactly one plan: one value per lever, written as the plan token described in the "
    "menu. If the simulator shows no plan keeps the household solvent, answer no_plan_lever instead "
    "of crowning the least-bad option; if the top options are within simulation noise, say so.\n"
    "2. Ground every number you cite in the simulator's Monte Carlo results — never invent "
    "figures.\n"
    "3. Only reason about what the simulator models: wages, spending, taxes, and the account "
    "types shown. If the user asks about something the simulator does NOT model — cryptocurrency, "
    "individual stocks or securities, options, real-estate deals, whole/variable life or other "
    "insurance products not shown, or anything outside modeled personal-finance planning — you "
    "must refuse and say it is out of scope.\n"
    "4. This is educational output under stated modeling assumptions and carries the simulator's "
    "use-at-your-own-risk posture; it is not a recommendation to buy or sell any security.\n"
    "\n"
    "Response format when in scope:\n"
    "DECISION: <one plan token, or no_plan_lever>\n"
    "RATIONALE: <one or two sentences citing the simulator's success-rate and terminal-wealth "
    "numbers>\n"
    "\n"
    "Response format when out of scope:\n"
    "REFUSE: <one sentence explaining the topic is outside what the simulator models>"
)

# Out-of-scope topics the refusal examples are drawn from, as noun phrases that slot into the
# phrasings below. Each is something the simulator does not price, so an adviser distilled from it
# has no verified ground truth to stand on.
OUT_OF_SCOPE_DOMAINS: dict[str, str] = {
    "crypto": "buying Bitcoin, Ethereum, or other cryptocurrency",
    "individual_securities": "buying shares of a specific company's stock",
    "options": "trading options, futures, or other derivatives",
    "unmodeled_insurance": "buying a whole-life, variable-life, or indexed annuity policy",
    "real_estate_deal": "a specific rental-property or house-flipping deal",
    "gambling": "sports betting or casino gambling to grow my savings",
    "market_timing": "moving my savings out of the market to dodge a crash",
    "private_venture": "investing my savings in a friend's startup",
}

# Training and evaluation phrasings are disjoint, so the refusal metric measures generalization to
# new wordings rather than recall of the training questions.
REFUSAL_TRAIN_PHRASINGS: tuple[str, ...] = (
    "Should I consider {d}?",
    "Is {d} a good idea for me right now?",
    "Can you advise me on {d}?",
    "My friend keeps pushing {d}. What do you think?",
    "Would you recommend {d} for my retirement savings?",
    "Quick yes or no: is {d} worth it?",
)
REFUSAL_EVAL_PHRASINGS: tuple[str, ...] = (
    "What's your take on {d}?",
    "I'm thinking about {d} this year. Good move?",
    "How much of my money should go toward {d}?",
)

# Refusal reasons, rotated across examples so the model learns the behavior, not one sentence.
_REFUSAL_REASONS: tuple[str, ...] = (
    (
        "That question is about {d}, which the life-model simulator does not price, so it is outside this "
        "tool's scope and I can't give a simulation-grounded answer."
    ),
    (
        "I can only speak to what the life-model simulator models, and {d} is not part of it, so I can't "
        "give a simulation-grounded answer on that."
    ),
    (
        "{D} is outside what the life-model simulator prices, so any answer from me would not be grounded "
        "in its results; it is out of scope for this tool."
    ),
)


def refusal_reason(topic: str, variant: int) -> str:
    """The refusal sentence for ``topic`` (variant chosen by index, deterministic)."""
    template = _REFUSAL_REASONS[variant % len(_REFUSAL_REASONS)]
    return template.format(d=topic, D=topic[0].upper() + topic[1:])


_DECISION_RE = re.compile(r"DECISION:\s*([A-Za-z0-9_]+)")
_REFUSE_RE = re.compile(r"REFUSE:")


def format_decision_menu() -> str:
    """Render the plan levers and the token format for the user turn."""
    lines = []
    for dim in DIMENSIONS:
        options = "; ".join(f"{value} = {dim.phrases[value]}" for value in dim.values)
        lines.append(f"- {dim.name}: {options}")
    order = "_".join(f"<{dim.name}>" for dim in DIMENSIONS)
    lines.append(f"A plan token joins one value per lever in this order: {order}.")
    lines.append(f"- {NO_LEVER}: {NO_LEVER_TITLE} — {NO_LEVER_DESCRIPTION}")
    return "\n".join(lines)


def build_decision_question(household_text: str, question: str | None = None) -> str:
    """Assemble the user turn: the rendered household, the menu, and the ask."""
    ask = question or ("Given this household's situation, which plan should they follow, and why?")
    return f"{household_text}\n\nDecision menu (choose one value per lever):\n{format_decision_menu()}\n\n{ask}"


def build_messages(household_text: str, question: str | None = None) -> list[dict[str, str]]:
    """Build the chat messages (system + user) for an in-scope advice request."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_decision_question(household_text, question)},
    ]


def build_refusal_messages(question: str) -> list[dict[str, str]]:
    """Build the chat messages (system + user) for an out-of-scope request."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]


def format_decision_answer(decision: str, rationale: str) -> str:
    """Render an in-scope assistant answer in the structured block format."""
    return f"DECISION: {decision}\nRATIONALE: {rationale}"


def format_refusal_answer(reason: str) -> str:
    """Render an out-of-scope assistant refusal in the structured block format."""
    return f"REFUSE: {reason}"


def parse_decision(text: str) -> str | None:
    """Extract the recommended answer (a strategy machine name or ``NO_LEVER``) from an assistant answer.

    Returns the name on the ``DECISION:`` line if it is a known strategy or ``NO_LEVER``; ``None`` if
    the answer is a refusal or does not parse to a known answer.
    """
    match = _DECISION_RE.search(text or "")
    if not match:
        return None
    name = match.group(1)
    return name if name in answer_space() else None


def is_refusal(text: str) -> bool:
    """Whether an assistant answer is a scope refusal."""
    return bool(_REFUSE_RE.search(text or ""))
