# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Accounts entered as the statements show them.

Existing positions (brokerage lots, IRA / Roth / HSA / 529 basis), fixed-income holdings, standalone and
after-tax 401(k) money, Roth conversions, portfolio allocation, recurring contributions and the surplus sweep.
Dollar assertions read published years (2026) of the packaged ``tax_years`` table or constructed balances.
"""

import unittest
import warnings

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount, Lot
from ..account.fixed_income import FixedIncomeHolding
from ..account.hsa import HealthSavingsAccount
from ..account.job401k import Job401kAccount
from ..account.roth_IRA import RothIRA
from ..account.traditional_IRA import TraditionalIRA
from ..dependents.plan529 import Plan529
from ..invariants import check_model
from ..ledger import FlowKind
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..policies import ContributionPlan, RothConversionPolicy, SavingsPolicy, convert_to_roth
from ..tax.income import IncomeType
from ..work.job import Job, Salary


def _model(start=2026, end=None, **kwargs):
    kwargs.setdefault("checks", "strict")
    return LifeModel(start_year=start, end_year=end or start, **kwargs)


def _person(model, name="Alex", age=40, bank=0.0, spending=0.0, retirement_age=67):
    person = Person(Family(model), name, age=age, retirement_age=retirement_age, spending=Spending(model, spending))
    if bank is not None:
        BankAccount(person, company="Bank", balance=bank, interest_pct=0)
    return person


def _income(person, income_type, source=None):
    return sum(
        e.amount
        for e in person.income.entries
        if e.income_type == income_type and (source is None or e.source == source)
    )


class TestBrokerageLots(unittest.TestCase):
    def test_statement_lot_with_embedded_gain_sells_at_its_long_term_gain(self):
        """Acceptance: an account entered with a $300k value / $120k basis sells with a $180k LTCG."""
        model = _model()
        alex = _person(model)
        account = BrokerageAccount(alex, lots=[Lot(300_000, 120_000, "2018-05")], growth_pct=0, dividend_yield_pct=0)
        self.assertEqual(account.balance, 300_000)
        self.assertEqual(account.cost_basis, 120_000)
        account.withdraw(300_000)
        self.assertAlmostEqual(_income(alex, IncomeType.LONG_TERM_CAPITAL_GAIN), 180_000, places=6)
        self.assertEqual(_income(alex, IncomeType.SHORT_TERM_CAPITAL_GAIN), 0)

    def test_recent_lot_is_short_term_and_balance_and_lots_are_exclusive(self):
        model = _model()
        alex = _person(model)
        account = BrokerageAccount(alex, lots=[Lot(10_000, 8_000, "2025-09")], growth_pct=0, dividend_yield_pct=0)
        account.withdraw(10_000)
        self.assertAlmostEqual(_income(alex, IncomeType.SHORT_TERM_CAPITAL_GAIN), 2_000, places=6)
        with self.assertRaises(ValueError):
            BrokerageAccount(alex, balance=5, lots=[Lot(1, 1)])

    def test_dividends_paid_to_the_bank(self):
        model = _model(checks="off")
        alex = _person(model)
        account = BrokerageAccount(alex, balance=100_000, growth_pct=0, dividend_yield_pct=2, reinvest_dividends=False)
        model.step_year()
        self.assertAlmostEqual(alex.bank_accounts[0].balance + account.balance, 100_000 + 0, delta=1e-6)
        self.assertGreater(alex.bank_accounts[0].balance, 0)
        dividends = [e for e in model.ledger if e.kind == FlowKind.DIVIDEND.value]
        self.assertTrue(dividends)
        self.assertTrue(all(e.to_account.startswith("BankAccount") for e in dividends))


class TestAllocation(unittest.TestCase):
    def test_blended_return_rebalanced_yearly_and_expense_ratio(self):
        model = _model(end=2027)
        alex = _person(model)
        blended = BrokerageAccount(
            alex, balance=100_000, allocation={"equity": 70, "bond": 30}, dividend_yield_pct=0, expense_ratio_pct=0
        )
        self.assertAlmostEqual(blended.growth_rate, 0.7 * 7 + 0.3 * 3, places=9)  # fixed economy
        model.step_year()
        # Each sleeve compounds at its own rate within the year (drift), then rebalances.
        self.assertAlmostEqual(blended.balance, 100_000 * (0.7 * 1.07 + 0.3 * 1.03), places=2)
        self.assertEqual(blended._weights, blended.allocation)
        model2 = _model()
        bob = _person(model2)
        fee = BrokerageAccount(bob, balance=100_000, growth_pct=7, dividend_yield_pct=0, expense_ratio_pct=1)
        model2.step_year()
        monthly = (1.07 ** (1 / 12) - 1) - 0.01 / 12
        self.assertAlmostEqual(fee.balance, 100_000 * (1 + monthly) ** 12, places=2)
        with self.assertRaises(ValueError):
            TraditionalIRA(bob, allocation={"equity": 50})


class TestIraBasis(unittest.TestCase):
    def test_roth_with_basis_taxes_and_penalizes_only_the_earnings(self):
        """Acceptance: a Roth with $50k basis / $80k balance under 59.5 pays tax + penalty only on $30k."""
        model = _model()
        alex = _person(model, age=45)
        roth = RothIRA(alex, balance=80_000, contribution_basis=50_000)
        self.assertAlmostEqual(roth.earnings, 30_000)
        self.assertAlmostEqual(roth.tax_free_withdrawable(), 50_000)
        alex.withdraw_from_roth_iras(80_000)
        self.assertAlmostEqual(_income(alex, IncomeType.PRETAX_DISTRIBUTION), 30_000, places=6)
        self.assertAlmostEqual(alex.income.penalties, 3_000, places=6)

    def test_roth_ordering_contributions_then_conversions_then_earnings(self):
        model = _model()
        alex = _person(model, age=45)
        roth = RothIRA(alex, balance=100_000, contribution_basis=20_000, conversion_basis=30_000)
        roth.withdraw(50_000)  # contributions and (seasoned) conversions: no tax, no penalty
        self.assertEqual(_income(alex, IncomeType.PRETAX_DISTRIBUTION), 0)
        self.assertEqual(alex.income.penalties, 0)
        self.assertAlmostEqual(roth.earnings, 50_000)
        # A conversion made this year is tax-free on the way out but its taxable part is penalized (< 5 years).
        roth.receive_conversion(10_000, taxable=10_000)
        roth.withdraw(10_000)
        self.assertAlmostEqual(alex.income.penalties_by_source["roth_conversion_recapture"], 1_000)

    def test_traditional_ira_distributions_are_pro_rata_to_form_8606_basis(self):
        model = _model()
        alex = _person(model, age=62)
        ira = TraditionalIRA(alex, balance=100_000, nondeductible_basis=20_000, growth_pct=0)
        TraditionalIRA(alex, balance=100_000, growth_pct=0)  # basis is aggregated across the owner's IRAs
        alex.withdraw_from_traditional_iras(20_000)
        self.assertAlmostEqual(_income(alex, IncomeType.PRETAX_DISTRIBUTION), 18_000, places=6)
        self.assertAlmostEqual(ira.nondeductible_basis, 18_000, places=6)

    def test_ira_catch_up_from_fifty(self):
        model = _model()
        young = TraditionalIRA(_person(model, age=40))
        older = RothIRA(_person(model, "Lee", age=55))
        self.assertEqual(young.annual_contribution_limit(), 7_500)  # 2026: Notice 2025-67
        self.assertEqual(older.annual_contribution_limit(), 7_500 + 1_100)

    def test_hsa_and_529_basis(self):
        model = _model()
        alex = _person(model)
        hsa = HealthSavingsAccount(alex, balance=10_000, basis=6_000)
        self.assertAlmostEqual(hsa.earnings, 4_000)
        plan = Plan529(alex, balance=20_000, basis=12_000, growth_pct=0)
        _, penalty = plan.withdraw_non_qualified(10_000)
        self.assertAlmostEqual(_income(alex, IncomeType.ORDINARY, "529_nonqualified"), 4_000, places=6)
        self.assertAlmostEqual(penalty, 400, places=6)


class TestRothConversion(unittest.TestCase):
    def test_conversion_is_pro_rata_ordinary_income_and_a_transfer(self):
        model = _model()
        alex = _person(model, age=50, bank=50_000)
        ira = TraditionalIRA(alex, balance=100_000, nondeductible_basis=25_000, growth_pct=0)
        roth = RothIRA(alex, growth_pct=0)
        model.step()
        converted = convert_to_roth(alex, 40_000)
        self.assertEqual(converted, 40_000)
        self.assertAlmostEqual(_income(alex, IncomeType.PRETAX_DISTRIBUTION, "roth_conversion"), 30_000, places=6)
        self.assertAlmostEqual(ira.nondeductible_basis, 15_000, places=6)
        self.assertAlmostEqual(roth.conversion_basis, 40_000)
        transfers = [e for e in model.ledger if e.cause == "2026 Roth conversion"]
        self.assertEqual(sum(e.amount for e in transfers), 40_000)
        self.assertEqual(alex.income.penalties, 0)  # a conversion is not an early distribution
        model.step_year()
        self.assertEqual(check_model(model), [])

    def test_fill_the_twelve_percent_bracket(self):
        model = _model()
        alex = _person(model, age=66, bank=200_000)
        TraditionalIRA(alex, balance=500_000, growth_pct=0)
        alex.roth_conversion_policy = RothConversionPolicy(fill_bracket_pct=12)
        model.step_year()
        tax_return = model.tax_returns[2026]
        # 2026 single: the 12% bracket ends at $50,400 of taxable income (Rev. Proc. 2025-32).
        self.assertAlmostEqual(tax_return.taxable_ordinary_income, 50_400, delta=1.0)
        self.assertEqual(tax_return.marginal_rate, 12)
        self.assertGreater(alex.roth_iras[0].conversion_basis, 50_000)

    def test_in_plan_conversion_of_a_401k(self):
        model = _model()
        alex = _person(model, age=50)
        plan = Job401kAccount(owner=alex, pretax_balance=50_000, roth_balance=0, roth_basis=0, growth_pct=0)
        convert_to_roth(alex, 10_000, source=plan)
        self.assertEqual(plan.pretax_balance, 40_000)
        self.assertEqual(plan.roth_balance, 10_000)
        self.assertEqual(plan.roth_basis, 10_000)
        self.assertAlmostEqual(_income(alex, IncomeType.PRETAX_DISTRIBUTION, "roth_conversion"), 10_000)


class TestStandaloneAndAfterTax401k(unittest.TestCase):
    def test_old_employer_plan_without_a_job(self):
        model = _model(end=2027)
        alex = _person(model, age=50, spending=24_000)
        old = Job401kAccount(owner=alex, pretax_balance=100_000, growth_pct=0)
        self.assertTrue(old.is_standalone)
        self.assertIn(old, alex.all_retirement_accounts)
        with self.assertRaises(ValueError):
            ContributionPlan(old, pct_of_pay=5, source="payroll")
        model.run()  # the waterfall draws it (taxed and penalized before 59.5)
        self.assertLess(old.balance, 100_000)
        self.assertEqual(check_model(model), [])

    def test_after_tax_contributions_convert_in_plan_and_stay_outside_402g(self):
        model = _model()
        alex = _person(model, age=40)
        job = Job(alex, company="Example Analytics", salary=Salary(model, base_annual=200_000))
        plan = Job401kAccount(
            job,
            pretax_contrib_pct=10,
            after_tax_contrib_pct=10,
            in_plan_roth_conversion=True,
            roth_basis=0,
            growth_pct=0,
        )
        model.step_year()
        self.assertAlmostEqual(plan.pretax_balance, 20_000, places=2)
        self.assertAlmostEqual(plan.roth_balance, 20_000, places=2)
        self.assertAlmostEqual(plan.roth_basis, 20_000, places=2)
        self.assertAlmostEqual(alex.elective_deferrals_ytd + 0, 0)  # reset at the year end
        self.assertEqual(check_model(model), [])

    def test_after_tax_bucket_earnings_are_taxable_on_withdrawal(self):
        model = _model()
        alex = _person(model, age=62)
        plan = Job401kAccount(owner=alex, after_tax_balance=10_000, after_tax_basis=6_000, growth_pct=0)
        alex.withdraw_from_after_tax_401ks(5_000)
        self.assertAlmostEqual(_income(alex, IncomeType.PRETAX_DISTRIBUTION), 2_000, places=6)
        self.assertAlmostEqual(plan.after_tax_basis, 3_000, places=6)

    def test_roth_401k_basis_taxes_early_earnings_pro_rata(self):
        model = _model()
        alex = _person(model, age=45)
        plan = Job401kAccount(owner=alex, roth_balance=40_000, roth_basis=30_000, growth_pct=0)
        alex.withdraw_from_roth_401ks(20_000)
        self.assertAlmostEqual(_income(alex, IncomeType.PRETAX_DISTRIBUTION, "roth_401k_earnings"), 5_000, places=6)
        self.assertAlmostEqual(alex.income.penalties, 500, places=6)
        self.assertAlmostEqual(plan.roth_basis, 15_000, places=6)

    def test_super_catch_up_at_sixty_to_sixty_three(self):
        model = _model()
        self.assertEqual(_person(model, age=61).remaining_401k_elective_room(), 24_500 + 11_250)
        self.assertEqual(_person(model, "Lee", age=55).remaining_401k_elective_room(), 24_500 + 8_000)
        self.assertEqual(_person(model, "Sam", age=70).remaining_401k_elective_room(), 24_500 + 8_000)


class TestFixedIncome(unittest.TestCase):
    def test_cd_matures_to_the_bank(self):
        """Acceptance: a CD matures to the bank."""
        model = _model()
        alex = _person(model)
        cd = FixedIncomeHolding(alex, kind="cd", face=10_000, rate_pct=4.8, maturity="2026-06", reserve=False)
        model.step_year()
        expected = 10_000 * (1 + 0.048 / 12) ** 6
        self.assertTrue(cd.matured)
        self.assertEqual(cd.balance, 0)
        self.assertAlmostEqual(alex.bank_accounts[0].balance, expected, places=2)
        self.assertAlmostEqual(_income(alex, IncomeType.INTEREST) + 0, 0)  # the ledger was settled
        self.assertAlmostEqual(model.tax_returns[2026].taxable_interest, expected - 10_000, places=2)
        self.assertEqual(check_model(model), [])

    def test_cd_early_withdrawal_penalty_is_deductible(self):
        model = _model()
        alex = _person(model)
        cd = FixedIncomeHolding(
            alex, kind="cd", face=12_000, rate_pct=5, maturity="2028-01", early_withdrawal_penalty_months=6
        )
        cash = cd.redeem(12_000)
        self.assertAlmostEqual(cash, 12_000 - 12_000 * 0.05 / 12 * 6)
        self.assertAlmostEqual(-_income(alex, IncomeType.ORDINARY, "early_withdrawal_penalty"), 300)

    def test_treasury_coupon_is_state_exempt_and_paid_to_the_bank(self):
        model = _model()
        alex = _person(model)
        FixedIncomeHolding(alex, kind="treasury", face=100_000, rate_pct=4.2, maturity="2030-11")
        model.step()
        self.assertAlmostEqual(alex.bank_accounts[0].balance, 350.0)
        self.assertAlmostEqual(_income(alex, IncomeType.TREASURY_INTEREST), 350.0)

    def test_i_bond_lock_penalty_and_deferral(self):
        model = _model()
        alex = _person(model)
        bond = FixedIncomeHolding(alex, kind="i_bond", face=10_000, rate_pct=1.0, purchased="2025-09")
        self.assertEqual(bond.redeemable, 0)  # locked for 12 months
        composite = bond.i_bond_composite_rate()
        self.assertAlmostEqual(composite, (0.01 + 2 * 0.015 + 0.01 * 0.015) * 100)  # 3% inflation economy
        for _ in range(12):
            model.step()
        self.assertGreater(bond.redeemable, 10_000)
        interest = bond.accrued_interest
        self.assertEqual(_income(alex, IncomeType.TREASURY_INTEREST), 0)  # deferred
        cash = bond.redeem(bond.balance)
        self.assertLess(cash, 10_000 + interest)  # the last three months' interest is forfeited
        self.assertGreater(_income(alex, IncomeType.TREASURY_INTEREST), 0)

    def test_reserves_are_drawn_last(self):
        model = _model(end=2027)
        alex = _person(model, spending=24_000)
        BankAccount(alex, company="Credit Union", type="Savings", balance=30_000, reserve=True, interest_pct=0)
        treasury = FixedIncomeHolding(alex, kind="treasury", face=30_000, rate_pct=0, maturity="2040-01")
        brokerage = BrokerageAccount(alex, balance=30_000, growth_pct=0, dividend_yield_pct=0)
        model.step_year()
        self.assertAlmostEqual(brokerage.balance, 6_000, delta=1.0)
        self.assertEqual(treasury.balance, 30_000)
        self.assertEqual(alex.reserve_bank_balance(), 30_000)
        model.step_year()  # the brokerage runs out: the reserve bank, then the reserve Treasury
        self.assertEqual(brokerage.balance, 0)
        self.assertLess(alex.reserve_bank_balance(), 30_000)
        self.assertEqual(check_model(model), [])


class TestYearlySpending(unittest.TestCase):
    def test_a_part_year_counts_only_the_months_simulated(self):
        model = LifeModel(start="2026-10", end_year=2026, checks="strict")
        alex = _person(model, bank=100_000, spending=60_000)
        self.assertAlmostEqual(alex.spending.get_yearly_spending(), 15_000)  # October through December
        self.assertAlmostEqual(alex.spending.year_spending_lines()["base"], 15_000)
        model.step_year()
        self.assertAlmostEqual(alex.bank_account_balance, 85_000, places=2)
        self.assertEqual(check_model(model), [])

    def test_a_mid_year_change_counts_the_months_at_each_base(self):
        model = _model()
        alex = _person(model, bank=100_000, spending=12_000)
        self.assertAlmostEqual(alex.spending.get_yearly_spending(), 12_000)
        for _ in range(6):
            model.step()
        alex.spending.base = 24_000
        self.assertAlmostEqual(alex.spending.get_yearly_spending(), 6 * 1_000 + 6 * 2_000)
        model.step_year()
        self.assertAlmostEqual(alex.bank_account_balance, 100_000 - 18_000, places=2)
        self.assertAlmostEqual(alex.spending.get_yearly_spending(), 24_000)  # next year, at its base


class TestPolicies(unittest.TestCase):
    def test_sweep_moves_surplus_above_the_floor(self):
        """Acceptance: the sweep moves surplus above the floor."""
        model = _model()
        alex = _person(model, bank=100_000)
        brokerage = BrokerageAccount(alex, growth_pct=0, dividend_yield_pct=0)
        alex.savings_policy = SavingsPolicy(cash_floor=20_000, sweep_to=brokerage)
        model.step_year()
        self.assertAlmostEqual(alex.bank_account_balance, 20_000, places=2)
        self.assertAlmostEqual(brokerage.balance, 80_000, places=2)
        self.assertEqual(check_model(model), [])

    def test_sweep_to_a_bond_holding(self):
        model = _model()
        alex = _person(model, bank=50_000)
        bonds = FixedIncomeHolding(alex, kind="bond_fund", face=0, rate_pct=3, growth_pct=3)
        alex.savings_policy = SavingsPolicy(cash_floor=10_000, sweep_to=bonds)
        model.step_year()
        self.assertAlmostEqual(bonds.balance, 40_000, places=2)

    def _ira_sweeper(self, *, plan: bool):
        model = _model(end=2027)
        alex = _person(model, bank=50_000)
        Job(alex, company="Example Analytics", salary=Salary(model, base_annual=60_000))
        ira = TraditionalIRA(alex, growth_pct=0)
        if plan:
            alex.add_contribution_plan(ContributionPlan(ira, amount_annual="max"))
        alex.savings_policy = SavingsPolicy(cash_floor=10_000, sweep_to=ira)
        return model, alex, ira

    def test_sweep_into_an_ira_is_made_at_the_year_start_and_deducted_that_year(self):
        """A sweep into a tax-advantaged account runs at the start of the year: the year-end return is
        settled by then, so a year-end contribution would be deducted on no return."""
        model, alex, ira = self._ira_sweeper(plan=False)
        limits = []
        for year in (2026, 2027):
            limits.append(ira.annual_contribution_limit())
            model.step_year()
            self.assertAlmostEqual(ira.balance, sum(limits), places=2)
            self.assertAlmostEqual(model.tax_returns[year].adjustments["ira_deduction"], limits[-1], places=2)
        self.assertGreaterEqual(alex.bank_account_balance, 10_000)
        self.assertEqual(check_model(model), [])

    def test_sweep_into_an_ira_shares_the_years_room_with_the_contribution_plan(self):
        model, _alex, ira = self._ira_sweeper(plan=True)
        limits = []
        for year in (2026, 2027):
            limits.append(ira.annual_contribution_limit())
            model.step_year()
            self.assertAlmostEqual(ira.balance, sum(limits), places=2)
            self.assertAlmostEqual(model.tax_returns[year].adjustments["ira_deduction"], limits[-1], places=2)
        self.assertEqual(check_model(model), [])

    def test_a_cd_matures_with_its_interest_labeled_as_the_cds(self):
        model = _model()
        alex = _person(model)
        cd = FixedIncomeHolding(
            alex, kind="cd", face=10_000, rate_pct=4.0, maturity="2026-02", accrued_interest=200, growth_pct=0
        )
        for _ in range(2):
            model.step()
        self.assertTrue(cd.matured)
        interest = _income(alex, cd.income_type, source="cd_interest")
        self.assertGreater(interest, 200)  # the opening accrual plus two months'
        self.assertAlmostEqual(interest, _income(alex, cd.income_type))  # all of it labeled as the CD's
        self.assertEqual(_income(alex, cd.income_type, source="i_bond_interest"), 0)

    def test_ira_contribution_plan_maxes_out_from_the_bank(self):
        model = _model(end=2027)
        alex = _person(model, bank=0)
        Job(alex, company="Example Analytics", salary=Salary(model, base_annual=60_000))
        ira = TraditionalIRA(alex, growth_pct=0)
        plan = alex.add_contribution_plan(ContributionPlan(ira, amount_annual="max"))
        model.step_year()
        self.assertAlmostEqual(ira.balance, 7_500, places=2)
        plan.set_amount(1_200)  # change it between months
        model.step_year()
        self.assertAlmostEqual(ira.balance, 8_700, places=2)
        alex.remove_contribution_plan(ira)
        self.assertEqual(alex.contribution_plans, ())
        self.assertEqual(check_model(model), [])

    def test_401k_rate_plan_writes_the_deferral_percent(self):
        model = _model()
        alex = _person(model)
        job = Job(alex, company="Example Analytics", salary=Salary(model, base_annual=100_000))
        plan_account = Job401kAccount(job, growth_pct=0)
        plan = alex.add_contribution_plan(ContributionPlan(plan_account, pct_of_pay=6, source="payroll"))
        self.assertEqual(plan_account.pretax_contrib_percent, 6)
        plan.set_rate(10)
        self.assertEqual(plan_account.pretax_contrib_percent, 10)
        alex.add_contribution_plan(ContributionPlan(plan_account, amount_annual="max", source="payroll", bucket="roth"))
        self.assertAlmostEqual(plan_account.roth_contrib_percent, 24.5)
        model.step_year()
        self.assertAlmostEqual(plan_account.balance, 24_500, places=2)  # pre-tax first, then the Roth room left

    def test_hsa_max_through_payroll(self):
        model = _model()
        alex = _person(model, bank=10_000)
        from ..work.payroll import PayrollDeductions

        Job(
            alex,
            company="Example Analytics",
            salary=Salary(model, base_annual=90_000),
            payroll=PayrollDeductions(hsa_employer_annual=600),
        )
        hsa = HealthSavingsAccount(alex, growth_pct=0, employer_contribution_annual=0)
        alex.add_contribution_plan(ContributionPlan(hsa, amount_annual="max", source="payroll"))
        model.step_year()
        self.assertAlmostEqual(hsa.balance, 4_400, places=2)  # 2026 self-only limit (Rev. Proc. 2025-19)
        self.assertEqual(check_model(model), [])


class TestDeprecatedAliases(unittest.TestCase):
    def test_old_names_and_positional_arguments_still_work_with_a_warning(self):
        model = _model()
        alex = _person(model)
        with self.assertWarns(DeprecationWarning):
            account = BrokerageAccount(alex, "Example Brokerage", 1000, 5)
        self.assertEqual((account.company, account.balance, account.growth_rate), ("Example Brokerage", 1000, 5))
        with self.assertWarns(DeprecationWarning):
            bank = BankAccount(owner=alex, company="Bank", interest_rate=1.5)
        self.assertEqual(bank.interest_rate, 1.5)
        with self.assertWarns(DeprecationWarning):
            ira = TraditionalIRA(person=alex, growth_rate=4)
        self.assertEqual(ira.person, alex)
        with self.assertRaises(TypeError):
            TraditionalIRA(alex, growth_rate=4, growth_pct=5)
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            BrokerageAccount(alex, company="Example Brokerage", balance=1, growth_pct=5)
