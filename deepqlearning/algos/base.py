# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The interface every algorithm implements, and the pieces they share.

The interface is **batched**: a training loop hands the algorithm ``N >= 1`` parallel environment
streams and the algorithm decides what to do with them. A single environment is simply ``N = 1``,
so the episodic trainer and the vectorized trainer speak the same protocol.

One collection step is::

    result = algo.act(obs, legal, training=True)      # choose actions for all N streams
    ...                                                # step the environments
    algo.observe(StepBatch(...))                       # hand back what happened
    metrics = algo.update()                            # gradient step(s) if the algorithm is ready

``observe`` and ``update`` are separate because algorithms disagree about *when* learning happens:
DQN can take a gradient step on every collected step, while REINFORCE and PPO buffer until a whole
batch of episodes / a fixed rollout is available and return ``None`` from ``update`` until then.
The loop does not need to know which; it calls ``update`` every step either way.

``StepBatch.env_ids`` names which environment stream each row came from. It matters because
autoreset steps are dropped from the batch, so rows are not always a contiguous ``0..N-1`` — an
algorithm that keeps per-stream state (n-step accumulation, rollout segments) keys it by env id.
"""

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Dict, List, Optional, Sequence

import numpy as np
import torch
from gymnasium import spaces
from torch.distributions import Categorical

# Checkpoint format for the algorithms that do not pin their own version. Bumped when the
# checkpoint key schema changes in a way that makes older files unreadable.
ALGO_CHECKPOINT_VERSION = 1

# Logit assigned to an illegal action by a stochastic policy. Large enough that the action's
# post-softmax probability underflows to zero in float32, but finite so entropy stays defined.
POLICY_MASK_LOGIT = -1e8


@dataclass
class ActResult:
    """Actions chosen for a batch of observations, plus whatever the algorithm needs to keep.

    ``extras`` carries per-row quantities the algorithm computed while acting and will want back
    at ``observe`` time — the policy log-probability and state value for the on-policy algorithms.
    They must be handed back unchanged by the training loop, because recomputing them later would
    not give the same values the action was actually sampled under.
    """

    actions: np.ndarray
    extras: Dict[str, np.ndarray] = field(default_factory=dict)


@dataclass
class StepBatch:
    """One collection step's worth of transitions, for the environment streams that were active.

    ``terminated`` and ``truncated`` are kept apart rather than collapsed into a single "done":
    bootstrapping must continue through a time-limit truncation and must stop at a real terminal
    state, and only these two flags distinguish the cases.
    """

    obs: np.ndarray
    actions: np.ndarray
    rewards: np.ndarray
    next_obs: np.ndarray
    terminated: np.ndarray
    truncated: np.ndarray
    legal: List[List[int]]
    next_legal: List[List[int]]
    env_ids: np.ndarray
    extras: Dict[str, np.ndarray] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.actions)


def select_device(preference: Optional[str] = None) -> torch.device:
    """Pick a compute device: CUDA when available, otherwise CPU. Apple MPS (Metal) is used
    only when explicitly requested (``preference="mps"``).

    ``preference`` may force a specific backend (``"cuda"``, ``"mps"``, ``"cpu"``); an
    unavailable choice falls back to CPU. MPS is opt-in (never auto-selected) because for this
    workload the per-step cost is dominated by the CPU-bound ``life_model`` simulation and the
    network is small, so MPS typically performs worse than CPU for single-env training — the
    vectorized trainer's environment parallelism is the larger lever.
    """
    if preference:
        pref = preference.lower()
        if pref == "cuda" and torch.cuda.is_available():
            return torch.device("cuda")
        if pref == "mps" and torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def legal_mask_tensor(
    legal_actions_batch: Sequence[Sequence[int]], action_size: int, device: torch.device
) -> torch.Tensor:
    """Additive logit mask: 0 for legal actions, ``-inf`` for illegal ones.

    A row with no legal actions recorded is left unmasked rather than becoming all ``-inf``, which
    would make the row's softmax/argmax undefined.
    """
    mask = torch.full((len(legal_actions_batch), action_size), float("-inf"), device=device)
    for i, legal in enumerate(legal_actions_batch):
        if len(legal):
            mask[i, list(legal)] = 0.0
        else:
            mask[i, :] = 0.0
    return mask


def masked_categorical(logits: torch.Tensor, legal_actions_batch: Sequence[Sequence[int]]) -> Categorical:
    """Categorical policy over the legal actions of each row.

    Illegal actions are pushed to a large *finite* negative logit rather than ``-inf``: after the
    softmax their probability underflows to exactly zero either way, but ``-inf`` would make the
    distribution's entropy ``nan`` (``0 * -inf``), and the entropy bonus is part of the loss.
    """
    mask = torch.zeros_like(logits, dtype=torch.bool)
    for i, legal in enumerate(legal_actions_batch):
        if len(legal):
            mask[i, list(legal)] = True
        else:
            # No mask recorded for this row: every action stays available.
            mask[i, :] = True
    return Categorical(logits=logits.masked_fill(~mask, POLICY_MASK_LOGIT))


def as_box_space(obs_space) -> spaces.Space:
    """Accept either a Gymnasium space or a plain flat size, and return a space."""
    if isinstance(obs_space, spaces.Space):
        return obs_space
    size = int(obs_space)
    return spaces.Box(low=-np.inf, high=np.inf, shape=(size,), dtype=np.float32)


def as_discrete_space(action_space) -> spaces.Discrete:
    """Accept either a ``Discrete`` space or a plain action count, and return a ``Discrete``."""
    if isinstance(action_space, spaces.Discrete):
        return action_space
    if isinstance(action_space, spaces.Space):
        raise TypeError(f"Only Discrete action spaces are supported, got {action_space}")
    return spaces.Discrete(int(action_space))


class Algorithm(ABC):
    """Base class for the learning algorithms.

    Subclasses declare :attr:`name` (written into checkpoints and accepted by the training CLI)
    and :attr:`on_policy` (whether stored data is invalidated by a policy update — which is what
    decides whether a trainer may replay old transitions).

    ``obs_space``/``action_space`` accept either the environment's Gymnasium spaces or plain
    integer sizes, so a caller that only knows "34 features, 52 actions" does not have to
    construct spaces.
    """

    on_policy: ClassVar[bool] = False
    name: ClassVar[str] = "algorithm"

    def __init__(self, obs_space, action_space, config: Optional[Dict] = None):
        self.obs_space = as_box_space(obs_space)
        self.action_space = as_discrete_space(action_space)
        self.obs_shape = tuple(self.obs_space.shape)
        self.state_size = int(np.prod(self.obs_shape))
        self.action_size = int(self.action_space.n)

        self.config = dict(self.default_config())
        if config:
            self.config.update(config)

        self.device = select_device(self.config.get("device"))
        # Training history, kept on the algorithm so it survives a save/load round trip and is
        # available to the plotting helpers.
        self.training_losses: List[float] = []
        self.episode_rewards: List[float] = []
        self.steps_done = 0

    @staticmethod
    def default_config() -> Dict:
        """Hyperparameters this algorithm accepts, with their defaults."""
        return {}

    # --- acting and learning ---------------------------------------------------------------

    @abstractmethod
    def act(self, obs: np.ndarray, legal: Sequence[Sequence[int]], training: bool = True) -> ActResult:
        """Choose an action for each row of ``obs``, given each row's legal actions."""

    @abstractmethod
    def observe(self, batch: StepBatch) -> None:
        """Record a batch of transitions (into a replay buffer or a rollout segment)."""

    @abstractmethod
    def update(self) -> Optional[Dict[str, float]]:
        """Take a gradient step if enough data is buffered; return metrics, or ``None`` if not."""

    def anneal(self, progress: float) -> None:
        """Advance any schedules (exploration, entropy) to ``progress`` in ``[0, 1]`` of training."""

    def on_env_count(self, num_envs: int) -> None:
        """Tell the algorithm how many environment streams will feed it.

        Algorithms that size a fixed rollout buffer need this before the first ``observe``; the
        rest ignore it.
        """

    def select_action(self, ob: np.ndarray, legal_actions: Sequence[int], training: bool = False) -> int:
        """Single-observation convenience wrapper over :meth:`act`."""
        result = self.act(np.expand_dims(np.asarray(ob), 0), [list(legal_actions)], training=training)
        return int(result.actions[0])

    # --- checkpointing ---------------------------------------------------------------------

    @staticmethod
    def history_path(filepath: str) -> str:
        """Path of the JSON sidecar holding non-tensor training history for ``filepath``."""
        return os.path.splitext(str(filepath))[0] + ".history.json"

    def checkpoint_state(self) -> Dict:
        """Tensors and scalars to persist. Must stay ``torch.load(weights_only=True)``-safe."""
        raise NotImplementedError

    def restore_checkpoint(self, checkpoint: Dict) -> None:
        """Restore the state produced by :meth:`checkpoint_state`."""
        raise NotImplementedError

    def save(self, filepath) -> None:
        """Write a tensor-only ``.pt`` checkpoint plus a JSON history sidecar next to it.

        Splitting the history out is what keeps the ``.pt`` loadable under modern PyTorch's
        ``weights_only=True`` default, which refuses to unpickle arbitrary Python objects.
        """
        filepath = str(filepath)
        checkpoint = {"algo": self.name, "algo_version": ALGO_CHECKPOINT_VERSION}
        checkpoint.update(self.checkpoint_state())
        torch.save(checkpoint, filepath)

        history = {
            "algo": self.name,
            "algo_version": ALGO_CHECKPOINT_VERSION,
            "config": self.config,
            "training_losses": [float(x) for x in self.training_losses],
            "episode_rewards": [float(x) for x in self.episode_rewards],
        }
        with open(self.history_path(filepath), "w") as f:
            json.dump(history, f, default=str)

        print(f"Model saved to {filepath}")

    def load(self, filepath) -> None:
        """Load a checkpoint written by :meth:`save`.

        Raises:
            ValueError: If the checkpoint was produced by a different algorithm. The weights of a
                policy network and a Q-network have no meaning in common, so loading across
                algorithms is refused rather than silently reinterpreted.
        """
        filepath = str(filepath)
        if not os.path.exists(filepath):
            print(f"Model file {filepath} not found")
            return

        checkpoint = torch.load(filepath, map_location=self.device, weights_only=True)
        algo = checkpoint.get("algo")
        if algo != self.name:
            raise ValueError(
                f"Checkpoint {filepath!r} was written by algorithm {algo!r}, but this is {self.name!r}. "
                "Checkpoints are not portable across algorithms."
            )
        self.restore_checkpoint(checkpoint)

        history_path = self.history_path(filepath)
        if os.path.exists(history_path):
            with open(history_path) as f:
                history = json.load(f)
            self.training_losses = history.get("training_losses", [])
            self.episode_rewards = history.get("episode_rewards", [])

        print(f"Model loaded from {filepath}")
