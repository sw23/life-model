# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for HEAD_OF_HOUSEHOLD: enum, config fallback, and tax-unit derivation.

The frozen fixture config has no head_of_household data, pinning the documented fallback to
SINGLE. Tests that exercise real HoH data apply a scenario override.
"""

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..config.financial_config import FinancialConfig
from ..dependents.child import Child
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..people.tax_unit import TaxUnit
from ..tax.federal import FilingStatus, get_federal_standard_deduction, get_federal_tax_brackets
from ..tax.fica import get_medicare_additional_rate_threshold

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    return FinancialConfig(config_file=TEST_CONFIG)


def _fixture_config_with_hoh() -> FinancialConfig:
    """Fixture config plus explicit round-number head-of-household data."""
    cfg = _fixture_config()
    cfg.apply_scenario(
        "_hoh",
        {
            "tax": {
                "federal": {
                    "standard_deduction": {"head_of_household": 15000},
                    "tax_brackets": {
                        "head_of_household": [
                            [0, 60000, 10],
                            [60001, float("inf"), 25],
                        ]
                    },
                }
            }
        },
    )
    return cfg


class TestFilingStatusEnum(unittest.TestCase):
    def test_head_of_household_member_exists(self):
        self.assertTrue(hasattr(FilingStatus, "HEAD_OF_HOUSEHOLD"))
        self.assertNotEqual(FilingStatus.HEAD_OF_HOUSEHOLD, FilingStatus.SINGLE)
        self.assertNotEqual(FilingStatus.HEAD_OF_HOUSEHOLD, FilingStatus.MARRIED_FILING_JOINTLY)


class TestHoHConfigFallback(unittest.TestCase):
    def test_falls_back_to_single_when_config_absent(self):
        cfg = _fixture_config()
        self.assertEqual(
            get_federal_standard_deduction(FilingStatus.HEAD_OF_HOUSEHOLD, cfg),
            get_federal_standard_deduction(FilingStatus.SINGLE, cfg),
        )
        self.assertEqual(
            get_federal_tax_brackets(FilingStatus.HEAD_OF_HOUSEHOLD, cfg),
            get_federal_tax_brackets(FilingStatus.SINGLE, cfg),
        )

    def test_uses_hoh_data_when_config_supplies_it(self):
        cfg = _fixture_config_with_hoh()
        self.assertEqual(get_federal_standard_deduction(FilingStatus.HEAD_OF_HOUSEHOLD, cfg), 15000)
        brackets = get_federal_tax_brackets(FilingStatus.HEAD_OF_HOUSEHOLD, cfg)
        self.assertEqual(brackets[0][1], 60000)

    def test_defaults_ship_hoh_data(self):
        # The packaged defaults carry real HoH data (Rev. Proc. 2025-32: $24,150 for 2026).
        cfg = FinancialConfig()
        self.assertEqual(get_federal_standard_deduction(FilingStatus.HEAD_OF_HOUSEHOLD, cfg), 24150)
        self.assertEqual(get_federal_tax_brackets(FilingStatus.HEAD_OF_HOUSEHOLD, cfg)[0][1], 17700)
        # Every tax_years block carries HoH data too.
        for year, params in cfg.model.tax_years.items():
            self.assertIsNotNone(params.standard_deduction.head_of_household, f"missing HoH std ded for {year}")
            self.assertIsNotNone(params.tax_brackets.head_of_household, f"missing HoH brackets for {year}")

    def test_medicare_additional_threshold_hoh_uses_single(self):
        # Statutory: HoH shares the single $200k additional-Medicare threshold.
        cfg = _fixture_config()
        self.assertEqual(
            get_medicare_additional_rate_threshold(FilingStatus.HEAD_OF_HOUSEHOLD, cfg),
            get_medicare_additional_rate_threshold(FilingStatus.SINGLE, cfg),
        )


class TestBuildUnitsHoHDerivation(unittest.TestCase):
    def _model(self):
        return LifeModel(start_year=2026, end_year=2027, config=_fixture_config())

    def test_unmarried_parent_with_dependent_child_files_hoh(self):
        model = self._model()
        family = Family(model)
        parent = Person(family, "Solo", age=35, retirement_age=70, spending=Spending(model, 0))
        Child(parent, "Kid", birth_year=2020)
        units = TaxUnit.build_units(family)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].filing_status, FilingStatus.HEAD_OF_HOUSEHOLD)

    def test_unmarried_person_without_children_files_single(self):
        model = self._model()
        family = Family(model)
        Person(family, "Solo", age=35, retirement_age=70, spending=Spending(model, 0))
        units = TaxUnit.build_units(family)
        self.assertEqual(units[0].filing_status, FilingStatus.SINGLE)

    def test_married_parent_still_files_jointly(self):
        model = self._model()
        family = Family(model)
        a = Person(family, "Ada", age=35, retirement_age=70, spending=Spending(model, 0))
        b = Person(family, "Ben", age=36, retirement_age=70, spending=Spending(model, 0))
        a.get_married(b)
        Child(a, "Kid", birth_year=2020)
        units = TaxUnit.build_units(family)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].filing_status, FilingStatus.MARRIED_FILING_JOINTLY)

    def test_parent_of_adult_child_files_single(self):
        model = self._model()
        family = Family(model)
        parent = Person(family, "Solo", age=55, retirement_age=70, spending=Spending(model, 0))
        Child(parent, "Grown", birth_year=2000)  # age 26 >= adult_age
        units = TaxUnit.build_units(family)
        self.assertEqual(units[0].filing_status, FilingStatus.SINGLE)


class TestHoHSettlement(unittest.TestCase):
    def test_hoh_deduction_used_in_settlement(self):
        """An unmarried parent settles with the HoH standard deduction when configured.

        Fixture+HoH override: HoH std ded 15000 vs single 10000; brackets 10% to 60000 (vs
        40000 single). Income 50000 wages, one qualifying child (CTC 2000 fully usable).
          HoH:    taxable 50000-15000=35000 -> federal 3500;  state 5% of 35000 = 1750
          SINGLE: taxable 50000-10000=40000 -> federal 4000;  state 2000
        FICA identical. Settled taxes must reflect the HoH numbers (750 lower).
        """

        def run(cfg):
            from ..work.job import Job, Salary

            model = LifeModel(start_year=2026, end_year=2026, config=cfg)
            parent = Person(Family(model), "Solo", age=35, retirement_age=70, spending=Spending(model, base=0))
            BankAccount(parent, "Bank", balance=50000, interest_rate=0)
            Job(parent, "Co", "Dev", Salary(model=model, base=50000, yearly_increase=0, yearly_bonus=0))
            Child(parent, "Kid", birth_year=2020)
            model.step()
            return parent.stat_taxes_paid

        taxes_hoh = run(_fixture_config_with_hoh())
        taxes_fallback = run(_fixture_config())
        self.assertAlmostEqual(taxes_fallback - taxes_hoh, 750, places=2)


if __name__ == "__main__":
    unittest.main()
