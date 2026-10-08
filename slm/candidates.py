# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Executable policies for each strategy in the decision vocabulary.

This is the bridge from a strategy *name* (see :mod:`slm.strategies`) to the deterministic
baseline policy that realizes it in the RL environment. The candidate set is the planner-grade
heuristics plus two Roth/pre-tax split levers, matching the plan-level levers.

**Teacher gating:** no trained RL policy is in the candidate set. Per the committed protocol
reports (``deepqlearning/reports/retirement_security/protocol_report.json`` for DQN and
``retirement_security_ppo/protocol_report.json`` for PPO, both ``verdict_intelligent = false`` at
the committed seed 0), no learned policy achieved CI-separated superiority over the heuristics at
the seed fixed in advance, so distilling from one would silently cap the student. (PPO seed 1 does
clear the bar in ``reports/algorithm_sweep.txt``; promoting it would mean choosing a seed after
seeing results, which the seed convention exists to prevent.) Candidates are therefore heuristics +
the Roth/pre-tax levers only, and the label is the grid argmax.

Imports the RL package, so the repo root must be on ``sys.path`` (the SLM test conftest arranges
this, mirroring ``deepqlearning/tests/conftest.py``).
"""

from deepqlearning.envs.financial.actions import ActionType, encode_flat_action
from deepqlearning.envs.financial.environment import FinancialLifeEnv
from deepqlearning.evaluation.baselines import (
    _NO_ACTION,
    BaselinePolicy,
    _first_legal,
    age_glide_policy,
    always_max_401k_policy,
    contribution_waterfall_policy,
    emergency_fund_first_policy,
    four_percent_drawdown_policy,
)

_MAX_ROTH_401K = encode_flat_action(ActionType.TRANSFER_BANK_TO_401K_ROTH, 1.00)


def max_roth_401k_policy(env: FinancialLifeEnv) -> int:
    """Contribute as much as allowed to the Roth 401k every working year (the Roth split lever)."""
    if env.person.is_retired:
        return _NO_ACTION
    return _first_legal(env, [_MAX_ROTH_401K])


# Strategy name -> executable baseline policy. Order matches slm.strategies.STRATEGY_NAMES.
CANDIDATE_POLICIES: dict[str, BaselinePolicy] = {
    "contribution_waterfall": contribution_waterfall_policy,
    "age_glide": age_glide_policy,
    "emergency_fund_first": emergency_fund_first_policy,
    "four_percent_drawdown": four_percent_drawdown_policy,
    "max_pretax_401k": always_max_401k_policy,
    "max_roth_401k": max_roth_401k_policy,
}
