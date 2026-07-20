# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for capital gains, qualified dividends, and the net investment income surtax.

Dollar assertions read the frozen fixture config (fixtures/test_config.yaml): ordinary rates are
10% to $40k then 25%, and the preferential schedule is 0% to $40k ($80k MFJ), then 15%, then 20%.
"""

import unittest
from pathlib import Path

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount, TaxLot
from ..config.financial_config import FinancialConfig
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..people.tax_unit import TaxUnit
from ..tax.federal import FilingStatus, capital_gains_tax, net_investment_income_tax
from ..tax.income import IncomeType
from ..tax.tax import compute_taxes

TEST_CONFIG = str(Path(__file__).parent / "fixtures" / "test_config.yaml")


def _fixture_config() -> FinancialConfig:
    """Fresh FinancialConfig loaded from the frozen test fixture."""
    return FinancialConfig(config_file=TEST_CONFIG)


def _person(model: LifeModel, bank_balance: float = 0.0, spending: float = 0.0) -> Person:
    family = Family(model)
    person = Person(family, "P", age=40, retirement_age=70, spending=Spending(model, base=spending))
    BankAccount(person, "Bank", balance=bank_balance, interest_rate=0)
    return person


class TestTaxLots(unittest.TestCase):
    """Basis tracking: FIFO consumption, pro-rata growth, holding-period classification."""

    def setUp(self):
        self.model = LifeModel(start_year=2020, end_year=2030, config=_fixture_config())
        self.person = _person(self.model)

    def test_opening_balance_seeds_a_full_basis_lot(self):
        account = BrokerageAccount(self.person, "B", balance=10000, growth_rate=0)
        self.assertEqual(account.cost_basis, 10000)
        self.assertEqual(account.unrealized_gain, 0)

    def test_growth_is_untaxed_until_sale(self):
        account = BrokerageAccount(self.person, "B", balance=10000, growth_rate=10)
        account.apply_growth()
        self.assertEqual(account.balance, 11000)
        self.assertEqual(account.cost_basis, 10000)
        self.assertEqual(account.unrealized_gain, 1000)
        # Realization principle: growth alone creates no income.
        self.assertEqual(self.person.income.ordinary_taxable, 0)
        self.assertEqual(self.person.income.preferential_income, 0)

    def test_growth_accrues_to_lots_pro_rata(self):
        account = BrokerageAccount(self.person, "B", balance=1000, growth_rate=10)
        account.deposit(3000)  # 25% / 75% split of a $4,000 balance
        account.apply_growth()
        self.assertAlmostEqual(account.lots[0].value, 1100.0, places=6)
        self.assertAlmostEqual(account.lots[1].value, 3300.0, places=6)

    def test_fifo_consumes_oldest_lot_first(self):
        account = BrokerageAccount(self.person, "B", balance=0, growth_rate=0)
        account.lots.append(TaxLot(value=1000, cost_basis=400, acquired_year=2015))
        account.lots.append(TaxLot(value=1000, cost_basis=900, acquired_year=2019))
        account.balance = 2000

        withdrawn, long_term, short_term = account.sell(1000)
        self.assertEqual(withdrawn, 1000)
        self.assertEqual(long_term, 600)  # the older, lower-basis lot
        self.assertEqual(short_term, 0)
        self.assertEqual(len(account.lots), 1)
        self.assertEqual(account.lots[0].cost_basis, 900)

    def test_partial_lot_sale_consumes_basis_proportionally(self):
        account = BrokerageAccount(self.person, "B", balance=0, growth_rate=0)
        account.lots.append(TaxLot(value=1000, cost_basis=400, acquired_year=2015))
        account.balance = 1000

        _, long_term, _ = account.sell(250)  # a quarter of the lot
        self.assertEqual(long_term, 150)  # 250 - (400 * 0.25)
        self.assertEqual(account.lots[0].cost_basis, 300)
        self.assertEqual(account.lots[0].value, 750)

    def test_holding_period_classification(self):
        account = BrokerageAccount(self.person, "B", balance=0, growth_rate=0)
        account.lots.append(TaxLot(value=1000, cost_basis=500, acquired_year=self.model.year))
        account.balance = 1000
        _, long_term, short_term = account.sell(1000)
        self.assertEqual(long_term, 0)
        self.assertEqual(short_term, 500)  # acquired this year

        account.lots.append(TaxLot(value=1000, cost_basis=500, acquired_year=self.model.year - 1))
        account.balance = 1000
        _, long_term, short_term = account.sell(1000)
        self.assertEqual(long_term, 500)
        self.assertEqual(short_term, 0)

    def test_basis_never_exceeds_balance_across_deposits_and_sales(self):
        account = BrokerageAccount(self.person, "B", balance=5000, growth_rate=8)
        for _ in range(5):
            account.apply_growth()
            account.deposit(1000)
            account.sell(2000)
            self.assertLessEqual(round(account.cost_basis, 6), round(account.balance, 6))

    def test_withdraw_posts_gains_to_the_ledger(self):
        account = BrokerageAccount(self.person, "B", balance=0, growth_rate=0)
        account.lots.append(TaxLot(value=1000, cost_basis=400, acquired_year=2015))
        account.balance = 1000
        account.withdraw(1000)
        totals = self.person.income.totals_by_type()
        self.assertEqual(totals[IncomeType.LONG_TERM_CAPITAL_GAIN], 600)
        self.assertEqual(self.person.income.preferential_income, 600)
        # The gain is not swept into the ordinary base — that is the whole point of the channel.
        self.assertEqual(self.person.income.ordinary_taxable, 0)

    def test_person_withdrawal_realizes_gains_and_credits_the_bank(self):
        account = BrokerageAccount(self.person, "B", balance=0, growth_rate=0)
        account.lots.append(TaxLot(value=1000, cost_basis=400, acquired_year=2015))
        account.balance = 1000
        withdrawn = self.person.withdraw_from_brokerage_accounts(1000)
        self.assertEqual(withdrawn, 1000)
        self.assertEqual(self.person.bank_account_balance, 1000)
        self.assertEqual(self.person.income.preferential_income, 600)

    def test_selling_at_a_loss_produces_a_negative_gain(self):
        account = BrokerageAccount(self.person, "B", balance=0, growth_rate=0)
        account.lots.append(TaxLot(value=600, cost_basis=1000, acquired_year=2015))
        account.balance = 600
        _, long_term, _ = account.sell(600)
        self.assertEqual(long_term, -400)


class TestDividends(unittest.TestCase):
    """The dividend yield is carved out of the growth rate, not added on top."""

    def setUp(self):
        self.model = LifeModel(start_year=2020, end_year=2030, config=_fixture_config())
        self.person = _person(self.model)

    def test_default_yield_leaves_growth_untouched(self):
        account = BrokerageAccount(self.person, "B", balance=10000, growth_rate=7)
        account.apply_growth()
        self.assertAlmostEqual(account.balance, 10700.0, places=6)
        self.assertEqual(self.person.income.preferential_income, 0)
        self.assertEqual(len(account.lots), 1)

    def test_dividend_splits_total_return_without_changing_it(self):
        account = BrokerageAccount(self.person, "B", balance=10000, growth_rate=7, dividend_yield=2)
        account.apply_growth()
        # Total return is still 7%: 5% appreciation plus a 2% dividend that is reinvested.
        self.assertAlmostEqual(account.balance, 10700.0, places=6)
        self.assertAlmostEqual(self.person.income.preferential_income, 200.0, places=6)
        totals = self.person.income.totals_by_type()
        self.assertAlmostEqual(totals[IncomeType.QUALIFIED_DIVIDEND], 200.0, places=6)

    def test_reinvested_dividend_gets_full_basis(self):
        account = BrokerageAccount(self.person, "B", balance=10000, growth_rate=7, dividend_yield=2)
        account.apply_growth()
        # $10,000 original basis plus the $200 dividend that was reinvested at cost.
        self.assertAlmostEqual(account.cost_basis, 10200.0, places=6)
        self.assertAlmostEqual(account.unrealized_gain, 500.0, places=6)
        self.assertEqual(len(account.lots), 2)


class TestPreferentialStacking(unittest.TestCase):
    """The gain is stacked above ordinary income; ordinary income fills the low bands first."""

    def setUp(self):
        self.config = _fixture_config()

    def test_gain_alone_fills_the_zero_band(self):
        tax = capital_gains_tax(0, 40000, FilingStatus.SINGLE, self.config)
        self.assertAlmostEqual(tax, 0.0, places=6)

    def test_ordinary_income_pushes_the_gain_into_the_next_band(self):
        # Ordinary income exactly fills the 0% band, so the gain's first dollar is taxed at 15%.
        tax = capital_gains_tax(40000, 10000, FilingStatus.SINGLE, self.config)
        self.assertAlmostEqual(tax, 1500.0, places=6)

    def test_gain_straddling_a_boundary_is_split(self):
        # $30k of ordinary leaves $10k of 0% band; the remaining $10k of gain is taxed at 15%.
        tax = capital_gains_tax(30000, 20000, FilingStatus.SINGLE, self.config)
        self.assertAlmostEqual(tax, 1500.0, places=6)

    def test_negative_preferential_income_is_clamped(self):
        self.assertEqual(capital_gains_tax(50000, -10000, FilingStatus.SINGLE, self.config), 0.0)

    def test_retiree_living_on_gains_owes_no_federal_tax(self):
        # MFJ with $20k ordinary and $80k of long-term gain. The $20k standard deduction wipes out
        # the ordinary income and spills onto the gain, leaving $80k of gain inside the $80k 0%
        # band. This single case pins both the stacking direction and the deduction spillover.
        taxes = compute_taxes(
            20000,
            20000,
            FilingStatus.MARRIED_FILING_JOINTLY,
            [0.0],
            self.config,
            preferential_income=80000,
        )
        self.assertAlmostEqual(taxes.federal, 0.0, places=6)

    def test_deduction_applies_to_ordinary_income_first(self):
        # Single: $30k ordinary, $30k gain, $10k deduction. The deduction comes off ordinary
        # income, leaving $20k ordinary (taxed at 10%) and $30k of gain stacked above it. $20k of
        # the 0% band remains, so $20k of gain is free and $10k is taxed at 15%.
        taxes = compute_taxes(30000, 10000, FilingStatus.SINGLE, [0.0], self.config, preferential_income=30000)
        self.assertAlmostEqual(taxes.federal, 2000.0 + 1500.0, places=6)

    def test_zero_preferential_income_matches_the_ordinary_only_path(self):
        with_arg = compute_taxes(100000, 10000, FilingStatus.SINGLE, [0.0], self.config, preferential_income=0)
        without = compute_taxes(100000, 10000, FilingStatus.SINGLE, [0.0], self.config)
        self.assertEqual(with_arg.federal, without.federal)
        self.assertEqual(with_arg.total, without.total)


class TestNIIT(unittest.TestCase):
    """§1411 surtax: 3.8% on the lesser of net investment income and the MAGI excess."""

    def setUp(self):
        self.config = _fixture_config()

    def test_no_surtax_below_the_threshold(self):
        tax = net_investment_income_tax(50000, 150000, FilingStatus.SINGLE, self.config)
        self.assertEqual(tax, 0.0)

    def test_surtax_limited_by_the_magi_excess(self):
        # $210k MAGI is $10k over the $200k single threshold, so only $10k is surtaxed even
        # though there is $50k of investment income.
        tax = net_investment_income_tax(50000, 210000, FilingStatus.SINGLE, self.config)
        self.assertAlmostEqual(tax, 10000 * 0.038, places=6)

    def test_surtax_limited_by_investment_income(self):
        tax = net_investment_income_tax(5000, 300000, FilingStatus.SINGLE, self.config)
        self.assertAlmostEqual(tax, 5000 * 0.038, places=6)

    def test_mfj_threshold_is_higher(self):
        tax = net_investment_income_tax(50000, 240000, FilingStatus.MARRIED_FILING_JOINTLY, self.config)
        self.assertEqual(tax, 0.0)

    def test_zero_investment_income_owes_nothing(self):
        self.assertEqual(net_investment_income_tax(0, 1000000, FilingStatus.SINGLE, self.config), 0.0)

    def test_wages_are_not_investment_income(self):
        model = LifeModel(start_year=2020, end_year=2020, config=_fixture_config())
        person = _person(model)
        person.income.add_wages(ordinary_amount=500000, fica_wages=500000)
        self.assertEqual(person.income.net_investment_income, 0.0)

    def test_gains_and_dividends_are_investment_income(self):
        model = LifeModel(start_year=2020, end_year=2020, config=_fixture_config())
        person = _person(model)
        person.income.add(IncomeType.LONG_TERM_CAPITAL_GAIN, 10000)
        person.income.add(IncomeType.QUALIFIED_DIVIDEND, 2000)
        person.income.add(IncomeType.INTEREST, 500)
        person.income.add(IncomeType.PRETAX_DISTRIBUTION, 40000)
        self.assertEqual(person.income.net_investment_income, 12500)


class TestCapitalLosses(unittest.TestCase):
    """Losses net against gains, offset $3,000 of ordinary income, and carry forward."""

    def _settle(self, person: Person) -> TaxUnit:
        unit = TaxUnit([person])
        unit._apply_capital_loss_netting()
        return unit

    def setUp(self):
        self.model = LifeModel(start_year=2020, end_year=2030, config=_fixture_config())
        self.person = _person(self.model)

    def test_loss_year_clamps_the_preferential_base_and_offsets_ordinary(self):
        self.person.income.add_wages(ordinary_amount=100000, fica_wages=100000)
        self.person.income.add(IncomeType.LONG_TERM_CAPITAL_GAIN, -10000)
        self._settle(self.person)

        self.assertEqual(self.person.income.preferential_income, 0.0)
        # Exactly $3,000 offsets ordinary income; the other $7,000 carries forward.
        self.assertAlmostEqual(self.person.income.ordinary_taxable, 97000.0, places=6)
        self.assertAlmostEqual(self.person.capital_loss_carryforward, 7000.0, places=6)

    def test_losses_cancel_the_years_gains_first(self):
        self.person.income.add(IncomeType.LONG_TERM_CAPITAL_GAIN, 4000)
        self.person.income.add(IncomeType.SHORT_TERM_CAPITAL_GAIN, -10000)
        self._settle(self.person)
        # Net loss is $6,000: $3,000 offsets ordinary income, $3,000 carries forward.
        self.assertEqual(self.person.income.preferential_income, 0.0)
        self.assertAlmostEqual(self.person.income.ordinary_taxable, -3000.0, places=6)
        self.assertAlmostEqual(self.person.capital_loss_carryforward, 3000.0, places=6)

    def test_carryforward_is_consumed_by_a_later_gain_year(self):
        self.person.capital_loss_carryforward = 7000
        self.person.income.add(IncomeType.LONG_TERM_CAPITAL_GAIN, 20000)
        self._settle(self.person)
        self.assertAlmostEqual(self.person.income.preferential_income, 13000.0, places=6)
        self.assertEqual(self.person.capital_loss_carryforward, 0.0)

    def test_carryforward_consumes_short_term_gains_first(self):
        self.person.capital_loss_carryforward = 5000
        self.person.income.add(IncomeType.SHORT_TERM_CAPITAL_GAIN, 4000)
        self.person.income.add(IncomeType.LONG_TERM_CAPITAL_GAIN, 6000)
        self._settle(self.person)
        totals = self.person.income.totals_by_type()
        self.assertAlmostEqual(totals[IncomeType.SHORT_TERM_CAPITAL_GAIN], 0.0, places=6)
        self.assertAlmostEqual(totals[IncomeType.LONG_TERM_CAPITAL_GAIN], 5000.0, places=6)

    def test_gainless_year_leaves_the_ledger_untouched(self):
        self.person.income.add_wages(ordinary_amount=100000, fica_wages=100000)
        entries_before = len(self.person.income.entries)
        self._settle(self.person)
        self.assertEqual(len(self.person.income.entries), entries_before)

    def test_mfj_carryforward_is_attributed_to_whoever_realized_the_loss(self):
        family = Family(self.model)
        a = Person(family, "A", age=40, retirement_age=70, spending=Spending(self.model, 0))
        b = Person(family, "B", age=40, retirement_age=70, spending=Spending(self.model, 0))
        a.get_married(b)
        a.income.add(IncomeType.LONG_TERM_CAPITAL_GAIN, -20000)
        b.income.add(IncomeType.LONG_TERM_CAPITAL_GAIN, 2000)

        unit = TaxUnit([a, b])
        unit._apply_capital_loss_netting()

        # $18,000 net loss, $3,000 offset, $15,000 carried forward — all of it to the member who
        # actually realized a loss, so a surviving spouse never inherits the decedent's carryover.
        self.assertAlmostEqual(a.capital_loss_carryforward, 15000.0, places=6)
        self.assertEqual(b.capital_loss_carryforward, 0.0)


class TestAgiIncludesGains(unittest.TestCase):
    """AGI must include preferential income or the IRMAA lookback under-charges."""

    def test_settled_agi_includes_capital_gains(self):
        model = LifeModel(start_year=2020, end_year=2020, config=_fixture_config())
        person = _person(model, bank_balance=500000)
        person.income.add_wages(ordinary_amount=50000, fica_wages=50000)
        person.income.add(IncomeType.LONG_TERM_CAPITAL_GAIN, 100000)

        TaxUnit([person]).settle_year()

        # $150k of total income less the $10k fixture standard deduction.
        self.assertAlmostEqual(person.agi_history[2020], 140000.0, places=2)


class TestBasisStepUpAtDeath(unittest.TestCase):
    """IRC §1014: an heir's basis is fair market value at the decedent's death."""

    def setUp(self):
        self.model = LifeModel(start_year=2020, end_year=2030, config=_fixture_config())
        self.family = Family(self.model)
        self.owner = Person(self.family, "Owner", age=80, retirement_age=70, spending=Spending(self.model, 0))
        self.heir = Person(self.family, "Heir", age=50, retirement_age=70, spending=Spending(self.model, 0))
        BankAccount(self.owner, "Bank", balance=0, interest_rate=0)
        BankAccount(self.heir, "Bank", balance=0, interest_rate=0)
        self.owner.estate_beneficiary = self.heir

    def test_immediate_post_inheritance_sale_realizes_nothing(self):
        account = BrokerageAccount(self.owner, "B", balance=0, growth_rate=0)
        account.lots.append(TaxLot(value=100000, cost_basis=20000, acquired_year=2000))
        account.balance = 100000

        self.owner._step_up_taxable_basis()

        self.assertEqual(account.cost_basis, 100000)
        _, long_term, short_term = account.sell(100000)
        self.assertEqual(long_term, 0)
        self.assertEqual(short_term, 0)

    def test_post_death_appreciation_is_taxed_as_long_term(self):
        account = BrokerageAccount(self.owner, "B", balance=0, growth_rate=0)
        account.lots.append(TaxLot(value=100000, cost_basis=20000, acquired_year=2000))
        account.balance = 100000

        self.owner._step_up_taxable_basis()
        account.person = self.heir
        account.balance += 5000
        account.lots[0].value += 5000

        _, long_term, short_term = account.sell(105000)
        self.assertEqual(long_term, 5000)  # inherited property is always long-term
        self.assertEqual(short_term, 0)


class TestWithdrawalSolverWithGains(unittest.TestCase):
    """The fixed-point withdrawal solve still terminates once gains enter the tax base."""

    def test_brokerage_funded_retiree_solve_terminates_without_over_withdrawing(self):
        from ..account.job401k import Job401kAccount
        from ..work.job import Job, Salary

        model = LifeModel(start_year=2020, end_year=2020, config=_fixture_config())
        person = _person(model, bank_balance=0.0, spending=60000)
        job = Job(person, "Old Co", "Retiree", Salary(model=model, base=0))
        Job401kAccount(job=job, pretax_balance=1000000, average_growth=0)
        job.retired = True

        account = BrokerageAccount(person, "B", balance=0, growth_rate=0)
        account.lots.append(TaxLot(value=200000, cost_basis=50000, acquired_year=2000))
        account.balance = 200000
        person.withdraw_from_brokerage_accounts(100000)  # realizes $75k of long-term gain

        unit = TaxUnit([person])
        unit.settle_year()

        # The unit is solvent: bills and taxes were covered without leaving year-end debt, and
        # the solver did not drain the 401k beyond what was actually needed.
        self.assertEqual(person.debt, 0)
        self.assertGreater(sum(a.pretax_balance for a in person.all_retirement_accounts), 0)


if __name__ == "__main__":
    unittest.main()
