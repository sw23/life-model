# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Unit tests for the RL action space and the can_execute => execute-succeeds invariant."""

import unittest

import numpy as np

from deepqlearning.envs.financial.actions import (
    AMOUNT_BEARING_ACTIONS,
    AMOUNT_BUCKETS,
    SINGLETON_ACTIONS,
    ActionType,
    build_action,
    decode_flat_action,
    encode_flat_action,
    flat_action_count,
)
from deepqlearning.envs.financial.environment import FinancialLifeEnv


class TestActionSpaceHonesty(unittest.TestCase):
    """Every declared action is implemented and reachable (no 'not implemented' fall-throughs)."""

    def test_no_action_type_is_unimplemented(self):
        env = FinancialLifeEnv()
        env.reset(seed=0)
        for action_type in ActionType:
            result = env.action_executor.execute_action(env.person, action_type, amount=1000.0)
            self.assertNotIn("not implemented", result.message.lower(), f"{action_type} is not implemented")

    def test_build_action_covers_every_non_noop_type(self):
        env = FinancialLifeEnv()
        env.reset(seed=0)
        for action_type in ActionType:
            action = build_action(action_type, env.person, amount=1000.0)
            if action_type == ActionType.NO_ACTION:
                self.assertIsNone(action)
            else:
                self.assertIsNotNone(action, f"{action_type} has no action builder")


class TestFlatActionIndexer(unittest.TestCase):
    """The flat index space is exactly (amount actions x buckets) + singletons and
    the encoder/decoder are exact inverses."""

    def test_flat_action_count(self):
        self.assertEqual(flat_action_count(), len(AMOUNT_BEARING_ACTIONS) * len(AMOUNT_BUCKETS) + 4)
        self.assertEqual(flat_action_count(), 52)

    def test_round_trip_index_to_action_to_index(self):
        # Exhaustive: every index decodes to an action that encodes back to the same index.
        for index in range(flat_action_count()):
            flat = decode_flat_action(index)
            self.assertEqual(encode_flat_action(flat.action_type, flat.amount_fraction), index)

    def test_round_trip_action_to_index_to_action(self):
        for action_type in AMOUNT_BEARING_ACTIONS:
            for bucket in AMOUNT_BUCKETS:
                flat = decode_flat_action(encode_flat_action(action_type, bucket))
                self.assertEqual(flat.action_type, action_type)
                self.assertEqual(flat.amount_fraction, bucket)
        for action_type in SINGLETON_ACTIONS:
            flat = decode_flat_action(encode_flat_action(action_type))
            self.assertEqual(flat.action_type, action_type)
            self.assertIsNone(flat.amount_fraction)

    def test_every_action_type_is_reachable(self):
        reachable = {decode_flat_action(i).action_type for i in range(flat_action_count())}
        self.assertEqual(reachable, set(ActionType))

    def test_out_of_range_index_rejected(self):
        with self.assertRaises(ValueError):
            decode_flat_action(flat_action_count())
        with self.assertRaises(ValueError):
            decode_flat_action(-1)

    def test_bad_bucket_rejected(self):
        with self.assertRaises(ValueError):
            encode_flat_action(ActionType.WITHDRAW_401K_PRETAX, 0.33)
        with self.assertRaises(ValueError):
            encode_flat_action(ActionType.NO_ACTION, 0.10)


class TestBucketMasking(unittest.TestCase):
    """The legality mask extends per composite (action, bucket): a bucket is illegal if it maps
    to $0."""

    def test_empty_account_masks_all_its_buckets(self):
        env = FinancialLifeEnv()
        env.reset(seed=0)
        # The fresh 401k has no Roth balance: every Roth-withdrawal bucket must be illegal.
        legal = set(env.get_legal_actions())
        for bucket in AMOUNT_BUCKETS:
            self.assertNotIn(encode_flat_action(ActionType.WITHDRAW_401K_ROTH, bucket), legal)

    def test_funded_account_unmasks_buckets(self):
        env = FinancialLifeEnv()
        env.reset(seed=0)
        env.job401k.roth_balance = 10000.0
        legal = set(env.get_legal_actions())
        for bucket in AMOUNT_BUCKETS:
            self.assertIn(encode_flat_action(ActionType.WITHDRAW_401K_ROTH, bucket), legal)

    def test_no_action_always_legal(self):
        env = FinancialLifeEnv()
        env.reset(seed=0)
        self.assertIn(encode_flat_action(ActionType.NO_ACTION), env.get_legal_actions())


class TestCanExecuteImpliesSuccess(unittest.TestCase):
    """The mask (can_execute) must never disagree with the executor (execute)."""

    def test_every_legal_action_succeeds_at_reset(self):
        # Rebuild the environment to the same fresh state for each legal action so executing one
        # action does not perturb the check of the next.
        base = FinancialLifeEnv()
        base.reset(seed=0)
        legal = base.get_legal_actions()
        self.assertTrue(legal)

        for index in legal:
            flat = decode_flat_action(index)
            env = FinancialLifeEnv()
            env.reset(seed=0)
            amount = env._calculate_action_amount(flat.action_type, flat.amount_fraction or 0.0)
            result = env.action_executor.execute_action(
                env.person, flat.action_type, amount=amount, percentage_change=env.SPENDING_STEP
            )
            self.assertTrue(result.success, f"legal action {flat} failed to execute")

    def test_property_legal_actions_execute_over_random_states(self):
        # Over many random states, every flat action the mask reports as legal must execute
        # successfully. Covers >= 500 (state, action) samples across diverse states.
        samples = 0
        for seed in range(60):
            env = FinancialLifeEnv()
            _state, _ = env.reset(seed=seed)
            rng = np.random.RandomState(seed)
            for _ in range(40):
                legal = env.get_legal_actions()
                index = int(rng.choice(legal))
                _, _, terminated, truncated, info = env.step(index)
                result = info["action_result"]
                self.assertTrue(
                    result.success, f"legal action {decode_flat_action(index)} reported failure at seed {seed}"
                )
                samples += 1
                if terminated or truncated:
                    break
        self.assertGreaterEqual(samples, 500)


class TestActionEffects(unittest.TestCase):
    """Spot-check that actions move money the way they claim to."""

    def _fresh_env(self):
        env = FinancialLifeEnv()
        env.reset(seed=0)
        return env

    def test_transfer_bank_to_brokerage_moves_money(self):
        env = self._fresh_env()
        bank_before = env.person.bank_account_balance
        brokerage_before = env.brokerage.balance
        result = env.action_executor.execute_action(env.person, ActionType.TRANSFER_BANK_TO_BROKERAGE, amount=1000.0)
        self.assertTrue(result.success)
        self.assertAlmostEqual(env.person.bank_account_balance, bank_before - 1000.0)
        self.assertAlmostEqual(env.brokerage.balance, brokerage_before + 1000.0)

    def test_transfer_to_capped_account_is_limited_to_room(self):
        env = self._fresh_env()
        room = env.traditional_ira.remaining_contribution_room()
        result = env.action_executor.execute_action(
            env.person, ActionType.TRANSFER_BANK_TO_IRA_TRADITIONAL, amount=room + 100000.0
        )
        self.assertTrue(result.success)
        # Only up to the contribution room (and bank balance) can move.
        self.assertLessEqual(env.traditional_ira.balance, room + 1e-6)

    def test_withdraw_401k_pretax_records_early_penalty_for_settlement(self):
        env = self._fresh_env()
        env.job401k.pretax_balance = 10000.0
        bank_before = env.person.bank_account_balance
        result = env.action_executor.execute_action(env.person, ActionType.WITHDRAW_401K_PRETAX, amount=1000.0)
        self.assertTrue(result.success)
        # The gross reaches the bank; the person is 25 (< 59.5), so the core model records a 10%
        # penalty that is paid as federal tax when the year settles.
        self.assertAlmostEqual(result.fees_paid, 0.0)
        self.assertAlmostEqual(env.person.bank_account_balance, bank_before + 1000.0)
        self.assertAlmostEqual(env.person.income.penalties, 100.0)

    def test_withdraw_401k_roth_penalty_stays_at_action_level(self):
        env = self._fresh_env()
        env.job401k.roth_balance = 10000.0
        bank_before = env.person.bank_account_balance
        result = env.action_executor.execute_action(env.person, ActionType.WITHDRAW_401K_ROTH, amount=1000.0)
        self.assertTrue(result.success)
        self.assertAlmostEqual(result.fees_paid, 100.0)
        self.assertAlmostEqual(env.person.bank_account_balance, bank_before + 900.0)
        self.assertAlmostEqual(env.person.income.penalties, 0.0)

    def test_retire_early_brings_retirement_age_forward(self):
        env = self._fresh_env()
        self.assertFalse(env.person.is_retired)
        result = env.action_executor.execute_action(env.person, ActionType.RETIRE_EARLY)
        self.assertTrue(result.success)
        self.assertTrue(env.person.is_retired)
        # Retiring again is illegal (already retired).
        self.assertFalse(env.action_executor.can_execute_action(env.person, ActionType.RETIRE_EARLY))


class TestWithdrawalTaxDifferential(unittest.TestCase):
    """Headline criterion: pre-tax vs Roth withdrawals of the same gross amount must
    produce measurably different multi-year net worth, because pre-tax withdrawals are taxed at
    year-end settlement while Roth withdrawals are not."""

    def _run_episode(self, action_type, seed=0, years=5):
        env = FinancialLifeEnv()
        env.reset(seed=seed)
        # Same starting balances on both sides so the ONLY difference is which side is drawn.
        env.job401k.pretax_balance = 500000.0
        env.job401k.roth_balance = 500000.0
        index = encode_flat_action(action_type, 0.10)
        for _ in range(years):
            _, _, terminated, truncated, info = env.step(index)
            self.assertTrue(info["action_result"].success)
            if terminated or truncated:
                break
        return env._calculate_net_worth()

    def test_pretax_vs_roth_withdrawal_yields_different_net_worth(self):
        pretax_net_worth = self._run_episode(ActionType.WITHDRAW_401K_PRETAX)
        roth_net_worth = self._run_episode(ActionType.WITHDRAW_401K_ROTH)
        # The pre-tax episode paid income tax on every withdrawal; Roth paid none.
        self.assertGreater(roth_net_worth - pretax_net_worth, 1000.0)

    def test_taxable_withdrawal_creates_ledger_income(self):
        env = FinancialLifeEnv()
        env.reset(seed=0)
        env.job401k.pretax_balance = 100000.0
        income_before = env.person.taxable_income
        result = env.action_executor.execute_action(env.person, ActionType.WITHDRAW_401K_PRETAX, amount=10000.0)
        self.assertTrue(result.success)
        self.assertAlmostEqual(env.person.taxable_income - income_before, 10000.0)

    def test_roth_withdrawal_creates_no_ledger_income(self):
        env = FinancialLifeEnv()
        env.reset(seed=0)
        env.job401k.roth_balance = 100000.0
        income_before = env.person.taxable_income
        result = env.action_executor.execute_action(env.person, ActionType.WITHDRAW_401K_ROTH, amount=10000.0)
        self.assertTrue(result.success)
        self.assertAlmostEqual(env.person.taxable_income, income_before)


class TestContributionTaxTreatment(unittest.TestCase):
    """Bank-to-401k transfers stand in for payroll deferrals: pre-tax ones are deductible, and both
    kinds share the 402(g) elective-deferral limit (regression: pre-tax was taxed going in and
    coming out, and 401k transfers were uncapped, so Roth always won)."""

    def _fresh_env(self):
        env = FinancialLifeEnv()
        env.reset(seed=0)
        env.person.deposit_into_bank_account(200000.0)  # enough cash that only the limit binds
        return env

    def test_pretax_transfer_is_deductible_roth_is_not(self):
        pretax, roth = self._fresh_env(), self._fresh_env()
        for env, action in (
            (pretax, ActionType.TRANSFER_BANK_TO_401K_PRETAX),
            (roth, ActionType.TRANSFER_BANK_TO_401K_ROTH),
        ):
            before = env.person.taxable_income
            result = env.action_executor.execute_action(env.person, action, amount=5000.0)
            self.assertTrue(result.success)
            env.delta = env.person.taxable_income - before
        self.assertAlmostEqual(pretax.delta, -5000.0)
        self.assertAlmostEqual(roth.delta, 0.0)

    def test_401k_transfers_share_the_402g_limit(self):
        env = self._fresh_env()
        room = env.person.remaining_401k_elective_room()
        self.assertGreater(room, 0)
        first = env.action_executor.execute_action(env.person, ActionType.TRANSFER_BANK_TO_401K_PRETAX, amount=1e9)
        self.assertAlmostEqual(first.amount_transferred, room)
        # The Roth side draws on the same (now exhausted) room.
        self.assertFalse(env.action_executor.can_execute_action(env.person, ActionType.TRANSFER_BANK_TO_401K_ROTH))
        self.assertAlmostEqual(env.job401k.pretax_balance, room)

    def test_retiree_cannot_defer_into_the_401k(self):
        env = self._fresh_env()
        env.action_executor.execute_action(env.person, ActionType.RETIRE_EARLY)
        for action in (ActionType.TRANSFER_BANK_TO_401K_PRETAX, ActionType.TRANSFER_BANK_TO_401K_ROTH):
            self.assertFalse(env.action_executor.can_execute_action(env.person, action))

    def test_pretax_deferral_lowers_that_years_income_tax(self):
        taxes = {}
        for action in (ActionType.TRANSFER_BANK_TO_401K_PRETAX, ActionType.TRANSFER_BANK_TO_401K_ROTH):
            env = self._fresh_env()
            env.step(encode_flat_action(action, 1.00))
            taxes[action] = env.person.stat_taxes_paid
        saved = taxes[ActionType.TRANSFER_BANK_TO_401K_ROTH] - taxes[ActionType.TRANSFER_BANK_TO_401K_PRETAX]
        self.assertGreater(saved, 1000.0)


if __name__ == "__main__":
    unittest.main()
