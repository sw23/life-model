# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The natively monthly engine.

``LifeModel.step()`` simulates one calendar month; a year is a reporting cadence (``step_year()``,
data collected at each year end). These tests pin the period plumbing, the monthly flows and their
December settlement, exact ages and the money-conservation guard that runs every month.
"""

import unittest
from itertools import pairwise
from pathlib import Path

from ..account.bank import BankAccount
from ..account.job401k import Job401kAccount
from ..checks import assert_conservation, check_conservation, conservation_records
from ..config.financial_config import FinancialConfig
from ..economy import annual_to_monthly, compound_months
from ..lifeevents import LifeEvent, LifeEvents
from ..model import LifeModel, LifeModelAgent, ModelSetupException, parse_year_month
from ..people.family import Family
from ..people.mortality import monthly_hazard
from ..people.person import Person, Spending
from ..people.types import MortalityMode
from ..work.job import Job, Salary
from .scenarios import married_homeowners, mortality_and_estate, renter_buys_home, stochastic_retiree


class TestPeriodPlumbing(unittest.TestCase):
    def test_step_advances_one_month(self):
        model = LifeModel(start_year=2026, end_year=2027)
        self.assertEqual((model.year, model.month, model.period), (2026, 1, 0))
        model.step()
        self.assertEqual((model.year, model.month, model.period), (2026, 2, 1))
        for _ in range(11):
            model.step()
        self.assertEqual((model.year, model.month, model.period), (2027, 1, 12))
        self.assertEqual(model.simulated_years, [2026])
        self.assertEqual(len(model.balance_sheets), 1)
        self.assertEqual(len(model.month_balance_sheets), 12)

    def test_start_month_gives_a_part_year(self):
        model = LifeModel(start="2026-10", end_year=2027)
        self.assertEqual((model.start_year, model.start_month, model.year, model.month), (2026, 10, 2026, 10))
        self.assertEqual(model.months_in_year(2026), 3)
        self.assertEqual(model.months_in_year(2027), 12)
        self.assertTrue(model.is_year_start)
        model.step_year()
        self.assertEqual((model.year, model.month, model.period), (2027, 1, 3))
        model.run()
        self.assertEqual(model.simulated_years, [2026, 2027])
        self.assertEqual(model.period, 15)
        self.assertFalse(model.running)

    def test_start_arguments(self):
        self.assertEqual(LifeModel(start_year=2030, start_month=4).month, 4)
        self.assertEqual(LifeModel(start="2030-04", start_year=2030).start_year, 2030)
        with self.assertRaises(ValueError):
            LifeModel(start="2030-04", start_year=2031)
        with self.assertRaises(ValueError):
            LifeModel(start="2030-04", start_month=5)
        with self.assertRaises(ValueError):
            LifeModel(start_year=2030, start_month=13)
        with self.assertRaises(ValueError):
            LifeModel(start="2030-4x")
        self.assertEqual(parse_year_month("1966-07"), (1966, 7))
        self.assertEqual(parse_year_month("1966-07-15"), (1966, 7))

    def test_year_end_flag_and_running(self):
        model = LifeModel(start_year=2026, end_year=2026)
        months = []
        while model.running:
            months.append((model.month, model.is_year_end))
            model.step()
        self.assertEqual(months[-1], (12, True))
        self.assertEqual(len(months), 12)
        model.step()  # past the end: a no-op
        self.assertEqual(model.period, 12)
        model.step_year()
        self.assertEqual(model.period, 12)

    def test_year_hooks_run_once_a_year_in_order(self):
        calls = []

        class Probe(LifeModelAgent):
            def on_year_start(self):
                calls.append(("start", self.model.year, self.model.month))

            def pre_step(self):
                calls.append(("pre", self.model.year, self.model.month))

            def on_year_end(self):
                calls.append(("end", self.model.year, self.model.month))

        model = LifeModel(start="2026-11", end_year=2027)
        Probe(model)
        model.run()
        self.assertEqual(calls[:4], [("start", 2026, 11), ("pre", 2026, 11), ("pre", 2026, 12), ("end", 2026, 12)])
        self.assertEqual(calls[4], ("start", 2027, 1))
        self.assertEqual(sum(1 for c in calls if c[0] == "pre"), 14)
        self.assertEqual(sum(1 for c in calls if c[0] == "end"), 2)

    def test_agents_record_their_creation_period(self):
        model = LifeModel(start_year=2026, end_year=2027)
        before = Spending(model, 0)
        model.step()
        model.step()
        after = Spending(model, 0)
        self.assertEqual((before.created_period, after.created_period), (0, 2))

    def test_collect_month_keeps_the_yearly_frame(self):
        model = LifeModel(start_year=2026, end_year=2027, collect="month")
        person = Person(Family(model), "Pat", 40, 65, Spending(model, base_annual=12000))
        BankAccount(person, company="Bank", balance=50000)
        model.run()
        yearly = model.get_yearly_stat_df(styled=False)
        self.assertEqual(yearly["Year"].tolist(), [2026, 2027])
        monthly = model.monthly_frame()
        self.assertEqual(len(monthly), 24)
        self.assertEqual(monthly[["Year", "Month"]].iloc[0].tolist(), [2026, 1])
        december = monthly[monthly.Month == 12].reset_index(drop=True)
        self.assertEqual(december["Bank Balance"].tolist(), yearly["Bank Balance"].tolist())
        with self.assertRaises(ModelSetupException):
            LifeModel(start_year=2026).monthly_frame()
        with self.assertRaises(ValueError):
            LifeModel(start_year=2026, collect="week")


def _economy_config(**economy) -> FinancialConfig:
    config = FinancialConfig()
    config.apply_scenario("test", {"economy": economy})
    return config


class TestMonthlyEconomy(unittest.TestCase):
    def test_fixed_annual_rates_become_monthly_rates_that_compound_back(self):
        model = LifeModel(start_year=2026, end_year=2030, config=_economy_config(equity_return=7.0, inflation=3.0))
        economy = model.economy
        monthly = economy.monthly_rate("equity_return")
        self.assertAlmostEqual(monthly, (1.07 ** (1 / 12) - 1) * 100)
        self.assertAlmostEqual(compound_months(economy.monthly_rates("equity_return", 2028)), 7.0)
        self.assertEqual(economy.equity_return(2028), 7.0)  # the annual view is exact
        self.assertAlmostEqual(annual_to_monthly(-100), -100)

    def test_path_months_override_the_year(self):
        drop = (0.8 ** (1 / 3) - 1) * 100  # -20% over three months
        config = _economy_config(
            mode="path",
            equity_return=7.0,
            paths={"equity_return": {2027: 10.0, "2026-01": drop, "2026-2": drop, "2026-03": drop}},
        )
        economy = LifeModel(start_year=2026, end_year=2028, config=config).economy
        months = economy.monthly_rates("equity_return", 2026)
        self.assertEqual(months[:3], [drop] * 3)
        self.assertAlmostEqual(months[3], annual_to_monthly(7.0))
        expected = (0.8 * 1.07 ** (9 / 12) - 1) * 100
        self.assertAlmostEqual(economy.equity_return(2026), expected)
        self.assertEqual(economy.equity_return(2027), 10.0)
        self.assertEqual(economy.monthly_rate("equity_return", 2027, 6), annual_to_monthly(10.0))

    def test_path_keys_are_validated(self):
        with self.assertRaises(ValueError):
            _economy_config(mode="path", paths={"equity_return": {"2026-13": 1.0}})
        with self.assertRaises(ValueError):
            _economy_config(mode="stochastic", stochastic={"autocorrelation": {"equity_return": 1.0}})
        config = _economy_config(mode="stochastic", stochastic={"autocorrelation": {"not_a_rate": 0.5}})
        with self.assertRaises(ValueError):
            LifeModel(start_year=2026, config=config)

    def test_stochastic_months_compound_to_the_year_and_reproduce(self):
        def draw(seed, start="2026-01"):
            model = LifeModel(start=start, end_year=2030, seed=seed, config=_economy_config(mode="stochastic"))
            return [model.economy.monthly_rates("equity_return", y) for y in range(2026, 2031)], model

        months, model = draw(42)
        self.assertEqual(months, draw(42)[0])
        self.assertNotEqual(months, draw(7)[0])
        # A model started in October draws the same first year (the economy resolves whole years).
        self.assertEqual(months[0], draw(42, start="2026-10")[0][0])
        for year, year_months in zip(range(2026, 2031), months, strict=True):
            self.assertAlmostEqual(model.economy.equity_return(year), compound_months(year_months))
        # Monthly volatility is the annual volatility over sqrt(12).
        many = LifeModel(start_year=2000, end_year=2400, seed=3, config=_economy_config(mode="stochastic"))
        draws = [r for y in range(2000, 2400) for r in many.economy.monthly_rates("equity_return", y)]
        mean = sum(draws) / len(draws)
        std = (sum((d - mean) ** 2 for d in draws) / len(draws)) ** 0.5
        self.assertAlmostEqual(std, 15.0 / 12**0.5, delta=0.15)
        self.assertAlmostEqual(mean, annual_to_monthly(7.0), delta=0.1)

    def test_autocorrelation_clusters_months(self):
        def lag1(phi):
            stochastic = {"autocorrelation": {"equity_return": phi}} if phi else {}
            model = LifeModel(
                start_year=2000, seed=11, config=_economy_config(mode="stochastic", stochastic=stochastic)
            )
            draws = [r for y in range(2000, 2300) for r in model.economy.monthly_rates("equity_return", y)]
            mean = sum(draws) / len(draws)
            num = sum((a - mean) * (b - mean) for a, b in pairwise(draws))
            return num / sum((d - mean) ** 2 for d in draws)

        self.assertLess(abs(lag1(0.0)), 0.05)
        self.assertAlmostEqual(lag1(0.5), 0.5, delta=0.05)

    def test_cumulative_inflation_has_monthly_resolution(self):
        model = LifeModel(start_year=2026, end_year=2030, config=_economy_config(inflation=3.0))
        economy = model.economy
        self.assertEqual(economy.cumulative_inflation(2028, 1), economy.cumulative_inflation(2028))
        self.assertAlmostEqual(economy.cumulative_inflation(2028, 7), 1.03**2.5)


class TestExactAges(unittest.TestCase):
    def test_born_july_1966_is_fifty_nine_and_a_half_in_january_2026(self):
        model = LifeModel(start="2025-12", end_year=2026)
        person = Person(Family(model), "Jo", None, 65, Spending(model, 0), birth="1966-07")
        self.assertEqual(person.age, 59)
        self.assertLess(person.age_years_fractional, 59.5)  # December 2025
        model.step()
        self.assertEqual((model.year, model.month), (2026, 1))
        self.assertEqual(person.age_years_fractional, 59.5)
        self.assertEqual(person.get_period_at_age(59.5), (2026, 1))
        self.assertEqual(person.age, 59)
        for _ in range(6):
            model.step()
        self.assertEqual((model.month, person.age), (7, 60))  # the 60th birthday month
        self.assertEqual((person.get_year_at_age(60), person.age_in(2026)), (2026, 60))

    def test_age_without_birth_assumes_january(self):
        model = LifeModel(start="2026-10", end_year=2027)
        person = Person(Family(model), "Al", 40, 65, Spending(model, 0))
        self.assertEqual((person.birth_year, person.birth_month, person.birth_month_assumed), (1986, 1, True))
        self.assertEqual((person.age, person.age_years_fractional), (40, 40.75))
        model.step_year()
        self.assertEqual((model.year, person.age), (2027, 41))
        self.assertEqual(person.get_year_at_age(65), 2051)

    def test_birth_and_age_must_agree(self):
        model = LifeModel(start_year=2026)
        with self.assertRaises(ValueError):
            Person(Family(model), "Al", 40, 65, Spending(model, 0), birth="1990-03")
        with self.assertRaises(ValueError):
            Person(Family(model), "Al", None, 65, Spending(model, 0))
        person = Person(Family(model), "Al", 35, 65, Spending(model, 0), birth="1990-03")
        self.assertFalse(person.birth_month_assumed)
        person.age = 50  # re-dates the birth year, keeping the month
        self.assertEqual((person.age, person.birth_year, person.birth_month), (50, 1975, 3))


TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    return FinancialConfig(config_file=TEST_CONFIG)


class TestMonthlyPayroll(unittest.TestCase):
    def _worker(self, model, base=120000, bonus=0, **salary):
        person = Person(Family(model), "Pat", 40, 70, Spending(model, 0))
        BankAccount(person, company="Bank", balance=0, interest_pct=0)
        job = Job(person, company="Co", role="Dev", salary=Salary(model, base_annual=base, bonus_pct=bonus, **salary))
        return person, job

    def test_paid_monthly_with_the_bonus_in_its_month(self):
        model = LifeModel(start_year=2026, end_year=2026)
        _person, job = self._worker(model, bonus=10)
        wages = []
        for _ in range(12):
            model.step()
            wages.append(job.stat_gross_income)
        self.assertAlmostEqual(wages[0], 10000)
        self.assertAlmostEqual(wages[2] - wages[1], 10000 + 12000)  # March: the bonus month
        self.assertEqual(job.stat_gross_income, 132000)
        months = {e.month for e in model.ledger if e.kind == "wage"}
        self.assertEqual(months, set(range(1, 13)))
        self.assertEqual({e.month for e in model.ledger if e.kind == "bonus"}, {3})

    def test_deferrals_stop_at_the_402g_limit_and_true_up_restores_the_match(self):
        for true_up, expected_match in ((True, 6000), (False, 2000)):
            with self.subTest(true_up=true_up):
                model = LifeModel(start_year=2026, end_year=2026, config=_fixture_config())
                _person, job = self._worker(model, base=120000)
                account = Job401kAccount(
                    job, pretax_contrib_pct=50, growth_pct=0, match_tiers=[(100, 5)], match_true_up=true_up
                )
                deferred = []
                for _ in range(12):
                    model.step()
                    deferred.append(job.stat_retirement_contrib)
                # $5k a month against the fixture's $20k limit: full in Jan-Apr, nothing after.
                self.assertEqual(deferred[:5], [5000, 10000, 15000, 20000, 20000])
                # Per paycheck, 5% of $10k pay is matched in the four months with deferrals ($2k);
                # the December true-up pays the formula on the year: 5% of $120k.
                self.assertAlmostEqual(job.stat_retirement_match, expected_match, places=6)
                self.assertAlmostEqual(account.pretax_balance, 20000 + expected_match, places=6)

    def test_retirement_takes_effect_after_the_birthday_month_paycheck(self):
        model = LifeModel(start_year=2026, end_year=2027)
        person = Person(Family(model), "Pat", None, 65, Spending(model, 0), birth="1961-04")
        BankAccount(person, company="Bank", balance=0, interest_pct=0)
        job = Job(person, company="Co", role="Dev", salary=Salary(model, base_annual=120000))
        model.run()
        # Pat turns 65 in April 2026: paid January through April, retired from May.
        frame = model.get_yearly_stat_df(styled=False).set_index("Year")
        self.assertAlmostEqual(frame.loc[2026, "Income"], 40000)
        self.assertEqual(frame.loc[2027, "Income"], 0)
        self.assertTrue(job.retired)


class TestMonthlyMortality(unittest.TestCase):
    def test_monthly_hazard_compounds_to_the_annual_probability(self):
        for q in (0.0, 0.01, 0.3, 1.0):
            self.assertAlmostEqual(1 - (1 - monthly_hazard(q)) ** 12, q)

    def test_a_spouse_who_dies_mid_year_is_on_that_years_joint_return(self):
        model = LifeModel(start_year=2026, end_year=2027)
        family = Family(model)
        ann = Person(family, "Ann", 50, 70, Spending(model, 0))
        bob = Person(
            family,
            "Bob",
            None,
            70,
            Spending(model, 0),
            birth="1966-07",
            mortality_mode=MortalityMode.FIXED_AGE,
            death_age=60,
        )
        ann.get_married(bob)
        BankAccount(ann, company="Bank", balance=0, interest_pct=0)
        BankAccount(bob, company="Bank", balance=0, interest_pct=0)
        Job(ann, company="A", role="Dev", salary=Salary(model, base_annual=60000))
        Job(bob, company="B", role="Dev", salary=Salary(model, base_annual=120000))
        model.run()
        self.assertTrue(bob.is_deceased)
        # Bob turned 60 (and died) in July 2026 after July's paycheck: 7 months of his pay.
        joint = model.tax_returns[2026]
        self.assertEqual(joint.filing_status, "MARRIED_FILING_JOINTLY")
        self.assertAlmostEqual(joint.wages, 60000 + 120000 * 7 / 12, places=2)
        self.assertEqual(model.tax_returns[2027].filing_status, "SINGLE")
        assert_conservation(model, monthly=True)


class TestMonthlyBenefits(unittest.TestCase):
    def test_social_security_starts_in_the_claim_month(self):
        from ..insurance.social_security import SocialSecurity
        from .scenarios import EARNINGS_HISTORY

        model = LifeModel(start_year=2026, end_year=2027)
        person = Person(Family(model), "Pat", None, 60, Spending(model, 0), birth="1964-03")
        BankAccount(person, company="Bank", balance=0, interest_pct=0)
        ss = SocialSecurity(person, claim_age=62.5, earnings_history=EARNINGS_HISTORY)
        self.assertEqual(ss.claim_period, (2026, 9))  # 62 in March 2026, 62.5 in September
        model.run()
        months = sorted((e.year, e.month) for e in model.ledger if e.source == "Social Security")
        self.assertEqual(months[0], (2026, 9))
        self.assertEqual(len(months), 4 + 12)
        frame = model.get_yearly_stat_df(styled=False).set_index("Year")
        self.assertAlmostEqual(frame.loc[2026, "SS Income"], 4 * ss.get_pia(2026), places=2)

    def test_pension_and_annuity_pay_monthly(self):
        from ..account.pension import Pension
        from ..insurance.annuity import Annuity, AnnuityType

        model = LifeModel(start_year=2026, end_year=2026)
        person = Person(Family(model), "Pat", 70, 65, Spending(model, 0))
        BankAccount(person, company="Bank", balance=0, interest_pct=0)
        Pension(person, company="Co", vesting_years=1, benefit_annual=24000)
        annuity = Annuity(person, annuity_type=AnnuityType.IMMEDIATE, balance=100000, rate_pct=4.0)
        model.run()
        pension_months = [e for e in model.ledger if e.kind == "benefit" and e.source == "Co pension"]
        self.assertEqual([e.month for e in pension_months], list(range(1, 13)))
        self.assertEqual({round(e.amount, 2) for e in pension_months}, {2000.0})
        payouts = [e for e in model.ledger if e.cause == "annuity payout"]
        self.assertEqual(len(payouts), 12)
        self.assertAlmostEqual(annuity.stat_payouts_received, 12 * annuity.monthly_payout, places=6)

    def test_flows_of_an_agent_removed_mid_year_stay_in_the_years_totals(self):
        from ..account.pension import Pension

        model = LifeModel(start_year=2026, end_year=2026)
        person = Person(
            Family(model),
            "Pat",
            None,
            65,
            Spending(model, 0),
            birth="1946-05",
            mortality_mode=MortalityMode.FIXED_AGE,
            death_age=80,
        )
        heir = Person(person.family, "Kim", 40, 65, Spending(model, 0))
        BankAccount(heir, company="Bank", balance=0, interest_pct=0)
        BankAccount(person, company="Bank", balance=0, interest_pct=0)
        Pension(person, company="Co", vesting_years=1, benefit_annual=12000)
        model.run()
        # Paid January through May (Pat turns 80 and dies in May); the pension ends with Pat.
        frame = model.get_yearly_stat_df(styled=False, extra_columns=["Pension Income"]).set_index("Year")
        self.assertAlmostEqual(frame.loc[2026, "Pension Income"], 5000, places=2)


class TestMonthlyInvestments(unittest.TestCase):
    def test_lots_held_twelve_months_are_long_term(self):
        from ..account.brokerage import BrokerageAccount

        model = LifeModel(start="2026-12", end_year=2028)
        person = Person(Family(model), "Pat", 40, 70, Spending(model, 0))
        BankAccount(person, company="Bank", balance=0, interest_pct=0)
        account = BrokerageAccount(person, company="B", balance=0, growth_pct=0)
        account.deposit_with_basis(1000, 400)  # bought December 2026
        model.step()  # -> January 2027
        self.assertEqual(account.preview_gain(1000), (0.0, 600.0))  # one month: short-term
        for _ in range(11):
            model.step()  # -> December 2027
        self.assertEqual(account.preview_gain(1000), (600.0, 0.0))  # twelve months: long-term

    def test_dividends_are_paid_quarterly(self):
        from ..account.brokerage import BrokerageAccount

        model = LifeModel(start_year=2026, end_year=2026)
        person = Person(Family(model), "Pat", 40, 70, Spending(model, 0))
        BankAccount(person, company="Bank", balance=0, interest_pct=0)
        BrokerageAccount(person, company="B", balance=100000, growth_pct=0, dividend_yield_pct=2)
        model.run()
        dividends = [(e.month, round(e.amount, 2)) for e in model.ledger if e.kind == "dividend"]
        self.assertEqual(dividends, [(3, 500.0), (6, 500.0), (9, 500.0), (12, 500.0)])

    def test_rmd_is_set_at_the_year_start_and_paid_in_twelfths(self):
        from ..account.traditional_IRA import TraditionalIRA
        from ..limits import required_min_distrib

        model = LifeModel(start_year=2026, end_year=2026)
        person = Person(Family(model), "Pat", 80, 65, Spending(model, 0))
        BankAccount(person, company="Bank", balance=0, interest_pct=0)
        ira = TraditionalIRA(person, balance=100000, growth_pct=6)
        model.run()
        payments = [e.amount for e in model.ledger if e.kind == "rmd"]
        annual = required_min_distrib(80, 100000, config=model.config)
        self.assertEqual(len(payments), 12)
        for payment in payments:
            self.assertAlmostEqual(payment, annual / 12, places=6)
        self.assertAlmostEqual(ira.stat_required_min_distrib, annual, places=6)
        self.assertEqual(len(model.event_log.of_kind("rmd")), 1)

    def test_money_grows_from_the_month_it_arrives(self):
        from ..account.brokerage import BrokerageAccount

        model = LifeModel(start_year=2026, end_year=2026)
        person = Person(Family(model), "Pat", 40, 70, Spending(model, 0))
        BankAccount(person, company="Bank", balance=0, interest_pct=0)
        account = BrokerageAccount(person, company="B", balance=0, growth_pct=12)
        for _ in range(6):
            model.step()
        account.deposit(1000)  # arrives for July
        model.run()
        self.assertAlmostEqual(account.balance, 1000 * 1.12**0.5, places=6)


class TestMonthlyBills(unittest.TestCase):
    def test_spending_rent_and_one_time_expenses_are_paid_in_their_month(self):
        from ..housing.apartment import Apartment

        model = LifeModel(start_year=2026, end_year=2026)
        person = Person(Family(model), "Pat", 40, 70, Spending(model, base_annual=12000))
        BankAccount(person, company="Bank", balance=100000, interest_pct=0)
        Apartment(person, "Flat", rent_monthly=1500, rent_growth_pct=0)
        LifeEvents(model, [LifeEvent(2026, "trip", person.spending.add_expense, 4000, month=5)])
        model.run()
        spending = {}
        for entry in model.ledger:
            if entry.kind in ("spending", "housing"):
                spending[entry.month] = spending.get(entry.month, 0.0) + entry.amount
        self.assertEqual(spending[1], 1000 + 1500)
        self.assertEqual(spending[5], 1000 + 1500 + 4000)
        self.assertEqual(set(spending), set(range(1, 13)))
        self.assertEqual(person.bank_account_balance, 100000 - 12000 - 18000 - 4000)

    def test_loan_payoff_month_follows_the_amortization_schedule(self):
        from ..debt.car_loan import CarLoan

        model = LifeModel(start="2026-04", end_year=2032)
        person = Person(Family(model), "Pat", 40, 70, Spending(model, 0))
        BankAccount(person, company="Bank", balance=100000, interest_pct=0)
        loan = CarLoan(person, original_amount=30000, term_years=5, rate_pct=6.0, name="Car")
        paid_off = None
        while model.running:
            model.step()
            if paid_off is None and loan.principal < 0.01:
                paid_off = model.period  # months paid (the step just taken was payment number `period`)
        self.assertEqual(paid_off, 60)  # 60 payments: April 2026 through March 2031
        payments = [e for e in model.ledger if e.cause == "principal: Car"]
        self.assertEqual((payments[0].year, payments[0].month), (2026, 4))
        self.assertEqual((payments[-1].year, payments[-1].month), (2031, 3))

    def test_short_months_draw_the_waterfall_and_carry_unpaid_bills(self):
        model = LifeModel(start_year=2026, end_year=2026)
        person = Person(Family(model), "Pat", 40, 70, Spending(model, base_annual=24000))
        BankAccount(person, company="Bank", balance=5000, interest_pct=0)
        model.run()
        # $2,000 a month: the bank covers January and February and half of March; the rest is
        # carried as debt from March on, with a month of interest each month.
        shortfalls = model.event_log.of_kind("shortfall_debt")
        self.assertEqual(shortfalls[0].cause, "unpaid 2026-03 bills")
        self.assertAlmostEqual(shortfalls[0].amount, 1000.0, places=2)
        assert_conservation(model, monthly=True)


class TestEventsInTheirMonth(unittest.TestCase):
    def test_an_event_fires_in_its_month(self):
        model = LifeModel(start_year=2026, end_year=2026)
        fired = []
        LifeEvents(model, [LifeEvent(2026, "july", lambda: fired.append(model.month), month=7)])
        result = model.run()
        self.assertEqual(fired, [7])
        (record,) = model.event_log.of_kind("life_event_fired")
        self.assertEqual((record.year, record.month, record.scheduled_month), (2026, 7, 7))
        self.assertEqual(result.events["month"].tolist(), [7])

    def test_a_year_only_event_fires_in_the_first_simulated_month(self):
        model = LifeModel(start="2026-10", end_year=2027)
        fired = []
        LifeEvents(
            model,
            [
                LifeEvent(2026, "start year", lambda: fired.append((model.year, model.month))),
                LifeEvent(2027, "next year", lambda: fired.append((model.year, model.month))),
            ],
        )
        model.run()
        self.assertEqual(fired, [(2026, 10), (2027, 1)])

    def test_an_event_before_the_next_month_is_past(self):
        model = LifeModel(start="2026-10", end_year=2027)
        with self.assertRaises(ValueError):
            LifeEvents(model, [LifeEvent(2026, "too early", print, month=9)])
        with self.assertRaises(ValueError):
            LifeEvent(2026, "bad month", print, month=13)


class TestMonthlyConservation(unittest.TestCase):
    """Every month's change in household net worth equals that month's ledger flows."""

    def test_scenario_households(self):
        for name, build in {
            "married_homeowners": lambda: married_homeowners(years=30),
            "stochastic_retiree": lambda: stochastic_retiree(seed=5, years=30),
            "mortality_and_estate": lambda: mortality_and_estate(years=30),
            "renter_buys_home": lambda: renter_buys_home(years=30),
        }.items():
            with self.subTest(household=name):
                model = build()
                model.run()
                assert_conservation(model, monthly=True)
                assert_conservation(model)
                self.assertFalse(check_conservation(model, monthly=True))
                months = conservation_records(model, monthly=True)
                self.assertEqual(len(months), 30 * 12)
                # The months of a year add up to the year.
                years = {r.year: r for r in conservation_records(model)}
                for year, record in years.items():
                    flow = sum(m.net_flow for m in months if m.year == year)
                    self.assertAlmostEqual(flow, record.net_flow, places=4)


if __name__ == "__main__":
    unittest.main()
