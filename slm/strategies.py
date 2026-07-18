# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The adviser's decision vocabulary — plan-level levers.

Each *strategy* is a named, plan-level lever the adviser can recommend: a savings/contribution
policy (savings rate, Roth vs pre-tax split, emergency-fund ordering) or a drawdown policy. This
module is deliberately dependency-light (no ``deepqlearning`` / gymnasium / torch imports) so the
schema, serializer, prompt, and adviser-stub tests can import the decision vocabulary without the
RL stack. The mapping from a strategy name to the executable baseline policy that realizes it in
the simulator lives in :mod:`slm.candidates`, which does import the RL env.

The vocabulary is fixed and ordered; the ordering is the canonical decision-space order used in
prompts and serialized examples, so datasets stay comparable across runs.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class Strategy:
    """A named plan-level lever the adviser recommends."""

    #: Machine name (the token the model emits in its DECISION block).
    name: str
    #: Short human-readable title.
    title: str
    #: One-sentence description of the lever, used in prompts and rationales.
    description: str


# Canonical, ordered decision vocabulary. Each maps to an executable baseline policy in
# slm.candidates. These cover the plan-level levers: savings rate (age_glide),
# Roth/pre-tax split (max_pretax_401k vs max_roth_401k), emergency-fund ordering
# (emergency_fund_first), a tax-advantaged waterfall (contribution_waterfall), and drawdown
# ordering (four_percent_drawdown).
STRATEGIES: Tuple[Strategy, ...] = (
    Strategy(
        "contribution_waterfall",
        "Tax-advantaged contribution waterfall",
        "Keep a ~3-month cash reserve, then fund scarce tax-advantaged room first "
        "(HSA, then traditional IRA), then the pre-tax 401k, then a taxable brokerage.",
    ),
    Strategy(
        "age_glide",
        "Age-based savings glide path",
        "Contribute a rising share of savings to the pre-tax 401k as you age (about 10% under 35, up to 100% at 55+).",
    ),
    Strategy(
        "emergency_fund_first",
        "Emergency fund first",
        "Build a 6-month cash cushion before investing any surplus, then invest via the tax-advantaged waterfall.",
    ),
    Strategy(
        "four_percent_drawdown",
        "Accumulate then 4%-rule drawdown",
        "Build the nest egg while working, then draw it down in retirement taxable-and-"
        "tax-deferred first and Roth last.",
    ),
    Strategy(
        "max_pretax_401k",
        "Maximize pre-tax 401k",
        "Defer as much income as possible into the pre-tax 401k every working year "
        "(tax-deferred, taxed on withdrawal).",
    ),
    Strategy(
        "max_roth_401k",
        "Maximize Roth 401k",
        "Contribute as much as possible to the Roth 401k every working year "
        "(taxed now, tax-free growth and withdrawals).",
    ),
)

#: Ordered strategy names — the canonical decision-space ordering.
STRATEGY_NAMES: Tuple[str, ...] = tuple(s.name for s in STRATEGIES)

#: name -> Strategy lookup.
STRATEGY_BY_NAME: Dict[str, Strategy] = {s.name: s for s in STRATEGIES}


def decision_space() -> List[str]:
    """The canonical ordered list of recommendable strategy names."""
    return list(STRATEGY_NAMES)


def describe(name: str) -> str:
    """Human-readable ``title — description`` for a strategy name."""
    s = STRATEGY_BY_NAME[name]
    return f"{s.title} — {s.description}"
