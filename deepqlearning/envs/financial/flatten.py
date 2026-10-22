# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""``FlattenPolicies``: a ``Discrete`` view of a factored (``MultiDiscrete``) environment, for DQN.

A Q-network outputs one value per discrete action, so it cannot consume a ``MultiDiscrete`` space
directly. Two flattenings:

* **joint** — enumerate every combination of slot values as one discrete action. Exact, but the
  space is the product of the slot sizes: for the financial standing policies that is
  ``7*7*4*3*4*6*5*3*3*4 = 2,540,160`` actions (see ``policies.joint_action_count``), far too many for
  a Q-head, so ``mode="auto"`` only picks it when the product is at most ``max_joint``.
* **sequential** — one decision becomes a few *sub-steps*. Each sub-step either stages one change
  (a ``(slot, value)`` pair, ``NO_CHANGE`` excluded) or **commits**; the staged vector (``NO_CHANGE``
  in every unstaged slot) is sent to the wrapped env on commit, or automatically once
  ``max_changes`` slots are staged (the cap). The action space is ``Discrete(1 + sum(nvec - 1))``
  (37 for the financial slots). Staging sub-steps return reward 0 and are never terminal; the
  observation is the wrapped observation plus the staged values, a staged flag per slot, and the
  remaining change budget, so the Q-function sees what it has already chosen. Each staging sub-step
  is one more transition for the learner's ``gamma``, so a decision that changes ``c`` slots is
  discounted ``gamma ** (c + 1)``; ``max_changes`` bounds that (default 3).

Value 0 of every slot must be that slot's no-op (``NO_CHANGE`` in the financial env): the sequential
mode sends 0 for every slot it did not stage. Masks follow the wrapped env's ``info["legal_mask"]`` (the per-slot masks concatenated): a pair is
legal when its value is legal in its slot and the slot is not staged yet; commit is always legal.
:func:`compose_action` replays the same staging procedure against a raw (unwrapped) env, so a Q-agent
trained through the wrapper can be scored by the evaluation protocol next to the factored baselines.
"""

from collections.abc import Callable, Sequence

import gymnasium as gym
import numpy as np
from gymnasium import spaces

#: Flattening modes.
FLATTEN_MODES = ("auto", "joint", "sequential")
#: ``mode="auto"`` enumerates the joint space only up to this many actions.
DEFAULT_MAX_JOINT = 4096
#: Sequential mode: slots changed per decision before the decision is committed automatically.
DEFAULT_MAX_CHANGES = 3


def _slot_masks(flat_mask, nvec: Sequence[int]) -> list[np.ndarray]:
    flat = np.asarray(flat_mask, dtype=bool)
    offsets = np.cumsum((0, *nvec))
    return [flat[offsets[i] : offsets[i + 1]] for i in range(len(nvec))]


def sequential_pairs(nvec: Sequence[int]) -> list[tuple[int, int]]:
    """The ``(slot, value)`` pair of each staging action (action ``k >= 1`` is ``pairs[k - 1]``)."""
    return [(slot, value) for slot, n in enumerate(nvec) for value in range(1, int(n))]


def sequential_mask(slot_masks: Sequence[np.ndarray], staged: dict[int, int], nvec: Sequence[int]) -> np.ndarray:
    """Legal mask of the sequential space: commit, then every legal pair of an unstaged slot."""
    mask = [True]
    for slot, value in sequential_pairs(nvec):
        mask.append(slot not in staged and bool(slot_masks[slot][value]))
    return np.array(mask, dtype=bool)


def sequential_features(staged: dict[int, int], nvec: Sequence[int], max_changes: int) -> np.ndarray:
    """The staging features appended to the observation: staged value per slot (``value / (n - 1)``,
    0 when unstaged), a staged flag per slot, and the share of the change budget left."""
    values = np.zeros(len(nvec), dtype=np.float32)
    flags = np.zeros(len(nvec), dtype=np.float32)
    for slot, value in staged.items():
        values[slot] = value / max(1, int(nvec[slot]) - 1)
        flags[slot] = 1.0
    left = np.array([(max_changes - len(staged)) / max(1, max_changes)], dtype=np.float32)
    return np.concatenate([values, flags, left])


def compose_action(
    choose: Callable[[np.ndarray, list[int]], int],
    obs: np.ndarray,
    flat_mask,
    nvec: Sequence[int],
    max_changes: int = DEFAULT_MAX_CHANGES,
) -> np.ndarray:
    """Build one factored action by running the sequential staging procedure with ``choose``.

    ``choose(augmented_obs, legal_indices) -> index`` is a policy over the sequential space (a greedy
    Q-agent's ``select_action``). Returns the ``MultiDiscrete`` action the wrapper would commit.
    """
    slot_masks = _slot_masks(flat_mask, nvec)
    pairs = sequential_pairs(nvec)
    staged: dict[int, int] = {}
    while len(staged) < max_changes:
        aug = np.concatenate([np.asarray(obs, dtype=np.float32), sequential_features(staged, nvec, max_changes)])
        legal = np.nonzero(sequential_mask(slot_masks, staged, nvec))[0].tolist()
        index = int(choose(aug, legal))
        if index == 0:
            break
        slot, value = pairs[index - 1]
        staged[slot] = value
    vector = np.zeros(len(nvec), dtype=np.int64)
    for slot, value in staged.items():
        vector[slot] = value
    return vector


def resolve_mode(mode: str, nvec: Sequence[int], max_joint: int = DEFAULT_MAX_JOINT) -> str:
    """``"joint"`` or ``"sequential"`` for ``mode`` (``"auto"``: joint only when the product of the
    slot sizes is at most ``max_joint``)."""
    if mode not in FLATTEN_MODES:
        raise ValueError(f"Unknown flatten mode {mode!r}; expected one of {FLATTEN_MODES}")
    if mode != "auto":
        return mode
    joint = int(np.prod([int(n) for n in nvec], dtype=np.int64))
    return "joint" if joint <= max_joint else "sequential"


class FlattenPolicies(gym.Wrapper):
    """Expose a ``MultiDiscrete`` env as ``Discrete`` (joint enumeration or sequential sub-steps)."""

    def __init__(
        self,
        env: gym.Env,
        mode: str = "auto",
        *,
        max_joint: int = DEFAULT_MAX_JOINT,
        max_changes: int = DEFAULT_MAX_CHANGES,
    ):
        super().__init__(env)
        if not isinstance(env.action_space, spaces.MultiDiscrete):
            raise TypeError(f"FlattenPolicies wraps a MultiDiscrete env, got {env.action_space}")
        self.nvec = tuple(int(n) for n in env.action_space.nvec)
        self.mode = resolve_mode(mode, self.nvec, max_joint)
        if max_changes < 1:
            raise ValueError("max_changes must be at least 1")
        self.max_changes = int(min(max_changes, len(self.nvec)))
        if self.mode == "joint":
            self.action_space = spaces.Discrete(int(np.prod(self.nvec, dtype=np.int64)))
        else:
            self.pairs = sequential_pairs(self.nvec)
            self.action_space = spaces.Discrete(1 + len(self.pairs))
            base = env.observation_space
            extra = 2 * len(self.nvec) + 1
            self.observation_space = spaces.Box(
                low=np.concatenate([base.low, np.zeros(extra, dtype=np.float32)]).astype(np.float32),
                high=np.concatenate([base.high, np.ones(extra, dtype=np.float32)]).astype(np.float32),
                dtype=np.float32,
            )
        self._obs: np.ndarray | None = None
        self._info: dict = {}
        self._staged: dict[int, int] = {}

    # --- masks ---------------------------------------------------------------------------------

    def _wrapped_slot_masks(self) -> list[np.ndarray]:
        mask = self._info.get("legal_mask")
        if mask is None:
            return [np.ones(n, dtype=bool) for n in self.nvec]
        return _slot_masks(mask, self.nvec)

    def legal_action_mask(self) -> np.ndarray:
        """Boolean mask over the flattened ``Discrete`` space for the current (sub-)state."""
        slot_masks = self._wrapped_slot_masks()
        if self.mode == "joint":
            joint = slot_masks[0]
            for mask in slot_masks[1:]:
                joint = np.logical_and.outer(joint, mask)
            return joint.reshape(-1)
        return sequential_mask(slot_masks, self._staged, self.nvec)

    def get_legal_actions(self) -> list[int]:
        return np.nonzero(self.legal_action_mask())[0].tolist()

    # --- observations --------------------------------------------------------------------------

    def _observe(self) -> np.ndarray:
        if self.mode == "joint":
            return self._obs
        features = sequential_features(self._staged, self.nvec, self.max_changes)
        return np.concatenate([np.asarray(self._obs, dtype=np.float32), features])

    def _wrapped_info(self, *, substep: bool) -> dict:
        info = dict(self._info)
        info["legal_mask"] = self.legal_action_mask()
        info["decision_substep"] = substep
        return info

    # --- gym API -------------------------------------------------------------------------------

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        self._obs, self._info = self.env.reset(seed=seed, options=options)
        self._staged = {}
        return self._observe(), self._wrapped_info(substep=False)

    def decode(self, action: int) -> np.ndarray:
        """Joint mode: the ``MultiDiscrete`` vector of a flattened index."""
        return np.array(np.unravel_index(int(action), self.nvec), dtype=np.int64)

    def _commit(self, vector: np.ndarray):
        self._staged = {}
        self._obs, reward, terminated, truncated, self._info = self.env.step(vector)
        return self._observe(), reward, terminated, truncated, self._wrapped_info(substep=False)

    def step(self, action):
        action = int(np.asarray(action).item())
        if self.mode == "joint":
            return self._commit(self.decode(action))
        if action != 0:
            slot, value = self.pairs[action - 1]
            if slot not in self._staged:
                self._staged[slot] = value
            if len(self._staged) < self.max_changes:
                return self._observe(), 0.0, False, False, self._wrapped_info(substep=True)
        vector = np.zeros(len(self.nvec), dtype=np.int64)
        for slot, value in self._staged.items():
            vector[slot] = value
        return self._commit(vector)

    # --- evaluation ----------------------------------------------------------------------------

    def agent_policy(self, agent) -> Callable:
        """A ``raw env -> MultiDiscrete action`` policy from a Q-agent trained through this wrapper
        (greedy), for scoring next to the factored baselines on the unwrapped env."""
        return flattened_agent_policy(agent, self.mode, self.nvec, self.max_changes)


def flattened_agent_policy(agent, mode: str, nvec: Sequence[int], max_changes: int = DEFAULT_MAX_CHANGES):
    """``env -> MultiDiscrete action`` for an agent trained on a :class:`FlattenPolicies` view."""
    nvec = tuple(int(n) for n in nvec)

    def policy(env) -> np.ndarray:
        obs = env._get_observation()
        mask = env.legal_action_mask()
        if mode == "joint":
            slot_masks = _slot_masks(mask, nvec)
            joint = slot_masks[0]
            for m in slot_masks[1:]:
                joint = np.logical_and.outer(joint, m)
            legal = np.nonzero(joint.reshape(-1))[0].tolist()
            index = agent.select_action(obs, legal, training=False)
            return np.array(np.unravel_index(int(index), nvec), dtype=np.int64)

        def choose(aug, legal):
            return agent.select_action(aug, legal, training=False)

        return compose_action(choose, obs, mask, nvec, max_changes)

    return policy


def maybe_flatten(env: gym.Env, config: dict) -> gym.Env:
    """Wrap ``env`` in :class:`FlattenPolicies` when ``config["flatten_policies"]`` names a mode."""
    mode = config.get("flatten_policies")
    if not mode:
        return env
    return FlattenPolicies(
        env,
        mode,
        max_joint=int(config.get("flatten_max_joint", DEFAULT_MAX_JOINT)),
        max_changes=int(config.get("flatten_max_changes", DEFAULT_MAX_CHANGES)),
    )
