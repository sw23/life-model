# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for revocable/irrevocable trusts and their estate integration."""

import unittest

from ..account.bank import BankAccount
from ..config.financial_config import FinancialConfig
from ..estate.trust import Trust, TrustType
from ..model import LifeModel
from ..people.family import Family
from ..people.person import MortalityMode, Person, Spending


def _model(*, estate_tax_exemption=None, start_year=2026, end_year=2027):
    cfg = FinancialConfig()
    if estate_tax_exemption is not None:
        cfg.model.tax.federal.estate_tax_exemption = estate_tax_exemption
    return LifeModel(start_year=start_year, end_year=end_year, config=cfg)


def _person(model, family, name="Grantor", age=60, death_age=None, **kwargs):
    if death_age is not None:
        kwargs.update(mortality_mode=MortalityMode.FIXED_AGE, death_age=death_age)
    return Person(family, name, age=age, retirement_age=100, spending=Spending(model, 0), **kwargs)


class TestTrustBasics(unittest.TestCase):
    def setUp(self):
        self.model = _model()
        self.family = Family(self.model)
        self.grantor = _person(self.model, self.family)
        self.child = _person(self.model, self.family, name="Kid", age=30)
        BankAccount(self.grantor, "GB", balance=500000, interest_rate=0)
        BankAccount(self.child, "KB", balance=0, interest_rate=0)

    def test_fund_moves_cash_from_grantor(self):
        trust = Trust(self.grantor, TrustType.REVOCABLE, [self.child])
        moved = trust.fund(100000)
        self.assertEqual(moved, 100000)
        self.assertEqual(trust.balance, 100000)
        self.assertEqual(self.grantor.bank_account_balance, 400000)

    def test_fund_limited_by_available_cash(self):
        trust = Trust(self.grantor, TrustType.REVOCABLE, [self.child])
        moved = trust.fund(600000)
        self.assertEqual(moved, 500000)
        self.assertEqual(self.grantor.bank_account_balance, 0)

    def test_distributions_conserve_money(self):
        trust = Trust(self.grantor, TrustType.IRREVOCABLE, [self.child])
        trust.fund(100000)
        distributed = trust.distribute(30000, self.child)
        self.assertEqual(distributed, 30000)
        self.assertEqual(trust.balance, 70000)
        self.assertEqual(self.child.bank_account_balance, 30000)
        # Total money unchanged: 500k = 400k grantor bank + 70k trust + 30k child bank.
        total = self.grantor.bank_account_balance + trust.balance + self.child.bank_account_balance
        self.assertEqual(total, 500000)

    def test_distribution_limited_by_balance(self):
        trust = Trust(self.grantor, TrustType.IRREVOCABLE, [self.child])
        trust.fund(10000)
        self.assertEqual(trust.distribute(25000, self.child), 10000)
        self.assertEqual(trust.balance, 0)

    def test_registered_on_grantor(self):
        trust = Trust(self.grantor, TrustType.REVOCABLE, [self.child])
        self.assertIn(trust, self.grantor.trusts)


class TestGiftExclusionAndExemption(unittest.TestCase):
    def setUp(self):
        self.model = _model()
        self.family = Family(self.model)
        self.grantor = _person(self.model, self.family)
        self.child = _person(self.model, self.family, name="Kid", age=30)
        BankAccount(self.grantor, "GB", balance=1000000, interest_rate=0)
        self.exclusion = self.model.tax_params_for_year(self.model.year).gift_exclusion

    def test_funding_within_exclusion_leaves_exemption_intact(self):
        trust = Trust(self.grantor, TrustType.IRREVOCABLE, [self.child])
        trust.fund(self.exclusion)
        self.assertEqual(self.grantor.estate_exemption_used, 0.0)

    def test_over_exclusion_funding_reduces_remaining_exemption(self):
        trust = Trust(self.grantor, TrustType.IRREVOCABLE, [self.child])
        trust.fund(self.exclusion + 50000)
        self.assertEqual(self.grantor.estate_exemption_used, 50000)

    def test_incremental_funding_accumulates_within_the_year(self):
        trust = Trust(self.grantor, TrustType.IRREVOCABLE, [self.child])
        trust.fund(self.exclusion)  # uses up the annual exclusion
        trust.fund(20000)  # entirely above the exclusion
        self.assertEqual(self.grantor.estate_exemption_used, 20000)

    def test_revocable_funding_has_no_gift_consequence(self):
        trust = Trust(self.grantor, TrustType.REVOCABLE, [self.child])
        trust.fund(self.exclusion + 500000)
        self.assertEqual(self.grantor.estate_exemption_used, 0.0)


class TestTrustEstateIntegration(unittest.TestCase):
    def _dying_grantor_with_trust(self, trust_type, *, exemption=100000, trust_balance=200000, residual=100000):
        model = _model(estate_tax_exemption=exemption)
        family = Family(model)
        grantor = _person(model, family, age=75, death_age=76)
        child = _person(model, family, name="Kid", age=40)
        BankAccount(grantor, "GB", balance=residual, interest_rate=0)
        BankAccount(child, "KB", balance=0, interest_rate=0)
        # Endow the corpus via the constructor (not fund()) so the tiny test exemption isn't
        # consumed by gift accounting; gift accounting has its own test class above.
        trust = Trust(grantor, trust_type, [child], balance=trust_balance)
        return model, grantor, child, trust

    def test_irrevocable_assets_excluded_from_gross_estate(self):
        model, grantor, child, trust = self._dying_grantor_with_trust(TrustType.IRREVOCABLE, residual=0)
        self.assertEqual(grantor._gross_estate_value(), 0.0)

    def test_revocable_assets_included_in_gross_estate(self):
        model, grantor, child, trust = self._dying_grantor_with_trust(TrustType.REVOCABLE, residual=0)
        self.assertEqual(grantor._gross_estate_value(), 200000)

    def test_revocable_trust_taxed_at_death_irrevocable_not(self):
        # Revocable: $200k trust + $100k residual bank in a $100k-exemption estate -> taxable
        # $200k -> $80k estate tax (40%). The child receives the residual bank ($100k, out of
        # which the estate tax is paid) plus the trust payout: 100k - 80k + 200k = 220k.
        model_r, grantor_r, child_r, _ = self._dying_grantor_with_trust(TrustType.REVOCABLE)
        model_r.run()
        events_r = " | ".join(e.message for e in model_r.event_log.list)
        self.assertIn("Estate tax", events_r)
        self.assertAlmostEqual(child_r.bank_account_balance, 220000, delta=1.0)

        # Irrevocable: the trust assets escape the estate tax; only the $100k residual is in the
        # gross estate, which sits within the exemption -> no estate tax at all.
        model_i, grantor_i, child_i, trust_i = self._dying_grantor_with_trust(TrustType.IRREVOCABLE)
        model_i.run()
        events_i = " | ".join(e.message for e in model_i.event_log.list)
        self.assertNotIn("Estate tax", events_i)
        self.assertAlmostEqual(child_i.bank_account_balance, 100000, delta=1.0)

    def test_revocable_pays_out_to_beneficiaries_outside_the_will(self):
        # Residual estate goes to the spouse, but the revocable trust pays its own beneficiary.
        model = _model(estate_tax_exemption=10000000)
        family = Family(model)
        grantor = _person(model, family, age=75, death_age=76)
        spouse = _person(model, family, name="Spouse", age=74)
        grantor.get_married(spouse)
        child = _person(model, family, name="Kid", age=40)
        BankAccount(grantor, "GB", balance=300000, interest_rate=0)
        BankAccount(spouse, "SB", balance=0, interest_rate=0)
        BankAccount(child, "KB", balance=0, interest_rate=0)
        trust = Trust(grantor, TrustType.REVOCABLE, [child])
        trust.fund(200000)
        model.run()

        self.assertTrue(grantor.is_deceased)
        # Trust corpus went to the child; the residual $100k bank went to the spouse.
        self.assertAlmostEqual(child.bank_account_balance, 200000, delta=1.0)
        self.assertAlmostEqual(spouse.bank_account_balance, 100000, delta=1.0)
        # The trust is gone (terminated at the grantor's death).
        self.assertNotIn(trust, model.agents)

    def test_revocable_trust_with_predeceased_beneficiaries_escheats_to_residual(self):
        # Regression (money conservation): when every trust beneficiary predeceases the grantor,
        # the corpus escheats to the residual inheritor instead of dissolving to nowhere.
        model = _model(estate_tax_exemption=10000000)
        family = Family(model)
        grantor = _person(model, family, age=75, death_age=76)
        heir = _person(model, family, name="Heir", age=45)
        dead_kid = _person(model, family, name="Gone", age=50)
        dead_kid.is_deceased = True
        BankAccount(grantor, "GB", balance=50000, interest_rate=0)
        BankAccount(heir, "HB", balance=0, interest_rate=0)
        trust = Trust(grantor, TrustType.REVOCABLE, [dead_kid], balance=200000)
        model.run()

        self.assertTrue(grantor.is_deceased)
        # The heir received both the residual bank ($50k) and the escheated corpus ($200k).
        self.assertAlmostEqual(heir.bank_account_balance, 250000, delta=1.0)
        self.assertNotIn(trust, model.agents)
        events = " | ".join(e.message for e in model.event_log.list)
        self.assertIn("escheated to Heir", events)

    def test_irrevocable_trust_survives_grantor_death(self):
        model, grantor, child, trust = self._dying_grantor_with_trust(TrustType.IRREVOCABLE)
        model.run()
        self.assertTrue(grantor.is_deceased)
        # The trust survives with its own registry entry and can still distribute.
        self.assertIn(trust, model.agents)
        self.assertIn(trust, model.registries.trusts.get_items(grantor))
        self.assertGreater(trust.balance, 0)
        distributed = trust.distribute(10000, child)
        self.assertEqual(distributed, 10000)


if __name__ == "__main__":
    unittest.main()
