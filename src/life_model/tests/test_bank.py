# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from ..account.bank import BankAccount
from ..model import LifeModel
from ..person import Person, Spending
from ..family import Family

import unittest

check_interest_table = {
    1:  5228.971130614779,
    2:  5463.732587816526,
    3:  5704.430800030053,
    4:  5951.215898629098,
    5:  6204.241811578181,
    6:  6463.6663594425345,
    7:  6729.651353825965,
    8:  7002.362698298062,
    9:  7281.970491873697,
    10: 7568.649135109362
}


def get_bank_account():
    """ Helper function to create a person for testing """
    model = LifeModel()
    person = Person(family=Family(model), name='Test Person', age=30, retirement_age=65, spending=Spending(model))
    return BankAccount(person, company='Test Company')


class TestBank(unittest.TestCase):

    def test_bank_account(self):
        """ Test bank account """

        account = get_bank_account()

        self.assertEqual(account.balance, 0)
        self.assertEqual(account.interest_rate, 0)

        account.balance = 5000
        account.interest_rate = 2.5

        for i in range(1, 11):
            account.balance += 100
            account.step()
            self.assertEqual(account.balance, check_interest_table[i])
