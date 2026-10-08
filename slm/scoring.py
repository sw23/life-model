# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Monte Carlo scoring of candidate decisions on a household.

Each candidate strategy is scored on a *shared* set of trial seeds so the comparison is paired:
the same economy/mortality draws under every strategy, so the deltas the rationale cites are
attributable to the decision, not to lucky seeds. Scoring reuses the RL outcome machinery
(``run_policy_episode``): per-trial real terminal net worth, ruin, and the utility return.

The label is the candidate with the highest mean **utility return** under the reward preset (the
objective the RL agents optimize: ruin-avoidance first, then the wealth left at death), and each
candidate records its paired per-trial shortfall to that best with a bootstrap CI. A label is
``clear`` only when every alternative's shortfall CI excludes zero; trials adaptively double
while it does not (see :func:`score_household`).

All figures are rounded deterministically (rates to 4 dp, dollars to 2 dp) so the scored records
— and therefore the rationale numbers copied from them and the serialized JSONL — are
byte-identical under the same seed. Trial counts are modest by design: they rank candidates (rank
stability), they are not tight confidence intervals, and the datasheet records the count so
precision claims stay honest.
"""

from typing import Literal

import numpy as np

from deepqlearning.envs.financial.environment import NAMED_ENV_BEQUEST_TAX_RATE, FinancialLifeEnv
from deepqlearning.evaluation.protocol import EpisodeOutcome, run_policy_episode

from .candidates import candidate_household, candidate_policy
from .schema import ScoredCandidate
from .strategies import DEFAULT_PLAN, DIMENSIONS, NO_LEVER, Plan

# Economy is stochastic during scoring so candidates are judged across good and bad years.
_DEFAULT_ECONOMY_MODE = "stochastic"

# Paired-bootstrap settings for the gap-to-best CIs (a fixed seed keeps scoring byte-reproducible).
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 0


def make_scoring_env(household: dict, reward_preset: str) -> FinancialLifeEnv:
    """Build a fixed-household env for scoring (the household is the env's point configuration)."""
    config = dict(household)
    config.setdefault("economy_mode", _DEFAULT_ECONOMY_MODE)
    config.setdefault("bequest_pretax_tax_rate", NAMED_ENV_BEQUEST_TAX_RATE)
    config["reward_preset"] = reward_preset
    return FinancialLifeEnv(config)


def _round_rate(x: float) -> float:
    return round(float(x), 4)


def _round_money(x: float) -> float:
    return round(float(x), 2)


class _Scorer:
    """Runs candidates on one household over a shared seed list, caching per-trial outcomes.

    Each candidate gets its own env (a plan's savings and claiming levers change the household the
    env builds); every env replays the same seeds, so outcomes stay paired across candidates.
    """

    def __init__(
        self,
        household: dict,
        seeds: list[int],
        reward_preset: str,
        outcomes: dict[str, list[EpisodeOutcome]] | None = None,
    ):
        self.household = household
        self.seeds = seeds
        self.reward_preset = reward_preset
        self.outcomes: dict[str, list[EpisodeOutcome]] = {k: list(v) for k, v in (outcomes or {}).items()}
        self._envs: dict[str, FinancialLifeEnv] = {}

    def __getstate__(self) -> dict:
        # Envs hold live models (not worth pickling across a process pool); they are rebuilt lazily.
        state = dict(self.__dict__)
        state["_envs"] = {}
        return state

    def ensure(self, names: list[str], n: int) -> None:
        """Make sure each of ``names`` has outcomes for the first ``n`` seeds."""
        for name in names:
            outs = self.outcomes.setdefault(name, [])
            if len(outs) >= n:
                continue
            if name not in self._envs:
                self._envs[name] = make_scoring_env(candidate_household(name, self.household), self.reward_preset)
            policy = candidate_policy(name)
            outs.extend(run_policy_episode(self._envs[name], policy, seed) for seed in self.seeds[len(outs) : n])

    def mean_return(self, name: str, n: int) -> float:
        return float(np.mean([o.total_reward for o in self.outcomes[name][:n]]))

    def summarize(self, names: list[str], n: int) -> list[ScoredCandidate]:
        return _summarize({name: self.outcomes[name][:n] for name in names})


def base_plans() -> list[str]:
    """The default plan and every one-dimension variant of it (what the search always scores)."""
    names = [DEFAULT_PLAN.name]
    for dim in DIMENSIONS:
        names.extend(DEFAULT_PLAN.with_value(dim.name, v).name for v in dim.values if v != dim.default)
    return names


def _variant_values(scored: list[ScoredCandidate], significant_only: bool) -> dict[str, str]:
    """Per dimension, the best one-lever variant's value (by mean return) — only among variants
    whose paired gain over the default has a CI above zero when ``significant_only`` — else the
    default value."""
    by_name = {c.decision: c for c in scored}
    values = {}
    for dim in DIMENSIONS:
        options = [
            by_name[name]
            for v in dim.values
            if v != dim.default and (name := DEFAULT_PLAN.with_value(dim.name, v).name) in by_name
        ]
        if significant_only:
            options = [c for c in options if c.gain_ci_low > 0.0]
        else:
            options = [c for c in options if c.mean_return > by_name[DEFAULT_PLAN.name].mean_return]
        best = max(options, key=lambda c: c.mean_return, default=None)
        values[dim.name] = getattr(Plan.parse(best.decision), dim.name) if best is not None else dim.default
    return values


def label_plan(scored: list[ScoredCandidate]) -> str | None:
    """The evidence-backed plan: each lever moves off its default only if that one-lever change
    beats the default plan on paired trials beyond Monte Carlo noise. ``None`` when the default
    plan is not among ``scored`` (e.g. reference policies only)."""
    if DEFAULT_PLAN.name not in {c.decision for c in scored}:
        return None
    return Plan(**_variant_values(scored, significant_only=True)).name


def _undecided(scored: list[ScoredCandidate]) -> bool:
    """Whether some lever looks better than the default but is not yet significant (more trials help)."""
    return any(c.gain_vs_default > 0.0 and c.gain_ci_low <= 0.0 for c in scored if c.decision in set(base_plans()))


def search_plans(scorer: "_Scorer", n: int) -> list[str]:
    """Coordinate search over the plan grid at ``n`` trials: the default plan, every one-dimension
    variant of it, the evidence-backed combination (:func:`label_plan`), and the combination of every
    dimension's best-on-average value (both only when not already scored).

    Scores at most ``1 + sum(len(values) - 1) + 2`` plans (10 for the current menu) instead of the
    full grid, and every dimension's effect is measured against the same default.
    """
    names = base_plans()
    scorer.ensure(names, n)
    scored = scorer.summarize(names, n)
    for combo in (label_plan(scored), Plan(**_variant_values(scored, significant_only=False)).name):
        if combo not in names:
            names.append(combo)
    scorer.ensure(names, n)
    return names


def paired_bootstrap_ci(diffs: np.ndarray, resamples: int = BOOTSTRAP_RESAMPLES, ci: float = 0.95) -> tuple:
    """Percentile-bootstrap CI for the mean of paired differences (deterministic: fixed RNG)."""
    diffs = np.asarray(diffs, dtype=float)
    if diffs.size < 2 or np.all(diffs == diffs[0]):
        m = float(diffs.mean()) if diffs.size else 0.0
        return m, m
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    means = diffs[rng.integers(0, diffs.size, size=(resamples, diffs.size))].mean(axis=1)
    return float(np.percentile(means, (1 - ci) / 2 * 100)), float(np.percentile(means, (1 + ci) / 2 * 100))


def _summarize(outcomes: dict[str, list[EpisodeOutcome]]) -> list[ScoredCandidate]:
    """Score every candidate from its per-trial outcomes, including the paired gap to the best."""
    returns = {name: np.array([o.total_reward for o in outs], dtype=float) for name, outs in outcomes.items()}
    base = {}
    for name, outs in outcomes.items():
        net_worths = np.array([o.real_terminal_net_worth for o in outs], dtype=float)
        base[name] = {
            "success_rate": _round_rate(np.mean([o.success for o in outs])),
            "mean_return": _round_money(returns[name].mean()),
            "net_worth_p10": _round_money(np.percentile(net_worths, 10)),
            "net_worth_p50": _round_money(np.percentile(net_worths, 50)),
            "net_worth_p90": _round_money(np.percentile(net_worths, 90)),
        }
    best = max(
        base,
        key=lambda n: (base[n]["mean_return"], base[n]["success_rate"], base[n]["net_worth_p50"], _neg_name(n)),
    )
    default = DEFAULT_PLAN.name
    scored = []
    for name, outs in outcomes.items():
        diffs = returns[best] - returns[name]
        low, high = paired_bootstrap_ci(diffs)
        gain = returns[name] - returns[default] if default in returns else np.zeros(len(outs))
        gain_low, gain_high = paired_bootstrap_ci(gain)
        scored.append(
            ScoredCandidate(
                decision=name,
                n_trials=len(outs),
                return_std=_round_rate(returns[name].std()),
                gap_to_best=_round_rate(diffs.mean()),
                gap_ci_low=_round_rate(low),
                gap_ci_high=_round_rate(high),
                in_top_set=bool(name == best or low <= 0.0),
                gain_vs_default=_round_rate(gain.mean()),
                gain_ci_low=_round_rate(gain_low),
                gain_ci_high=_round_rate(gain_high),
                **base[name],
            )
        )
    return scored


def score_candidate(household: dict, name: str, seeds: list[int], reward_preset: str) -> ScoredCandidate:
    """Score a single candidate on ``household`` over ``seeds`` (no paired comparison)."""
    scorer = _Scorer(household, seeds, reward_preset)
    scorer.ensure([name], len(seeds))
    return scorer.summarize([name], len(seeds))[0]


def score_household(
    household: dict,
    seeds: list[int],
    reward_preset: str,
    candidate_names: list[str] | None = None,
    *,
    min_trials: int | None = None,
    extra_candidates: list[str] | None = None,
) -> list[ScoredCandidate]:
    """Score candidates on one household over shared trial seeds.

    ``candidate_names`` (plans and/or reference policies) are scored as given; without it, the plan
    grid is explored by :func:`search_plans`, and any ``extra_candidates`` (e.g. a plan an adviser
    recommended) are scored alongside on the same seeds.

    With ``min_trials`` set, scoring is **adaptive**: it starts with the first ``min_trials`` seeds
    and doubles the trial count (up to ``len(seeds)``) while the decision is still open — for a plan
    search, while some lever beats the default on average without yet being significant; for an
    explicit list, while the top options are statistically equivalent. Without it every seed is used.

    Returns the scored candidates in a stable order (the search order, or ``candidate_names``).
    """
    scorer = _Scorer(household, seeds, reward_preset)
    n = len(seeds) if min_trials is None else max(1, min(min_trials, len(seeds)))
    extras = list(extra_candidates or [])
    if candidate_names is not None:
        names = list(candidate_names)
        while True:
            scorer.ensure(names, n)
            scored = scorer.summarize(names, n)
            if n >= len(seeds) or decision_basis(scored) != "equivalent":
                return scored
            n = min(2 * n, len(seeds))
    base = base_plans()
    while True:
        scorer.ensure(base, n)
        if n >= len(seeds) or not _undecided(scorer.summarize(base, n)):
            break
        n = min(2 * n, len(seeds))
    names = search_plans(scorer, n)
    names += [e for e in extras if e not in names]
    scorer.ensure(names, n)
    return scorer.summarize(names, n)


def argmax_candidate(scored: list[ScoredCandidate]) -> ScoredCandidate:
    """The winning candidate: highest mean return on the reward preset's objective (the paired
    trials make the comparison fair), breaking ties by success rate, median terminal wealth, then
    name (fully deterministic)."""
    return max(scored, key=lambda c: (c.mean_return, c.success_rate, c.net_worth_p50, _neg_name(c.decision)))


# Labeling thresholds. A household where even the best lever is solvent in at most this share of
# trials has no lever worth recommending (the shortfall is structural).
NO_VIABLE_MAX_SUCCESS = 0.10

DecisionBasis = Literal["clear", "equivalent", "no_viable"]


def decision_basis(scored: list[ScoredCandidate]) -> DecisionBasis:
    """How decisively the scores single out the label.

    ``no_viable``: no candidate keeps the household solvent in a meaningful share of trials.

    For a plan search (the default plan is scored): ``clear`` when the evidence-backed plan changes
    at least one lever off its default (each change beat the default beyond noise) and stays in the
    top set, or when the default beats every one-lever change beyond noise; ``equivalent`` when no
    change is proven but some is not ruled out either.

    For an explicit candidate list: ``clear`` when every other candidate's paired shortfall to the
    best has a CI above zero; ``equivalent`` otherwise.
    """
    if max(c.success_rate for c in scored) <= NO_VIABLE_MAX_SUCCESS:
        return "no_viable"
    by_name = {c.decision: c for c in scored}
    plan = label_plan(scored)
    if plan is not None:
        variants = [by_name[n] for n in base_plans()[1:] if n in by_name]
        if plan != DEFAULT_PLAN.name:
            return "clear" if plan in by_name and by_name[plan].in_top_set else "equivalent"
        return "clear" if variants and all(c.gain_ci_high < 0.0 for c in variants) else "equivalent"
    best = argmax_candidate(scored)
    if all(not c.in_top_set for c in scored if c.decision != best.decision):
        return "clear"
    return "equivalent"


def top_set(scored: list[ScoredCandidate]) -> list[str]:
    """Names of the candidates within Monte Carlo noise of the best (including the best)."""
    return [c.decision for c in scored if c.in_top_set]


def label_decision(scored: list[ScoredCandidate]) -> str:
    """The training label: ``NO_LEVER`` when nothing is viable; else the evidence-backed plan
    (:func:`label_plan`) when it was scored and is within noise of the best; else the argmax."""
    if decision_basis(scored) == "no_viable":
        return NO_LEVER
    plan = label_plan(scored)
    by_name = {c.decision: c for c in scored}
    if plan is not None and plan in by_name and by_name[plan].in_top_set:
        return plan
    return argmax_candidate(scored).decision


def _neg_name(name: str) -> tuple:
    """Sort key that makes an *earlier* name win ties (max picks the largest key)."""
    return tuple(-ord(ch) for ch in name)
