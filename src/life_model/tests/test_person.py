# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..config.financial_config import FinancialConfig
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..work.job import Job, Salary

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    """Fresh FinancialConfig loaded from the frozen test fixture."""
    return FinancialConfig(config_file=TEST_CONFIG)


class TestPerson(unittest.TestCase):
    def test_get_year_at_age(self):
        model = LifeModel(start_year=2020)
        person = Person(
            family=Family(model), name="Yami Raymundo", age=23, retirement_age=60, spending=Spending(model, 10000)
        )
        self.assertEqual(person.get_year_at_age(50), 2047)

    def test_federal_taxes_due(self):
        model = LifeModel(start_year=2020, config=_fixture_config())
        person = Person(
            family=Family(model), name="Cas Harjabertaz", age=36, retirement_age=56, spending=Spending(model, 0)
        )
        BankAccount(owner=person, company="Bank of Mojave", type="Checking")
        job = Job(owner=person, company="Fiber Fashion", role="Personal Shopper", salary=Salary(model=model, base=0))
        # Fixture: $10k standard deduction, brackets 10% to $40k then 25%.
        tax_data = (
            (5900, 0),  # Below standard deduction
            (15900, 590),
            (50900, 4225),
            (95900, 15475),
            (109900, 18975),
            (120900, 21725),
            (575900, 135475),
        )
        for salary, taxes_due in tax_data:
            job.salary.base = salary
            model.step()
            self.assertEqual(person.stat_taxes_paid_federal, taxes_due)

    # TODO - Add test for state taxes

    def test_ss_taxes_due(self):
        model = LifeModel(start_year=2020, config=_fixture_config())
        person = Person(
            family=Family(model), name="Julie Antipater", age=24, retirement_age=65, spending=Spending(model, 0)
        )
        BankAccount(owner=person, company="Acrobatable", type="Checking")
        job = Job(owner=person, company="Acrobatable", role="Software Developer", salary=Salary(model=model, base=0))
        # Fixture Social Security wage base is $110,000.
        tax_data = (
            (5900, 5900 * 0.062),
            (15900, 15900 * 0.062),
            (50900, 50900 * 0.062),
            (95900, 95900 * 0.062),
            (109900, 109900 * 0.062),
            (120900, 110000 * 0.062),  # Above the fixture max of $110,000
            (575900, 110000 * 0.062),  # Above the fixture max of $110,000
        )
        for salary, taxes_due in tax_data:
            job.salary.base = salary
            model.step()
            self.assertEqual(person.stat_taxes_paid_ss, taxes_due)

    def test_medicare_taxes_due(self):
        model = LifeModel(start_year=2020, config=_fixture_config())
        person = Person(
            family=Family(model), name="Gunnel Ingi", age=33, retirement_age=50, spending=Spending(model, 0)
        )
        BankAccount(owner=person, company="Bits and Bytes", type="Checking")
        job = Job(owner=person, company="Bits and Bytes", role="Researcher", salary=Salary(model=model, base=0))
        # Fixture medicare rate 1.45%, additional 0.9% over $200,000 (single).
        tax_data = (
            (5900, 5900 * 0.0145),
            (15900, 15900 * 0.0145),
            (50900, 50900 * 0.0145),
            (95900, 95900 * 0.0145),
            (109900, 109900 * 0.0145),
            (120900, 120900 * 0.0145),
            (575900, (575900 * 0.0145 + (575900 - 200000) * 0.009)),  # Additional tax since over $200,000
        )
        for salary, taxes_due in tax_data:
            job.salary.base = salary
            model.step()
            self.assertAlmostEqual(person.stat_taxes_paid_medicare, taxes_due, places=2)
