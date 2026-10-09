# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The adviser's decision vocabulary — compositional retirement plans.

A plan fixes one value on each of four independent dimensions a planner actually advises on:

* **savings** — keep spending as is, or save 5 / 10 more percentage points of salary while working
  (spending is restored at retirement);
* **routing** — where 401k deferrals go: all ``pretax``, all ``roth``, or ``split`` (pre-tax down to
  the top of the 12% bracket, Roth for the rest); savings beyond the 402(g) room go to a taxable
  brokerage above a three-month cash reserve;
* **claim** — when Social Security is claimed: at retirement (``claimret``), at full retirement age
  (``claimfra``, or at retirement if later), or at 70 (``claim70``);
* **drawdown** — ``conventional`` (the simulator's default order: taxable and pre-tax sized against
  taxes, then Roth) or ``bracketfill`` (each retired year, draw pre-tax savings up to the top of the
  12% bracket before RMDs force larger, higher-taxed withdrawals).

Retirement age is deliberately *not* a lever: the objective prices consumption and wealth but not
leisure, so "work two more years" would win almost everywhere and teach nothing.

A plan is written as one token, ``save5_roth_claim70_bracketfill`` (dimension values joined in a
fixed order), so the decision line stays a single machine name. The vocabulary is fixed and ordered;
the ordering is the canonical decision-space order. This module is dependency-light (no RL imports)
so schema, prompt, and stub tests can import it.
"""

import itertools
from dataclasses import dataclass


@dataclass(frozen=True)
class Dimension:
    """One plan dimension: its name, its ordered values, the default, and how each value reads."""

    name: str
    values: tuple[str, ...]
    default: str
    phrases: dict[str, str]


DIMENSIONS: tuple[Dimension, ...] = (
    Dimension(
        "savings",
        ("save0", "save5", "save10"),
        "save0",
        {
            "save0": "keep current spending",
            "save5": "save 5 more points of salary while working",
            "save10": "save 10 more points of salary while working",
        },
    ),
    Dimension(
        "routing",
        ("pretax", "roth", "split"),
        "pretax",
        {
            "pretax": "defer to the pre-tax 401k",
            "roth": "defer to the Roth 401k",
            "split": "defer pre-tax on pay above the 12% bracket and Roth on the rest",
        },
    ),
    Dimension(
        "claim",
        ("claimret", "claimfra", "claim70"),
        "claimret",
        {
            "claimret": "claim Social Security at retirement",
            "claimfra": "claim Social Security at full retirement age",
            "claim70": "claim Social Security at 70",
        },
    ),
    Dimension(
        "drawdown",
        ("conventional", "bracketfill"),
        "conventional",
        {
            "conventional": "draw down in the default order",
            "bracketfill": "fill the 12% bracket from the pre-tax 401k each retired year",
        },
    ),
)

DIMENSION_BY_NAME: dict[str, Dimension] = {d.name: d for d in DIMENSIONS}


@dataclass(frozen=True)
class Plan:
    """A compositional retirement plan: one value per dimension."""

    savings: str = "save0"
    routing: str = "pretax"
    claim: str = "claimret"
    drawdown: str = "conventional"

    @property
    def name(self) -> str:
        return "_".join(getattr(self, d.name) for d in DIMENSIONS)

    @property
    def savings_boost_pct(self) -> int:
        return int(self.savings.removeprefix("save"))

    def with_value(self, dimension: str, value: str) -> "Plan":
        return Plan(**{**self.values(), dimension: value})

    def values(self) -> dict[str, str]:
        return {d.name: getattr(self, d.name) for d in DIMENSIONS}

    @classmethod
    def parse(cls, name: str) -> "Plan | None":
        """The plan a token names, or ``None`` if it is not a well-formed plan token."""
        parts = name.split("_")
        if len(parts) != len(DIMENSIONS):
            return None
        if any(part not in dim.values for part, dim in zip(parts, DIMENSIONS)):
            return None
        return cls(**{dim.name: part for part, dim in zip(parts, DIMENSIONS)})


DEFAULT_PLAN = Plan()

#: Every plan, in canonical order (savings-major, then routing, claim, drawdown).
ALL_PLANS: tuple[Plan, ...] = tuple(Plan(*combo) for combo in itertools.product(*(d.values for d in DIMENSIONS)))


@dataclass(frozen=True)
class Strategy:
    """A named plan the adviser can recommend (kept for the prompt/rationale vocabulary)."""

    #: Machine name (the token the model emits in its DECISION block).
    name: str
    #: Short human-readable title.
    title: str
    #: One-sentence description, used in prompts and rationales.
    description: str


def plan_title(plan: Plan) -> str:
    """Human-readable plan description, e.g. "keep current spending, defer to the Roth 401k, ..."."""
    phrases = [DIMENSION_BY_NAME[d.name].phrases[getattr(plan, d.name)] for d in DIMENSIONS]
    text = ", ".join(phrases)
    return text[0].upper() + text[1:]


STRATEGIES: tuple[Strategy, ...] = tuple(Strategy(p.name, plan_title(p), plan_title(p)) for p in ALL_PLANS)

#: Ordered plan names — the canonical decision-space ordering.
STRATEGY_NAMES: tuple[str, ...] = tuple(s.name for s in STRATEGIES)

#: name -> Strategy lookup.
STRATEGY_BY_NAME: dict[str, Strategy] = {s.name: s for s in STRATEGIES}


#: The one non-plan answer: no plan keeps the household solvent, so the adviser says so instead of
#: crowning the least-bad one. It is not executable; the eval harness runs the default plan
#: (``NO_LEVER_DEFAULT_PLAN``) for it, so abstaining never beats a plan that helps.
NO_LEVER = "no_plan_lever"
NO_LEVER_TITLE = "No plan is sufficient"
NO_LEVER_DESCRIPTION = (
    "Every plan leaves the household short in nearly all trials; the gap is spending versus income, which "
    "these levers do not close."
)
NO_LEVER_DEFAULT_PLAN = DEFAULT_PLAN.name


def decision_space() -> list[str]:
    """The canonical ordered list of recommendable plan names."""
    return list(STRATEGY_NAMES)


def answer_space() -> list[str]:
    """Every answer the adviser may give: the plans plus ``NO_LEVER``."""
    return [*STRATEGY_NAMES, NO_LEVER]


def describe(name: str) -> str:
    """Human-readable ``title — description`` for a plan name."""
    s = STRATEGY_BY_NAME[name]
    return s.title


def dimension_agreement(a: str, b: str) -> float:
    """Share of plan dimensions on which two answers agree (1.0 for identical; 0.0 if either is not a plan)."""
    pa, pb = Plan.parse(a), Plan.parse(b)
    if pa is None or pb is None:
        return float(a == b)
    return sum(getattr(pa, d.name) == getattr(pb, d.name) for d in DIMENSIONS) / len(DIMENSIONS)
