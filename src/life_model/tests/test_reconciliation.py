# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Actual records in the spec and the reconciliation report (Plan 29 tasks 1-2). The household
goldens (``test_household_goldens.py``) reconcile real hand-computed returns; these tests cover the
records, the mapping and the cause classification on a synthetic example."""

import json
import tempfile
import unittest
import warnings
from pathlib import Path

import yaml

from .. import api, cli, mcp
from ..reconciliation import GREEN, NOT_MODELED, RED, form_1040_lines, reconcile, run_for_reconciliation
from ..spec import ERROR, HouseholdSpec, build_model, dumps, load_example, loads, to_data, validate_spec
from ..spec.actuals import FORM_1040_LINES, ActualRecords
from .test_cli import invoke, invoke_json

YEAR = 2026


def _spec() -> HouseholdSpec:
    return load_example("married_homeowners")


def _simulated_records() -> ActualRecords:
    """The example's own simulated 2026 return as whole-dollar 'actuals' (what a filed return shows)."""
    sim = run_for_reconciliation(_spec(), YEAR)
    lines = form_1040_lines(sim.model.tax_returns[YEAR])
    return ActualRecords(form_1040={line: round(value) for line, value in lines.items()})


class TestActualRecordsInTheSpec(unittest.TestCase):
    def test_round_trip_and_builder_ignores_them(self):
        data = to_data(_spec())
        data["actuals"] = {YEAR: {"form_1040": {"1a": 99550, "11a": 99882}, "balances": {"john_job": 1.0}}}
        spec = HouseholdSpec.model_validate(data)
        self.assertEqual(loads(dumps(spec)), spec)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with_actuals = build_model(spec, check=False).run().model_frame
            without = build_model(_spec(), check=False).run().model_frame
        self.assertTrue(with_actuals.equals(without))

    def test_validator_checks_lines_and_ids(self):
        data = to_data(_spec())
        data["actuals"] = {
            YEAR: {
                "form_1040": {"11": 1.0, "1a": 2.0},
                "balances": {"nope": 1.0},
                "w2": [{"person": "zed", "employer": "X"}],
            },
            2019: {"form_1040": {"1a": 1.0}},
        }
        findings = validate_spec(data)
        errors = {(f.path, f.code) for f in findings if f.level == ERROR}
        self.assertIn((f"actuals.{YEAR}.form_1040.11", "unknown_line"), errors)  # 2026 uses 11a / 11b
        self.assertIn((f"actuals.{YEAR}.balances.nope", "unknown_ref"), errors)
        self.assertIn((f"actuals.{YEAR}.w2[0].person", "unknown_ref"), errors)
        self.assertIn("actuals_outside_run", {f.code for f in findings})

    def test_line_tables_follow_the_forms(self):
        self.assertIn("7", FORM_1040_LINES[2024])
        self.assertIn("7a", FORM_1040_LINES[2025])
        self.assertIn("13b", FORM_1040_LINES[2025])
        self.assertIn("24c", FORM_1040_LINES[2026])

    def test_one_return_or_returns(self):
        with self.assertRaises(ValueError):
            ActualRecords(form_1040={"1a": 1}, returns=[{"form_1040": {"1a": 1}}])


class TestReconcile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = _simulated_records()

    def test_own_return_has_no_red_lines(self):
        report = reconcile(_spec(), YEAR, actuals=self.records)
        self.assertEqual(report.red, [])
        self.assertEqual(report.by_status("yellow"), [])
        self.assertGreater(len(report.by_status(GREEN)), 20)

    def test_perturbed_income_names_the_line_and_cause(self):
        lines = dict(self.records.form_1040)
        for line in ("2b", "9", "11a", "11b", "15"):
            lines[line] += 1500  # interest the spec does not have, carried through the totals
        report = reconcile(_spec(), YEAR, actuals=ActualRecords(form_1040=lines))
        root = report.find("1040", "2b")
        self.assertEqual((root.status, root.cause), (RED, "input_difference"))
        for line in ("9", "11a", "15"):
            item = report.find("1040", line)
            self.assertEqual(item.cause, "propagated", line)
        self.assertIn("follows 1040 line 2b", report.find("1040", "9").note)

    def test_unmodeled_credit_and_timing(self):
        lines = {**self.records.form_1040, "20": 600, "25a": 9000}
        report = reconcile(_spec(), YEAR, actuals=ActualRecords(form_1040=lines))
        self.assertEqual(report.find("1040", "20").cause, "unmodeled_credit")
        withheld = report.find("1040", "25a")
        self.assertEqual((withheld.status, withheld.cause), (NOT_MODELED, "timing"))

    def test_documents_and_unit_mismatch(self):
        records = ActualRecords(
            w2=[{"person": "john", "employer": "Pizza Papa", "boxes": {"1": 43000, "3": 50500, "5": 50500, "2": 4000}}],
            paystub=[
                {"person": "john", "gross_monthly": 50500, "pretax_deductions_monthly": {"401k": 625, "health": 300}}
            ],
            spending={"living_annual": 24000},
        )
        report = reconcile(_spec(), YEAR, actuals=records)
        self.assertEqual(report.find("W-2", "box 1").status, GREEN)
        self.assertEqual(report.find("W-2", "box 2").cause, "timing")
        self.assertEqual(report.find("paystub", "gross").cause, "unit_mismatch")  # an annual figure entered monthly
        self.assertEqual(report.find("paystub", "health").cause, "missing_input")
        self.assertEqual(report.find("spending", "living_annual").status, GREEN)

    def test_renderers(self):
        report = reconcile(_spec(), YEAR, actuals=self.records)
        markdown = report.to_markdown()
        self.assertIn("# Reconciliation: Married homeowners, 2026", markdown)
        self.assertIn("| 11a |", markdown)
        data = json.loads(report.to_json())
        self.assertEqual(data["counts"]["red"], 0)
        self.assertEqual(
            {"section", "line", "simulated", "actual", "difference", "status", "cause"} - set(data["lines"][0]), set()
        )

    def test_part_year_start_reconciles_only_the_simulated_months(self):
        spec = _spec()
        part = spec.model_copy(update={"meta": spec.meta.model_copy(update={"start": f"{YEAR}-05"})})
        full_return = run_for_reconciliation(spec, YEAR).model.tax_returns[YEAR]
        sim = run_for_reconciliation(part, YEAR)
        self.assertEqual(sim.model.months_in_year(YEAR), 8)  # May-December (before John's June birthday)
        part_lines = form_1040_lines(sim.model.tax_returns[YEAR])
        full_lines = form_1040_lines(full_return)
        # May-December gross pay: 8/12 of the year's (same pay, no raise inside the year).
        full_wages = sum(e.amount for e in run_for_reconciliation(spec, YEAR).entries() if e.kind == "wage")
        part_wages = sum(e.amount for e in sim.entries() if e.kind == "wage")
        self.assertAlmostEqual(part_wages, full_wages * 8 / 12, delta=1.0)
        self.assertLess(part_lines["1a"], full_lines["1a"] * 0.7)
        records = ActualRecords(form_1040={line: round(value) for line, value in part_lines.items()})
        report = reconcile(part, YEAR, actuals=records)
        self.assertEqual(report.red, [])
        self.assertTrue(any("part year" in note and f"{YEAR}-05" in note for note in report.notes))
        # The full-year return against the part-year run is red on wages, with the note explaining why.
        full = ActualRecords(form_1040={line: round(value) for line, value in full_lines.items()})
        report = reconcile(part, YEAR, actuals=full)
        self.assertEqual(report.find("1040", "1a").status, RED)
        self.assertTrue(any("last 8 months" in note for note in report.notes))

    def test_api_errors(self):
        with self.assertRaises(api.InputError):
            api.reconcile(_spec(), YEAR)  # no actuals in the spec
        with self.assertRaises(api.InputError):
            api.reconcile(_spec(), 2025, actuals=self.records)  # before start_year


class TestCommandLineAndMcp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        records = _simulated_records()
        self.actuals = self.dir / "actuals.yaml"
        self.actuals.write_text(yaml.safe_dump({YEAR: records.model_dump(mode="json", exclude_defaults=True)}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_cli_text_and_json(self):
        code, out, _ = invoke(
            "reconcile", "--example", "married_homeowners", "--year", str(YEAR), "--actuals", str(self.actuals)
        )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("0 red", out)
        code, payload = invoke_json(
            "reconcile",
            "--example",
            "married_homeowners",
            "--year",
            str(YEAR),
            "--actuals",
            str(self.actuals),
            "--json",
        )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(payload["report"]["counts"]["red"], 0)

    def test_cli_errors(self):
        code, payload = invoke_json("reconcile", "--example", "married_homeowners", "--year", str(YEAR), "--json")
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertIn("No actual records", payload["error"]["message"])
        code, _ = invoke_json(
            "reconcile", "--example", "married_homeowners", "--year", str(YEAR), "--years", "2", "--json"
        )
        self.assertEqual(code, cli.EXIT_INVALID)

    def test_spec_actuals_and_mcp_tool(self):
        data = to_data(_spec())
        data["actuals"] = yaml.safe_load(self.actuals.read_text())
        result = mcp.reconcile_household(YEAR, spec=data)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["report"]["counts"]["red"], 0)
        self.assertIn("Reconciliation", result["markdown"])
        bad = mcp.reconcile_household(YEAR, example="married_homeowners")
        self.assertFalse(bad["ok"])


if __name__ == "__main__":
    unittest.main()
