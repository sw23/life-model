# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Adviser households under the core invariant checker: every SLM scenario's sampled
households play each of a few plans to the end of the episode, and run 50 years as a spec, with
``checks="strict"``."""

import warnings

from life_model.spec import build_model
from slm.candidates import candidate_household, candidate_policy
from slm.households import SLM_SCENARIOS, sample_households
from slm.scoring import make_scoring_env
from slm.strategies import ALL_PLANS, DEFAULT_PLAN

PLANS = (DEFAULT_PLAN.name, ALL_PLANS[0].name, ALL_PLANS[-1].name)


def test_sampled_households_play_plans_strict():
    for scenario, household, index in sample_households(list(SLM_SCENARIOS), 1, generation_seed=11):
        for plan in PLANS:
            env = make_scoring_env({**candidate_household(plan, household), "checks": "strict"}, "retirement_security")
            env.reset(seed=index)
            policy = candidate_policy(plan)
            done = False
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                while not done:
                    _, _, terminated, truncated, _ = env.step(policy(env))
                    done = terminated or truncated
            assert env.model.invariant_violations == [], (scenario, plan)


def test_sampled_households_run_fifty_years_strict():
    for scenario, household, index in sample_households(list(SLM_SCENARIOS), 1, generation_seed=12):
        env = make_scoring_env(household, "retirement_security")
        env.reset(seed=index)
        spec = env.episode_spec
        meta = spec.meta.model_copy(update={"end_year": spec.meta.start_year + 49})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = build_model(spec.model_copy(update={"meta": meta}), seed=index, check=False)
            model.checks = "strict"
            model.run()
        assert len(model.simulated_years) == 50, scenario
        assert model.invariant_violations == [], scenario
