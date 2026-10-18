# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The cash-flow ledger and the money-conservation check (Plan 28, task 3).

The conservation check compares each year's change in household net worth, measured from the
balances, with the year's net external flow on the ledger. The whole-household tests run decades
of every major code path; the bug tests below each pin one place where money used to appear or
vanish.
"""

import unittest

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount
from ..checks import (
    ConservationError,
    account_residuals,
    assert_conservation,
    check_conservation,
    conservation_records,
)
from ..housing.home import Home, HomeExpenses, Mortgage
from ..insurance.social_security import SocialSecurity
from ..ledger import FlowKind, LedgerEntry, household_balance_sheet
from ..lifeevents import LifeEvent, LifeEvents
from ..model import LifeModel
from ..people.family import Family
from ..people.person import MortalityMode, Person, Spending
from ..work.job import Job, Salary
from .scenarios import (
    EARNINGS_HISTORY,
    married_homeowners,
    mortality_and_estate,
    renter_buys_home,
    stochastic_retiree,
)


def _person(model, name="Pat", age=40, **kwargs) -> Person:
    return Person(Family(model), name, age, 65, Spending(model, base=kwargs.pop("spending", 0)), **kwargs)


class TestLedgerEntries(unittest.TestCase):
    def test_entry_classification(self):
        inflow = LedgerEntry(0, 2026, None, "step", "wage", 10.0, None, "Bank:1", "Acme", None, None, 1)
        outflow = LedgerEntry(1, 2026, None, "step", "tax", 4.0, "Bank:1", None, None, "IRS", None, 1)
        transfer = LedgerEntry(2, 2026, None, "step", "sale", 7.0, "Brokerage:2", "Bank:1", None, None, None, 1)
        self.assertEqual((inflow.is_inflow, inflow.net_worth_effect), (True, 10.0))
        self.assertEqual((outflow.is_outflow, outflow.net_worth_effect), (True, -4.0))
        self.assertEqual((transfer.is_transfer, transfer.net_worth_effect), (True, 0.0))

    def test_post_requires_a_household_side_and_skips_zero(self):
        model = LifeModel(start_year=2026, end_year=2026)
        with self.assertRaises(ValueError):
            model.ledger.post(5, FlowKind.OTHER, source="a", sink="b")
        self.assertIsNone(model.ledger.post(0, FlowKind.OTHER, to_account="Cash:1"))
        self.assertEqual(len(model.ledger), 0)

    def test_paycheck_tax_and_spending_are_posted(self):
        model = LifeModel(start_year=2026, end_year=2026)
        person = _person(model, spending=30000)
        bank = BankAccount(person, "Bank", balance=10000)
        Job(person, "Acme", "Dev", Salary(model, base=100000, yearly_bonus=10))
        model.run()
        frame = model.ledger.to_frame()
        wage = frame[frame.kind == "wage"]
        self.assertEqual(wage.amount.sum(), 100000)
        self.assertEqual(wage.source.iloc[0], "Acme")
        self.assertEqual(wage.to_account.iloc[0], f"BankAccount:{bank.unique_id}")
        self.assertEqual(frame[frame.kind == "bonus"].amount.sum(), 10000)
        self.assertAlmostEqual(frame[frame.kind == "spending"].amount.sum(), 30000)
        taxes = frame[frame.kind.isin(["tax", "penalty"])].amount.sum()
        self.assertAlmostEqual(taxes, person.tax_returns[2026].total_tax, places=6)
        self.assertEqual(frame.year.unique().tolist(), [2026])
        self.assertTrue(frame.month.isna().all())
        self.assertEqual(model.ledger.names[f"BankAccount:{bank.unique_id}"], "Pat's BankAccount (Bank)")
        # The DataCollector table exposes the same rows.
        table = model.datacollector.get_table_dataframe("Ledger")
        self.assertEqual(len(table), len(frame))
        assert_conservation(model)

    def test_settlement_draws_carry_their_cause(self):
        model = LifeModel(start_year=2026, end_year=2026)
        person = _person(model, spending=60000)
        BankAccount(person, "Bank", balance=1000)
        BrokerageAccount(person, "Broker", balance=200000)
        model.run()
        sales = [e for e in model.ledger if e.kind == "sale"]
        self.assertEqual(len(sales), 1)
        self.assertEqual(sales[0].cause, "fund 2026 bills and taxes")
        self.assertTrue(sales[0].is_transfer)
        assert_conservation(model)


class TestTaxOutflowMatchesTheReturn(unittest.TestCase):
    def test_married_homeowners_2030(self):
        model = married_homeowners()
        model.run()
        (tax_return,) = [r for (year, _), r in model.tax_returns.items() if year == 2030]
        entries = [e for e in model.ledger.for_year(2030) if e.kind in ("tax", "penalty")]
        federal = sum(
            e.amount
            for e in entries
            if e.sink and e.sink.startswith("IRS:") and "social security" not in e.sink and "medicare" not in e.sink
        )
        self.assertAlmostEqual(federal, tax_return.federal_tax, places=2)
        self.assertAlmostEqual(sum(e.amount for e in entries), tax_return.total_tax, places=2)


class TestConservationOnWholeHouseholds(unittest.TestCase):
    """Δ(assets − liabilities) equals the ledger's net flow, every year, to within $1."""

    def _assert_conserved(self, model: LifeModel, years: int):
        model.run()
        self.assertEqual(len(model.balance_sheets), years)
        assert_conservation(model)
        self.assertFalse(check_conservation(model))

    def test_married_homeowners_45_years(self):
        self._assert_conserved(married_homeowners(years=45), 45)

    def test_stochastic_retiree_many_seeds(self):
        for seed in (1, 2, 3, 11, 42):
            with self.subTest(seed=seed):
                self._assert_conserved(stochastic_retiree(seed=seed, years=40), 40)

    def test_mortality_estate_and_inheritance_50_years(self):
        self._assert_conserved(mortality_and_estate(years=50), 50)

    def test_home_purchase_by_event_debts_rsus_45_years(self):
        self._assert_conserved(renter_buys_home(years=45), 45)

    def test_records_describe_the_year(self):
        model = married_homeowners(years=10)
        model.run()
        records = conservation_records(model)
        self.assertEqual([r.year for r in records], list(range(2026, 2036)))
        for record in records:
            self.assertAlmostEqual(record.change, record.net_flow, delta=1.0)
        sheet = household_balance_sheet(model)
        self.assertAlmostEqual(sheet.net_worth, records[-1].closing_net_worth, places=6)
        self.assertGreater(sheet.assets, sheet.liabilities)

    def test_unposted_money_is_caught(self):
        model = LifeModel(start_year=2026, end_year=2027)
        person = _person(model)
        account = BankAccount(person, "Bank", balance=100)

        def windfall():
            account.balance += 500  # moved without posting

        LifeEvents(model, [LifeEvent(2027, "Unrecorded windfall", windfall)])
        model.run()
        failures = check_conservation(model)
        self.assertEqual([r.year for r in failures], [2027])
        self.assertAlmostEqual(failures[0].residual, 500)
        self.assertEqual(account_residuals(model, 2027), {f"BankAccount:{account.unique_id}": 500})
        with self.assertRaises(ConservationError) as raised:
            assert_conservation(model)
        self.assertIn("Pat's BankAccount (Bank)", str(raised.exception))

    def test_accounts_opened_mid_run_post_their_opening_balance(self):
        model = LifeModel(start_year=2026, end_year=2027)
        person = _person(model)
        BankAccount(person, "Bank", balance=100)
        LifeEvents(model, [LifeEvent(2027, "Open a brokerage account", BrokerageAccount, person, "Broker", 5000)])
        model.run()
        assert_conservation(model)
        (opening,) = [e for e in model.ledger if e.kind == "opening_balance"]
        self.assertEqual(opening.amount, 5000)


class TestMoneyConservationBugs(unittest.TestCase):
    """Each test pins a place where money used to be created or destroyed without a flow."""

    def test_social_security_stops_at_death(self):
        # Bug: SocialSecurity kept paying a dead person, into a cash pocket nobody owned.
        model = LifeModel(start_year=2026, end_year=2030)
        person = _person(model, age=70, mortality_mode=MortalityMode.FIXED_AGE, death_age=72)
        heir = Person(person.family, "Heir", 40, 65, Spending(model, base=0))
        BankAccount(person, "Bank", balance=10000)
        BankAccount(heir, "Bank", balance=10000)
        SocialSecurity(person, withdrawal_start_age=67, income_history=EARNINGS_HISTORY)
        model.run()
        benefits = [e for e in model.ledger if e.kind == "benefit" and e.source == "Social Security"]
        self.assertEqual(sorted({e.year for e in benefits}), [2026, 2027])
        self.assertEqual(person.cash, 0)
        assert_conservation(model)

    def test_unpaid_bills_debt_passes_to_the_heir(self):
        # Bug: a decedent's carried unpaid-bills debt vanished at death (free money for the estate).
        model = LifeModel(start_year=2026, end_year=2027)
        person = _person(model, age=80, mortality_mode=MortalityMode.FIXED_AGE, death_age=81, spending=50000)
        heir = Person(person.family, "Heir", 50, 65, Spending(model, base=0))
        BankAccount(person, "Bank", balance=1000)
        BankAccount(heir, "Bank", balance=200000)
        model.step()
        carried = person.debt
        self.assertGreater(carried, 40000)
        model.step()
        self.assertTrue(person.is_deceased)
        self.assertEqual(person.debt, 0)
        # The heir's settlement repaid the inherited debt (with a year of interest).
        repaid = [e for e in model.ledger.for_year(2027) if e.cause == "repay unpaid bills carried from last year"]
        self.assertGreater(sum(e.amount for e in repaid), carried)
        assert_conservation(model)

    def test_cash_held_outside_banks_passes_to_the_heir(self):
        # Bug: cash a decedent held without a bank account vanished at death.
        model = LifeModel(start_year=2026, end_year=2027)
        person = _person(model, age=80, mortality_mode=MortalityMode.FIXED_AGE, death_age=81)
        heir = Person(person.family, "Heir", 50, 65, Spending(model, base=0))
        BankAccount(heir, "Bank", balance=1000)
        LifeEvents(model, [LifeEvent(2026, "Gift", person.receive_cash, 25000, "a relative")])
        model.run()
        self.assertEqual(person.cash, 0)
        self.assertAlmostEqual(heir.bank_account_balance, 1000 + 25000, places=2)
        assert_conservation(model)

    def test_agents_removed_at_a_death_do_not_run_the_rest_of_that_stage(self):
        # Bug: die() removes the decedent's pensions "so nothing of theirs steps again", but the
        # engine had already snapshotted the stage's agent list, so a survivor pension still paid
        # the survivor (into a cash pocket nobody owned) in the year she died.
        from ..account.pension import Pension

        model = LifeModel(start_year=2026, end_year=2031)
        family = Family(model)
        bob = Person(
            family, "Bob", 75, 65, Spending(model, base=0), mortality_mode=MortalityMode.FIXED_AGE, death_age=76
        )
        sue = Person(
            family, "Sue", 70, 65, Spending(model, base=0), mortality_mode=MortalityMode.FIXED_AGE, death_age=73
        )
        kid = Person(family, "Kid", 40, 65, Spending(model, base=0))
        bob.get_married(sue)
        for person in (bob, sue, kid):
            BankAccount(person, "Bank", balance=10000)
        Pension(bob, "Utility", vesting_years=1, benefit_amount=20000, survivor_percent=50)
        model.run()
        self.assertTrue(sue.is_deceased)
        paid = {(e.year, e.to_account) for e in model.ledger if e.kind == "benefit"}
        self.assertNotIn(2029, {year for year, _ in paid})  # Sue died in 2029
        self.assertEqual(sue.cash, 0)
        assert_conservation(model)

    def test_death_with_a_529_plan_passes_it_on(self):
        # Crash (found by the conservation scenarios): a 529 plan's ``beneficiary`` is the student, a
        # Child, which the estate code read as a designated Person (``beneficiary.is_deceased``).
        from ..dependents.plan529 import Plan529

        model = LifeModel(start_year=2026, end_year=2027)
        family = Family(model)
        parent = Person(
            family, "Parent", 70, 65, Spending(model, base=0), mortality_mode=MortalityMode.FIXED_AGE, death_age=71
        )
        spouse = Person(family, "Spouse", 68, 65, Spending(model, base=0))
        parent.get_married(spouse)
        BankAccount(spouse, "Bank", balance=10000)
        plan = Plan529(parent, beneficiary=parent.add_child("Kid", birth_year=2015), balance=30000)
        model.run()
        self.assertTrue(parent.is_deceased)
        self.assertIs(plan.person, spouse)
        assert_conservation(model)

    def test_a_dissolved_estate_stops_donating(self):
        # Bug: with no heir, the decedent's dissolved bank account kept its balance after removal and
        # their Donation agent kept spending it every year (and reporting it in the Charity column).
        from ..charity.donation import Donation

        model = LifeModel(start_year=2026, end_year=2030)
        loner = _person(model, age=80, mortality_mode=MortalityMode.FIXED_AGE, death_age=81)
        account = BankAccount(loner, "Bank", balance=50000)
        Donation(loner, "Shelter", annual_amount=3000)
        model.run()
        frame = model.datacollector.get_model_vars_dataframe().set_index("Year")
        self.assertEqual(frame.loc[2026, "Charity"], 3000)
        self.assertEqual(frame.loc[2028:, "Charity"].sum(), 0)
        self.assertEqual(account.balance, 0)
        dissolved = [e for e in model.ledger if e.sink == "dissolved estate"]
        self.assertEqual(len(dissolved), 1)
        assert_conservation(model)

    def test_a_closed_whole_life_policy_holds_no_money(self):
        # Bug: a policy that ended (death, lapse) kept its cash value and loan balance, so surrendering
        # it later paid the stale cash value out again, and repaying its loan paid off a loan the death
        # benefit (or the lapse) had already settled.
        from ..insurance.life_insurance import LifeInsurance, LifeInsuranceType

        model = LifeModel(start_year=2026, end_year=2029)
        family = Family(model)
        insured = Person(
            family, "Insured", 70, 65, Spending(model, base=0), mortality_mode=MortalityMode.FIXED_AGE, death_age=71
        )
        spouse = Person(family, "Spouse", 68, 65, Spending(model, base=0))
        insured.get_married(spouse)
        BankAccount(insured, "Bank", balance=50000)
        BankAccount(spouse, "Bank", balance=50000)
        policy = LifeInsurance(insured, LifeInsuranceType.WHOLE, death_benefit=100000, monthly_premium=300)
        LifeEvents(
            model,
            [
                LifeEvent(2026, "Loan", policy.take_loan, 1000),
                LifeEvent(2028, "Repay the loan", policy.repay_loan, 1000),
                LifeEvent(2028, "Surrender", policy.drop_policy),
            ],
        )
        model.run()
        self.assertFalse(policy.is_active)
        self.assertEqual((policy.cash_value, policy.outstanding_loan_balance), (0, 0))
        self.assertFalse(
            [
                e
                for e in model.ledger.for_year(2028)
                if e.from_account == f"LifeInsurance:{policy.unique_id}"
                or e.to_account == f"LifeInsurance:{policy.unique_id}"
            ]
        )
        assert_conservation(model)

    def test_underwater_home_sale_is_paid_by_the_owner(self):
        # Bug: selling a home for less than the mortgage payoff (plus selling costs) silently wrote
        # the difference off: the mortgage vanished and nobody paid.
        model = LifeModel(start_year=2026, end_year=2026)
        person = _person(model)
        BankAccount(person, "Bank", balance=100000)
        home = Home(
            person,
            "Condo",
            purchase_price=300000,
            value_yearly_increase=0,
            down_payment=0,
            mortgage=Mortgage(loan_amount=320000, start_date=2026, length_years=30, yearly_interest_rate=6),
            expenses=HomeExpenses(model, 0, 0, 0, 0, 0, 0, 0, 0),
        )
        LifeEvents(model, [LifeEvent(2026, "Sell", home.sell)])
        model.run()
        selling_costs = 300000 * model.config.housing.selling_cost_percent / 100
        shortfall = 320000 + selling_costs - 300000
        self.assertAlmostEqual(person.bank_account_balance, 100000 - shortfall, places=2)
        assert_conservation(model)


if __name__ == "__main__":
    unittest.main()
