# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Optional legal-action masking protocol.

Environments may restrict which of their discrete actions are currently valid. The protocol is
opt-in and has three fallbacks, checked in order:

1. ``info["legal_mask"]`` — a boolean array of length ``action_space.n``. This is the only form
   that survives a vectorized (especially async) backend, since the collector never touches the
   sub-environments.
2. ``env.get_legal_actions()`` — a method returning the legal indices, for single-env loops.
3. Every action is legal — the case for standard environments, which declare nothing.

Algorithms treat "all actions legal" and "no mask" identically, so nothing needs to change to
train on an environment without masking.
"""

from typing import Dict, List, Optional

import numpy as np


def _action_count(env, n: Optional[int]) -> int:
    """Number of discrete actions, from the explicit ``n`` or the env's action space."""
    if n is not None:
        return int(n)
    space = getattr(env, "single_action_space", None) or getattr(env, "action_space", None)
    return int(space.n)


def legal_actions_of(env, info: Optional[Dict] = None, n: Optional[int] = None) -> List[int]:
    """Legal action indices for ``env``'s current state, using the fallback chain above."""
    if info is not None:
        mask = info.get("legal_mask")
        if mask is not None:
            return np.nonzero(np.asarray(mask))[0].tolist()
    getter = getattr(env, "get_legal_actions", None)
    if callable(getter):
        return list(getter())
    return list(range(_action_count(env, n)))


def masks_from_vector_info(info: Dict, num_envs: int, action_size: int) -> List[List[int]]:
    """Per-env legal-action lists from a vector env's batched ``info``.

    Vector environments stack each sub-env's ``info`` value into an array indexed by env. An
    environment that publishes no mask (or a per-env ``None`` entry) yields every action.
    """
    masks = info.get("legal_mask")
    result: List[List[int]] = []
    for i in range(num_envs):
        row = masks[i] if masks is not None and masks[i] is not None else None
        if row is None:
            result.append(list(range(action_size)))
        else:
            result.append(np.nonzero(row)[0].tolist())
    return result
