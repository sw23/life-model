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


if __name__ == "__main__":
    unittest.main()
