# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""From-scratch PyTorch algorithms behind one :class:`~deepqlearning.algos.base.Algorithm` API."""

from typing import Dict, Type

from .base import ActResult, Algorithm, StepBatch
from .dqn import DQNAgent
from .ppo import PPOAgent
from .reinforce import ReinforceAgent

# Name -> class, keyed by the algorithm's ``name`` attribute (the same string written into its
# checkpoints and accepted by the training CLI's ``--algo``).
ALGORITHMS: Dict[str, Type[Algorithm]] = {
    DQNAgent.name: DQNAgent,
    ReinforceAgent.name: ReinforceAgent,
    PPOAgent.name: PPOAgent,
}

__all__ = ["ALGORITHMS", "ActResult", "Algorithm", "DQNAgent", "PPOAgent", "ReinforceAgent", "StepBatch"]
