# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Plan 32 acceptance tests: the monthly engine against its acceptance criteria.

* A household started in October books three months of salary, rent and growth in its first year,
  and its first tax return matches a hand computation of a three-month W-2.
* Under a fixed economy, year-end net worth stays within the recorded tolerances of the pre-plan
  annual engine (``docs/rebaseline-plan-32.md`` explains every source of the difference).
* Sequence-of-returns risk is visible: a crash early in the year hurts more than the same crash late.
* A person born in July 1966 reaches 59½ in January 2026.
* Money is conserved every month for 50 years under a stochastic economy on every example spec.
"""

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount
from ..account.traditional_IRA import TraditionalIRA
from ..checks import assert_conservation, conservation_records
from ..config.financial_config import FinancialConfig
from ..housing.apartment import Apartment
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..spec import EXAMPLES, build_model, load_example, to_data
from ..spec.builder import SpecValidationError
from ..spec.schema import HouseholdSpec
from ..work.job import Job, Salary
from . import scenarios

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


class TestOctoberStart(unittest.TestCase):
    """A household whose simulation starts in October 2020 (the frozen fixture's tax year)."""

    def setUp(self):
        self.model = LifeModel(start="2020-10", end_year=2021, config=FinancialConfig(config_file=TEST_CONFIG))
        self.person = Person(Family(self.model), "Oct", 40, 70, Spending(self.model, base_annual=0))
        self.bank = BankAccount(self.person, company="Bank", balance=50000, interest_pct=0)
        self.brokerage = BrokerageAccount(self.person, company="Broker", balance=100000, growth_pct=12)
        Apartment(self.person, "Flat", rent_monthly=2000, rent_growth_pct=0)
        self.job = Job(self.person, company="Co", role="Dev", salary=Salary(self.model, base_annual=120000))
        self.model.step_year()

    def test_three_months_of_salary_rent_and_growth(self):
        frame = self.model.get_yearly_stat_df(styled=False).set_index("Year")
        self.assertEqual(frame.index.tolist(), [2020])
        self.assertEqual(frame.loc[2020, "Income"], 30000)  # October, November, December
        self.assertEqual(frame.loc[2020, "Housing"], 6000)
        self.assertAlmostEqual(self.brokerage.balance, 100000 * 1.12 ** (3 / 12), places=6)
        months = sorted({(e.year, e.month) for e in self.model.ledger})
        self.assertEqual(months, [(2020, 10), (2020, 11), (2020, 12)])

    def test_first_return_is_a_three_month_w2(self):
        tax_return = self.model.tax_returns[2020]
        # Hand computation on the fixture's 2020 parameters: $30,000 of wages, $10,000 standard
        # deduction, 10% on the first $40,000 of taxable income, a flat 5% state rate on income after
        # the federal deduction, 6.2% Social Security and 1.45% Medicare on the wages.
        wages = 3 * 120000 / 12
        taxable = wages - 10000
        self.assertEqual(tax_return.wages, wages)
        self.assertEqual(tax_return.taxable_income, taxable)
        self.assertAlmostEqual(tax_return.federal_tax, 0.10 * taxable, places=2)
        self.assertAlmostEqual(tax_return.state_tax, 0.05 * taxable, places=2)
        self.assertAlmostEqual(tax_return.social_security_tax, 0.062 * wages, places=2)
        self.assertAlmostEqual(tax_return.medicare_tax, 0.0145 * wages, places=2)
        total = 0.10 * taxable + 0.05 * taxable + 0.062 * wages + 0.0145 * wages
        self.assertAlmostEqual(tax_return.total_tax, total, places=2)
        # Cash: three paychecks in, three rents and the year's taxes out.
        self.assertAlmostEqual(self.bank.balance, 50000 + wages - 6000 - total, places=2)
        assert_conservation(self.model, monthly=True)


def _shift_retirement(model: LifeModel) -> LifeModel:
    """Retire in December of the year the retirement age is reached: the annual engine paid the whole
    year in which a person reached their retirement age, so this aligns the paid months and leaves
    the comparison to measure the monthly flows themselves."""
    for agent in model.agents:
        if isinstance(agent, Person) and not agent.retirement_triggered:
            agent.retirement_age += 11 / 12
    return model


def _spec_fixed(name: str) -> LifeModel:
    data = to_data(load_example(name))
    data.pop("economy", None)
    for person in data["people"]:
        person["mortality"] = "immortal"
        person.pop("death_age", None)
        person.pop("birth", None)  # the annual engine's values are for the age-only example
    data["meta"]["end_year"] = data["meta"]["start_year"] + 19
    return build_model(HouseholdSpec.model_validate(data))


#: Year-end net worth from the pre-plan annual engine (fourth-wave at f66307f, with Plans 29 and 30) under
#: the fixed economy, in years 1, 5, 10 and 20 (``docs/rebaseline-plan-32.md``, "Fixed-economy tolerance").
ANNUAL_ENGINE_NET_WORTH = {
    "spec_single_renter": {2026: 81906.82, 2030: 182710.97, 2035: 426597.66, 2045: 1232550.88},
    "spec_married_homeowners": {2026: 546979.78, 2030: 941760.71, 2035: 1407704.97, 2045: 2499441.99},
    "spec_retiree_couple": {2026: 1491226.71, 2030: 1731972.56, 2035: 2033657.23, 2045: 2553160.72},
    "scn_married_homeowners": {2026: 1066243.59, 2030: 1790192.55, 2035: 2951423.5, 2045: 6044398.45},
    "scn_stochastic_retiree": {2026: 1485951.2, 2030: 1775419.5, 2035: 2207432.14, 2045: 3139082.6},
    "scn_mortality_and_estate": {2026: 4973286.26, 2030: 6434775.25, 2035: 9109242.07, 2045: 16239174.12},
}

#: Allowed relative difference (percent) by horizon: year 1, through year 10, through year 20.
TOLERANCE_PERCENT = {2026: 1.0, 2030: 2.5, 2035: 2.5, 2045: 3.0}


class TestFixedEconomyMatchesTheAnnualEngine(unittest.TestCase):
    def _models(self):
        fixed = FinancialConfig  # the scenarios' stochastic retiree is compared under a fixed economy
        original = scenarios._stochastic_config
        scenarios._stochastic_config = fixed
        try:
            yield "spec_single_renter", _spec_fixed("single_renter")
            yield "spec_married_homeowners", _spec_fixed("married_homeowners")
            yield "spec_retiree_couple", _spec_fixed("retiree_couple")
            yield "scn_married_homeowners", scenarios.married_homeowners(years=20)
            yield "scn_stochastic_retiree", scenarios.stochastic_retiree(seed=11, years=20)
            yield "scn_mortality_and_estate", scenarios.mortality_and_estate(years=20)
        finally:
            scenarios._stochastic_config = original

    def test_year_end_net_worth_within_tolerance(self):
        for name, model in self._models():
            _shift_retirement(model).run()
            frame = model.get_yearly_stat_df(styled=False, extra_columns=["Net Worth"]).set_index("Year")
            for year, annual in ANNUAL_ENGINE_NET_WORTH[name].items():
                with self.subTest(household=name, year=year):
                    difference = abs(frame.loc[year, "Net Worth"] - annual) / annual * 100
                    self.assertLess(difference, TOLERANCE_PERCENT[year])


class TestSequenceOfReturns(unittest.TestCase):
    """A retiree drawing $5k a month from $1M: a -20% quarter in January-March hurts more than the
    same quarter in October-December. The annual engine saw only the year's return, which is the same
    for both paths, so it gave both retirees the same result (docs/rebaseline-plan-32.md)."""

    @staticmethod
    def _retiree(crash_months) -> LifeModel:
        drop = (0.8 ** (1 / 3) - 1) * 100  # -20% over three months
        paths = {"equity_return": {2026: 0.0, **{f"2026-{month:02d}": drop for month in crash_months}}}
        config = FinancialConfig()
        config.apply_scenario("crash", {"economy": {"mode": "path", "equity_return": 0.0, "paths": paths}})
        model = LifeModel(start_year=2026, end_year=2026, config=config)
        person = Person(Family(model), "Ret", 70, 65, Spending(model, base_annual=60000))
        BankAccount(person, company="Bank", balance=0, interest_pct=0)
        BrokerageAccount(person, company="Broker", balance=1_000_000)
        return model

    def test_an_early_crash_ends_the_year_lower(self):
        early, late = self._retiree((1, 2, 3)), self._retiree((10, 11, 12))
        for model in (early, late):
            model.run()
            assert_conservation(model, monthly=True)
        self.assertEqual(early.economy.equity_return(2026), late.economy.equity_return(2026))  # -20% both
        early_worth = conservation_records(early)[-1].closing_net_worth
        late_worth = conservation_records(late)[-1].closing_net_worth
        # Withdrawals made before the crash escape it; after it they sell more of a cheaper account:
        # the late crash leaves about 20% of the ~$45k sold in the nine months before it unhurt.
        self.assertLess(early_worth, late_worth - 5000)


class TestFiftyNineAndAHalf(unittest.TestCase):
    def test_born_july_1966_reaches_fifty_nine_and_a_half_in_january_2026(self):
        model = LifeModel(start="2025-12", end_year=2026)
        person = Person(Family(model), "Jo", None, 70, Spending(model, 0), birth="1966-07")
        BankAccount(person, company="Bank", balance=5000, interest_pct=0)  # pays the year's taxes
        ira = TraditionalIRA(person, balance=10000, growth_pct=0)
        self.assertEqual(person.get_period_at_age(59.5), (2026, 1))
        self.assertFalse(ira.is_useable)  # December 2025: 59 and 5 months
        person.withdraw_from_traditional_iras(1000)
        self.assertAlmostEqual(person.income.penalties, 100)  # 10% early-withdrawal tax
        model.step()  # December 2025 runs (its return settles the penalty) -> January 2026
        self.assertAlmostEqual(model.tax_returns[2025].total_penalties, 100)
        self.assertTrue(ira.is_useable)
        person.withdraw_from_traditional_iras(1000)
        self.assertEqual(person.income.penalties, 0)  # no penalty from 59½


class TestMonthlyConservationOnEveryExample(unittest.TestCase):
    def test_fifty_years_stochastic_every_example(self):
        checked = 0
        for name in EXAMPLES:
            data = to_data(load_example(name))
            data["economy"] = {"mode": "stochastic"}
            data["meta"]["end_year"] = data["meta"]["start_year"] + 49
            for seed in (1, 2):
                data["meta"]["seed"] = seed
                try:
                    model = build_model(HouseholdSpec.model_validate(data))
                except SpecValidationError:
                    continue  # uses a field the engine does not support yet (self-employment, Plan 31)
                with self.subTest(example=name, seed=seed):
                    model.run()
                    self.assertEqual(len(model.month_balance_sheets), 50 * 12)
                    assert_conservation(model, monthly=True)
                    checked += 1
        self.assertGreaterEqual(checked, 6)


if __name__ == "__main__":
    unittest.main()
