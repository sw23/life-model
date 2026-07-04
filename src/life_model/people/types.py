# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from enum import Enum


class GenderAtBirth(Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class MortalityMode(Enum):
    """How a person's death is determined each simulated year.

    - ``IMMORTAL``: the person never dies (default; preserves deterministic back-compat behavior).
    - ``STOCHASTIC``: draw against the SSA mortality table each year using the model RNG (seeded,
      reproducible).
    - ``FIXED_AGE``: the person dies deterministically once they reach ``death_age``.
    """

    IMMORTAL = "immortal"
    STOCHASTIC = "stochastic"
    FIXED_AGE = "fixed_age"
