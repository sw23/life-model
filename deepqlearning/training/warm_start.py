# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Seed an off-policy agent's replay buffer with a scripted teacher's experience (Plan 19 D2).

Off by default: imitation can bias the learned policy toward the teacher. The CLI exposes it as
``--warm-start-teacher`` / ``--warm-start-seeds`` so a run can be compared with and without it.
"""

from deepqlearning.evaluation.baselines import BASELINES, collect_teacher_experiences

# Teacher seeds live far from the training (episode-index) and evaluation-protocol seed ranges so
# warm-start episodes never duplicate the episodes the agent is later trained or scored on.
WARM_START_SEED_BASE = 900_000


def warm_start_replay(agent, env, teacher: str, num_seeds: int, max_per_seed: int | None = None) -> int:
    """Roll ``teacher`` for ``num_seeds`` episodes and store every transition in ``agent``'s replay.

    Args:
        agent: An off-policy agent exposing ``store_experience`` (DQN).
        env: The financial environment to roll the teacher in.
        teacher: Name of a scripted policy in :data:`BASELINES`.
        num_seeds: Number of teacher episodes.
        max_per_seed: Optional cap on transitions kept per episode.

    Returns:
        The number of transitions stored.
    """
    if teacher not in BASELINES:
        raise ValueError(f"Unknown teacher {teacher!r}; expected one of {sorted(BASELINES)}")
    if not hasattr(agent, "store_experience"):
        raise TypeError(f"{type(agent).__name__} has no replay buffer to warm-start (use an off-policy algorithm)")
    seeds = list(range(WARM_START_SEED_BASE, WARM_START_SEED_BASE + num_seeds))
    transitions = collect_teacher_experiences(env, BASELINES[teacher], seeds, max_per_seed=max_per_seed)
    for transition in transitions:
        agent.store_experience(*transition)
    return len(transitions)
