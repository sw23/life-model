# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for stock compensation (RSU grants, vesting, and disposition).

Dollar assertions read the frozen fixture config (fixtures/test_config.yaml) so they stay stable
across annual data refreshes.
"""

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount
from ..account.job401k import Job401kAccount
from ..config.financial_config import FinancialConfig
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..tax.income import IncomeType
from ..work.job import Job, Salary
from ..work.stock import StockGrant, StockPlan, VestingSchedule

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    """Fresh FinancialConfig loaded from the frozen test fixture."""
    return FinancialConfig(config_file=TEST_CONFIG)


def _person(model: LifeModel, bank_balance: float = 0.0) -> Person:
    family = Family(model)
    person = Person(family, "P", age=40, retirement_age=70, spending=Spending(model, base=0))
    BankAccount(person, "Bank", balance=bank_balance, interest_rate=0)
    return person


def _job(person: Person, base: float = 200000) -> Job:
    return Job(person, "Tech Co", "Engineer", Salary(model=person.model, base=base, yearly_increase=0))


def _advance(model: LifeModel) -> None:
    """Move the model to the next simulated year without running a full step."""
    model.year += 1


class TestVestingSchedule(unittest.TestCase):
    def test_presets_each_sum_to_one(self):
        for schedule in (
            VestingSchedule.four_year(),
            VestingSchedule.three_year(),
            VestingSchedule.front_loaded(),
            VestingSchedule.back_loaded(),
        ):
            with self.subTest(schedule=schedule):
                self.assertAlmostEqual(sum(schedule.fractions), 1.0, places=9)

    def test_fractions_must_sum_to_one(self):
        with self.assertRaises(ValueError):
            VestingSchedule([0.25, 0.25, 0.25])

    def test_fractions_must_be_non_negative(self):
        with self.assertRaises(ValueError):
            VestingSchedule([0.5, 0.75, -0.25])

    def test_empty_schedule_is_rejected(self):
        with self.assertRaises(ValueError):
            VestingSchedule([])

    def test_thirds_are_accepted_within_tolerance(self):
        schedule = VestingSchedule([1 / 3, 1 / 3, 1 / 3])
        self.assertEqual(len(schedule), 3)

    def test_fraction_for_year_is_indexed_from_the_grant(self):
        schedule = VestingSchedule.front_loaded()
        self.assertEqual(schedule.fraction_for_year(0), 0.0)  # grant year itself vests nothing
        self.assertEqual(schedule.fraction_for_year(1), 0.40)
        self.assertEqual(schedule.fraction_for_year(4), 0.10)
        self.assertEqual(schedule.fraction_for_year(5), 0.0)  # past the end

    def test_from_name_resolves_presets(self):
        self.assertEqual(VestingSchedule.from_name("four_year").fractions, (0.25, 0.25, 0.25, 0.25))
        self.assertEqual(len(VestingSchedule.from_name("even", 5)), 5)
        with self.assertRaises(ValueError):
            VestingSchedule.from_name("nonesuch")


class TestVesting(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(start_year=2020, end_year=2030, config=_fixture_config())
        self.person = _person(self.model)
        self.job = _job(self.person)

    def test_four_year_grant_vests_evenly_then_stops(self):
        plan = StockPlan(self.job, signon_value=400000, growth_rate=0)
        vested = []
        for _ in range(5):
            _advance(self.model)
            plan.pre_step()
            vested.append(plan.stat_stock_vested)
        self.assertEqual(vested, [100000, 100000, 100000, 100000, 0])

    def test_grant_year_vests_nothing(self):
        plan = StockPlan(self.job, signon_value=400000, growth_rate=0)
        plan.pre_step()  # still the grant year
        self.assertEqual(plan.stat_stock_vested, 0)

    def test_vest_is_ordinary_income_and_fica_wages(self):
        plan = StockPlan(self.job, signon_value=400000, growth_rate=0)
        _advance(self.model)
        plan.pre_step()
        self.assertEqual(self.person.taxable_income, 100000)
        self.assertEqual(self.person.fica_wages, 100000)
        totals = self.person.income.totals_by_type()
        self.assertEqual(totals[IncomeType.WAGES], 100000)

    def test_appreciation_revalues_the_vest(self):
        plan = StockPlan(self.job, signon_value=400000, growth_rate=10)
        _advance(self.model)
        plan.pre_step()
        # One year of 10% appreciation on the whole award before the first slice vests.
        self.assertAlmostEqual(plan.stat_stock_vested, 110000.0, places=6)
        _advance(self.model)
        plan.pre_step()
        self.assertAlmostEqual(plan.stat_stock_vested, 121000.0, places=6)

    def test_unvested_value_tracks_what_is_left(self):
        plan = StockPlan(self.job, signon_value=400000, growth_rate=0)
        _advance(self.model)
        plan.pre_step()
        self.assertAlmostEqual(plan.stat_stock_unvested, 300000.0, places=6)

    def test_refreshers_overlap_with_the_signon_grant(self):
        plan = StockPlan(self.job, signon_value=400000, refresher_value=200000, growth_rate=0)
        vested = []
        for _ in range(5):
            _advance(self.model)
            plan.pre_step()
            vested.append(round(plan.stat_stock_vested))
        # Sign-on vests $100k for four years; refreshers granted in years 1-4 add a $50k slice
        # each, so steady state is reached in year 5 with four concurrent refresher slices.
        self.assertEqual(vested, [100000, 150000, 200000, 250000, 200000])

    def test_refresher_growth_compounds_from_the_first_refresher(self):
        plan = StockPlan(self.job, refresher_value=100000, refresher_growth_percent=10, growth_rate=0)
        _advance(self.model)
        plan.pre_step()  # first refresher, ungrown
        self.assertAlmostEqual(plan.grants[0].value_at_grant, 100000.0, places=6)
        _advance(self.model)
        plan.pre_step()
        self.assertAlmostEqual(plan.grants[1].value_at_grant, 110000.0, places=6)

    def test_retirement_forfeits_unvested_grants(self):
        plan = StockPlan(self.job, signon_value=400000, growth_rate=0)
        _advance(self.model)
        plan.pre_step()
        self.assertEqual(plan.stat_stock_vested, 100000)

        self.job.retire()
        self.person.income.clear()
        _advance(self.model)
        plan.pre_step()

        self.assertEqual(plan.stat_stock_vested, 0)
        self.assertEqual(plan.stat_stock_unvested, 0)
        self.assertEqual(self.person.taxable_income, 0)


class TestStockPlanWiring(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(start_year=2020, end_year=2030, config=_fixture_config())
        self.person = _person(self.model)
        self.job = _job(self.person)

    def test_plan_attaches_to_the_job(self):
        plan = StockPlan(self.job, signon_value=100000)
        self.assertIs(self.job.stock_plan, plan)

    def test_job_without_a_plan_has_none(self):
        self.assertIsNone(self.job.stock_plan)

    def test_unknown_disposition_is_rejected(self):
        with self.assertRaises(ValueError):
            StockPlan(self.job, signon_value=100000, disposition="donate")

    def test_schedule_defaults_to_the_configured_preset(self):
        plan = StockPlan(self.job, signon_value=100000)
        self.assertEqual(plan.schedule.fractions, (0.25, 0.25, 0.25, 0.25))

    def test_signon_schedule_defaults_to_the_refresher_schedule(self):
        schedule = VestingSchedule.three_year()
        plan = StockPlan(self.job, signon_value=100000, schedule=schedule)
        self.assertIs(plan.signon_schedule, schedule)

    def test_vest_income_is_excluded_from_401k_eligible_compensation(self):
        # Contributions are computed off base salary alone, so adding equity changes nothing.
        without_equity = self._contribution_with_plan(equity=0)
        with_equity = self._contribution_with_plan(equity=400000)
        self.assertEqual(with_equity, without_equity)

    def _contribution_with_plan(self, equity: float) -> float:
        model = LifeModel(start_year=2020, end_year=2030, config=_fixture_config())
        person = _person(model)
        job = _job(person)
        Job401kAccount(job=job, pretax_balance=0, average_growth=0, pretax_contrib_percent=10)
        if equity > 0:
            plan = StockPlan(job, signon_value=equity, growth_rate=0)
        else:
            plan = None
        model.year += 1
        job.pre_step()
        if plan is not None:
            plan.pre_step()
        return job.stat_retirement_contrib


class TestDisposition(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(start_year=2020, end_year=2030, config=_fixture_config())
        self.person = _person(self.model)
        self.job = _job(self.person)

    def test_sell_credits_the_bank_account(self):
        plan = StockPlan(self.job, signon_value=400000, growth_rate=0, disposition="sell")
        _advance(self.model)
        plan.pre_step()
        self.assertEqual(self.person.bank_account_balance, 100000)

    def test_hold_deposits_into_the_brokerage_account_at_vest_basis(self):
        account = BrokerageAccount(self.person, "B", balance=0, growth_rate=0)
        plan = StockPlan(self.job, signon_value=400000, growth_rate=0, disposition="hold")
        _advance(self.model)
        plan.pre_step()

        self.assertEqual(self.person.bank_account_balance, 0)
        self.assertEqual(account.balance, 100000)
        # Basis is fair market value at vest, so selling immediately realizes no gain.
        self.assertEqual(account.cost_basis, 100000)
        self.assertEqual(account.unrealized_gain, 0)

    def test_held_shares_are_long_term_once_a_year_passes(self):
        account = BrokerageAccount(self.person, "B", balance=0, growth_rate=0)
        plan = StockPlan(self.job, signon_value=400000, growth_rate=0, disposition="hold")
        _advance(self.model)
        plan.pre_step()

        _advance(self.model)
        account.balance += 20000
        account.lots[0].value += 20000
        _, long_term, short_term = account.sell(120000)
        self.assertEqual(long_term, 20000)
        self.assertEqual(short_term, 0)

    def test_hold_falls_back_to_cash_without_a_brokerage_account(self):
        plan = StockPlan(self.job, signon_value=400000, growth_rate=0, disposition="hold")
        _advance(self.model)
        plan.pre_step()
        self.assertEqual(self.person.bank_account_balance, 100000)

    def test_selling_and_holding_recognize_the_same_vest_income(self):
        sell_plan = StockPlan(self.job, signon_value=400000, growth_rate=0, disposition="sell")
        _advance(self.model)
        sell_plan.pre_step()
        sell_income = self.person.taxable_income

        model = LifeModel(start_year=2020, end_year=2030, config=_fixture_config())
        person = _person(model)
        BrokerageAccount(person, "B", balance=0, growth_rate=0)
        hold_plan = StockPlan(_job(person), signon_value=400000, growth_rate=0, disposition="hold")
        model.year += 1
        hold_plan.pre_step()

        self.assertEqual(person.taxable_income, sell_income)


class TestStockGrant(unittest.TestCase):
    def test_fraction_vesting_in_is_relative_to_the_grant_year(self):
        grant = StockGrant(value_at_grant=100000, grant_year=2020, schedule=VestingSchedule.four_year())
        self.assertEqual(grant.fraction_vesting_in(2020), 0.0)
        self.assertEqual(grant.fraction_vesting_in(2021), 0.25)
        self.assertEqual(grant.fraction_vesting_in(2025), 0.0)

    def test_unvested_fraction_tracks_vesting(self):
        grant = StockGrant(value_at_grant=100000, grant_year=2020, schedule=VestingSchedule.four_year())
        self.assertEqual(grant.unvested_fraction, 1.0)
        grant.vested_fraction = 0.75
        self.assertAlmostEqual(grant.unvested_fraction, 0.25, places=9)


if __name__ == "__main__":
    unittest.main()
