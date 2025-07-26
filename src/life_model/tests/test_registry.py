# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..account.bank import BankAccount
from ..work.job import Job, Salary
from ..housing.home import Home, HomeExpenses, Mortgage
from ..housing.apartment import Apartment
from ..insurance.life_insurance import LifeInsurance, LifeInsuranceType


class TestRegistry(unittest.TestCase):
    """Test the registry pattern implementation"""

    def setUp(self):
        self.model = LifeModel()
        self.family = Family(self.model)
        self.spending = Spending(
            model=self.model,
            base=12000,  # yearly base spending
            yearly_increase=2.0  # 2% yearly increase
        )
        self.person = Person(
            family=self.family,
            name="Test Person",
            age=30,
            retirement_age=65,
            spending=self.spending
        )

    def test_bank_account_registration(self):
        """Test that bank accounts are registered correctly"""
        # Initially no bank accounts
        self.assertEqual(len(self.person.bank_accounts), 0)

        # Create a bank account
        bank = BankAccount(
            owner=self.person,
            company="Test Bank",
            type="Checking",
            balance=10000,
            interest_rate=0.1
        )

        # Check that the bank account was registered
        self.assertEqual(len(self.person.bank_accounts), 1)
        self.assertIn(bank, self.person.bank_accounts)

        # Create another bank account
        bank2 = BankAccount(
            owner=self.person,
            company="Test Bank 2",
            type="Savings",
            balance=5000,
            interest_rate=0.5
        )

        # Check that both are registered
        self.assertEqual(len(self.person.bank_accounts), 2)
        self.assertIn(bank, self.person.bank_accounts)
        self.assertIn(bank2, self.person.bank_accounts)

    def test_job_registration(self):
        """Test that jobs are registered correctly"""
        # Initially no jobs
        self.assertEqual(len(self.person.jobs), 0)

        # Create a job
        salary = Salary(
            model=self.model,
            base=100000,
            yearly_increase=3.0
        )
        job = Job(
            owner=self.person,
            company="Tech Corp",
            role="Software Engineer",
            salary=salary
        )

        # Check that the job was registered
        self.assertEqual(len(self.person.jobs), 1)
        self.assertIn(job, self.person.jobs)

    def test_home_registration(self):
        """Test that homes are registered correctly"""
        # Initially no homes
        self.assertEqual(len(self.person.homes), 0)

        # Create home components
        mortgage = Mortgage(
            loan_amount=300000,
            start_date=2023,
            length_years=30,
            yearly_interest_rate=4.5
        )

        expenses = HomeExpenses(
            model=self.model,
            property_tax_percent=1.5,
            home_insurance_percent=0.5,
            maintenance_amount=1000,
            maintenance_increase=2.0,
            improvement_amount=500,
            improvement_increase=2.0,
            hoa_amount=100,
            hoa_increase=2.0
        )

        # Create a home
        home = Home(
            person=self.person,
            name="Test House",
            purchase_price=400000,
            value_yearly_increase=3.0,
            down_payment=100000,
            mortgage=mortgage,
            expenses=expenses
        )

        # Check that the home was registered
        self.assertEqual(len(self.person.homes), 1)
        self.assertIn(home, self.person.homes)

    def test_apartment_registration(self):
        """Test that apartments are registered correctly"""
        # Initially no apartments
        self.assertEqual(len(self.person.apartments), 0)

        # Create an apartment
        apartment = Apartment(
            person=self.person,
            name="Test Apartment",
            monthly_rent=1500,
            yearly_increase=3.0
        )

        # Check that the apartment was registered
        self.assertEqual(len(self.person.apartments), 1)
        self.assertIn(apartment, self.person.apartments)

    def test_life_insurance_registration(self):
        """Test that life insurance policies are registered correctly"""
        # Initially no life insurance
        self.assertEqual(len(self.person.life_insurance_policies), 0)

        # Create a life insurance policy
        policy = LifeInsurance(
            person=self.person,
            policy_type=LifeInsuranceType.TERM,
            death_benefit=500000,
            monthly_premium=50,
            term_years=20
        )

        # Check that the policy was registered
        self.assertEqual(len(self.person.life_insurance_policies), 1)
        self.assertIn(policy, self.person.life_insurance_policies)

    def test_multiple_person_registrations(self):
        """Test that registrations work correctly for multiple people"""
        # Create a second person
        person2 = Person(
            family=self.family,
            name="Test Person 2",
            age=25,
            retirement_age=65,
            spending=self.spending
        )

        # Create bank accounts for each person
        bank1 = BankAccount(
            owner=self.person,
            company="Bank 1",
            type="Checking",
            balance=10000,
            interest_rate=0.1
        )

        bank2 = BankAccount(
            owner=person2,
            company="Bank 2",
            type="Checking",
            balance=5000,
            interest_rate=0.1
        )

        # Check that each person only sees their own accounts
        self.assertEqual(len(self.person.bank_accounts), 1)
        self.assertIn(bank1, self.person.bank_accounts)
        self.assertNotIn(bank2, self.person.bank_accounts)

        self.assertEqual(len(person2.bank_accounts), 1)
        self.assertIn(bank2, person2.bank_accounts)
        self.assertNotIn(bank1, person2.bank_accounts)

    def test_registry_clear(self):
        """Test clearing registries for a person"""
        # Create some accounts
        bank = BankAccount(
            owner=self.person,
            company="Test Bank",
            type="Checking",
            balance=10000,
            interest_rate=0.1
        )

        salary = Salary(
            model=self.model,
            base=100000,
            yearly_increase=3.0
        )
        job = Job(
            owner=self.person,
            company="Tech Corp",
            role="Software Engineer",
            salary=salary
        )

        # Verify they exist
        self.assertEqual(len(self.person.bank_accounts), 1)
        self.assertEqual(len(self.person.jobs), 1)
        self.assertIn(bank, self.person.bank_accounts)
        self.assertIn(job, self.person.jobs)

        # Clear all registries for this person
        self.model.registries.clear_all(self.person)

        # Verify they are cleared
        self.assertEqual(len(self.person.bank_accounts), 0)
        self.assertEqual(len(self.person.jobs), 0)

    def test_no_self_appending(self):
        """Test that lists are not stored on Person objects anymore"""
        # Check that Person doesn't have list attributes (they are now properties)
        self.assertFalse(hasattr(self.person, '_jobs'))
        self.assertFalse(hasattr(self.person, '_bank_accounts'))
        self.assertFalse(hasattr(self.person, '_homes'))
        self.assertFalse(hasattr(self.person, '_apartments'))

        # The properties should still work
        self.assertIsInstance(self.person.jobs, list)
        self.assertIsInstance(self.person.bank_accounts, list)
        self.assertIsInstance(self.person.homes, list)
        self.assertIsInstance(self.person.apartments, list)


if __name__ == '__main__':
    unittest.main()
