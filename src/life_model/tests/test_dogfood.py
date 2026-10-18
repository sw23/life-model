# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Fixes from the Plan 30 dogfood test: a fresh agent modeled a household from the agent docs alone and
reported what it could not represent or what misled it (docs/rebaseline-dogfood.md)."""

import contextlib
import io
import json
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

import yaml

import life_model

from .. import api, cli
from ..account.bank import BankAccount
from ..invariants import InvariantError
from ..results import RunResult
from ..spec import SpecWarning
from .spec_helpers import minimal


def _invoke(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


@contextlib.contextmanager
def _leaky_bank(amount: float = 500.0):
    """Make money appear without a ledger entry: every bank gains ``amount`` (once a year, in December)."""
    original = BankAccount.step

    def step(self):
        original(self)
        if self.model.month == 12:
            self._balance += amount

    with mock.patch.object(BankAccount, "step", step):
        yield


class _SpecFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, data: dict, name: str = "h.yaml") -> Path:
        path = self.tmp / name
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return path


class TestRealDollarConservation(_SpecFile):
    """Friction 1: a real-dollar run reported a conservation failure in every year after the first."""

    def test_real_dollar_result_conserves(self):
        spec = minimal()
        spec["meta"]["end_year"] = 2035
        nominal = life_model.run(spec, seed=1)
        real = nominal.real_dollars()
        self.assertEqual([r.year for r in nominal.conservation() if not r.ok()], [])
        self.assertEqual([r.year for r in real.conservation() if not r.ok()], [])
        # The records are nominal either way (inflation erodes a real opening balance with no ledger flow).
        for a, b in zip(nominal.conservation(), real.conservation(), strict=True):
            self.assertAlmostEqual(a.residual, b.residual, places=4)
            self.assertAlmostEqual(a.closing_net_worth, b.closing_net_worth, places=2)
        # The displayed balance sheets stay in start-year dollars.
        sheet = real.balance_sheets.set_index("year")
        nominal_sheet = nominal.balance_sheets.set_index("year")
        self.assertLess(sheet.loc[2035, "closing_net_worth"], nominal_sheet.loc[2035, "closing_net_worth"])
        self.assertEqual(api.summarize(real)["conservation_failures"], [])

    def test_loaded_real_result_conserves(self):
        spec = minimal()
        result = life_model.run(spec, seed=1, real_dollars=True)
        loaded = RunResult.load(result.to_csv(self.tmp / "out"))
        self.assertTrue(loaded.real)
        self.assertEqual([r.year for r in loaded.conservation() if not r.ok()], [])

    def test_strict_fails_on_a_conservation_failure_in_every_mode(self):
        path = self.write(minimal())
        for extra in ((), ("--real-dollars",)):
            with self.subTest(extra=extra), _leaky_bank():
                code, out, err = _invoke("run", str(path), "--checks", "strict", *extra)
                self.assertEqual(code, cli.EXIT_RUNTIME, msg=out + err)
                self.assertIn("conservation", err)
                code, out, err = _invoke("explain", str(path), "--year", "2027", "--checks", "strict", *extra)
                self.assertEqual(code, cli.EXIT_RUNTIME, msg=out + err)
        with _leaky_bank(), self.assertRaises(InvariantError):
            api.run_montecarlo(minimal(), n=2, seed=1, workers=1, checks="strict")

    def test_warn_reports_the_same_failures_nominal_and_real(self):
        path = self.write(minimal())
        reports = []
        for extra in ((), ("--real-dollars",)):
            with self.subTest(extra=extra), _leaky_bank():
                code, out, err = _invoke("run", str(path), "--json", *extra)
                self.assertEqual(code, 0, msg=err)
                reports.append(json.loads(out)["summary"]["conservation_failures"])
        self.assertEqual(reports[0], [2026, 2027, 2028, 2029, 2030])
        self.assertEqual(reports[0], reports[1])


class TestOutputs(_SpecFile):
    """Friction 16: the summaries answer the questions agents ask without re-running in Python."""

    def test_run_text_always_prints_shortfalls_and_conservation(self):
        code, out, err = _invoke("run", str(self.write(minimal())))
        self.assertEqual(code, 0, msg=err)
        self.assertIn("shortfall years (bills carried as debt): none", out)
        self.assertIn("conservation check: passed in every year", out)
        self.assertIn("net worth peak:", out)
        self.assertIn("lowest cash (year-end bank balance):", out)

    def test_summary_peak_and_lowest_cash(self):
        spec = minimal(retirement_age=43)
        spec["meta"]["end_year"] = 2040
        result = life_model.run(spec, seed=1)
        summary = api.summarize(result)
        frame = result.model_frame.set_index("Year")
        peak = summary["net_worth_peak"]
        self.assertEqual(peak["nominal"]["year"], int(frame["Net Worth"].idxmax()))
        real = result.real_dollars().model_frame.set_index("Year")
        self.assertEqual(peak["real"]["year"], int(real["Net Worth"].idxmax()))
        self.assertAlmostEqual(peak["real"]["amount"], float(real["Net Worth"].max()), places=1)
        low = summary["lowest_cash"]
        self.assertEqual(low["nominal"]["year"], int(frame["Bank Balance"].idxmin()))
        retired = summary["lowest_cash_retired"]
        self.assertGreater(retired["nominal"]["year"], 2029)  # Alex (born 1986-01) retires at 43 in 2029
        # The same numbers from a real-dollar result.
        again = api.summarize(result.real_dollars())
        self.assertEqual(again["net_worth_peak"]["nominal"]["year"], peak["nominal"]["year"])
        self.assertAlmostEqual(again["net_worth_peak"]["nominal"]["amount"], peak["nominal"]["amount"], places=1)

    def test_compare_json_has_yearly_rows_and_text_has_the_shortfall_delta(self):
        path = self.write(minimal())
        code, out, err = _invoke("compare", str(path), "--set", "people[alex].retirement_age=62", "--json")
        self.assertEqual(code, 0, msg=err)
        payload = json.loads(out)
        self.assertEqual(len(payload["base"]["yearly"]), 5)
        self.assertEqual(len(payload["changed"]["yearly"]), 5)
        self.assertIn("net_worth_peak", payload["deltas"])
        code, out, err = _invoke("compare", str(path), "--set", "people[alex].retirement_age=62")
        self.assertIn("shortfall years: 0 -> 0 (+0)", out)
        self.assertIn("net worth peak (start-year dollars):", out)

    def test_montecarlo_real_dollars(self):
        spec = minimal()
        nominal = api.montecarlo_summary(api.run_montecarlo(spec, n=3, seed=2, workers=1, scenario="stochastic"))
        real = api.montecarlo_summary(
            api.run_montecarlo(spec, n=3, seed=2, workers=1, scenario="stochastic", real_dollars=True)
        )
        self.assertEqual((nominal["dollars"], real["dollars"]), ("nominal", "real"))
        self.assertLess(real["final_net_worth"]["p50"], nominal["final_net_worth"]["p50"])
        code, out, err = _invoke("montecarlo", str(self.write(spec)), "--n", "2", "--workers", "1", "--real-dollars")
        self.assertEqual(code, 0, msg=err)
        self.assertIn("real dollars", out)


def _quiet_build(data: dict):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SpecWarning)
        return api.build(data)


def _sam(retirement_age: float, *, history: bool = True) -> dict:
    data = minimal(age=39, birth="1986-09", retirement_age=retirement_age)
    data["meta"]["end_year"] = 2056
    data["people"][0]["jobs"][0]["salary_annual"] = 96000
    ss = {"pia_override_monthly": 2050, "claim_age": 67, "fra_from_birth_year": True}
    if history:
        ss["earnings_history"] = {year: min(90000, 40000 + (year - 2008) * 3000) for year in range(2008, 2026)}
    data["people"][0]["social_security"] = ss
    return data


class TestSocialSecurityOverride(unittest.TestCase):
    """Friction 4: an SSA estimate assumes work until full retirement age."""

    def _benefit(self, data: dict) -> float:
        model = _quiet_build(data)
        model.run()
        return model.household.people["alex"].social_security._pia_by_year[2054]

    def test_override_responds_to_early_retirement_with_an_earnings_history(self):
        at_55, at_60, at_67 = (self._benefit(_sam(age)) for age in (55, 60, 67))
        self.assertLess(at_55, at_60)
        self.assertLess(at_60, at_67)
        # Working to full retirement age at wage growth roughly reproduces the statement's estimate.
        model = _quiet_build(_sam(67))
        model.run()
        self.assertAlmostEqual(model.household.people["alex"].social_security.override_scale(), 1.0, delta=0.05)

    def test_override_alone_is_unchanged_and_warns_for_early_retirement(self):
        self.assertEqual(self._benefit(_sam(55, history=False)), self._benefit(_sam(67, history=False)))
        codes = [f.code for f in life_model.validate(_sam(55, history=False))]
        self.assertIn("ss_estimate_assumes_work", codes)
        self.assertNotIn("ss_estimate_assumes_work", [f.code for f in life_model.validate(_sam(55))])
        self.assertNotIn("ss_estimate_assumes_work", [f.code for f in life_model.validate(_sam(67, history=False))])


class TestContributionPlanWindows(unittest.TestCase):
    """Friction 7: contribution plans can end, and a 529 plan stops when college starts."""

    def _family(self, plan: dict, events: list | None = None, child: dict | None = None) -> dict:
        data = minimal()
        data["meta"]["end_year"] = 2040
        person = data["people"][0]
        person["accounts"].append({"kind": "529", "id": "kid_529", "beneficiary": "kid", "balance": 1000})
        person["accounts"].append({"kind": "brokerage", "id": "taxable", "balance": 1000})
        person["children"] = [{"id": "kid", "name": "Kit", "birth_year": 2017, "birth_month": 6, **(child or {})}]
        person["contribution_plans"] = [plan]
        data["events"] = events or []
        return data

    def _contributions(self, data: dict, account: str) -> "dict[int, float]":
        model = _quiet_build(data)
        result = model.run()
        label = f"{type(model.household.items[account]).__name__}:{model.household.items[account].unique_id}"
        ledger = result.ledger
        rows = ledger[(ledger["to_account"] == label) & (ledger["kind"] == "contribution")]
        return rows.groupby("year")["amount"].sum().round(2).to_dict()

    def test_529_stops_the_month_before_college(self):
        by_year = self._contributions(self._family({"account": "kid_529", "amount_annual": 2400}), "kid_529")
        self.assertEqual(by_year[2026], 2400)
        self.assertEqual(by_year[2034], 2400)
        self.assertAlmostEqual(by_year[2035], 1000, places=2)  # January-May: college starts June 2035
        self.assertNotIn(2036, by_year)
        # An explicit end keeps contributing through college.
        by_year = self._contributions(
            self._family({"account": "kid_529", "amount_annual": 2400, "end": "2038-12"}), "kid_529"
        )
        self.assertEqual(by_year[2037], 2400)
        self.assertNotIn(2039, by_year)

    def test_start_end_until_age_and_events(self):
        plan = {"account": "taxable", "amount_annual": 1200, "start": "2027-07", "end": 2029}
        by_year = self._contributions(self._family(plan), "taxable")
        self.assertEqual(sorted(by_year), [2027, 2028, 2029])
        self.assertAlmostEqual(by_year[2027], 600, places=2)
        by_year = self._contributions(self._family({"account": "taxable", "amount_annual": 1200, "until_age": 42}), "taxable")
        self.assertEqual(sorted(by_year), [2026, 2027])  # Alex (born 1986-01) turns 42 in January 2028
        events = [
            {"at": {"year": 2028, "month": 4}, "person": "alex", "action": "stop_contribution", "account": "taxable"},
            {"at": 2031, "person": "alex", "action": "change_contribution", "account": "taxable", "amount_annual": 2400},
        ]
        by_year = self._contributions(self._family({"account": "taxable", "amount_annual": 1200}, events), "taxable")
        self.assertAlmostEqual(by_year[2028], 300, places=2)  # January-March
        self.assertNotIn(2029, by_year)
        self.assertEqual(by_year[2031], 2400)

    def test_401k_events(self):
        data = minimal()
        data["people"][0]["accounts"].append({"kind": "401k", "id": "k", "job": "job", "pretax_contrib_pct": 10})
        data["events"] = [
            {"at": 2027, "person": "alex", "action": "stop_contribution", "account": "k"},
            {"at": 2029, "person": "alex", "action": "change_contribution", "account": "k", "pay_pct": 5},
        ]
        model = _quiet_build(data)
        result = model.run()
        frame = result.ledger
        deferrals = frame[frame["cause"] == "pre-tax 401k deferral"].groupby("year")["amount"].sum()
        deferrals = deferrals[deferrals.abs() > 0.01]  # a stopped paycheck's true-up nets to zero
        self.assertGreater(deferrals.get(2026, 0), 0)
        self.assertNotIn(2027, deferrals.index)
        self.assertGreater(deferrals.get(2029, 0), 0)


class TestLoanSchedule(unittest.TestCase):
    """Friction 8: a loan statement behind its own schedule."""

    def _car(self, **fields) -> dict:
        data = minimal()
        loan = {"kind": "car", "original_amount": 28000, "term_months": 60, "rate_pct": 6.9, "origination": "2024-02"}
        data["people"][0]["debts"] = [{**loan, "balance": 19450, **fields}]
        return data

    def test_behind_schedule_is_an_error_whose_fix_names_valid_fields(self):
        (finding,) = [f for f in life_model.validate(self._car()) if f.code == "loan_terms"]
        self.assertIn("schedule: statement", finding.fix)
        self.assertIn("balance + rate_pct + payment_monthly", finding.fix)
        for fields in ({"schedule": "statement"}, {"schedule": "statement", "remaining_months": 38}):
            self.assertEqual([f for f in life_model.validate(self._car(**fields)) if f.level == "error"], [])
        # The combination without the original terms validates too.
        data = self._car()
        loan = data["people"][0]["debts"][0]
        for key in ("original_amount", "term_months", "origination"):
            del loan[key]
        loan["payment_monthly"] = 553.11
        self.assertEqual([f for f in life_model.validate(data) if f.level == "error"], [])

    def test_statement_schedule_keeps_the_contract_payment(self):
        loan = _quiet_build(self._car(schedule="statement")).household.people["alex"].car_loans[0]
        self.assertAlmostEqual(loan.principal, 19450)
        self.assertAlmostEqual(loan.monthly_payment, 553.11, places=2)
        self.assertEqual(loan.remaining_months, 40)  # two months past the original 38
        loan = _quiet_build(self._car(schedule="statement", remaining_months=38)).household.people["alex"].car_loans[0]
        self.assertEqual(loan.remaining_months, 38)
        self.assertGreater(loan.monthly_payment, 553.11)


class TestChildAges(unittest.TestCase):
    """Friction 13: care_expenses_annual stops at the 13th birthday month."""

    def _care(self, **child) -> "dict[int, float]":
        data = minimal()
        data["meta"]["end_year"] = 2031
        data["people"][0]["children"] = [
            {"name": "Kit", "birth_year": 2017, "cost_override_annual": 0, "college_cost_annual": 0, **child}
        ]
        data["people"][0]["children"][0]["care_expenses_annual"] = 5400
        model = _quiet_build(data)
        model.run()
        ledger = model.ledger.to_frame()
        care = ledger[ledger["sink"].fillna("").str.contains("dependent care")]
        return care.groupby("year")["amount"].sum().to_dict()

    def test_care_stops_in_the_birthday_month(self):
        care = self._care(birth_month=6)
        self.assertAlmostEqual(care[2029], 5400 * 1.03**3, places=0)
        self.assertAlmostEqual(care[2030], 5400 * 1.03**4 * 5 / 12, places=0)  # January-May
        self.assertNotIn(2031, care)
        self.assertNotIn(2030, self._care())  # no birth month: January

    def test_bands_follow_the_exact_age(self):
        data = minimal()
        data["meta"]["end_year"] = 2036
        data["people"][0]["children"] = [{"name": "Kit", "birth_year": 2017, "birth_month": 6}]
        model = _quiet_build(data)
        child = model.household.people["alex"].children[0]
        model.run()
        self.assertEqual(child.birth_month, 6)
        frame = model.ledger.to_frame()
        college = frame[(frame["sink"].fillna("").str.contains("dependents")) & (frame["year"] == 2035)]
        months = sorted(college["month"].unique())
        self.assertEqual(len(months), 12)
        self.assertGreater(college[college["month"] == 6]["amount"].sum(), 2 * college[college["month"] == 5]["amount"].sum())


class TestStartingStateAndInputs(unittest.TestCase):
    def test_past_marriage_is_not_an_event(self):
        """Friction 17."""
        data = minimal()
        sam = {**minimal()["people"][0], "id": "sam", "name": "Sam"}
        sam["jobs"] = [{**sam["jobs"][0], "id": "sam_job"}]
        data["people"].append(sam)
        for year, expected in ((2015, 0), (None, 0), (2026, 1)):
            marriage = {"spouses": ["alex", "sam"]}
            if year is not None:
                marriage["year"] = year
            data["relationships"] = {"marriages": [marriage]}
            result = _quiet_build(data).run()
            self.assertEqual(int((result.events["kind"] == "married").sum()), expected, year)

    def test_student_loan_type_unknown(self):
        """Friction 18."""
        data = minimal()
        data["people"][0]["debts"] = [{"kind": "student", "balance": 11200, "rate_pct": 4.5, "remaining_months": 41}]
        self.assertEqual([f for f in life_model.validate(data) if f.level == "error"], [])
        loan = _quiet_build(data).household.people["alex"].student_loans[0]
        self.assertEqual(loan.loan_type.name, "UNKNOWN")
        data["people"][0]["debts"][0]["repayment_plan"] = "repayment_assistance_plan"
        self.assertIn("rap_needs_federal_loan", [f.code for f in life_model.validate(data)])

    def test_bonus_is_plan_pay(self):
        """Friction 10: one field for the plan's compensation; match_on_bonus is a deprecated alias."""
        from ..spec import schema

        account = schema.Job401k.model_validate({"kind": "401k", "bonus_is_plan_pay": True})
        self.assertTrue(account.bonus_is_plan_pay)
        with self.assertWarns(UserWarning):
            old = schema.Job401k.model_validate({"kind": "401k", "match_on_bonus": True})
        self.assertEqual(old, account)
        data = minimal()
        data["people"][0]["jobs"][0]["bonus_pct"] = 10
        data["people"][0]["accounts"].append({"kind": "401k", "job": "job", "pretax_contrib_pct": 10})
        deferrals = []
        for flag in (False, True):
            data["people"][0]["accounts"][1]["bonus_is_plan_pay"] = flag
            ledger = _quiet_build(data).run().ledger
            deferrals.append(ledger[(ledger["year"] == 2026) & (ledger["cause"] == "pre-tax 401k deferral")]["amount"].sum())
        self.assertAlmostEqual(deferrals[0], 8000, places=0)
        self.assertAlmostEqual(deferrals[1], 8800, places=0)


if __name__ == "__main__":
    unittest.main()
