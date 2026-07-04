# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for mortality wiring, death orchestration, and estate transfer."""

import unittest

from ..account.bank import BankAccount
from ..account.traditional_IRA import TraditionalIRA
from ..housing.home import Home, HomeExpenses, Mortgage
from ..insurance.life_insurance import LifeInsurance, LifeInsuranceType
from ..model import LifeModel
from ..people.family import Family
from ..people.person import GenderAtBirth, MortalityMode, Person, Spending
from ..tax.federal import FilingStatus
from ..work.job import Job, Salary


def _make_home(person, purchase_price=400000, loan_amount=300000, rate=4.5):
    mortgage = Mortgage(loan_amount=loan_amount, start_date=2026, length_years=30, yearly_interest_rate=rate)
    expenses = HomeExpenses(
        model=person.model,
        property_tax_percent=1.0,
        home_insurance_percent=0.0,
        maintenance_amount=0,
        maintenance_increase=0.0,
        improvement_amount=0,
        improvement_increase=0.0,
        hoa_amount=0,
        hoa_increase=0.0,
    )
    return Home(
        person=person,
        name="Test House",
        purchase_price=purchase_price,
        value_yearly_increase=0.0,
        down_payment=100000,
        mortgage=mortgage,
        expenses=expenses,
    )


class TestMortalityModes(unittest.TestCase):
    def test_immortal_is_default_and_never_dies(self):
        model = LifeModel(start_year=2026, end_year=2076)
        family = Family(model)
        person = Person(family, "Ancient", age=80, retirement_age=100, spending=Spending(model, 0))
        BankAccount(person, "Bank", balance=1000, interest_rate=0)
        model.run()
        self.assertFalse(person.is_deceased)
        self.assertEqual(person.mortality_mode, MortalityMode.IMMORTAL)

    def test_fixed_age_death(self):
        model = LifeModel(start_year=2026, end_year=2036)
        family = Family(model)
        person = Person(
            family,
            "Mort",
            age=60,
            retirement_age=100,
            spending=Spending(model, 0),
            mortality_mode=MortalityMode.FIXED_AGE,
            death_age=65,
        )
        BankAccount(person, "Bank", balance=10000, interest_rate=0)
        Job(person, "Co", "Dev", Salary(model=model, base=50000))
        model.run()

        self.assertTrue(person.is_deceased)
        self.assertEqual(person.age, 65)  # aging stops at death
        # No income earned once dead: earning years are ages 61..64 (2026..2029), then zero.
        df = model.datacollector.get_model_vars_dataframe()
        income_by_year = dict(zip(df["Year"], df["Income"]))
        self.assertEqual(income_by_year[2029], 50000)
        self.assertEqual(income_by_year[2030], 0)  # died at start of 2030 (age 65)
        self.assertEqual(income_by_year[2035], 0)

    def test_stochastic_is_reproducible(self):
        def run_once():
            model = LifeModel(start_year=2026, end_year=2116, seed=1234)
            family = Family(model)
            person = Person(
                family,
                "Rand",
                age=50,
                retirement_age=100,
                spending=Spending(model, 0),
                gender=GenderAtBirth.MALE,
                mortality_mode=MortalityMode.STOCHASTIC,
            )
            BankAccount(person, "Bank", balance=1000, interest_rate=0)
            model.run()
            df = model.datacollector.get_model_vars_dataframe()
            return person.age, person.is_deceased, list(df["Year"])

        a = run_once()
        b = run_once()
        self.assertEqual(a, b)
        # Over a 90-year horizon from age 50, a stochastic person is essentially certain to die.
        self.assertTrue(a[1])


class TestEstateTransferToSpouse(unittest.TestCase):
    def test_spouse_inherits_bank_and_death_benefit(self):
        model = LifeModel(start_year=2026, end_year=2030)
        family = Family(model)
        breadwinner = Person(
            family,
            "Bread",
            age=74,
            retirement_age=100,
            spending=Spending(model, 0),
            mortality_mode=MortalityMode.FIXED_AGE,
            death_age=75,
        )
        spouse = Person(family, "Spouse", age=74, retirement_age=100, spending=Spending(model, 0))
        breadwinner.get_married(spouse)
        BankAccount(breadwinner, "B1", balance=20000, interest_rate=0)
        BankAccount(spouse, "B2", balance=5000, interest_rate=0)
        LifeInsurance(
            person=breadwinner,
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=0,
            term_years=30,
        )
        model.run()

        self.assertTrue(breadwinner.is_deceased)
        self.assertFalse(spouse.is_deceased)
        self.assertNotIn(breadwinner, family.members)
        # Spouse now holds both banks plus the death benefit: 5000 + 20000 + 500000.
        self.assertAlmostEqual(spouse.bank_account_balance, 525000, delta=1.0)
        self.assertIsNone(spouse.spouse)

        # Death benefits stat is recorded in the death year (2026).
        df = model.datacollector.get_model_vars_dataframe()
        death_benefits = dict(zip(df["Year"], df["Death Benefits"]))
        self.assertEqual(death_benefits[2026], 500000)

    def test_filing_status_switches_to_single_after_death(self):
        model = LifeModel(start_year=2026, end_year=2030)
        family = Family(model)
        breadwinner = Person(
            family,
            "Bread",
            age=74,
            retirement_age=100,
            spending=Spending(model, 0),
            mortality_mode=MortalityMode.FIXED_AGE,
            death_age=75,
        )
        spouse = Person(family, "Spouse", age=74, retirement_age=100, spending=Spending(model, 0))
        breadwinner.get_married(spouse)
        BankAccount(spouse, "B2", balance=5000, interest_rate=0)
        model.run()

        # Files jointly in the death year, single thereafter.
        self.assertEqual(spouse.filing_status, FilingStatus.SINGLE)

    def test_mortgage_still_serviced_after_owner_dies(self):
        model = LifeModel(start_year=2026, end_year=2031)
        family = Family(model)
        breadwinner = Person(
            family,
            "Bread",
            age=74,
            retirement_age=100,
            spending=Spending(model, 0),
            mortality_mode=MortalityMode.FIXED_AGE,
            death_age=75,
        )
        spouse = Person(family, "Spouse", age=74, retirement_age=100, spending=Spending(model, 0))
        breadwinner.get_married(spouse)
        BankAccount(spouse, "B2", balance=500000, interest_rate=0)
        home = _make_home(breadwinner)
        principal_at_start = home.mortgage.principal
        model.run()

        # Home transferred to the surviving spouse and mortgage kept amortizing.
        self.assertIn(home, spouse.homes)
        self.assertNotIn(home, breadwinner.homes)
        self.assertLess(home.mortgage.principal, principal_at_start)


class TestEstateTransferNonSpouse(unittest.TestCase):
    def test_estate_flows_to_child_when_both_parents_die(self):
        model = LifeModel(start_year=2026, end_year=2030)
        family = Family(model)
        dad = Person(
            family,
            "Dad",
            age=79,
            retirement_age=100,
            spending=Spending(model, 0),
            mortality_mode=MortalityMode.FIXED_AGE,
            death_age=80,
        )
        mom = Person(
            family,
            "Mom",
            age=79,
            retirement_age=100,
            spending=Spending(model, 0),
            mortality_mode=MortalityMode.FIXED_AGE,
            death_age=80,
        )
        dad.get_married(mom)
        child = Person(family, "Kid", age=40, retirement_age=100, spending=Spending(model, 0))
        BankAccount(dad, "D", balance=30000, interest_rate=0)
        BankAccount(mom, "M", balance=20000, interest_rate=0)
        BankAccount(child, "C", balance=1000, interest_rate=0)
        model.run()

        self.assertTrue(dad.is_deceased)
        self.assertTrue(mom.is_deceased)
        self.assertFalse(child.is_deceased)
        # Child ends up with everyone's cash: 1000 + 30000 + 20000.
        self.assertAlmostEqual(child.bank_account_balance, 51000, delta=1.0)

    def test_nonspouse_pretax_inheritance_is_taxed(self):
        model = LifeModel(start_year=2026, end_year=2027)
        family = Family(model)
        parent = Person(
            family,
            "Parent",
            age=79,
            retirement_age=50,
            spending=Spending(model, 0),
            mortality_mode=MortalityMode.FIXED_AGE,
            death_age=80,
        )
        child = Person(family, "Kid", age=40, retirement_age=100, spending=Spending(model, 0))
        BankAccount(child, "C", balance=1000, interest_rate=0)
        TraditionalIRA(person=parent, balance=100000, growth_rate=0)
        model.run()

        self.assertTrue(parent.is_deceased)
        # The inherited pre-tax balance was distributed as a lump sum and taxed to the child, so
        # the child's cash gain is less than the full $100k.
        df = model.datacollector.get_model_vars_dataframe()
        taxes = dict(zip(df["Year"], df["Taxes"]))
        self.assertGreater(taxes[2026], 0)
        self.assertLess(child.bank_account_balance, 101000)


class TestDeathConservation(unittest.TestCase):
    def test_money_conserved_through_spousal_death(self):
        model = LifeModel(start_year=2026, end_year=2027)
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
        BankAccount(breadwinner, "B1", balance=40000, interest_rate=0)
        BankAccount(spouse, "B2", balance=10000, interest_rate=0)
        model.run()

        # No income, no spending, no interest: assets are exactly conserved into the survivor.
        self.assertAlmostEqual(spouse.bank_account_balance, 50000, delta=1.0)


if __name__ == "__main__":
    unittest.main()
