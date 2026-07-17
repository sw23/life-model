# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the unreimbursed-medical itemized deduction."""

import unittest

from ..account.bank import BankAccount
from ..healthcare import LongTermCare, MedicalCosts
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..tax.income import IncomeType


def _make_person(model, age, balance=5_000_000):
    family = Family(model)
    person = Person(family=family, name="P", age=age, retirement_age=90, spending=Spending(model, base=0))
    BankAccount(owner=person, company="Bank", balance=balance)
    return person


class TestMedicalDeduction(unittest.TestCase):
    def test_no_healthcare_agents_no_deduction(self):
        """Without healthcare agents there is no medical deduction (opt-in guarantee)."""
        model = LifeModel(start_year=2026, end_year=2027)
        person = _make_person(model, age=70)
        person.income.add(IncomeType.ORDINARY, 50000)
        self.assertEqual(person.unreimbursed_medical_expenses, 0.0)
        self.assertEqual(person.medical_expense_deduction, 0.0)

    def test_deduction_is_excess_over_floor(self):
        """Only medical spend above 7.5% of pre-deduction ordinary income is deductible."""
        model = LifeModel(start_year=2026, end_year=2027)
        person = _make_person(model, age=70)
        mc = MedicalCosts(person)
        mc.stat_medical_costs = 20000.0  # as stamped by pre_step
        person.income.add(IncomeType.ORDINARY, 100000)
        # Floor = 7.5% of 100,000 = 7,500; deduction = 20,000 - 7,500 = 12,500.
        self.assertEqual(person.unreimbursed_medical_expenses, 20000.0)
        self.assertAlmostEqual(person.medical_expense_deduction, 12500.0, places=6)
        self.assertGreaterEqual(person.total_itemized_deductions, 12500.0)

    def test_below_floor_no_deduction(self):
        """Medical spend below the floor yields no deduction."""
        model = LifeModel(start_year=2026, end_year=2027)
        person = _make_person(model, age=70)
        mc = MedicalCosts(person)
        mc.stat_medical_costs = 5000.0
        person.income.add(IncomeType.ORDINARY, 100000)  # floor 7,500 > 5,000
        self.assertEqual(person.medical_expense_deduction, 0.0)

    def test_ltc_net_cost_counts_toward_deduction(self):
        """The LTC agent's net (post-insurance) cost feeds the medical deduction."""
        model = LifeModel(start_year=2026, end_year=2027)
        person = _make_person(model, age=80)
        ltc = LongTermCare(person)
        ltc.stat_medical_costs = 60000.0  # net care cost stamped by pre_step
        person.income.add(IncomeType.ORDINARY, 40000)
        # Floor = 3,000; deduction = 57,000.
        self.assertAlmostEqual(person.medical_expense_deduction, 57000.0, places=6)

    def test_high_medical_retiree_itemizes_end_to_end(self):
        """A retiree with medical > floor and other itemized > standard deduction pays less tax.

        Acceptance scenario: identical high-income retirees, one with a MedicalCosts agent whose
        costs exceed the 7.5% floor. The medical retiree's federal taxes must be lower by more
        than zero (they itemize past the standard deduction), and their reported itemized
        deduction must include the medical excess.
        """

        def run(with_medical: bool):
            from ..config.financial_config import FinancialConfig

            cfg = FinancialConfig()
            # Inflate the top medical band so the retiree's costs decisively beat the floor and
            # the standard deduction (isolates the deduction path from the config's magnitudes).
            cfg.apply_scenario(
                "high_medical",
                {
                    "economy": {"inflation": 0.0},
                    "healthcare": {
                        "medical_inflation_premium": 0.0,
                        "medical_cost_bands": [{"max_age": 200, "annual_cost": 40000}],
                    },
                },
            )
            model = LifeModel(start_year=2026, end_year=2026, config=cfg)
            person = _make_person(model, age=70)
            if with_medical:
                MedicalCosts(person)
            person.income.add(IncomeType.ORDINARY, 100000)
            model.step()
            return person

        without = run(False)
        with_med = run(True)
        # Floor = 7.5% of 100k = 7.5k; deduction = 40k - 7.5k = 32.5k > standard deduction.
        self.assertGreater(with_med.stat_taxes_paid, 0)
        self.assertLess(with_med.stat_taxes_paid, without.stat_taxes_paid)

    def test_agi_history_reflects_medical_deduction(self):
        """Recorded AGI is reduced by the itemized medical deduction (consistent with returns)."""
        from ..config.financial_config import FinancialConfig

        cfg = FinancialConfig()
        cfg.apply_scenario(
            "high_medical",
            {
                "economy": {"inflation": 0.0},
                "healthcare": {
                    "medical_inflation_premium": 0.0,
                    "medical_cost_bands": [{"max_age": 200, "annual_cost": 40000}],
                },
            },
        )
        model = LifeModel(start_year=2026, end_year=2026, config=cfg)
        person = _make_person(model, age=70)
        MedicalCosts(person)
        person.income.add(IncomeType.ORDINARY, 100000)
        model.step()
        # AGI = 100,000 - itemized (32,500 medical) = 67,500.
        self.assertAlmostEqual(person.agi_history[2026], 100000 - 32500, places=2)


class TestWithdrawalSizingWithMedicalDeduction(unittest.TestCase):
    """The 401k-withdrawal solver and settlement must agree on the medical floor (review fix).

    The prospective withdrawal is ``additional_income`` during sizing but ledger income at
    settlement. If the 7.5% medical floor ignores it during sizing, the sized taxes come in
    lower than the settled taxes and the difference lands as phantom year-end debt.
    """

    @staticmethod
    def _high_medical_config(annual_cost):
        from ..config.financial_config import FinancialConfig

        cfg = FinancialConfig()
        cfg.apply_scenario(
            "high_medical",
            {
                "economy": {"inflation": 0.0},
                "healthcare": {
                    "medical_inflation_premium": 0.0,
                    "medical_cost_bands": [{"max_age": 200, "annual_cost": annual_cost}],
                },
            },
        )
        return cfg

    def _make_retiree(self, model, pretax_balance):
        from ..account.job401k import Job401kAccount
        from ..work.job import Job, Salary

        family = Family(model)
        person = Person(family=family, name="R", age=70, retirement_age=65, spending=Spending(model, base=0))
        BankAccount(owner=person, company="Bank", balance=1000)
        job = Job(owner=person, company="Co", role="Retiree", salary=Salary(model, base=0))
        Job401kAccount(job=job, pretax_balance=pretax_balance, roth_balance=0)
        return person

    def test_medical_costs_funded_from_401k_leave_no_phantom_debt(self):
        """Reviewer's repro: $2M pretax, $1k bank, $60k medical band => debt == 0 at year end."""
        model = LifeModel(start_year=2026, end_year=2026, config=self._high_medical_config(60000))
        person = self._make_retiree(model, pretax_balance=2_000_000)
        MedicalCosts(person)
        model.step()
        self.assertEqual(person.debt, 0)
        # The withdrawal actually happened (medical costs were funded from the 401k).
        self.assertLess(person.all_retirement_accounts[0].pretax_balance, 2_000_000)

    def test_ltc_episode_funded_from_401k_leaves_no_phantom_debt(self):
        """LTC variant: a $111,325/yr care episode funded from the 401k => debt == 0."""
        model = LifeModel(start_year=2026, end_year=2026, config=self._high_medical_config(0))
        person = self._make_retiree(model, pretax_balance=2_000_000)
        ltc = LongTermCare(person)
        ltc.in_care = True
        ltc.care_years_remaining = 2
        model.step()
        self.assertEqual(person.debt, 0)
        self.assertLess(person.all_retirement_accounts[0].pretax_balance, 2_000_000)


if __name__ == "__main__":
    unittest.main()
