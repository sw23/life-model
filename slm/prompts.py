# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""System prompt, chat-message construction, and the structured decision protocol (Plan 20 D6).

The framing here is load-bearing, not boilerplate (D6): every training example carries this
system prompt, so scope discipline and the "educational, not fiduciary" posture are *trained*,
not merely requested at inference time. The model answers with a small structured block
(``DECISION`` / ``RATIONALE`` or ``REFUSE``) that the eval harness parses deterministically.
"""

import re
from typing import Dict, List, Optional

from .strategies import STRATEGIES, decision_space

#: The system prompt baked into every training example and every inference call (D6). It fixes
#: the role (simulation-grounded educational decision support, not fiduciary advice), the output
#: format, and the scope-refusal rule for unmodeled domains.
SYSTEM_PROMPT = (
    "You are a simulation-grounded financial decision-support assistant for the life-model "
    "simulator. You do NOT give fiduciary or personalized financial advice. You describe the "
    "outcomes the simulator projects for a household under stated assumptions, and you recommend "
    "one plan-level strategy from a fixed menu.\n"
    "\n"
    "Rules:\n"
    "1. Recommend exactly one strategy from the provided decision menu, by its machine name.\n"
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
    "DECISION: <one strategy machine name>\n"
    "RATIONALE: <one or two sentences citing the simulator's success-rate and terminal-wealth "
    "numbers>\n"
    "\n"
    "Response format when out of scope:\n"
    "REFUSE: <one sentence explaining the topic is outside what the simulator models>"
)

# Out-of-scope domains the refusal examples (D6) are drawn from. Each is something the simulator
# does not price, so an adviser distilled from it has no verified ground truth to stand on.
OUT_OF_SCOPE_DOMAINS: Dict[str, str] = {
    "crypto": "whether to buy Bitcoin, Ethereum, or other cryptocurrency",
    "individual_securities": "whether to buy shares of a specific company or a specific stock",
    "options": "trading options, futures, or other derivatives",
    "unmodeled_insurance": "whether to buy a whole-life, variable-life, or indexed annuity policy",
    "real_estate_deal": "whether a specific rental-property or house-flipping deal is a good buy",
}

_DECISION_RE = re.compile(r"DECISION:\s*([A-Za-z0-9_]+)")
_REFUSE_RE = re.compile(r"REFUSE:")


def format_decision_menu() -> str:
    """Render the ordered decision menu as a bulleted list for the user turn."""
    return "\n".join(f"- {s.name}: {s.title} — {s.description}" for s in STRATEGIES)


def build_decision_question(household_text: str, question: Optional[str] = None) -> str:
    """Assemble the user turn: the rendered household, the menu, and the ask."""
    ask = question or (
        "Given this household's situation, which single strategy from the menu should they "
        "follow, and why?"
    )
    return (
        f"{household_text}\n\n"
        f"Decision menu (choose exactly one by machine name):\n{format_decision_menu()}\n\n"
        f"{ask}"
    )


def build_messages(household_text: str, question: Optional[str] = None) -> List[Dict[str, str]]:
    """Build the chat messages (system + user) for an in-scope advice request."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_decision_question(household_text, question)},
    ]


def build_refusal_messages(question: str) -> List[Dict[str, str]]:
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


def parse_decision(text: str) -> Optional[str]:
    """Extract the recommended strategy machine name from an assistant answer.

    Returns the first strategy name that both matches the ``DECISION:`` line and is a known
    strategy; ``None`` if the answer is a refusal or does not parse to a known strategy.
    """
    match = _DECISION_RE.search(text or "")
    if not match:
        return None
    name = match.group(1)
    return name if name in decision_space() else None


def is_refusal(text: str) -> bool:
    """Whether an assistant answer is a scope refusal."""
    return bool(_REFUSE_RE.search(text or ""))
