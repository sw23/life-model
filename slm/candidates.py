# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Executable policies for each strategy in the decision vocabulary (Plan 20 D2).

This is the bridge from a strategy *name* (see :mod:`slm.strategies`) to the deterministic
baseline policy that realizes it in the RL environment. The candidate set is the Plan 19 planner
heuristics plus two Roth/pre-tax split levers, matching the plan-level levers named in D2.

**Teacher gating (D2, Risks):** the trained DQN is *not* in the candidate set. Per Plan 19's
protocol report (``deepqlearning/reports/retirement_security/protocol_report.json``:
``verdict_intelligent = false``, ``ci_does_not_overlap_best = false``), the DQN did not achieve
CI-separated superiority over the heuristics, so distilling from it would silently cap the
student. Candidates are therefore heuristics + the Roth/pre-tax levers only, and the label is the
grid argmax.

Imports the RL modules with bare names, so ``deepqlearning/`` must be on ``sys.path`` (the SLM
test conftest arranges this, mirroring ``deepqlearning/tests/conftest.py``).
"""

from typing import Dict

from actions import ActionType, encode_flat_action
from baselines import (
    _NO_ACTION,
    BaselinePolicy,
    _first_legal,
    age_glide_policy,
    always_max_401k_policy,
    contribution_waterfall_policy,
    emergency_fund_first_policy,
    four_percent_drawdown_policy,
)
from environment import FinancialLifeEnv

_MAX_ROTH_401K = encode_flat_action(ActionType.TRANSFER_BANK_TO_401K_ROTH, 1.00)


def max_roth_401k_policy(env: FinancialLifeEnv) -> int:
    """Contribute as much as allowed to the Roth 401k every working year (the Roth split lever)."""
    if env.person.is_retired:
        return _NO_ACTION
    return _first_legal(env, [_MAX_ROTH_401K])


# Strategy name -> executable baseline policy. Order matches slm.strategies.STRATEGY_NAMES.
CANDIDATE_POLICIES: Dict[str, BaselinePolicy] = {
    "contribution_waterfall": contribution_waterfall_policy,
    "age_glide": age_glide_policy,
    "emergency_fund_first": emergency_fund_first_policy,
    "four_percent_drawdown": four_percent_drawdown_policy,
    "max_pretax_401k": always_max_401k_policy,
    "max_roth_401k": max_roth_401k_policy,
}
