# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Evaluation on the factored action space: the baselines as policy vectors, the protocol, and the
policy-vector-by-age analysis."""

import json
import os
import tempfile
import unittest
import warnings

import numpy as np

from deepqlearning.algos.ppo import PPOAgent
from deepqlearning.envs.financial.environment import FinancialLifeEnv, FinancialLifeEnvGenerator
from deepqlearning.envs.financial.policies import SLOT_NAMES, decode_policy_action, split_mask
from deepqlearning.evaluation.analyze_policy import analyze, policy_vector_schedule
from deepqlearning.evaluation.baselines import (
    BASELINES,
    FACTORED_BASELINES,
    PLANNER_BASELINES,
    affordable_401k_rate,
    baselines_for,
)
from deepqlearning.evaluation.protocol import EvalProtocol, format_comparison_table


class TestFactoredBaselines(unittest.TestCase):
    def test_same_names_as_the_flat_baselines(self):
        self.assertEqual(set(FACTORED_BASELINES), set(BASELINES))
        self.assertIs(baselines_for({"action_space": "factored"})["age_glide"], FACTORED_BASELINES["age_glide"])
        self.assertIs(baselines_for({})["age_glide"], BASELINES["age_glide"])
        env = FinancialLifeEnv({"action_space": "factored"})
        self.assertEqual(set(baselines_for(env)), set(FACTORED_BASELINES))

    def test_each_baseline_only_emits_legal_vectors(self):
        env = FinancialLifeEnvGenerator.create_scenario_env("mid_career", {"action_space": "factored"})
        for name in PLANNER_BASELINES:
            policy = FACTORED_BASELINES[name]
            for seed in range(8):
                env.reset(seed=seed, options={"randomize": True})
                done = False
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    while not done:
                        action = policy(env)
                        for value, mask in zip(action, split_mask(env.legal_action_mask())):
                            self.assertTrue(mask[value], f"{name} chose an illegal value at seed {seed}")
                        _, _, terminated, truncated, _ = env.step(action)
                        done = terminated or truncated

    def test_always_max_401k_defers_what_take_home_pay_carries(self):
        env = FinancialLifeEnvGenerator.create_scenario_env("high_earner", {"action_space": "factored"})
        env.reset(seed=0)
        # $120k of pay, $60k of spending: the take-home surplus covers the 402(g) limit.
        self.assertEqual(affordable_401k_rate(env), "max")
        changes = decode_policy_action(FACTORED_BASELINES["always_max_401k"](env))
        self.assertEqual(changes["pretax_401k_rate"], "max")
        low = FinancialLifeEnvGenerator.create_scenario_env("low_earner", {"action_space": "factored"})
        low.reset(seed=0)
        self.assertIn(affordable_401k_rate(low), ("0", "3"))


class TestFactoredProtocol(unittest.TestCase):
    def test_protocol_scores_factored_baselines_and_an_agent(self):
        config = {"action_space": "factored", "decision_interval": "quarter"}
        protocol = EvalProtocol(
            env_config=config, n_eval=2, master_seed=1, bootstrap_resamples=50, held_out_scenario=None
        )
        env = FinancialLifeEnv(config)
        agent = PPOAgent(env.observation_space, env.action_space, {"num_envs": 1, "verbose": False})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            report = protocol.run(agent=agent)
        self.assertEqual((report["action_space"], report["decision_interval"]), ("factored", "quarter"))
        self.assertEqual(set(report["conditions"]["train"]), {"agent", *FACTORED_BASELINES})
        self.assertIn("decision_interval=quarter", format_comparison_table(report))
        self.assertIn("verdict_intelligent", report["intelligent"])


class TestPolicyVectorAnalysis(unittest.TestCase):
    def test_schedule_takes_the_modal_value_per_age(self):
        base = dict.fromkeys(SLOT_NAMES, None)
        base.update(
            {
                "pretax_401k_rate": "6",
                "roth_401k_rate": "0",
                "ira_contribution": "none",
                "hsa_contribution": "none",
                "sweep_policy": "hold_cash",
                "spending_adjust": "hold",
                "withdrawal_order": "default",
                "retire": "no",
                "claim_social_security": "not_yet",
                "roth_conversion": "none",
            }
        )
        later = dict(base, pretax_401k_rate="max")
        trajectories = [
            [{"age": 30, "policy_vector": base}, {"age": 31, "policy_vector": later}],
            [{"age": 30, "policy_vector": base}, {"age": 31, "policy_vector": base}],
            [{"age": 30, "policy_vector": later}, {"age": 31, "policy_vector": later}],
        ]
        out = tempfile.mkdtemp()
        schedule = policy_vector_schedule(trajectories, os.path.join(out, "p.png"), os.path.join(out, "p.txt"))
        self.assertEqual(schedule["ages"], [30, 31])
        self.assertEqual(schedule["by_age"]["30"]["pretax_401k_rate"], {"value": "6", "share": 0.667})
        self.assertEqual(schedule["by_age"]["31"]["pretax_401k_rate"], {"value": "max", "share": 0.667})
        with open(os.path.join(out, "p.txt")) as f:
            table = f.read().splitlines()
        self.assertTrue(table[0].startswith("age"))
        self.assertIn("6 67%", table[1])
        self.assertTrue(os.path.exists(os.path.join(out, "p.png")))

    def test_analyze_writes_the_policy_vector_artifacts(self):
        config = {"action_space": "factored", "economy_mode": "fixed"}
        env = FinancialLifeEnv(config)
        agent = PPOAgent(env.observation_space, env.action_space, {"num_envs": 1, "verbose": False})
        out = tempfile.mkdtemp()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            manifest = analyze(agent, config, out, n_episodes=2)
        for name in (
            "policy_vector_by_age.png",
            "policy_vector_by_age.txt",
            "policy_vector_by_age.json",
            "lifetime_trace.json",
        ):
            self.assertTrue(os.path.exists(os.path.join(out, name)), name)
        self.assertNotIn("heatmap", manifest)
        with open(os.path.join(out, "lifetime_trace.json")) as f:
            rows = json.load(f)
        self.assertEqual(set(rows[0]["policy_vector"]), set(SLOT_NAMES))
        self.assertTrue(np.isfinite(rows[0]["reward"]))


if __name__ == "__main__":
    unittest.main()
