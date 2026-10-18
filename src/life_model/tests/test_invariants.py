# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The invariant checker (Plan 29 D4): every packaged example and broad scenario passes under
``checks="strict"``, each invariant catches the violation it exists for, and the cash-floor rule
flags the pre-Plan-26 married-homeowner waterfall."""

import unittest
import warnings
from dataclasses import replace
from unittest import mock

from .. import invariants
from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount
from ..account.traditional_IRA import TraditionalIRA
from ..invariants import InvariantError, InvariantWarning, check_model
from ..ledger import FlowKind
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..people.tax_unit import TaxUnit
from ..spec import ERROR, EXAMPLES, build_model, load_example, validate_spec
from ..work.job import Job, Salary
from . import scenarios


def _quiet(function, *args, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return function(*args, **kwargs)


def _simple_model(*, years: int = 3, checks: str = "strict", bank: float = 20000.0) -> LifeModel:
    model = LifeModel(start_year=2026, end_year=2026 + years - 1, checks=checks)
    family = Family(model)
    person = Person(family=family, name="Avery", age=40, retirement_age=65, spending=Spending(model, base_annual=30000))
    BankAccount(owner=person, company="Bank", balance=bank)
    Job(owner=person, company="Acme", role="Analyst", salary=Salary(model, base_annual=80000))
    return model


class TestExamplesAndScenariosAreClean(unittest.TestCase):
    def test_every_runnable_example_runs_fifty_years_strict(self):
        for name in EXAMPLES:
            spec = load_example(name)
            if any(f.level == ERROR for f in validate_spec(spec)):
                continue  # shows a not-yet-supported field (self_employed)
            spec = spec.model_copy(
                update={"meta": spec.meta.model_copy(update={"end_year": spec.meta.start_year + 49})}
            )
            for seed in (1, 2):
                with self.subTest(example=name, seed=seed):
                    model = _quiet(build_model, spec, seed=seed)
                    model.checks = "strict"
                    _quiet(model.run)
                    self.assertEqual(model.invariant_violations, [])

    def test_broad_scenarios_strict(self):
        builders = {
            "married_homeowners": scenarios.married_homeowners,
            "renter_buys_home": scenarios.renter_buys_home,
            "mortality_and_estate": scenarios.mortality_and_estate,
        }
        # Seeds 4, 7 and 11 used to over-sell brokerage in a year with a capital-loss carryforward.
        for seed in (1, 4, 7, 11, 22):
            builders[f"stochastic_retiree_{seed}"] = lambda seed=seed: scenarios.stochastic_retiree(seed)
            builders[f"everything_stochastic_{seed}"] = lambda seed=seed: scenarios.everything_stochastic(seed)
        for name, build in builders.items():
            with self.subTest(scenario=name):
                model = build()
                model.checks = "strict"
                _quiet(model.run)
                self.assertEqual(model.invariant_violations, [])


class TestModes(unittest.TestCase):
    def test_default_is_off(self):
        model = LifeModel(start_year=2026, end_year=2027)
        self.assertEqual(model.checks, "off")

    def test_bad_mode(self):
        with self.assertRaises(ValueError):
            LifeModel(start_year=2026, checks="loud")

    def test_checks_record_balance_sheets_without_data_collection(self):
        model = LifeModel(start_year=2026, end_year=2027, collect_data=False, checks="strict")
        family = Family(model)
        person = Person(
            family=family, name="Avery", age=40, retirement_age=65, spending=Spending(model, base_annual=1000)
        )
        BankAccount(owner=person, company="Bank", balance=5000)
        model.run()
        self.assertEqual(sorted(model.balance_sheets), [2026, 2027])
        self.assertEqual(check_model(model), [])

    def _break_bank(self, model):
        """Make money appear inside a year: the bank pays interest that is never posted."""
        bank = next(a for a in model.agents if isinstance(a, BankAccount))
        original = BankAccount.step

        def step(self):
            original(self)
            if self is bank:
                self._balance += 500.0

        return mock.patch.object(BankAccount, "step", step)

    def test_strict_raises(self):
        model = _simple_model()
        with self._break_bank(model), self.assertRaises(InvariantError) as raised:
            model.run()
        self.assertEqual(raised.exception.violations[0].invariant, "conservation")
        self.assertIn("residual 500.00", str(raised.exception))

    def test_warn_warns_and_keeps_going(self):
        model = _simple_model(checks="warn")
        with self._break_bank(model), self.assertWarns(InvariantWarning):
            model.run()
        self.assertEqual({v.year for v in model.invariant_violations}, {2026, 2027, 2028})

    def test_off_does_nothing(self):
        model = _simple_model(checks="off")
        with self._break_bank(model):
            model.run()
        self.assertEqual(model.invariant_violations, [])


class TestEachInvariant(unittest.TestCase):
    def _run(self, model):
        model.checks = "warn"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model.run()
        return {v.invariant for v in model.invariant_violations}

    def test_continuity_flags_money_moved_between_years(self):
        model = _simple_model(checks="warn")
        bank = next(a for a in model.agents if isinstance(a, BankAccount))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model.step_year()
            bank.balance += 1000  # a driver moved money without posting it
            model.step_year()
            model.step_year()
        found = [v for v in model.invariant_violations if v.invariant == "continuity"]
        self.assertEqual([v.year for v in found], [2027])
        self.assertIsNone(found[0].month)
        self.assertAlmostEqual(found[0].amount, 1000.0)

    def test_continuity_flags_money_moved_between_months(self):
        model = _simple_model(checks="warn")
        bank = next(a for a in model.agents if isinstance(a, BankAccount))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for _ in range(4):
                model.step()
            bank.balance += 1000  # moved between April and May without a ledger entry
            model.step_year()
        found = [v for v in model.invariant_violations if v.invariant == "continuity"]
        self.assertEqual([(v.year, v.month) for v in found], [(2026, 5)])
        self.assertAlmostEqual(found[0].amount, 1000.0)
        self.assertIn("2026-04's close and 2026-05's open", found[0].message)

    def test_continuity_accepts_posted_moves(self):
        model = _simple_model(checks="strict")
        person = next(a for a in model.agents if isinstance(a, Person))
        model.step_year()
        person.receive_cash(1000, source="gift from a relative", kind=FlowKind.GIFT)
        model.step()
        person.receive_cash(1000, source="gift from a relative", kind=FlowKind.GIFT)
        model.step_year()
        self.assertEqual(model.invariant_violations, [])

    def test_monthly_conservation_catches_money_moved_inside_a_year(self):
        model = _simple_model(years=1, checks="warn")
        bank = next(a for a in model.agents if isinstance(a, BankAccount))
        original = BankAccount.step

        def step(self):
            original(self)
            if self is bank and model.month in (3, 9):
                # Unposted: +500 in March, -500 in September; the year nets to zero.
                self._balance += 500.0 if model.month == 3 else -500.0

        with mock.patch.object(BankAccount, "step", step):
            found = self._run(model)
        self.assertNotIn("conservation", found)
        months = [(v.month, round(v.amount, 2)) for v in model.invariant_violations]
        self.assertEqual(months, [(3, 500.0), (9, -500.0)])
        self.assertTrue(all(v.invariant == "monthly_conservation" for v in model.invariant_violations))

    def test_negative_balance(self):
        model = _simple_model()
        bank = next(a for a in model.agents if isinstance(a, BankAccount))
        original = BankAccount.post_step

        def post_step(self):
            original(self)
            if self is bank:
                model.ledger.post(bank.balance + 50, FlowKind.OTHER, from_account=bank, sink="test")
                self._balance = -50.0

        with mock.patch.object(BankAccount, "post_step", post_step):
            found = self._run(model)
        self.assertIn("no_negative_balances", found)
        self.assertNotIn("conservation", found)

    def test_contribution_limit(self):
        model = _simple_model()
        person = next(a for a in model.agents if isinstance(a, Person))
        ira = TraditionalIRA(owner=person, balance=0, contribution_limit_annual=50000)
        original = TraditionalIRA.pre_step

        def pre_step(self):
            original(self)
            if self is ira and model.month == 1:
                self.contribute(20000, from_account=person.bank_accounts[0])
                person.bank_accounts[0].balance -= 20000

        with mock.patch.object(TraditionalIRA, "pre_step", pre_step):
            found = [v for v in self._run_violations(model) if v.invariant == "contribution_limits"]
        self.assertTrue(found)
        self.assertIn("IRA contributions: 20,000.00 contributed, limit 7,500.00", found[0].message)

    def _run_violations(self, model):
        self._run(model)
        return model.invariant_violations

    def test_income_after_job_end(self):
        model = _simple_model(years=3)
        person = next(a for a in model.agents if isinstance(a, Person))
        job = person.jobs[0]
        original = Job.pre_step

        def pre_step(self):
            original(self)
            if model.year == 2027:
                job.retire()
            if model.year == 2028 and model.month == 1:
                person.receive_cash(5000, source="Acme", kind=FlowKind.WAGE)

        with mock.patch.object(Job, "pre_step", pre_step):
            violations = self._run_violations(model)
        found = [v for v in violations if v.invariant == "no_income_after_job_end"]
        self.assertEqual([v.year for v in found], [2028])

    def test_rmd_minimum(self):
        model = LifeModel(start_year=2026, end_year=2027)
        family = Family(model)
        person = Person(
            family=family, name="Rory", age=76, retirement_age=65, spending=Spending(model, base_annual=1000)
        )
        BankAccount(owner=person, company="Bank", balance=50000)
        TraditionalIRA(owner=person, balance=100000)
        with mock.patch.object(TraditionalIRA, "pre_step", lambda self: None):
            violations = self._run_violations(model)
        found = [v for v in violations if v.invariant == "rmd_minimum"]
        self.assertEqual(len(found), 2)
        self.assertIn("required 4,219.41", found[0].message)  # 100,000 / 23.7 (age 76)

    def test_return_lines(self):
        model = _simple_model(years=1)
        original = TaxUnit.settle_year

        def settle_year(self):
            original(self)
            key = max(model.tax_returns)
            bad = model.tax_returns[key]
            fica = (replace(bad.fica[0], social_security=bad.fica[0].social_security + 10),)
            model.tax_returns[key] = replace(
                bad, fica=fica, deduction=bad.deduction + 5, state_tax=-1.0, deduction_taken="itemized"
            )

        with mock.patch.object(TaxUnit, "settle_year", settle_year):
            found = self._run(model)
        for name in ("fica_wage_base", "taxes_non_negative", "deduction_choice", "return_identities"):
            self.assertIn(name, found)


class TestCashFloorRegressionGuard(unittest.TestCase):
    """Before Plan 26 each spouse settled through their own waterfall: the head sold brokerage to pay
    the household's bills while the spouse's bank still held cash. Reconstructing that sizing (the
    unit sees only the head's bank) must trip ``no_draw_above_cash_floor``; the real engine must not."""

    def _couple(self) -> LifeModel:
        model = LifeModel(start_year=2026, end_year=2027)
        family = Family(model)
        head = Person(
            family=family, name="Jordan", age=50, retirement_age=50, spending=Spending(model, base_annual=40000)
        )
        spouse = Person(
            family=family, name="Casey", age=50, retirement_age=50, spending=Spending(model, base_annual=10000)
        )
        head.get_married(spouse)
        BankAccount(owner=head, company="Bank", balance=1000)
        BankAccount(owner=spouse, company="Credit Union", balance=80000)
        BrokerageAccount(owner=head, company="Brokerage", balance=200000, growth_pct=0)
        return model

    def test_engine_spends_spouse_cash_before_selling(self):
        model = self._couple()
        model.checks = "strict"
        model.run()
        self.assertEqual(model.invariant_violations, [])
        # 2026's bills fit in the two banks together; the brokerage is first sold in 2027 (monthly
        # from the month the banks run dry).
        sales = [e.year for e in model.event_log.list if e.kind.value == "forced_sale"]
        self.assertEqual(sorted(set(sales)), [2027])

    def test_pre_plan_26_waterfall_is_flagged(self):
        model = self._couple()
        # The unit sees (sizes against, and pays from) only the head's bank.
        head_only = property(lambda self: self.members[0].bank_account_balance)
        head_banks = lambda self: list(self.members[0].bank_accounts)
        with (
            mock.patch.object(TaxUnit, "bank_account_balance", head_only),
            mock.patch.object(TaxUnit, "_bank_accounts_in_draw_order", head_banks),
        ):
            violations = _quiet(lambda: (setattr(model, "checks", "warn"), model.run(), model.invariant_violations)[2])
        found = [v for v in violations if v.invariant == "no_draw_above_cash_floor"]
        self.assertEqual(found[0].year, 2026)
        self.assertIn("Jordan, Casey", found[0].message)


class TestBrokerageSizingWithCarryforward(unittest.TestCase):
    """The sale that funds the year is sized against the gains *after* a prior-year loss carryforward
    nets them, so nothing is over-sold into the bank (found by ``no_draw_above_cash_floor``)."""

    def test_no_cash_left_after_a_netted_sale(self):
        model = LifeModel(start_year=2026, end_year=2026, checks="strict")
        family = Family(model)
        person = Person(
            family=family, name="Ari", age=62, retirement_age=60, spending=Spending(model, base_annual=60000)
        )
        BankAccount(owner=person, company="Bank", balance=0)
        account = BrokerageAccount(owner=person, company="Brokerage", balance=0, growth_pct=0)
        account.deposit_with_basis(400000, 100000)
        person.capital_loss_carryforward = 20000.0
        model.run()
        self.assertLess(person.bank_account_balance, invariants.CASH_FLOOR_TOLERANCE)
        tax_return = model.tax_returns[2026]
        self.assertGreater(tax_return.capital_loss_carryforward_used, 0)


if __name__ == "__main__":
    unittest.main()
