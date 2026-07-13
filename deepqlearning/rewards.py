# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Utility-based reward for the financial life environment (Plan 19 D1).

The reward has genuine financial-planning semantics instead of the old ad-hoc net-worth-growth
shaping (which is maximized by hoarding and never spending). Each simulated year the agent earns
the **CRRA utility of its real (inflation-deflated) consumption** ``u(c_t)``; at the end of the
episode it earns a **bequest term** ``b(W)`` on the real net worth it leaves behind, unless it
went bankrupt, in which case it takes a large **ruin penalty** aligned with the environment's
bankruptcy termination threshold.

Design notes:

* **Purity.** Every function here is pure: it takes plain Python floats and returns a Python
  ``float`` (never an ``np.float64`` — the Plan 12 regression stays fixed). The environment feeds
  it nominal dollars, the cumulative-inflation deflator, and terminal flags; nothing here touches
  the model. That makes the objective unit-testable in isolation (monotonicity, concavity,
  deflation correctness, ruin alignment).
* **No double discounting.** Time preference is the DQN's ``gamma`` alone. The per-year reward is
  the *undiscounted* utility of that year's consumption; the optimizer discounts across years.
* **CRRA.** ``u(x) = (x**(1-g) - 1)/(1-g)`` for risk-aversion ``g != 1`` and ``log(x)`` at
  ``g == 1``. It is increasing and concave for ``x > 0`` and every ``g >= 0``, so more real
  consumption is always better but with diminishing returns — the shape that makes *smoothing*
  consumption optimal, i.e. actual financial planning.

``RewardConfig`` presets pin the risk-aversion / bequest / ruin parameters (they change
conclusions materially, so they are configuration recorded in the eval report, never buried
constants):

* ``wealth_max`` — bequest-dominant; approximates the old wealth-accumulation objective so the new
  and old worlds are comparable.
* ``retirement_security`` — *the default*; ruin-avoidance dominant (large ruin penalty, moderate
  risk aversion, modest bequest).
* ``smooth_consumption`` — high CRRA risk aversion, so the policy is pushed toward a smooth
  lifetime consumption path.
"""

from dataclasses import dataclass
from math import log
from typing import Dict


@dataclass(frozen=True)
class RewardConfig:
    """Parameters of the utility-based objective. All money values are in nominal dollars; the
    reward functions deflate them to real (start-of-episode) dollars before applying utility.

    Attributes:
        name: Preset name (recorded in the eval report).
        crra_gamma: Relative risk-aversion coefficient for the per-year consumption utility.
            0 = risk-neutral (linear), 1 = log, >1 = increasingly concave / risk-averse.
        consumption_weight: Multiplier on the per-year consumption utility term.
        consumption_scale: Dollars per consumption "unit"; real consumption is divided by this
            before the CRRA transform so per-year utilities stay O(1).
        consumption_floor: Real consumption is floored to this many dollars before the utility
            transform, so ``log(0)`` / negative-power blowups can't occur.
        bequest_weight: Multiplier on the terminal bequest utility term.
        bequest_gamma: CRRA coefficient for the bequest (warm-glow) utility.
        bequest_scale: Dollars per bequest "unit".
        ruin_penalty: Terminal penalty applied instead of the bequest when the episode ends in
            bankruptcy (net worth below the environment's ``BANKRUPTCY_THRESHOLD``).
    """

    name: str
    crra_gamma: float
    consumption_weight: float
    consumption_scale: float
    consumption_floor: float
    bequest_weight: float
    bequest_gamma: float
    bequest_scale: float
    ruin_penalty: float


def crra_utility(x: float, gamma: float) -> float:
    """Constant-relative-risk-aversion utility of ``x > 0``.

    ``u(x) = log(x)`` when ``gamma == 1`` else ``(x**(1 - gamma) - 1) / (1 - gamma)``. Increasing
    and concave in ``x`` for every ``gamma >= 0``. Returns a Python ``float``.

    Args:
        x: A strictly positive quantity (e.g. real consumption in scale units). Callers must floor
            it away from zero; this function does not.
        gamma: Relative risk-aversion coefficient (``>= 0``).
    """
    if x <= 0:
        raise ValueError(f"crra_utility requires x > 0, got {x!r}")
    if abs(gamma - 1.0) < 1e-12:
        return float(log(x))
    return float((x ** (1.0 - gamma) - 1.0) / (1.0 - gamma))


def _real(nominal: float, deflator: float) -> float:
    """Deflate a nominal dollar amount to real (start-of-episode) dollars."""
    return nominal / max(deflator, 1e-9)


def consumption_utility(nominal_consumption: float, deflator: float, config: RewardConfig) -> float:
    """Weighted CRRA utility of one year's **real** consumption.

    The nominal spending is deflated by ``deflator`` (the cumulative price level since the episode
    start), floored at ``config.consumption_floor``, expressed in ``config.consumption_scale``
    units, and passed through :func:`crra_utility`. Returns a Python ``float``.
    """
    real = max(_real(nominal_consumption, deflator), config.consumption_floor)
    units = real / config.consumption_scale
    return float(config.consumption_weight * crra_utility(units, config.crra_gamma))


def bequest_utility(nominal_net_worth: float, deflator: float, config: RewardConfig) -> float:
    """Weighted warm-glow CRRA utility of the **real** net worth left at the end of life.

    Uses the shifted (warm-glow) form ``crra(1 + W/scale, gamma)`` so that a zero estate yields
    exactly zero bequest utility and the term stays bounded below and finite even at ``gamma > 1``
    (an unshifted CRRA would go to ``-inf`` as ``W -> 0``, perversely making a near-broke solvent
    death worse than bankruptcy). Monotonic increasing and concave in ``W`` for ``W >= 0``. Real
    net worth is floored at zero (the ruin penalty, not the bequest, handles negative estates).
    Returns a Python ``float``.
    """
    real = max(_real(nominal_net_worth, deflator), 0.0)
    units = real / config.bequest_scale
    return float(config.bequest_weight * crra_utility(1.0 + units, config.bequest_gamma))


def step_reward(
    *,
    nominal_consumption: float,
    deflator: float,
    config: RewardConfig,
    terminal: bool,
    nominal_terminal_net_worth: float,
    ruined: bool,
) -> float:
    """Total reward for one environment step.

    Always includes the year's consumption utility. On the terminal step it adds either the ruin
    penalty (if the episode ended in bankruptcy) or the bequest utility (otherwise). Returns a
    Python ``float`` so no ``np.float64`` leaks into the replay buffer (Plan 12 regression).

    Args:
        nominal_consumption: This year's spending in nominal dollars.
        deflator: Cumulative price level since the episode start (``>= 1`` normally).
        config: The reward preset.
        terminal: Whether this step ends the episode (death, max age, bankruptcy, or horizon).
        nominal_terminal_net_worth: Net worth (or estate value at death) in nominal dollars; only
            used on the terminal step and only when not ruined.
        ruined: Whether the episode ended in bankruptcy (net worth below the bankruptcy threshold).
    """
    reward = consumption_utility(nominal_consumption, deflator, config)
    if terminal:
        if ruined:
            reward += config.ruin_penalty
        else:
            reward += bequest_utility(nominal_terminal_net_worth, deflator, config)
    return float(reward)


# Presets pin the parameters that materially change conclusions (risk aversion, bequest weight,
# ruin penalty). The eval report records which preset produced it.
REWARD_PRESETS: Dict[str, RewardConfig] = {
    # Bequest-dominant: per-year consumption barely matters and terminal (log) wealth dominates,
    # so the optimal policy accumulates — an approximation of the legacy wealth-max objective,
    # kept for comparability across the reward redesign.
    "wealth_max": RewardConfig(
        name="wealth_max",
        crra_gamma=1.0,
        consumption_weight=0.1,
        consumption_scale=10_000.0,
        consumption_floor=1_000.0,
        bequest_weight=10.0,
        bequest_gamma=1.0,
        bequest_scale=100_000.0,
        ruin_penalty=-20.0,
    ),
    # Default: ruin-avoidance dominant. A large terminal ruin penalty relative to a lifetime of
    # O(1) per-year consumption utilities makes "don't run out of money" the first-order goal,
    # with a modest bequest preference on top.
    "retirement_security": RewardConfig(
        name="retirement_security",
        crra_gamma=2.0,
        consumption_weight=1.0,
        consumption_scale=10_000.0,
        consumption_floor=1_000.0,
        bequest_weight=1.0,
        bequest_gamma=1.5,
        bequest_scale=100_000.0,
        ruin_penalty=-50.0,
    ),
    # High risk aversion (steeply concave consumption utility) pushes the policy toward a smooth
    # lifetime consumption path rather than feast-or-famine spending.
    "smooth_consumption": RewardConfig(
        name="smooth_consumption",
        crra_gamma=4.0,
        consumption_weight=1.0,
        consumption_scale=10_000.0,
        consumption_floor=1_000.0,
        bequest_weight=0.5,
        bequest_gamma=2.0,
        bequest_scale=100_000.0,
        ruin_penalty=-30.0,
    ),
}

# The plan's default objective (D1): ruin-avoidance is the headline retirement-planning question.
DEFAULT_PRESET = "retirement_security"


def get_reward_config(name: str) -> RewardConfig:
    """Look up a reward preset by name (raises ``KeyError`` with the valid names if unknown)."""
    if name not in REWARD_PRESETS:
        raise KeyError(f"Unknown reward preset {name!r}; expected one of {sorted(REWARD_PRESETS)}")
    return REWARD_PRESETS[name]
