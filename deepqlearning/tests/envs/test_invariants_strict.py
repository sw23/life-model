# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""RL episodes under the core invariant checker (Plan 29 D4).

Actions run between ``model.step()`` calls, so whatever money they move must be posted to the
ledger or the between-year ``continuity`` invariant fails. Every scenario household runs a full
episode of random legal actions under ``checks="strict"``, in the flat space and in the factored
standing-policy space (Plan 32 D8) at yearly and quarterly decisions (and one monthly run).
"""

import unittest
import warnings
from unittest import mock

import numpy as np

from deepqlearning.envs.financial.actions import ActionType, encode_flat_action
from deepqlearning.envs.financial.environment import FinancialLifeEnv, FinancialLifeEnvGenerator
from deepqlearning.envs.financial.policies import SLOT_NAMES, split_mask
from deepqlearning.envs.financial.scenarios import HOUSEHOLD_SCENARIOS
from life_model.invariants import InvariantError
from life_model.ledger import CashFlowLedger, FlowKind


def run_random_episode(env: FinancialLifeEnv, rng: np.random.Generator) -> int:
    """Play random legal actions to the end of the episode; returns the number of years stepped."""
    steps = 0
    done = False
    while not done:
        _, _, terminated, truncated, _ = env.step(int(rng.choice(env.get_legal_actions())))
        done = terminated or truncated
        steps += 1
    return steps


def run_random_factored_episode(
    env: FinancialLifeEnv, rng: np.random.Generator, change_prob: float = 0.3, keep: tuple[str, ...] = ()
) -> int:
    """Random legal standing-policy vectors to the end of the episode (each slot changes with
    ``change_prob``, else ``NO_CHANGE``; the ``keep`` slots never change); returns the number of
    decisions."""
    steps = 0
    done = False
    while not done:
        action = []
        for name, mask in zip(SLOT_NAMES, split_mask(env.legal_action_mask())):
            legal = np.nonzero(mask)[0]
            change = name not in keep and rng.random() < change_prob
            action.append(int(rng.choice(legal)) if change else 0)
        _, _, terminated, truncated, _ = env.step(np.array(action))
        done = terminated or truncated
        steps += 1
    return steps


class TestScenarioEpisodesStrict(unittest.TestCase):
    def test_every_scenario_random_actions_strict(self):
        rng = np.random.default_rng(0)
        for name in HOUSEHOLD_SCENARIOS:
            for seed, randomize in ((0, False), (1, True)):
                with self.subTest(scenario=name, seed=seed):
                    env = FinancialLifeEnvGenerator.create_scenario_env(
                        name, {"checks": "strict", "employer_match_rate": 0.5, "employer_match_cap": 0.06}
                    )
                    env.reset(seed=seed, options={"randomize": randomize})
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        steps = run_random_episode(env, rng)
                    self.assertGreaterEqual(steps, 1)
                    self.assertEqual(env.model.invariant_violations, [])

    def test_every_scenario_random_factored_actions_strict(self):
        """Random legal policy vectors: the engine carries every standing policy out and posts each
        dollar (contributions, match, sweeps, conversions, waterfall draws in any order)."""
        rng = np.random.default_rng(1)
        cases = [(name, interval) for name in HOUSEHOLD_SCENARIOS for interval in ("year", "quarter")]
        cases.append(("mid_career", "month"))
        for name, interval in cases:
            for seed, randomize in ((0, False), (1, True)):
                with self.subTest(scenario=name, interval=interval, seed=seed):
                    env = FinancialLifeEnvGenerator.create_scenario_env(
                        name,
                        {
                            "checks": "strict",
                            "action_space": "factored",
                            "decision_interval": interval,
                            "employer_match_rate": 0.5,
                            "employer_match_cap": 0.06,
                        },
                    )
                    env.reset(seed=seed, options={"randomize": randomize})
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        steps = run_random_factored_episode(env, rng)
                    self.assertGreaterEqual(steps, 1)
                    self.assertEqual(env.model.invariant_violations, [])

    def test_long_factored_episodes_strict(self):
        """Random policy vectors that never retire early or change spending, so episodes run decades
        (retirement drawdown, RMDs, claims, December Roth conversions, sweeps into bonds)."""
        rng = np.random.default_rng(2)
        for name in HOUSEHOLD_SCENARIOS:
            with self.subTest(scenario=name):
                env = FinancialLifeEnvGenerator.create_scenario_env(
                    name, {"checks": "strict", "action_space": "factored", "economy_mode": "stochastic"}
                )
                env.reset(seed=3)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    steps = run_random_factored_episode(env, rng, change_prob=0.15, keep=("retire", "spending_adjust"))
                self.assertGreater(steps, 30)
                self.assertEqual(env.model.invariant_violations, [])

    def test_scenario_households_run_fifty_years_strict(self):
        """Each scenario's household spec (the env's own construction) over 50 simulated years."""
        from life_model.spec import build_model

        for name in HOUSEHOLD_SCENARIOS:
            for seed in (0, 1):
                with self.subTest(scenario=name, seed=seed):
                    env = FinancialLifeEnvGenerator.create_scenario_env(name)
                    env.reset(seed=seed, options={"randomize": bool(seed)})
                    spec = env.episode_spec
                    meta = spec.meta.model_copy(update={"end_year": spec.meta.start_year + 49})
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        model = build_model(spec.model_copy(update={"meta": meta}), seed=seed, check=False)
                        model.checks = "strict"
                        model.run()
                    self.assertEqual(len(model.simulated_years), 50)
                    self.assertEqual(model.invariant_violations, [])


class TestActionsPostTheirMoney(unittest.TestCase):
    def _env(self) -> FinancialLifeEnv:
        env = FinancialLifeEnv(
            {"checks": "strict", "economy_mode": "fixed", "employer_match_rate": 1.0, "employer_match_cap": 0.06}
        )
        env.reset(seed=0)
        return env

    def test_match_and_transfers_are_posted(self):
        env = self._env()
        for action in (
            encode_flat_action(ActionType.TRANSFER_BANK_TO_401K_PRETAX, 0.5),
            encode_flat_action(ActionType.TRANSFER_BANK_TO_IRA_ROTH, 0.25),
            encode_flat_action(ActionType.TRANSFER_BANK_TO_BROKERAGE, 0.25),
            encode_flat_action(ActionType.WITHDRAW_401K_ROTH, 1.0),
        ):
            env.step(action)
        self.assertEqual(env.model.invariant_violations, [])
        kinds = {entry.kind for entry in env.model.ledger if entry.stage is None}
        self.assertIn(FlowKind.MATCH.value, kinds)

    def test_an_unposted_match_breaks_continuity(self):
        env = self._env()
        env.step(encode_flat_action(ActionType.NO_ACTION))  # continuity compares against a prior year
        original = CashFlowLedger.post

        def post(self, amount, kind, **kwargs):
            if kind == FlowKind.MATCH and kwargs.get("cause") == "employer match (RL deferral)":
                return None  # the pre-Plan-29 action layer: the match appeared from nowhere
            return original(self, amount, kind, **kwargs)

        with mock.patch.object(CashFlowLedger, "post", post), self.assertRaises(InvariantError) as raised:
            env.step(encode_flat_action(ActionType.TRANSFER_BANK_TO_401K_PRETAX, 0.5))
        self.assertEqual(raised.exception.violations[0].invariant, "continuity")


if __name__ == "__main__":
    unittest.main()
