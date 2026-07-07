# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""State tax pack tests (Plan 17).

Configs are built from the frozen fixture and augmented with explicit packs so the numbers stay
stable across annual data refreshes (they do not depend on the shipped state DOR values).
"""

import random
import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..config.financial_config import FinancialConfig
from ..config.models import StateTaxConfig, StateTaxPack
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..tax.brackets import apply_brackets
from ..tax.federal import FilingStatus, federal_income_tax, get_federal_tax_brackets
from ..tax.income import IncomeLedger, IncomeType
from ..tax.state import get_state_tax_rate, state_income_tax, state_income_tax_for_unit
from ..work.job import Job, Salary

FIXTURE = str(Path(__file__).parent / "fixtures" / "test_config.yaml")
INF = float("inf")


def _config(**state_overrides) -> FinancialConfig:
    config = FinancialConfig(config_file=FIXTURE)
    if state_overrides:
        config.apply_scenario("test", {"tax": {"state": state_overrides}})
    return config


# Representative packs used across the tax-side tests.
CA_PACK = {"brackets": {"single": [[0, 10000, 1], [10001, 50000, 5], [50001, INF, 10]]}}
PA_PACK = {"flat_rate": 3.07, "retirement_income_taxable": False}
TX_PACK = {"flat_rate": 0.0}


class TestBackCompatShim(unittest.TestCase):
    """Task 1: the legacy tax_rate key still loads and produces the DEFAULT flat pack."""

    def test_legacy_tax_rate_synthesizes_default_pack(self):
        config = _config()
        state = config.tax.state
        self.assertEqual(state.tax_rate, 5.0)  # fixture legacy rate
        self.assertEqual(state.default_state, "DEFAULT")
        self.assertIn("DEFAULT", state.packs)
        self.assertEqual(state.packs["DEFAULT"].flat_rate, 5.0)

    def test_get_state_tax_rate_reads_default(self):
        self.assertEqual(get_state_tax_rate(_config()), 5.0)

    def test_legacy_state_income_tax_scalar(self):
        self.assertAlmostEqual(state_income_tax(100000, _config()), 5000.0, places=6)


class TestPackValidation(unittest.TestCase):
    """Task 1: malformed packs are rejected at load, not at tax time."""

    def test_unknown_state_rejected(self):
        with self.assertRaises(ValueError):
            _config(packs={"ZZ": {"flat_rate": 1.0}})

    def test_flat_and_brackets_both_set_rejected(self):
        with self.assertRaises(ValueError):
            _config(packs={"CA": {"flat_rate": 1.0, "brackets": {"single": [[0, 10, 1]]}}})

    def test_neither_flat_nor_brackets_rejected(self):
        with self.assertRaises(ValueError):
            _config(packs={"CA": {"standard_deduction": {"single": 100}}})

    def test_bracket_gap_rejected(self):
        with self.assertRaises(ValueError):
            _config(packs={"CA": {"brackets": {"single": [[0, 10000, 1], [20000, 30000, 5]]}}})

    def test_bracket_must_start_at_zero(self):
        with self.assertRaises(ValueError):
            _config(packs={"CA": {"brackets": {"single": [[100, 10000, 1]]}}})

    def test_default_state_without_pack_rejected(self):
        with self.assertRaises(ValueError):
            # default_state points to a state with no pack and tax_rate=null (no DEFAULT synth).
            FinancialConfig(config_file=FIXTURE).apply_scenario(
                "b", {"tax": {"state": {"tax_rate": None, "default_state": "NY", "packs": {}}}}
            )

    def test_brackets_require_single(self):
        with self.assertRaises(ValueError):
            _config(packs={"CA": {"brackets": {"married_filing_jointly": [[0, 10000, 1]]}}})


class TestTotalsByType(unittest.TestCase):
    """Task 2: IncomeLedger.totals_by_type decomposes ordinary income by category."""

    def test_totals_by_type(self):
        ledger = IncomeLedger()
        ledger.add_wages(80000, 90000)
        ledger.add(IncomeType.PRETAX_DISTRIBUTION, 20000)
        ledger.add(IncomeType.SS_BENEFIT, 5000)
        ledger.add(IncomeType.INTEREST, 1000)
        totals = ledger.totals_by_type()
        self.assertEqual(totals[IncomeType.WAGES], 80000)
        self.assertEqual(totals[IncomeType.PRETAX_DISTRIBUTION], 20000)
        self.assertEqual(totals[IncomeType.SS_BENEFIT], 5000)
        self.assertEqual(totals[IncomeType.INTEREST], 1000)
        self.assertEqual(totals[IncomeType.ORDINARY], 0.0)  # every type present
        self.assertAlmostEqual(sum(totals.values()), ledger.ordinary_taxable)


class TestApplyBracketsProperty(unittest.TestCase):
    """Task 3 (Risks): the shared bracket helper must match federal_income_tax exactly."""

    def test_apply_brackets_matches_federal(self):
        rng = random.Random(20250707)
        for status in (FilingStatus.SINGLE, FilingStatus.MARRIED_FILING_JOINTLY):
            brackets = get_federal_tax_brackets(status)
            for _ in range(2000):
                income = rng.uniform(0, 2_000_000)
                self.assertAlmostEqual(
                    apply_brackets(income, brackets),
                    federal_income_tax(income, status),
                    places=6,
                    msg=f"mismatch at income={income}, status={status}",
                )

    def test_apply_brackets_boundaries(self):
        brackets = get_federal_tax_brackets(FilingStatus.SINGLE)
        for income in (0, 1, brackets[0][1], brackets[0][1] + 1, brackets[-2][1]):
            self.assertAlmostEqual(
                apply_brackets(income, brackets), federal_income_tax(income, FilingStatus.SINGLE), places=6
            )


class TestStateBase(unittest.TestCase):
    """Task 3: the state taxable-income base honors each pack's exemptions."""

    def _totals(self, **kwargs):
        totals = {t: 0.0 for t in IncomeType}
        for name, value in kwargs.items():
            totals[IncomeType[name]] = value
        return totals

    def test_default_uses_legacy_agi_base(self):
        config = _config()
        # DEFAULT ignores the pack base and applies the flat rate to the legacy AGI base.
        tax = state_income_tax_for_unit(
            self._totals(WAGES=100000), FilingStatus.SINGLE, None, legacy_agi_base=90000, config=config
        )
        self.assertAlmostEqual(tax, 90000 * 0.05, places=6)

    def test_flat_pack_uses_state_base(self):
        config = _config(default_state="TX", packs={"TX": TX_PACK, "PA": PA_PACK})
        totals = self._totals(PRETAX_DISTRIBUTION=40000)
        # PA exempts retirement income -> zero base -> zero tax.
        pa_tax = state_income_tax_for_unit(totals, FilingStatus.SINGLE, "PA", legacy_agi_base=99999, config=config)
        self.assertEqual(pa_tax, 0.0)
        # TX has no income tax.
        tx_tax = state_income_tax_for_unit(self._totals(WAGES=100000), FilingStatus.SINGLE, "TX",
                                           legacy_agi_base=99999, config=config)
        self.assertEqual(tx_tax, 0.0)

    def test_ss_exempt_by_default(self):
        config = _config(default_state="CA", packs={"CA": CA_PACK})
        totals = self._totals(WAGES=60000, SS_BENEFIT=10000)
        # SS is excluded from the base (ss_taxable defaults False): base = 60000 -> brackets.
        tax = state_income_tax_for_unit(totals, FilingStatus.SINGLE, "CA", legacy_agi_base=0, config=config)
        expected = apply_brackets(60000, CA_PACK["brackets"]["single"])
        self.assertAlmostEqual(tax, expected, places=6)

    def test_state_standard_deduction(self):
        pack = {"flat_rate": 5.0, "standard_deduction": {"single": 5000}}
        config = _config(default_state="CO", packs={"CO": pack})
        totals = self._totals(WAGES=50000)
        tax = state_income_tax_for_unit(totals, FilingStatus.SINGLE, "CO", legacy_agi_base=0, config=config)
        self.assertAlmostEqual(tax, (50000 - 5000) * 0.05, places=6)

    def test_bracket_mfj_falls_back_to_single(self):
        config = _config(default_state="CA", packs={"CA": CA_PACK})
        totals = self._totals(WAGES=60000)
        single = state_income_tax_for_unit(totals, FilingStatus.SINGLE, "CA", 0, config)
        mfj = state_income_tax_for_unit(totals, FilingStatus.MARRIED_FILING_JOINTLY, "CA", 0, config)
        self.assertEqual(single, mfj)  # no MFJ brackets -> single fallback


class TestModelDefaults(unittest.TestCase):
    """Direct model checks that don't need a full FinancialConfig."""

    def test_default_state_pack_synthesized(self):
        cfg = StateTaxConfig(tax_rate=6.0)
        self.assertEqual(cfg.packs["DEFAULT"].flat_rate, 6.0)

    def test_pack_defaults(self):
        pack = StateTaxPack(flat_rate=0.0)
        self.assertTrue(pack.retirement_income_taxable)
        self.assertFalse(pack.ss_taxable)
        self.assertEqual(pack.standard_deduction.single, 0)


class TestSALTIntegration(unittest.TestCase):
    """Task 4/D4: state income tax joins property tax under the SALT cap."""

    def test_state_income_tax_capped_in_salt(self):
        config = _config()  # fixture salt cap defaults to $40k
        model = LifeModel(config=config)
        person = Person(Family(model), "A", age=40, retirement_age=65, spending=Spending(model, 0))
        base = person.itemized_deductions(0.0)
        # A state income tax above the cap is limited to the cap in itemized SALT.
        self.assertAlmostEqual(person.itemized_deductions(50000.0) - base, 40000.0, places=6)
        # Below the cap it passes through in full.
        self.assertAlmostEqual(person.itemized_deductions(12000.0) - base, 12000.0, places=6)

    def test_ca_resident_state_tax_folds_into_federal(self):
        # A CA high earner pays bracketed CA tax that flips them from the standard deduction to
        # itemizing (state tax > standard), lowering federal tax vs. a no-income-tax resident.
        ca_config = _config(default_state="CA", packs={"CA": CA_PACK, "TX": TX_PACK})
        tx_config = _config(default_state="TX", packs={"CA": CA_PACK, "TX": TX_PACK})

        def run(config, state):
            model = LifeModel(config=config, start_year=2020, end_year=2020)
            person = Person(Family(model), "Rich", age=40, retirement_age=70, spending=Spending(model, 0), state=state)
            BankAccount(person, "Bank", balance=0, interest_rate=0)
            Job(person, "Co", "Dev", Salary(model=model, base=300000))
            model.step()
            return person

        ca = run(ca_config, "CA")
        tx = run(tx_config, "TX")
        self.assertGreater(ca.stat_taxes_paid_state, 0)
        self.assertEqual(tx.stat_taxes_paid_state, 0)
        # CA state tax feeds SALT, so CA's federal tax is lower than TX's (identical income).
        self.assertLess(ca.stat_taxes_paid_federal, tx.stat_taxes_paid_federal)


class TestScenarioComparisons(unittest.TestCase):
    """Task 5 acceptance scenarios (with fixture-frozen packs, not shipped DOR values)."""

    def _run(self, state, config, *, wages=0.0, pretax_income=0.0):
        model = LifeModel(config=config, start_year=2020, end_year=2020)
        person = Person(Family(model), "P", age=68, retirement_age=60, spending=Spending(model, 0), state=state)
        BankAccount(person, "Bank", balance=0, interest_rate=0)
        if wages:
            person.income.add_wages(wages, wages)
        if pretax_income:
            person.income.add(IncomeType.PRETAX_DISTRIBUTION, pretax_income)
        return person

    def test_pa_retiree_pays_zero_on_401k(self):
        # PA exempts retirement income: a retiree living on 401k distributions pays $0 PA tax,
        # while the same income under DEFAULT (5% fixture) is taxed.
        pa_config = _config(default_state="PA", packs={"PA": PA_PACK})
        pa = self._run("PA", pa_config, pretax_income=40000)
        self.assertEqual(pa.get_income_taxes_due().state, 0.0)

        default_person = self._run(None, _config(), pretax_income=40000)
        self.assertGreater(default_person.get_income_taxes_due().state, 0.0)

    def test_tx_vs_ca_identical_income_only_state_differs(self):
        cfg = _config(default_state="DEFAULT", packs={"CA": CA_PACK, "TX": TX_PACK})
        ca = self._run("CA", cfg, wages=80000)
        tx = self._run("TX", cfg, wages=80000)
        ca_taxes = ca.get_income_taxes_due()
        tx_taxes = tx.get_income_taxes_due()
        # Only the state component differs; federal + FICA are identical (same income, no SALT flip
        # because neither state tax exceeds the standard deduction at this income).
        self.assertEqual(tx_taxes.state, 0.0)
        self.assertGreater(ca_taxes.state, 0.0)
        self.assertAlmostEqual(ca_taxes.federal, tx_taxes.federal, places=6)
        self.assertAlmostEqual(ca_taxes.ss, tx_taxes.ss, places=6)
        self.assertAlmostEqual(ca_taxes.medicare, tx_taxes.medicare, places=6)


class TestPersonState(unittest.TestCase):
    """Task 2/D2: Person.state is keyword-only and defaults to None (config default)."""

    def test_person_state_default_none(self):
        model = LifeModel(config=_config())
        person = Person(Family(model), "A", age=40, retirement_age=65, spending=Spending(model, 0))
        self.assertIsNone(person.state)

    def test_person_state_set(self):
        model = LifeModel(config=_config(default_state="CA", packs={"CA": CA_PACK}))
        person = Person(Family(model), "A", age=40, retirement_age=65, spending=Spending(model, 0), state="CA")
        self.assertEqual(person.state, "CA")


if __name__ == "__main__":
    unittest.main()
