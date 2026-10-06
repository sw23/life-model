# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Reinforcement-learning stack for the life-model simulator.

The package is organized around three swappable pieces:

* :mod:`deepqlearning.envs` — a name -> factory registry of Gymnasium environments, one per
  financial household scenario.
* :mod:`deepqlearning.algos` — from-scratch PyTorch algorithms (DQN, REINFORCE, PPO) behind one
  :class:`~deepqlearning.algos.base.Algorithm` interface.
* :mod:`deepqlearning.training` — the collection loops (vectorized step-budget trainer, episodic
  trainer, single-episode rollout) that drive any algorithm against any environment.

:mod:`deepqlearning.evaluation` holds the financial-domain evaluation protocol, scripted planner
baselines, and policy-analysis artifacts; those reach into the financial environment's internals
and are financial-only by design.
"""
