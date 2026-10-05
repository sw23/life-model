# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Off-policy experience storage: the transition record, replay buffers, and n-step accumulation."""

import random
from collections import deque, namedtuple

import numpy as np

# Experience tuple for the replay buffer. ``legal_actions`` is the legal action list for ``state``
# and ``next_legal_actions`` is the list for ``next_state`` (needed to mask bootstrapped targets).
# ``reward`` is the (possibly n-step) discounted reward and ``discount`` is the discount applied to
# the bootstrapped next-state value: ``gamma`` for a 1-step transition, ``gamma**n`` for an n-step
# one. ``discount`` defaults to ``None`` (interpreted as plain ``gamma``) so callers/tests that
# build 7-field experiences keep working.
Experience = namedtuple(
    "Experience",
    ["state", "action", "reward", "next_state", "done", "legal_actions", "next_legal_actions", "discount"],
)
Experience.__new__.__defaults__ = (None,)


class ReplayBuffer:
    """Uniform experience replay buffer for training stability."""

    def __init__(self, capacity: int):
        self.buffer = deque(maxlen=capacity)

    def push(self, *args):
        """Add experience to buffer"""
        self.buffer.append(Experience(*args))

    def sample(self, batch_size: int) -> list[Experience]:
        """Sample random batch from buffer"""
        return random.sample(self.buffer, batch_size)

    def __len__(self):
        return len(self.buffer)


class PrioritizedReplayBuffer:
    """Proportional prioritized experience replay (Schaul et al. 2016).

    Transitions are sampled with probability proportional to ``priority**alpha``
    (priority = last-seen TD error), and the resulting bias is corrected with importance-sampling
    weights ``(N * P(i))**(-beta)`` normalized by their max. New transitions enter at the current
    max priority so they are seen at least once; :meth:`update_priorities` refreshes priorities
    after each gradient step.
    """

    def __init__(self, capacity: int, alpha: float = 0.6, epsilon: float = 1e-6):
        self.capacity = capacity
        self.alpha = alpha
        self.epsilon = epsilon
        self.buffer: list[Experience] = []
        self.priorities = np.zeros(capacity, dtype=np.float64)
        self.pos = 0

    def push(self, *args):
        max_prio = self.priorities[: len(self.buffer)].max() if self.buffer else 1.0
        if len(self.buffer) < self.capacity:
            self.buffer.append(Experience(*args))
        else:
            self.buffer[self.pos] = Experience(*args)
        self.priorities[self.pos] = max_prio
        self.pos = (self.pos + 1) % self.capacity

    def sample(self, batch_size: int, beta: float = 0.4):
        """Return ``(experiences, indices, is_weights)``."""
        size = len(self.buffer)
        prios = self.priorities[:size] ** self.alpha
        probs = prios / prios.sum()
        indices = np.random.choice(size, batch_size, p=probs)
        experiences = [self.buffer[i] for i in indices]
        weights = (size * probs[indices]) ** (-beta)
        weights = weights / weights.max()
        return experiences, indices, weights.astype(np.float32)

    def update_priorities(self, indices: np.ndarray, td_errors: np.ndarray):
        for idx, err in zip(indices, td_errors):
            self.priorities[idx] = abs(float(err)) + self.epsilon

    def __len__(self):
        return len(self.buffer)


class NStepAccumulator:
    """Builds n-step transitions for a single episode stream.

    Push each ``(state, action, reward, legal_actions)`` as it happens; :meth:`push` emits the
    finalized n-step transitions that are ready (their ``next_state`` is now known). On episode end,
    :meth:`flush` emits the truncated-horizon transitions for the tail of the episode. Each emitted
    transition carries ``reward = sum_{k} gamma**k r_{t+k}`` and ``discount = gamma**steps`` so the
    learner bootstraps with the correct horizon.
    """

    def __init__(self, n_step: int, gamma: float):
        self.n_step = max(1, int(n_step))
        self.gamma = gamma
        self._items: deque = deque()

    def _make(self, upto: int, next_state, next_legal_actions, done) -> Experience:
        """Build the transition starting at the oldest item, spanning ``upto`` rewards."""
        state, action, _, legal = self._items[0]
        reward = 0.0
        for k in range(upto):
            reward += (self.gamma**k) * self._items[k][2]
        discount = self.gamma**upto
        return Experience(state, action, float(reward), next_state, done, legal, next_legal_actions, discount)

    def push(self, state, action, reward, legal_actions, next_state, next_legal_actions, done):
        """Record a step and return a list of finalized n-step transitions (possibly empty)."""
        self._items.append((state, action, float(reward), list(legal_actions)))
        emitted: list[Experience] = []
        if done:
            emitted.extend(self.flush(next_state, next_legal_actions))
        elif len(self._items) >= self.n_step:
            emitted.append(self._make(self.n_step, next_state, next_legal_actions, done=False))
            self._items.popleft()
        return emitted

    def flush(self, next_state, next_legal_actions) -> list[Experience]:
        """Emit truncated transitions for every remaining start index at episode end."""
        emitted: list[Experience] = []
        while self._items:
            emitted.append(self._make(len(self._items), next_state, next_legal_actions, done=True))
            self._items.popleft()
        return emitted
