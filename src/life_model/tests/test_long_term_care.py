# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the long-term-care hazard/care-state agent and LTC insurance offset."""

import unittest

from ..account.bank import BankAccount
from ..healthcare import LongTermCare
from ..insurance.general_insurance import Insurance, InsuranceType
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending


def _flat_model(start_year=2026, end_year=2060, seed=None):
    """A model with zero CPI and zero medical inflation premium so dollar factors are exactly 1."""
    from ..config.financial_config import FinancialConfig

    cfg = FinancialConfig()
    cfg.apply_scenario("flat", {"economy": {"inflation": 0.0}, "healthcare": {"medical_inflation_premium": 0.0}})
    return LifeModel(start_year=start_year, end_year=end_year, seed=seed, config=cfg)


def _make_person(model, age, balance=10_000_000):
    family = Family(model)
    person = Person(family=family, name="P", age=age, retirement_age=90, spending=Spending(model, base=0))
    BankAccount(owner=person, company="Bank", balance=balance)
    return person


def _episode_trace(seed):
    """Run a seeded 40-year sim and return (yearly net LTC costs, episodes started)."""
    model = _flat_model(start_year=2026, end_year=2065, seed=seed)
    person = _make_person(model, age=64)
    ltc = LongTermCare(person)
    costs = []
    for _ in model.get_year_range():
        model.step()
        costs.append(ltc.stat_medical_costs)
    return costs, ltc.episodes_started


class TestLongTermCare(unittest.TestCase):
    def test_no_hazard_before_start_age(self):
        """No care episode can start before the configured start age."""
        model = _flat_model()
        person = _make_person(model, age=40)
        ltc = LongTermCare(person)
        self.assertEqual(ltc._annual_hazard(50), 0.0)
        self.assertGreater(ltc._annual_hazard(70), 0.0)

    def test_hazard_increases_with_age(self):
        """The configured hazard bands rise with age."""
        model = _flat_model()
        ltc = LongTermCare(_make_person(model, age=70))
        self.assertLess(ltc._annual_hazard(70), ltc._annual_hazard(80))
        self.assertLess(ltc._annual_hazard(80), ltc._annual_hazard(95))

    def test_seeded_determinism(self):
        """Same seed => identical episode timing and costs; different seed differs eventually."""
        costs_a, episodes_a = _episode_trace(seed=1234)
        costs_b, episodes_b = _episode_trace(seed=1234)
        self.assertEqual(costs_a, costs_b)
        self.assertEqual(episodes_a, episodes_b)

    def test_care_year_charges_annual_cost(self):
        """A forced care year charges the configured annual cost through the bill path."""
        model = _flat_model(end_year=2026)
        person = _make_person(model, age=80)
        ltc = LongTermCare(person)
        ltc.in_care = True
        ltc.care_years_remaining = 3
        model.step()
        annual_cost = model.config.healthcare.long_term_care.annual_cost
        self.assertEqual(ltc.stat_medical_costs, annual_cost)
        self.assertEqual(person.stat_money_spent, annual_cost)
        self.assertEqual(ltc.care_years_remaining, 2)
        self.assertTrue(ltc.in_care)

    def test_episode_ends_after_duration(self):
        """The care state clears when the drawn duration is exhausted."""
        model = _flat_model(end_year=2027)
        person = _make_person(model, age=80)
        ltc = LongTermCare(person)
        ltc.in_care = True
        ltc.care_years_remaining = 1
        model.step()
        self.assertFalse(ltc.in_care)

    def test_insurance_offsets_by_exactly_the_benefit_cap(self):
        """LTC insurance reduces the net care cost by exactly the annual benefit (worked example).

        Care cost $111,325; policy benefit $60,000/yr, no deductible => net cost $51,325.
        """
        model = _flat_model(end_year=2026)
        person = _make_person(model, age=80)
        Insurance(
            person=person,
            insurance_type=InsuranceType.LONG_TERM_CARE,
            company="CarePlus",
            annual_premium=3000,
            coverage_amount=60000,
            deductible=0,
        )
        ltc = LongTermCare(person)
        ltc.in_care = True
        ltc.care_years_remaining = 2
        model.step()
        annual_cost = model.config.healthcare.long_term_care.annual_cost  # 111,325
        self.assertEqual(ltc.stat_medical_costs, annual_cost - 60000)
        # Money spent includes the gross care cost plus the LTC premium (both through bills);
        # the insurance payout arrived in the bank before settlement.
        self.assertEqual(person.stat_money_spent, annual_cost + 3000)

    def test_insurance_with_deductible(self):
        """The deductible reduces the payout: claim capped at the benefit, payout net of deductible."""
        model = _flat_model(end_year=2026)
        person = _make_person(model, age=80)
        Insurance(
            person=person,
            insurance_type=InsuranceType.LONG_TERM_CARE,
            company="CarePlus",
            annual_premium=3000,
            coverage_amount=60000,
            deductible=10000,
        )
        ltc = LongTermCare(person)
        ltc.in_care = True
        ltc.care_years_remaining = 1
        model.step()
        annual_cost = model.config.healthcare.long_term_care.annual_cost
        # Claimable capped at coverage = 60,000; payout = 60,000 - 10,000 deductible = 50,000.
        self.assertEqual(ltc.stat_medical_costs, annual_cost - 50000)

    def test_non_ltc_policies_do_not_offset(self):
        """Only LONG_TERM_CARE policies offset care costs."""
        model = _flat_model(end_year=2026)
        person = _make_person(model, age=80)
        Insurance(
            person=person,
            insurance_type=InsuranceType.HEALTH,
            company="Blue Cross",
            annual_premium=5000,
            coverage_amount=1000000,
            deductible=0,
        )
        ltc = LongTermCare(person)
        ltc.in_care = True
        ltc.care_years_remaining = 1
        model.step()
        self.assertEqual(ltc.stat_medical_costs, model.config.healthcare.long_term_care.annual_cost)

    def test_no_agent_no_effect(self):
        """Without a LongTermCare agent, frames are unchanged (opt-in guarantee)."""

        def run(with_ltc: bool):
            model = _flat_model(start_year=2026, end_year=2056, seed=99)
            person = _make_person(model, age=64)
            if with_ltc:
                LongTermCare(person)
            model.run()
            return model.datacollector.get_model_vars_dataframe()

        self.assertTrue(run(False).equals(run(False)))


if __name__ == "__main__":
    unittest.main()
