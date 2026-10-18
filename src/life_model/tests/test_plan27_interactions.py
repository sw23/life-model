# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Plan 27's two halves together: 27b's spending categories and age schedule with 27a's bank-sourced
contribution plans and savings sweep. A contribution is made after the month's bills, so it is never
funded by money the month's spending (categories included) needs; nothing is sold to pay a bill a
contribution emptied the bank for; net worth covers both halves' new assets and liabilities."""

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount
from ..config.financial_config import FinancialConfig
from ..debt.heloc import HomeEquityLine
from ..housing.home import Home, HomeExpenses
from ..insurance.life_insurance import LifeInsurance, LifeInsuranceType
from ..ledger import account_label, household_balance_sheet
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending, SpendingLine
from ..policies import ContributionPlan, SavingsPolicy
from ..work.job import Job, Salary

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _household(*, categories, schedule=None, birth="1985-01", bank=0.0, end_year=2026):
    model = LifeModel(start_year=2026, end_year=end_year, config=FinancialConfig(config_file=TEST_CONFIG))
    spending = Spending(model, 0, 0, categories=categories, schedule=schedule)
    person = Person(Family(model), "P", None, 70, spending, birth=birth)
    bank = BankAccount(person, company="Bank", balance=bank, interest_pct=0)
    Job(person, company="Co", role="R", salary=Salary(model, base_annual=60000))
    brokerage = BrokerageAccount(person, company="Broker", growth_pct=0)
    return model, person, bank, brokerage


def spending_paid(person) -> float:
    return person.spending.get_yearly_spending()


class TestContributionsAfterSpendingCategories(unittest.TestCase):
    def _eleven_months(self, model, brokerage):
        """Run January through November (December adds the year's taxes, which an income this tight cannot
        pay whatever the plan does) and return the contributions by month and the events so far."""
        for _ in range(11):
            model.step()
        ledger = model.ledger.to_frame()
        label = account_label(brokerage)
        rows = ledger[(ledger.to_account == label) & (ledger.cause == "contribution plan")]
        return rows.groupby("month").amount.sum().to_dict(), set(model.event_log.to_frame()["kind"])

    def test_contribution_takes_only_what_the_months_categories_leave(self):
        categories = {
            "groceries": SpendingLine(1500, period="monthly", growth_pct=0),
            "travel": SpendingLine(30000, growth_pct=0, essential=False),
        }
        model, person, _bank, brokerage = _household(categories=categories)
        person.add_contribution_plan(ContributionPlan(brokerage, amount_annual=24000))
        by_month, kinds = self._eleven_months(model, brokerage)
        # $5,000 of pay a month, $4,000 of categorized spending: $1,000 left, not the plan's $2,000.
        for month in range(1, 12):
            self.assertAlmostEqual(by_month.get(month, 0.0), 1000.0, places=6)
        self.assertNotIn("forced_sale", kinds)
        self.assertNotIn("shortfall_debt", kinds)
        self.assertEqual(person.debt, 0)
        self.assertAlmostEqual(spending_paid(person), 11 * 4000, places=6)

    def test_schedule_step_frees_cash_for_the_plan(self):
        categories = {"living": SpendingLine(4000, period="monthly", growth_pct=0)}
        # Turns 41 in July 2026: spending halves from July.
        model, person, _bank, brokerage = _household(categories=categories, schedule=[(41, 50)], birth="1985-07")
        person.add_contribution_plan(ContributionPlan(brokerage, amount_annual=24000))
        by_month, kinds = self._eleven_months(model, brokerage)
        for month in range(1, 7):
            self.assertAlmostEqual(by_month.get(month, 0.0), 1000.0, places=6)
        # From July $3,000 is left: the plan catches up toward its yearly $24,000 within it.
        for month in range(7, 12):
            self.assertGreater(by_month.get(month, 0.0), 1000.0)
            self.assertLessEqual(by_month.get(month, 0.0), 3000.0 + 1e-6)
        self.assertNotIn("forced_sale", kinds)
        self.assertEqual(person.debt, 0)

    def test_sweep_keeps_the_floor_for_next_years_categories(self):
        categories = {"living": SpendingLine(3000, period="monthly", growth_pct=0)}
        model, person, _bank, brokerage = _household(categories=categories, bank=5000, end_year=2027)
        person.savings_policy = SavingsPolicy(cash_floor=6000, sweep_to=brokerage)
        model.step_year()
        self.assertAlmostEqual(person.bank_account_balance, 6000, places=2)
        self.assertGreater(brokerage.balance, 0)
        result = model.run()
        self.assertNotIn("forced_sale", set(result.events["kind"]))
        self.assertEqual(person.debt, 0)


class TestNetWorthCoversBothHalves(unittest.TestCase):
    def test_every_new_asset_and_liability_is_on_the_balance_sheet(self):
        from ..account.fixed_income import FixedIncomeHolding

        model, person, bank, _brokerage = _household(
            categories={"living": SpendingLine(1000, period="monthly", growth_pct=0)}, bank=50000
        )
        home = Home(person, "House", 400000, 0.0, 0, None, HomeExpenses(model), current_value=450000)
        heloc = HomeEquityLine(person, home=home, credit_limit=50000, rate_pct=8, balance=10000)
        policy = LifeInsurance(person, LifeInsuranceType.WHOLE, 100000, 100, cash_value=9000, loan_balance=2000)
        holding = FixedIncomeHolding(person, kind="cd", face=10000, rate_pct=4.0, maturity="2028-01")
        sheet = household_balance_sheet(model)
        for agent, value in ((home, 450000), (heloc, -10000), (policy, 7000), (holding, 10000), (bank, 50000)):
            self.assertAlmostEqual(sheet.lines[account_label(agent)], value, places=6)
        model.checks = "strict"
        model.run()


if __name__ == "__main__":
    unittest.main()
