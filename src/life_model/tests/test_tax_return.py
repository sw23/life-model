# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The per-year TaxReturn record (Plan 28, task 1).

The record is built from the numbers settlement paid, so these tests check two things: that its
lines reconcile among themselves the way Form 1040's do, and that on the IRS golden cases
(test_irs_golden.py) the record's line totals equal the hand-computed tax.
"""

import json
import unittest

from ..account.bank import BankAccount
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..tax.federal import FilingStatus
from ..tax.income import IncomeType
from ..tax.return_record import TaxReturn
from .scenarios import married_homeowners, mortality_and_estate, renter_buys_home, stochastic_retiree
from .test_irs_golden import GAINS_CASES, ORDINARY_CASES, PAYROLL_CASES

STANDARD_2026 = {
    FilingStatus.SINGLE: 16100,
    FilingStatus.MARRIED_FILING_JOINTLY: 32200,
    FilingStatus.HEAD_OF_HOUSEHOLD: 24150,
    FilingStatus.MARRIED_FILING_SEPARATELY: 16100,
}


def assert_return_reconciles(test: unittest.TestCase, tax_return: TaxReturn, places: int = 2) -> None:
    """The Form-1040 identities every return must satisfy."""
    r = tax_return
    test.assertAlmostEqual(max(r.total_income - r.total_adjustments, 0.0), r.agi, places=places)
    test.assertAlmostEqual(max(r.agi - r.deduction, 0.0), r.taxable_income, places=places)
    test.assertAlmostEqual(
        r.deduction, max(r.standard_deduction, r.itemized_deductions) + r.senior_deduction, places=places
    )
    test.assertAlmostEqual(r.taxable_ordinary_income + r.taxable_preferential_income, r.taxable_income, places=places)
    test.assertAlmostEqual(sum(row[4] for row in r.ordinary_brackets), r.ordinary_tax, places=places)
    test.assertAlmostEqual(sum(row[3] for row in r.ordinary_brackets), r.taxable_ordinary_income, places=places)
    test.assertAlmostEqual(
        r.ordinary_tax + r.preferential_tax + r.niit + r.amt - r.total_credits + r.total_penalties,
        r.federal_tax,
        places=places,
    )
    test.assertAlmostEqual(sum(r.credits.values()), r.total_credits, places=places)
    test.assertAlmostEqual(sum(r.penalties.values()), r.total_penalties, places=places)
    test.assertAlmostEqual(r.nonrefundable_credits + r.refundable_credits, r.total_credits, places=places)
    test.assertAlmostEqual(sum(line.social_security for line in r.fica), r.social_security_tax, places=places)
    test.assertAlmostEqual(sum(line.medicare for line in r.fica), r.medicare_tax, places=places)
    test.assertAlmostEqual(
        r.federal_tax + r.state_tax + r.social_security_tax + r.medicare_tax, r.total_tax, places=places
    )
    if r.state_return is not None:
        test.assertAlmostEqual(r.state_return.tax, r.state_tax, places=places)
    test.assertEqual(r.deduction_taken, "itemized" if r.itemized_deductions > r.standard_deduction else "standard")


def _one_year(status: FilingStatus, incomes: "list[list[tuple]]") -> tuple[LifeModel, list[Person]]:
    """A 2026 model with one person per entry of ``incomes`` (each a list of ledger entries
    ``(income_type, amount)``), in TX (no state income tax), settled once."""
    model = LifeModel(start_year=2026, end_year=2026)
    family = Family(model)
    people = []
    for i, entries in enumerate(incomes):
        person = Person(family, f"P{i}", 40, 65, Spending(model, base=0), state="TX")
        BankAccount(person, "Bank", balance=1_000_000)
        for income_type, amount in entries:
            if income_type == IncomeType.WAGES:
                person.income.add_wages(amount, amount)
            else:
                person.income.add(income_type, amount, source="test")
        people.append(person)
    if status in (FilingStatus.MARRIED_FILING_JOINTLY, FilingStatus.MARRIED_FILING_SEPARATELY):
        people[0].get_married(people[1])
        for person in people:
            person.filing_status = status
    if status == FilingStatus.HEAD_OF_HOUSEHOLD:
        people[0].add_child("Kid", birth_year=2010)
    model.step()
    return model, people


class TestGoldenCasesEndToEnd(unittest.TestCase):
    """The IRS golden cases, run through a real settlement, read back off the TaxReturn."""

    def test_ordinary_income_cases(self):
        for description, status, taxable, expected in ORDINARY_CASES:
            with self.subTest(description):
                wages = taxable + STANDARD_2026[status]
                count = (
                    2 if status in (FilingStatus.MARRIED_FILING_JOINTLY, FilingStatus.MARRIED_FILING_SEPARATELY) else 1
                )
                if status == FilingStatus.MARRIED_FILING_JOINTLY:
                    incomes = [[(IncomeType.WAGES, wages)], []]
                else:
                    incomes = [[(IncomeType.WAGES, wages)] for _ in range(count)]
                model, people = _one_year(status, incomes)
                tax_return = people[0].tax_returns[2026]
                self.assertEqual(tax_return.filing_status, status.name)
                self.assertEqual(tax_return.deduction_taken, "standard")
                self.assertAlmostEqual(tax_return.taxable_income, taxable, places=2)
                self.assertAlmostEqual(tax_return.ordinary_tax, expected, places=2)
                self.assertAlmostEqual(sum(row[4] for row in tax_return.ordinary_brackets), expected, places=2)
                # Credits (the head-of-household case has a child) are the only thing between the
                # ordinary tax and the federal tax on these returns.
                self.assertAlmostEqual(tax_return.federal_tax, expected - tax_return.total_credits, places=2)
                assert_return_reconciles(self, tax_return)
                self.assertIn((2026, people[0].unique_id), model.tax_returns)

    def test_gains_cases(self):
        for description, status, ordinary, gain, expected in GAINS_CASES:
            with self.subTest(description):
                deduction = STANDARD_2026[status]
                entries = [(IncomeType.WAGES, ordinary + deduction), (IncomeType.LONG_TERM_CAPITAL_GAIN, gain)]
                if ordinary == 0:
                    # A gain-only return: the deduction absorbs part of the gain instead.
                    entries = [(IncomeType.LONG_TERM_CAPITAL_GAIN, gain + deduction)]
                incomes = [entries, []] if status == FilingStatus.MARRIED_FILING_JOINTLY else [entries]
                _, people = _one_year(status, incomes)
                tax_return = people[0].tax_returns[2026]
                self.assertAlmostEqual(tax_return.taxable_income, ordinary + gain, places=2)
                self.assertAlmostEqual(tax_return.ordinary_tax + tax_return.preferential_tax, expected, places=2)
                self.assertAlmostEqual(tax_return.long_term_gains, entries[-1][1], places=2)
                assert_return_reconciles(self, tax_return)

    def test_payroll_cases(self):
        for description, status, wages, social_security, medicare in PAYROLL_CASES:
            with self.subTest(description):
                incomes = [[(IncomeType.WAGES, w)] for w in wages]
                _, people = _one_year(status, incomes)
                tax_return = people[0].tax_returns[2026]
                self.assertAlmostEqual(tax_return.social_security_tax, social_security, places=2)
                self.assertAlmostEqual(tax_return.medicare_tax, medicare, places=2)
                self.assertEqual([line.wages for line in tax_return.fica], wages)
                assert_return_reconciles(self, tax_return)

    def test_settled_taxes_equal_the_return(self):
        # The return's total is exactly what the settlement charged (the stats come from the same
        # TaxesDue object).
        _, people = _one_year(FilingStatus.SINGLE, [[(IncomeType.WAGES, 150000)]])
        person = people[0]
        tax_return = person.tax_returns[2026]
        self.assertAlmostEqual(tax_return.total_tax, person.stat_taxes_paid, places=6)
        self.assertAlmostEqual(tax_return.state_tax, 0.0)


class TestReturnsOnWholeHouseholds(unittest.TestCase):
    def _assert_all_reconcile(self, model: LifeModel):
        self.assertTrue(model.tax_returns)
        for (year, unit_id), tax_return in model.tax_returns.items():
            with self.subTest(year=year, unit=unit_id):
                self.assertEqual(tax_return.year, year)
                self.assertEqual(tax_return.unit_id, unit_id)
                assert_return_reconciles(self, tax_return)

    def test_married_homeowners_2030(self):
        model = married_homeowners()
        model.run()
        returns = [r for (year, _), r in model.tax_returns.items() if year == 2030]
        self.assertEqual(len(returns), 1)
        tax_return = returns[0]
        self.assertEqual(tax_return.filing_status, "MARRIED_FILING_JOINTLY")
        self.assertEqual(tax_return.member_names, ("John", "Jane"))
        self.assertEqual(tax_return.deduction_taken, "itemized")
        self.assertGreater(tax_return.itemized_components["mortgage_interest"], 0)
        self.assertGreater(tax_return.credits["child_tax_credit"], 0)
        self.assertEqual(tax_return.state, "CA")
        assert_return_reconciles(self, tax_return)
        # Both spouses point at the same record.
        john = next(p for p in model.agents if getattr(p, "name", None) == "John")
        jane = next(p for p in model.agents if getattr(p, "name", None) == "Jane")
        self.assertIs(john.tax_returns[2030], jane.tax_returns[2030])
        self._assert_all_reconcile(model)

    def test_other_households_reconcile_every_year(self):
        for build in (lambda: stochastic_retiree(seed=5), mortality_and_estate, renter_buys_home):
            model = build()
            model.run()
            self._assert_all_reconcile(model)

    def test_retiree_lines(self):
        model = stochastic_retiree(seed=5)
        model.run()
        returns = sorted(model.tax_returns.values(), key=lambda r: r.year)
        late = [r for r in returns if r.year >= 2034]
        self.assertTrue(any(r.ira_distributions_gross > 0 for r in late))  # RMDs from 73
        self.assertTrue(all(r.social_security_gross > 0 for r in late))
        self.assertTrue(all(0 <= r.social_security_taxable <= 0.85 * r.social_security_gross + 0.01 for r in late))

    def test_penalties_and_adjustments_are_itemized_by_source(self):
        model = LifeModel(start_year=2026, end_year=2026)
        person = Person(Family(model), "Young", 40, 65, Spending(model, base=0))
        BankAccount(person, "Bank", balance=100000)
        person.income.add_wages(90000, 90000)
        person.income.add_deduction(5000, source="ira_deduction")
        person.income.add(IncomeType.PRETAX_DISTRIBUTION, 10000, source="401k")
        person.income.add_penalty(1000)
        person.income.add_penalty(400, source="hsa_non_medical")
        model.step()
        tax_return = person.tax_returns[2026]
        self.assertEqual(tax_return.adjustments, {"ira_deduction": 5000})
        self.assertEqual(tax_return.penalties, {"early_withdrawal": 1000, "hsa_non_medical": 400})
        self.assertAlmostEqual(tax_return.agi, 95000)
        assert_return_reconciles(self, tax_return)


class TestFieldDocs(unittest.TestCase):
    def test_every_field_is_documented(self):
        from dataclasses import fields

        from ..tax.return_record import FIELD_DOCS

        self.assertEqual({f.name for f in fields(TaxReturn)}, set(FIELD_DOCS))


class TestSerialization(unittest.TestCase):
    def test_round_trip_and_scaling(self):
        model = married_homeowners(years=8)
        model.run()
        tax_return = next(iter(model.tax_returns.values()))
        data = json.loads(json.dumps(tax_return.to_dict()))
        self.assertEqual(TaxReturn.from_dict(data), tax_return)
        half = tax_return.scaled(2.0)
        self.assertAlmostEqual(half.total_tax, tax_return.total_tax / 2)
        self.assertAlmostEqual(half.ordinary_brackets[-1][4], tax_return.ordinary_brackets[-1][4] / 2)
        self.assertEqual(half.marginal_rate, tax_return.marginal_rate)
        self.assertEqual(half.year, tax_return.year)
        assert_return_reconciles(self, half)


if __name__ == "__main__":
    unittest.main()
