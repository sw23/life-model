# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The factored standing-policy action space (Plan 32 D8): slots, masks, and the engine objects
each slot sets."""

import unittest
import warnings

import numpy as np
from gymnasium import spaces

from deepqlearning.envs.financial.environment import FinancialLifeEnv, FinancialLifeEnvGenerator
from deepqlearning.envs.financial.policies import (
    NO_CHANGE,
    NVEC,
    SLOT_BY_NAME,
    SLOT_NAMES,
    SLOTS,
    WITHDRAWAL_ORDERS,
    decode_policy_action,
    encode_policy_action,
    joint_action_count,
    no_change_vector,
    split_mask,
)
from life_model.account.fixed_income import FixedIncomeHolding
from life_model.ledger import FlowKind
from life_model.people.tax_unit import TaxUnit
from life_model.policies import MAX


def _env(**config) -> FinancialLifeEnv:
    base = {"action_space": "factored", "economy_mode": "fixed", "social_security": True}
    base.update(config)
    env = FinancialLifeEnv(base)
    env.reset(seed=0)
    return env


def _set(env, **changes) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return env.policies.apply(encode_policy_action(changes), interval_months=env.interval_months)


def _year(env, action=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return env.step(no_change_vector() if action is None else action)


class TestSlots(unittest.TestCase):
    def test_slot_layout_matches_the_plan(self):
        self.assertEqual(
            SLOT_NAMES,
            (
                "pretax_401k_rate",
                "roth_401k_rate",
                "ira_contribution",
                "hsa_contribution",
                "sweep_policy",
                "spending_adjust",
                "withdrawal_order",
                "retire",
                "claim_social_security",
                "roth_conversion",
            ),
        )
        self.assertEqual(SLOT_BY_NAME["pretax_401k_rate"].values, ("0", "3", "6", "10", "15", "max"))
        self.assertEqual(SLOT_BY_NAME["sweep_policy"].values, ("hold_cash", "sweep_to_brokerage", "sweep_to_bonds"))
        for slot in SLOTS:
            self.assertEqual(slot.choices[0], NO_CHANGE)
            self.assertIn(slot.default, slot.values)
        self.assertEqual(NVEC, (7, 7, 4, 3, 4, 6, 5, 3, 3, 4))
        # Joint enumeration is far too large for a Q-head: FlattenPolicies uses sequential sub-steps.
        self.assertEqual(joint_action_count(), 2_540_160)

    def test_encode_decode_round_trip(self):
        rng = np.random.default_rng(0)
        for _ in range(50):
            vector = np.array([rng.integers(0, n) for n in NVEC])
            np.testing.assert_array_equal(encode_policy_action(decode_policy_action(vector)), vector)
        self.assertEqual(set(decode_policy_action(no_change_vector()).values()), {NO_CHANGE})
        with self.assertRaises(ValueError):
            decode_policy_action(np.zeros(3))
        with self.assertRaises(ValueError):
            decode_policy_action(np.array([7, 0, 0, 0, 0, 0, 0, 0, 0, 0]))

    def test_every_withdrawal_order_lists_every_source(self):
        orders = set(WITHDRAWAL_ORDERS.values())
        self.assertEqual(len(orders), 4)
        for order in orders:
            self.assertEqual(order[0], "bank")
            self.assertEqual(order[-1], "reserve")


class TestEnvSpaces(unittest.TestCase):
    def test_factored_env_is_multidiscrete_with_policy_features(self):
        env = _env()
        self.assertIsInstance(env.action_space, spaces.MultiDiscrete)
        np.testing.assert_array_equal(env.action_space.nvec, NVEC)
        flat = FinancialLifeEnv({"economy_mode": "fixed"})
        self.assertIsInstance(flat.action_space, spaces.Discrete)
        self.assertEqual(env.observation_space.shape[0], flat.observation_space.shape[0] + len(SLOTS) + 1)
        obs, info = env.reset(seed=1)
        self.assertEqual(obs.shape, env.observation_space.shape)
        self.assertEqual(info["legal_mask"].shape, (sum(NVEC),))
        self.assertEqual(info["policy_vector"], {slot.name: slot.default for slot in SLOTS})

    def test_unknown_space_or_interval_is_rejected(self):
        with self.assertRaises(ValueError):
            FinancialLifeEnv({"action_space": "continuous"})
        with self.assertRaises(ValueError):
            FinancialLifeEnv({"decision_interval": "week"})


class TestMasks(unittest.TestCase):
    def test_no_change_always_legal_and_masks_split_per_slot(self):
        env = _env()
        masks = env.legal_slot_masks()
        self.assertEqual([len(m) for m in masks], list(NVEC))
        self.assertTrue(all(m[0] for m in masks))
        for a, b in zip(split_mask(env.legal_action_mask()), masks):
            np.testing.assert_array_equal(a, b)
        self.assertEqual(env.get_legal_actions(), np.nonzero(env.legal_action_mask())[0].tolist())

    def test_contributions_need_pay_and_claiming_needs_62(self):
        env = _env()
        masks = dict(zip(SLOT_NAMES, env.legal_slot_masks()))
        self.assertTrue(masks["pretax_401k_rate"].all())
        self.assertTrue(masks["hsa_contribution"].all())
        # 25 years old: may restate "not yet" but cannot claim.
        self.assertEqual(list(masks["claim_social_security"]), [True, True, False])
        _set(env, retire="yes")
        masks = dict(zip(SLOT_NAMES, env.legal_slot_masks()))
        for name in ("pretax_401k_rate", "roth_401k_rate", "ira_contribution", "hsa_contribution", "retire"):
            self.assertEqual(masks[name].tolist(), [True] + [False] * (len(masks[name]) - 1), name)
        self.assertTrue(masks["sweep_policy"].all())

    def test_illegal_values_are_ignored(self):
        env = _env()
        changed = _set(env, claim_social_security="now", pretax_401k_rate="10")
        self.assertEqual(changed, {"pretax_401k_rate": "10"})
        self.assertFalse(env.person.social_security.is_claiming)


class TestSlotsSetEngineObjects(unittest.TestCase):
    def test_401k_rates_are_payroll_contribution_plans(self):
        env = _env()
        _set(env, pretax_401k_rate="10", roth_401k_rate="max")
        plans = {plan.bucket: plan for plan in env.person.contribution_plans}
        self.assertEqual(plans["pretax"].pct_of_pay, 10.0)
        self.assertEqual(plans["pretax"].source, "payroll")
        self.assertEqual(plans["roth"].amount_annual, MAX)
        self.assertEqual(env.job401k.pretax_contrib_percent, 10.0)
        _set(env, pretax_401k_rate="0")
        self.assertEqual([p.bucket for p in env.person.contribution_plans], ["roth"])
        self.assertEqual(env.job401k.pretax_contrib_percent, 0.0)

    def test_ira_and_hsa_plans(self):
        env = _env()
        _set(env, ira_contribution="traditional_max", hsa_contribution="max")
        targets = {type(p.account).__name__: p for p in env.person.contribution_plans}
        self.assertEqual(targets["TraditionalIRA"].amount_annual, MAX)
        self.assertEqual(targets["TraditionalIRA"].source, "bank")
        self.assertEqual(targets["HealthSavingsAccount"].source, "payroll")
        _set(env, ira_contribution="roth_max")
        names = sorted(type(p.account).__name__ for p in env.person.contribution_plans)
        self.assertEqual(names, ["HealthSavingsAccount", "RothIRA"])

    def test_sweep_policies(self):
        env = _env()
        _set(env, sweep_policy="sweep_to_brokerage")
        policy = env.person.savings_policy
        self.assertIs(policy.sweep_to, env.brokerage)
        self.assertAlmostEqual(policy.cash_floor, env.person.spending.base / 2)
        _set(env, sweep_policy="sweep_to_bonds")
        bonds = env.person.savings_policy.sweep_to
        self.assertIsInstance(bonds, FixedIncomeHolding)
        self.assertEqual(bonds.kind, "bond_fund")
        self.assertFalse(bonds.reserve)
        _set(env, sweep_policy="hold_cash")
        self.assertIsNone(env.person.savings_policy)

    def test_spending_adjust_is_scaled_by_the_interval(self):
        env = _env()
        base = env.person.spending.base
        _set(env, spending_adjust="cut_10")
        self.assertAlmostEqual(env.person.spending.base, base * 0.9)
        # An impulse: the standing value reads "hold" again after the step.
        _year(env)
        self.assertEqual(env.policy_vector()["spending_adjust"], "hold")
        quarterly = _env(decision_interval="quarter")
        base = quarterly.person.spending.base
        _set(quarterly, spending_adjust="raise_10")
        self.assertAlmostEqual(quarterly.person.spending.base, base * 1.025)

    def test_spending_adjust_spares_essential_categories(self):
        from life_model.people.person import SpendingLine

        env = _env()
        spending = env.person.spending
        spending.add_line("rent", SpendingLine(12_000, essential=True))
        spending.add_line("travel", SpendingLine(4_000, essential=False))
        base = spending.base
        rate = env.spending_rate()
        self.assertAlmostEqual(rate, base + 16_000)
        _set(env, spending_adjust="cut_10")
        self.assertAlmostEqual(spending.base, base * 0.9)
        self.assertEqual(spending.categories["rent"].amount, 12_000)
        self.assertAlmostEqual(spending.categories["travel"].amount, 3_600)
        self.assertAlmostEqual(env.spending_rate(), base * 0.9 + 15_600)

    def test_withdrawal_order_reaches_the_tax_unit(self):
        env = _env()
        _set(env, withdrawal_order="roth_first")
        self.assertEqual(env.family.withdrawal_order, WITHDRAWAL_ORDERS["roth_first"])
        self.assertEqual(TaxUnit.for_member(env.person).withdrawal_order, WITHDRAWAL_ORDERS["roth_first"])

    def test_retire_ends_jobs_and_contributions(self):
        env = _env()
        _set(env, pretax_401k_rate="10", hsa_contribution="max")
        _set(env, retire="yes")
        self.assertTrue(env.person.is_retired)
        self.assertTrue(all(job.retired for job in env.person.jobs))
        vector = env.policy_vector()
        self.assertEqual(
            (vector["pretax_401k_rate"], vector["hsa_contribution"], vector["retire"]), ("0", "none", "yes")
        )
        self.assertEqual(env.person.contribution_plans, ())

    def test_claim_now_starts_benefits(self):
        env = FinancialLifeEnvGenerator.create_scenario_env(
            "mid_career",
            {"action_space": "factored", "economy_mode": "fixed", "person_start_age": 63, "person_retirement_age": 64},
        )
        env.reset(seed=0)
        ss = env.person.social_security
        # The agent owns the claim: the backstop is the delayed-credit maximum.
        self.assertEqual(ss.withdrawal_start_age, 70)
        self.assertFalse(ss.is_claiming)
        self.assertEqual(_set(env, claim_social_security="now"), {"claim_social_security": "now"})
        self.assertTrue(ss.is_claiming)
        _year(env)
        self.assertGreater(env.person.stat_ss_income, 0)
        self.assertEqual(env.policy_vector()["claim_social_security"], "now")
        masks = dict(zip(SLOT_NAMES, env.legal_slot_masks()))
        self.assertEqual(masks["claim_social_security"].tolist(), [True, False, False])

    def test_roth_conversion_fills_the_bracket_from_the_401k(self):
        env = FinancialLifeEnvGenerator.create_scenario_env(
            "mid_career", {"action_space": "factored", "economy_mode": "fixed", "social_security": False}
        )
        env.reset(seed=0)
        _set(env, retire="yes", roth_conversion="to_bracket_12")
        policy = env.person.roth_conversion_policy
        self.assertEqual(policy.fill_bracket_pct, 12)
        self.assertIs(policy.source, env.job401k)  # the traditional IRA is empty: in-plan conversion
        roth_before = env.job401k.roth_balance
        _year(env)
        self.assertGreater(env.job401k.roth_balance, roth_before + 1000)


class TestStandingPoliciesPersist(unittest.TestCase):
    def test_a_rate_set_once_keeps_deferring_with_the_match(self):
        env = _env(employer_match_rate=0.5, employer_match_cap=0.06)
        _year(env, encode_policy_action({"pretax_401k_rate": "6"}))
        _year(env)  # NO_CHANGE: the 6% plan stays in force
        year = env.model.year - 1
        entries = [e for e in env.model.ledger if e.year == year and e.to_account is not None]
        deferrals = sum(e.amount for e in entries if e.kind == FlowKind.CONTRIBUTION.value and "401" in e.to_account)
        match = sum(e.amount for e in entries if e.kind == FlowKind.MATCH.value)
        pay = env.job.salary.base
        self.assertGreater(deferrals, 0.05 * pay * 0.95)
        self.assertLess(deferrals, 0.06 * pay * 1.1)
        self.assertAlmostEqual(match, 0.5 * deferrals, delta=0.02 * deferrals)


if __name__ == "__main__":
    unittest.main()
