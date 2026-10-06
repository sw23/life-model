# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Collection loops that drive any algorithm against any registered environment."""

from .episode_trainer import EpisodeTrainer
from .rollout import RolloutResult, rollout
from .trainer import Trainer

__all__ = ["EpisodeTrainer", "RolloutResult", "Trainer", "rollout"]
