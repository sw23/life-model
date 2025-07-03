# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from ..model import LifeModel
from ..people.person import Person, Spending
from ..people.family import Family
from ..insurance.social_security import SocialSecurity, Income, bend_points, last_bend_points_year, \
                                        cost_of_living_adj, last_cost_of_living_adj_year, \
                                        last_avg_wage_index_increase, last_avg_wage_index_year, \
                                        avg_wage_index

import unittest

# TODO - Add unit test for the scenario below:
# For example a person who had maximum-taxable earnings in each year since
# age 22 and who retires at age 62 in 2023 would have an AIME equal to
# $12,427. Based on this AIME amount and the bend points $1,115 and $6,721,
# the PIA would equal $3,653.30. This person would receive a reduced benefit
# based on the $3,653.30 PIA.


# Test the two scenarios detailed at this URL:
# https://www.ssa.gov/oact/ProgData/retirebenefit1.html
example_caseA_earnings = (
    (1983, 14249, 3.9749, 56639),
    (1984, 15134, 3.7542, 56817),
    (1985, 15828, 3.6008, 56994),
    (1986, 16349, 3.497,  57173),
    (1987, 17446, 3.2874, 57352),
    (1988, 18362, 3.1331, 57530),
    (1989, 19149, 3.0138, 57710),
    (1990, 20095, 2.8807, 57887),
    (1991, 20908, 2.7772, 58066),
    (1992, 22053, 2.6411, 58244),
    (1993, 22311, 2.6186, 58423),
    (1994, 22980, 2.5502, 58602),
    (1995, 23974, 2.4519, 58781),
    (1996, 25223, 2.3376, 58960),
    (1997, 26776, 2.2087, 59139),
    (1998, 28262, 2.0988, 59317),
    (1999, 29927, 1.988,  59496),
    (2000, 31677, 1.8839, 59675),
    (2001, 32529, 1.84,   59852),
    (2002, 32954, 1.8217, 60032),
    (2003, 33860, 1.7782, 60211),
    (2004, 35539, 1.6992, 60389),
    (2005, 36948, 1.6392, 60567),
    (2006, 38760, 1.5672, 60745),
    (2007, 40639, 1.4992, 60925),
    (2008, 41695, 1.4655, 61103),
    (2009, 41187, 1.4879, 61282),
    (2010, 42283, 1.4536, 61461),
    (2011, 43735, 1.4094, 61640),
    (2012, 45231, 1.3667, 61818),
    (2013, 45941, 1.3495, 61996),
    (2014, 47709, 1.3032, 62175),
    (2015, 49511, 1.2594, 62354),
    (2016, 50214, 1.2453, 62533),
    (2017, 52096, 1.2038, 62711),
    (2018, 54138, 1.1616, 62889),
    (2019, 56326, 1.1197, 63068),
    (2020, 58082, 1.0889, 63247),
    (2021, 63425, 1,      63425),
    (2022, 65712, 1,      65712),
)

example_caseB_earnings = (
    (1983, 35700,  3.3021, 117886),
    (1984, 37800,  3.1188, 117890),
    (1985, 39600,  2.9913, 118457),
    (1986, 42000,  2.9051, 122015),
    (1987, 43800,  2.731,  119616),
    (1988, 45000,  2.6028, 117124),
    (1989, 48000,  2.5036, 120174),
    (1990, 51300,  2.3931, 122766),
    (1991, 53400,  2.3071, 123200),
    (1992, 55500,  2.1941, 121771),
    (1993, 57600,  2.1754, 125301),
    (1994, 60600,  2.1185, 128381),
    (1995, 61200,  2.0369, 124656),
    (1996, 62700,  1.9419, 121756),
    (1997, 65400,  1.8348, 119998),
    (1998, 68400,  1.7436, 119260),
    (1999, 72600,  1.6515, 119901),
    (2000, 76200,  1.565,  119252),
    (2001, 80400,  1.5285, 122893),
    (2002, 84900,  1.5133, 128483),
    (2003, 87000,  1.4772, 128519),
    (2004, 87900,  1.4116, 124081),
    (2005, 90000,  1.3618, 122560),
    (2006, 94200,  1.3019, 122643),
    (2007, 97500,  1.2454, 121429),
    (2008, 102000, 1.2174, 124177),
    (2009, 106800, 1.2361, 132011),
    (2010, 106800, 1.2075, 128963),
    (2011, 106800, 1.1708, 125045),
    (2012, 110100, 1.1354, 125005),
    (2013, 113700, 1.1211, 127463),
    (2014, 117000, 1.0826, 126667),
    (2015, 118500, 1.0462, 123977),
    (2016, 118500, 1.0345, 122592),
    (2017, 127200, 1,      127200),
    (2018, 128400, 1,      128400),
    (2019, 132900, 1,      132900),
    (2020, 137700, 1,      137700),
    (2021, 142800, 1,      142800),
    (2022, 147000, 1,      147000),
)


class TestSocialSecurity(unittest.TestCase):

    def test_get_aime_caseA(self):
        model = LifeModel(start_year=1983)
        person = Person(family=Family(model),
                        name="Test A",
                        age=22,
                        retirement_age=62,
                        spending=Spending(model, 10000))
        self.assertEqual(person.get_year_at_age(62), 2023)

        income_history = []
        chk_scaled_income = []
        for year, income, _, scaled_income in example_caseA_earnings:
            income_history.append(Income(year, income))
            chk_scaled_income.append(scaled_income)

        ss = SocialSecurity(person=person,
                            withdrawal_start_age=67,
                            income_history=income_history)

        # Make sure the scaled income matches the example data
        indexed_income_history = ss.get_indexed_income_history()
        self.assertEqual(len(chk_scaled_income), len(indexed_income_history))
        for chk, val, in zip(chk_scaled_income, indexed_income_history):
            self.assertEqual(chk, round(val))

        # Make sure the AIME matches the example data
        self.assertEqual(5052, ss.get_aime())

        # Make sure PIA matches the example data
        self.assertEqual(2263.30, ss.get_pia(2023))
        ss.withdrawal_start_age = 62
        self.assertEqual(1584.31, ss.get_pia(2023))

    def test_get_aime_caseB(self):
        model = LifeModel(start_year=1983)
        person = Person(family=Family(model),
                        name="Test B",
                        age=26,
                        retirement_age=62,
                        spending=Spending(model, 10000))
        self.assertEqual(person.get_year_at_age(66), 2023)

        income_history = []
        chk_scaled_income = []
        for year, income, _, scaled_income in example_caseB_earnings:
            income_history.append(Income(year, income))
            chk_scaled_income.append(scaled_income)

        ss = SocialSecurity(person=person,
                            withdrawal_start_age=67,
                            income_history=income_history)

        # Make sure the scaled income matches the example data
        indexed_income_history = ss.get_indexed_income_history()
        self.assertEqual(len(chk_scaled_income), len(indexed_income_history))
        for chk, val, in zip(chk_scaled_income, indexed_income_history):
            self.assertEqual(chk, round(val))

        # Make sure the AIME matches the example data
        self.assertEqual(10503, ss.get_aime())

        # Make sure PIA matches the example data
        self.assertEqual(3627.10, ss.get_pia(2023))

    def test_get_early_delayed_pia(self):
        model = LifeModel(start_year=1983)
        person = Person(family=Family(model),
                        name="Test C",
                        age=26,
                        retirement_age=62,
                        spending=Spending(model, 10000))
        ss = SocialSecurity(person=person)

        # https://www.ssa.gov/oact/ProgData/ar_drc.html
        test_values = (
            (62, 70), (63, 75), (64, 80), (65, 86.667),
            (66, 93.333), (67, 100), (68, 108), (69, 116),
            (70, 124), (71, 124), (72, 124)
        )

        for age, pct in test_values:
            ss.withdrawal_start_age = age
            self.assertAlmostEqual(1000 * (pct / 100), ss.get_early_delayed_pia(1000), places=2)

    def test_variable_sanity_chk(self):
        # Make sure the last bend point year is accurate
        self.assertIn(last_bend_points_year, bend_points)
        self.assertNotIn(last_bend_points_year+1, bend_points)

        # Make sure the last cost of living year is accurate
        self.assertIn(last_cost_of_living_adj_year, cost_of_living_adj)
        self.assertNotIn(last_cost_of_living_adj_year+1, cost_of_living_adj)

        # Make sure the last avg wage index year is accurate
        self.assertIn(last_avg_wage_index_year, avg_wage_index)
        self.assertNotIn(last_avg_wage_index_year+1, avg_wage_index)
        chk_pct = avg_wage_index[last_avg_wage_index_year] / avg_wage_index[last_avg_wage_index_year-1]
        self.assertAlmostEqual(chk_pct * 100, last_avg_wage_index_increase + 100, places=2)
