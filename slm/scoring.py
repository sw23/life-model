# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Monte Carlo scoring of candidate decisions on a household.

Each candidate strategy is scored on a *shared* set of trial seeds so the comparison is paired:
the same economy/mortality draws under every strategy, so the deltas the rationale cites are
attributable to the decision, not to lucky seeds. Scoring reuses the RL outcome machinery
(``run_policy_episode``): per-trial real terminal net worth, ruin, and the utility return.

All figures are rounded deterministically (rates to 4 dp, dollars to 2 dp) so the scored records
— and therefore the rationale numbers copied from them and the serialized JSONL — are
byte-identical under the same seed. Trial counts are modest by design: they rank candidates (rank
stability), they are not tight confidence intervals, and the datasheet records the count so
precision claims stay honest.
"""

from typing import Dict, List, Optional

import numpy as np
from environment import FinancialLifeEnv
from evaluation import run_policy_episode

from .candidates import CANDIDATE_POLICIES
from .schema import ScoredCandidate
from .strategies import STRATEGY_NAMES

# Economy is stochastic during scoring so candidates are judged across good and bad years.
_DEFAULT_ECONOMY_MODE = "stochastic"


def make_scoring_env(household: Dict, reward_preset: str) -> FinancialLifeEnv:
    """Build a fixed-household env for scoring (the household is the env's point configuration)."""
    config = dict(household)
    config.setdefault("economy_mode", _DEFAULT_ECONOMY_MODE)
    config["reward_preset"] = reward_preset
    return FinancialLifeEnv(config)


def _round_rate(x: float) -> float:
    return round(float(x), 4)


def _round_money(x: float) -> float:
    return round(float(x), 2)


def score_candidate(env: FinancialLifeEnv, name: str, seeds: List[int]) -> ScoredCandidate:
    """Score a single candidate strategy on ``env`` over the shared ``seeds``."""
    policy = CANDIDATE_POLICIES[name]
    outcomes = [run_policy_episode(env, policy, seed) for seed in seeds]
    net_worths = np.array([o.real_terminal_net_worth for o in outcomes], dtype=float)
    returns = np.array([o.total_reward for o in outcomes], dtype=float)
    return ScoredCandidate(
        decision=name,
        success_rate=_round_rate(np.mean([o.success for o in outcomes])),
        mean_return=_round_money(returns.mean()),
        net_worth_p10=_round_money(np.percentile(net_worths, 10)),
        net_worth_p50=_round_money(np.percentile(net_worths, 50)),
        net_worth_p90=_round_money(np.percentile(net_worths, 90)),
        n_trials=len(seeds),
    )


def score_household(
    household: Dict,
    seeds: List[int],
    reward_preset: str,
    candidate_names: Optional[List[str]] = None,
) -> List[ScoredCandidate]:
    """Score every candidate strategy on one household over shared trial seeds.

    Returns the scored candidates in the canonical strategy order (not sorted by score), so the
    serialized ``decision_space`` / ``scored_alternatives`` ordering is stable across runs.
    """
    names = candidate_names or list(STRATEGY_NAMES)
    env = make_scoring_env(household, reward_preset)
    return [score_candidate(env, name, seeds) for name in names]


def argmax_candidate(scored: List[ScoredCandidate]) -> ScoredCandidate:
    """The winning candidate: highest success rate, breaking ties by median terminal wealth then
    by name (fully deterministic)."""
    return max(scored, key=lambda c: (c.success_rate, c.net_worth_p50, _neg_name(c.decision)))


def _neg_name(name: str) -> tuple:
    """Sort key that makes an *earlier* name win ties (max picks the largest key)."""
    return tuple(-ord(ch) for ch in name)
