# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Compositional plans: the token grammar, the executable levers, and the coordinate search."""

import pytest

from deepqlearning.envs.financial.environment import FinancialLifeEnv
from slm.candidates import candidate_household, candidate_policy, claim_age_for
from slm.generate_data import _sample_households, _trial_seeds
from slm.prompts import parse_decision
from slm.scoring import _Scorer, search_plans
from slm.strategies import ALL_PLANS, DEFAULT_PLAN, DIMENSIONS, NO_LEVER_DEFAULT_PLAN, Plan, dimension_agreement


def test_every_plan_token_round_trips_and_parses():
    assert len(ALL_PLANS) == 54
    for plan in ALL_PLANS:
        assert Plan.parse(plan.name) == plan
        assert parse_decision(f"DECISION: {plan.name}\nRATIONALE: x") == plan.name
    assert NO_LEVER_DEFAULT_PLAN == "save0_pretax_claimret_conventional"


@pytest.mark.parametrize("token", ["save0_pretax", "save3_pretax_claimret_conventional", "max_roth_401k", ""])
def test_malformed_tokens_rejected(token):
    assert Plan.parse(token) is None
    assert parse_decision(f"DECISION: {token}") is None


def test_dimension_agreement():
    assert dimension_agreement("save5_roth_claim70_conventional", "save5_roth_claim70_conventional") == 1.0
    assert dimension_agreement("save5_roth_claim70_conventional", "save0_roth_claim70_bracketfill") == 0.5
    assert dimension_agreement("no_plan_lever", "save0_pretax_claimret_conventional") == 0.0


def test_claim_age_never_before_retirement_and_within_window():
    assert claim_age_for(Plan(claim="claimret"), 60) == 62
    assert claim_age_for(Plan(claim="claimret"), 65) == 65
    assert claim_age_for(Plan(claim="claimfra"), 62) == 67
    assert claim_age_for(Plan(claim="claimfra"), 68) == 68
    assert claim_age_for(Plan(claim="claim70"), 63) == 70
    assert claim_age_for(Plan(claim="claimret"), 72) == 70


def test_candidate_household_applies_plan_levers():
    household = {"person_retirement_age": 64, "initial_salary": 80000}
    plan = Plan(savings="save10", claim="claim70")
    h = candidate_household(plan.name, household)
    assert h["savings_boost_pct"] == 10 and h["ss_claim_age"] == 70
    assert candidate_household("age_glide", household) == household


def _env(**config):
    base = {
        "economy_mode": "fixed",
        "person_start_age": 40,
        "person_retirement_age": 65,
        "initial_salary": 150000,
        "initial_bank_balance": 60000,
        "initial_spending": 60000,
    }
    base.update(config)
    env = FinancialLifeEnv(base)
    env.reset(seed=0)
    return env


@pytest.mark.parametrize(
    ("routing", "pretax_positive", "roth_positive"),
    [("pretax", True, False), ("roth", False, True), ("split", True, True)],
)
def test_routing_lever(routing, pretax_positive, roth_positive):
    # $75k of pay puts ~$12k above the 12% bracket's top: split defers that pre-tax, the rest Roth.
    env = _env(initial_salary=75000)
    candidate_policy(Plan(routing=routing).name)(env)
    assert (env.job401k.pretax_balance > 0) == pretax_positive
    assert (env.job401k.roth_balance > 0) == roth_positive
    # Overflow beyond the 402(g) room goes to brokerage; a three-month reserve stays in cash.
    assert env.brokerage.balance > 0
    assert env.person.bank_account_balance == pytest.approx(60000 * 3 / 12)


def test_split_is_all_roth_below_the_bracket():
    env = _env(initial_salary=40000, initial_spending=20000)
    candidate_policy(Plan(routing="split").name)(env)
    assert env.job401k.pretax_balance == 0 and env.job401k.roth_balance > 0


def test_bracketfill_draws_pretax_in_retirement():
    plans = {name: Plan(drawdown=name).name for name in ("conventional", "bracketfill")}
    balances = {}
    for drawdown, name in plans.items():
        env = _env(person_start_age=66, person_retirement_age=65, initial_401k_pretax=500000)
        candidate_policy(name)(env)
        balances[drawdown] = env.job401k.pretax_balance
    assert balances["conventional"] == 500000
    assert balances["bracketfill"] < 500000


def test_search_scores_default_variants_and_a_combination():
    household = _sample_households(["mid_career"], 1, 3)[0][1]
    scorer = _Scorer(household, _trial_seeds(3, 0, 4), "retirement_security")
    names = search_plans(scorer, 4)
    variants = sum(len(d.values) - 1 for d in DIMENSIONS)
    assert names[0] == DEFAULT_PLAN.name
    assert len(names) in (1 + variants, 2 + variants)
    assert len(set(names)) == len(names)
    assert all(Plan.parse(n) is not None for n in names)
