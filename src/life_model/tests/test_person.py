# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from ..model import LifeModel
from ..person import Person, Spending
from ..family import Family
from ..job import Job, Salary
from ..account.bank import BankAccount

import unittest


class TestPerson(unittest.TestCase):

    def test_get_year_at_age(self):
        model = LifeModel(start_year=2020)
        person = Person(family=Family(model),
                        name="Yami Raymundo",
                        age=23,
                        retirement_age=60,
                        spending=Spending(model, 10000))
        self.assertEqual(person.get_year_at_age(50), 2047)

    def test_get_federal_taxes_due(self):
        model = LifeModel(start_year=2020)
        person = Person(family=Family(model), name="Cas Harjabertaz",
                        age=36, retirement_age=56, spending=Spending(model, 0))
        BankAccount(owner=person, company="Bank of Mojave", type="Checking")
        job = Job(owner=person, company="Fiber Fashion",
                  role="Personal Shopper", salary=Salary(model=model, base=0))
        tax_data = (
            (5900,   0),  # Below standard deduction
            (15900,  205),
            (50900,  4240),
            (95900,  13668),
            (109900, 16887),
            (120900, 19527),
            (575900, 170912),
        )
        for salary, taxes_due in tax_data:
            job.salary.base = salary
            model.step()
            self.assertEqual(person.stat_taxes_paid_federal, taxes_due)

    # TODO - Add test for state taxes

    # TODO - Add test for ss taxes

    # TODO - Add test for medicare taxes
