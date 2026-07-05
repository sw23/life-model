# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Scenario-level integration tests with money-conservation assertions.

These are the primary regression net for the simulation as a whole. Each canonical scenario is
run year by year and checked with a single reusable invariant: with all account growth disabled,
the change in *liquid assets* (bank balances + 401k balances) over a year must equal that year's
external cash flows — gross income plus employer match plus Social Security, less spending,
housing and taxes — to within a dollar.

Home market value and mortgage debt are deliberately excluded from "liquid assets": a mortgage
principal payment leaves the bank and reduces the (untracked) mortgage balance, so it correctly
registers as a housing cash outflow that the invariant already accounts for.
"""

import unittest

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount
from ..account.job401k import Job401kAccount
from ..dependents.child import Child
from ..housing.apartment import Apartment
from ..housing.home import Home, HomeExpenses, Mortgage
from ..insurance.social_security import Income, SocialSecurity
from ..model import LifeModel
from ..people.family import Family
from ..people.person import MortalityMode, Person, Spending
from ..work.job import Job, Salary


def _no_growth_expenses(model):
    """Home expenses with property tax/insurance/maintenance so housing cash flow is deterministic."""
    return HomeExpenses(
        model=model,
        property_tax_percent=1.0,
        home_insurance_percent=0.5,
        maintenance_amount=1000.0,
        maintenance_increase=0.0,
        improvement_amount=0.0,
        improvement_increase=0.0,
        hoa_amount=0.0,
        hoa_increase=0.0,
    )


def _liquid_assets(persons) -> float:
    """Bank balances plus 401k balances across the given persons."""
    total = 0.0
    for person in persons:
        total += person.bank_account_balance
        total += sum(account.balance for account in person.all_retirement_accounts)
    return total


def assert_liquid_conserved(test: unittest.TestCase, model: LifeModel, persons) -> None:
    """Step ``model`` to completion, asserting liquid-asset conservation every year.

    Assumes every account's growth has been disabled (bank ``interest_rate=0``, 401k
    ``average_growth=0``), so the only balance movements are the external cash flows the
    DataCollector reports.
    """
    for _ in model.get_year_range():
        before = _liquid_assets(persons)
        model.step()
        row = model.datacollector.get_model_vars_dataframe().iloc[-1]
        after = _liquid_assets(persons)
        expected = (
            row["Income"] + row["401k Match"] + row["SS Income"] - row["Spending"] - row["Housing"] - row["Taxes"]
        )
        test.assertAlmostEqual(after - before, expected, delta=1.0, msg=f"conservation broke in {model.year}")


class TestSingleRenterScenario(unittest.TestCase):
    def test_single_renter_conserves_cash(self):
        model = LifeModel(start_year=2020, end_year=2025)
        person = Person(Family(model), "Riley", age=30, retirement_age=70, spending=Spending(model, base=25000))
        BankAccount(person, "Bank", balance=50000, interest_rate=0)
        Apartment(person, "Downtown", monthly_rent=1500, yearly_increase=0)
        Job(person, "Co", "Analyst", Salary(model=model, base=70000))
        assert_liquid_conserved(self, model, [person])


class TestSingleHomeownerScenario(unittest.TestCase):
    def test_single_homeowner_conserves_cash(self):
        model = LifeModel(start_year=2020, end_year=2025)
        person = Person(Family(model), "Sam", age=40, retirement_age=70, spending=Spending(model, base=20000))
        BankAccount(person, "Bank", balance=100000, interest_rate=0)
        mortgage = Mortgage(loan_amount=300000, start_date=2018, length_years=30, yearly_interest_rate=5.0)
        Home(
            person=person,
            name="House",
            purchase_price=375000,
            value_yearly_increase=0.0,
            down_payment=75000,
            mortgage=mortgage,
            expenses=_no_growth_expenses(model),
        )
        Job(person, "Co", "Engineer", Salary(model=model, base=120000))
        assert_liquid_conserved(self, model, [person])


class TestMarriedFamilyScenario(unittest.TestCase):
    def test_mfj_dual_earner_with_mortgage_and_kids_conserves_cash(self):
        model = LifeModel(start_year=2020, end_year=2025)
        family = Family(model)
        a = Person(family, "Ada", age=38, retirement_age=70, spending=Spending(model, base=30000))
        b = Person(family, "Ben", age=39, retirement_age=70, spending=Spending(model, base=10000))
        a.get_married(b)
        BankAccount(a, "Bank A", balance=120000, interest_rate=0)
        BankAccount(b, "Bank B", balance=30000, interest_rate=0)
        mortgage = Mortgage(loan_amount=400000, start_date=2019, length_years=30, yearly_interest_rate=4.5)
        Home(
            person=a,
            name="Family House",
            purchase_price=500000,
            value_yearly_increase=0.0,
            down_payment=100000,
            mortgage=mortgage,
            expenses=_no_growth_expenses(model),
        )
        Job(a, "Co", "Dev", Salary(model=model, base=130000))
        Job(b, "Shop", "Manager", Salary(model=model, base=80000))
        Child(a, "Kid One", birth_year=2016)
        Child(a, "Kid Two", birth_year=2019)
        assert_liquid_conserved(self, model, [a, b])


class TestRetireeScenario(unittest.TestCase):
    def test_retiree_drawing_401k_and_social_security_conserves_cash(self):
        model = LifeModel(start_year=2026, end_year=2030)
        person = Person(Family(model), "Pat", age=70, retirement_age=65, spending=Spending(model, base=40000))
        BankAccount(person, "Bank", balance=5000, interest_rate=0)
        job = Job(person, "Old Co", "Retiree", Salary(model=model, base=0))
        job.retired = True
        Job401kAccount(job=job, pretax_balance=800000, average_growth=0)
        income_history = [Income(year, 60000) for year in range(1985, 2020)]
        SocialSecurity(person=person, withdrawal_start_age=67, income_history=income_history)
        assert_liquid_conserved(self, model, [person])


class TestDeathOfSpouseScenario(unittest.TestCase):
    def test_assets_conserved_through_spousal_death(self):
        model = LifeModel(start_year=2026, end_year=2028)
        family = Family(model)
        breadwinner = Person(
            family,
            "Bread",
            age=74,
            retirement_age=50,
            spending=Spending(model, 0),
            mortality_mode=MortalityMode.FIXED_AGE,
            death_age=75,
        )
        spouse = Person(family, "Spouse", age=74, retirement_age=50, spending=Spending(model, 0))
        breadwinner.get_married(spouse)
        BankAccount(breadwinner, "B1", balance=60000, interest_rate=0)
        BankAccount(spouse, "B2", balance=15000, interest_rate=0)

        total_before = _liquid_assets([breadwinner, spouse])
        model.run()
        # No income or spending: assets are conserved, ending fully with the survivor.
        self.assertAlmostEqual(_liquid_assets([breadwinner, spouse]), total_before, delta=1.0)
        self.assertAlmostEqual(spouse.bank_account_balance, 75000, delta=1.0)


class TestRecessionScenario(unittest.TestCase):
    def _invested_end_balance(self, scenario):
        model = LifeModel(start_year=2026, end_year=2029, scenario=scenario)
        person = Person(Family(model), "Ivy", age=40, retirement_age=70, spending=Spending(model, base=0))
        BankAccount(person, "Bank", balance=0, interest_rate=0)
        # Economy-driven brokerage (no growth override) so the recession's negative equity path applies.
        account = BrokerageAccount(person, "Broker", balance=500000)
        model.run()
        return account.balance

    def test_recession_reduces_invested_balance_versus_baseline(self):
        baseline = self._invested_end_balance(scenario=None)
        recession = self._invested_end_balance(scenario="recession")
        # The recession's negative equity path leaves the invested balance below the baseline.
        self.assertLess(recession, baseline)


if __name__ == "__main__":
    unittest.main()
