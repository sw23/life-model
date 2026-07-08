#!/usr/bin/env python3
# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Performance harness for the RL environment (Plan 18 D7).

Measures and prints:

* **model-only steps/sec** — a bare :class:`LifeModel` (with a representative household)
  stepped year by year, with ``collect_data`` True and False, isolating the DataCollector cost.
* **env steps/sec** — full :class:`FinancialLifeEnv` episodes driven by random legal actions,
  including reset, action execution, observation building, and reward computation.

Run from the repo root::

    .venv-work/bin/python deepqlearning/benchmark_env.py

Record the numbers in deepqlearning/README.md whenever they change materially so future
regressions are measurable.
"""

import argparse
import time

import numpy as np
from environment import FinancialLifeEnv

from life_model.account.bank import BankAccount
from life_model.account.job401k import Job401kAccount
from life_model.model import LifeModel
from life_model.people.family import Family
from life_model.people.person import Person, Spending
from life_model.work.job import Job, Salary


def _build_model(collect_data: bool, seed: int = 0) -> LifeModel:
    """A LifeModel with a household comparable to the env's default scenario."""
    model = LifeModel(start_year=2025, end_year=2025 + 94, seed=seed, collect_data=collect_data)
    family = Family(model)
    person = Person(
        family=family,
        name="Bench",
        age=25,
        retirement_age=65,
        spending=Spending(model=model, base=30000, yearly_increase=2),
    )
    BankAccount(owner=person, company="Bank", type="Checking", balance=10000, interest_rate=0.5)
    job = Job(
        owner=person,
        company="Company",
        role="Employee",
        salary=Salary(model=model, base=50000, yearly_increase=3, yearly_bonus=1),
    )
    Job401kAccount(job=job, average_growth=6.0)
    return model


def bench_model_only(collect_data: bool, num_models: int) -> float:
    """Model-only steps/sec: step fresh models through their whole year range."""
    steps = 0
    start = time.perf_counter()
    for i in range(num_models):
        model = _build_model(collect_data, seed=i)
        for _ in model.get_year_range():
            model.step()
            steps += 1
    elapsed = time.perf_counter() - start
    return steps / elapsed


def bench_env(num_episodes: int) -> float:
    """Env steps/sec: full episodes with random legal actions (includes reset overhead)."""
    env = FinancialLifeEnv()
    steps = 0
    start = time.perf_counter()
    for episode in range(num_episodes):
        env.reset(seed=episode)
        while True:
            legal = env.get_legal_actions()
            idx = int(env.np_random.choice(legal))
            action = {"action_type": idx, "amount_percentage": np.array([0.1], dtype=np.float32)}
            _, _, terminated, truncated, _ = env.step(action)
            steps += 1
            if terminated or truncated:
                break
    elapsed = time.perf_counter() - start
    return steps / elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the RL environment and LifeModel step rate")
    parser.add_argument("--models", type=int, default=20, help="Model-only benchmark: number of models")
    parser.add_argument("--episodes", type=int, default=20, help="Env benchmark: number of episodes")
    args = parser.parse_args()

    with_collector = bench_model_only(collect_data=True, num_models=args.models)
    without_collector = bench_model_only(collect_data=False, num_models=args.models)
    env_rate = bench_env(num_episodes=args.episodes)

    print(f"model-only steps/sec (collect_data=True):  {with_collector:10.1f}")
    print(f"model-only steps/sec (collect_data=False): {without_collector:10.1f}")
    print(f"  speedup from collect_data=False:         {without_collector / with_collector:10.2f}x")
    print(f"env steps/sec (random legal actions):      {env_rate:10.1f}")


if __name__ == "__main__":
    main()
