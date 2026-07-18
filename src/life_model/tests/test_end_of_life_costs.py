# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for end-of-life costs at death."""

import unittest

from ..account.bank import BankAccount
from ..config.financial_config import FinancialConfig
from ..healthcare import MedicalCosts
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..people.types import MortalityMode


def _flat_config(extra_overrides=None):
    cfg = FinancialConfig()
    overrides = {
        "economy": {"inflation": 0.0},
        "healthcare": {
            "medical_inflation_premium": 0.0,
            # One flat band makes the final-medical arithmetic exact.
            "medical_cost_bands": [{"max_age": 200, "annual_cost": 10000}],
        },
    }
    if extra_overrides:
        for key, value in extra_overrides.items():
            overrides.setdefault(key, {}).update(value)
    cfg.apply_scenario("flat", overrides)
    return cfg


class TestEndOfLifeCosts(unittest.TestCase):
    def _run_death(self, with_medical: bool, cfg=None, balance=500000):
        """A parent dies at 80 (fixed age); the child inherits. Returns (child, model).

        Death happens in ``Person.pre_step`` (priority -20), before the MedicalCosts agent's
        own ``pre_step`` (priority 0) charges the regular annual cost — so in the death year the
        only healthcare charge is the end-of-life cost, making the arithmetic exact.
        """
        model = LifeModel(start_year=2026, end_year=2026, config=cfg or _flat_config())
        family = Family(model)
        parent = Person(
            family=family,
            name="Parent",
            age=79,
            retirement_age=65,
            spending=Spending(model, base=0),
            mortality_mode=MortalityMode.FIXED_AGE,
            death_age=80,
        )
        child = Person(family=family, name="Child", age=50, retirement_age=65, spending=Spending(model, base=0))
        BankAccount(owner=parent, company="Bank", balance=balance)
        BankAccount(owner=child, company="Bank", balance=0)
        if with_medical:
            MedicalCosts(parent)
        model.step()
        return child, model

    def test_estate_reduced_by_funeral_and_final_medical(self):
        """The inheritor receives the estate minus funeral + multiplier x current medical cost."""
        child_without, _ = self._run_death(with_medical=False)
        child_with, model = self._run_death(with_medical=True)
        healthcare = model.config.healthcare
        # Flat economy: funeral 8,300 (no CPI drift) + 2.0 x 10,000 final medical = 28,300.
        expected_end_of_life = healthcare.funeral_cost + healthcare.final_year_medical_multiplier * 10000
        self.assertEqual(child_without.bank_account_balance, 500000)
        delta = child_without.bank_account_balance - child_with.bank_account_balance
        self.assertAlmostEqual(delta, expected_end_of_life, places=2)
        self.assertTrue(any("end-of-life" in e.message for e in model.event_log.list))

    def test_no_healthcare_agents_death_flow_unchanged(self):
        """Without healthcare agents the death flow charges nothing (opt-in guarantee)."""
        child, model = self._run_death(with_medical=False, balance=250000)
        self.assertEqual(child.bank_account_balance, 250000)
        self.assertFalse(any("end-of-life" in e.message for e in model.event_log.list))

    def test_end_of_life_costs_reduce_estate_before_estate_tax(self):
        """Estate tax applies to the estate net of end-of-life costs (ordering pinned)."""
        cfg = _flat_config(extra_overrides={"tax": {"federal": {"estate_tax_exemption": 0}}})
        child, model = self._run_death(with_medical=True, cfg=cfg, balance=500000)
        healthcare = model.config.healthcare
        rate = model.config.tax.federal.estate_tax_rate / 100
        end_of_life = healthcare.funeral_cost + healthcare.final_year_medical_multiplier * 10000
        # Ordering: the estate is reduced by end-of-life costs BEFORE the estate tax is computed.
        # Child receives (500,000 - 28,300), then pays 40% estate tax on that reduced estate.
        reduced_estate = 500000 - end_of_life
        expected_balance = reduced_estate - reduced_estate * rate
        self.assertAlmostEqual(child.bank_account_balance, expected_balance, places=2)

    def test_healthcare_agents_not_inherited(self):
        """The deceased's healthcare agents are retired, not transferred to the inheritor."""
        child, model = self._run_death(with_medical=True)
        self.assertEqual(child.medical_costs, [])
        self.assertEqual(model.registries.medical_costs.get_all_items(), [])


if __name__ == "__main__":
    unittest.main()
