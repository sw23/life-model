# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Household goldens (Plan 29 D3): synthetic households whose full-year return was worked from the
IRS forms independently of the library (``scripts/household_goldens.py``; every line's arithmetic is
in the golden's ``worksheet.md``). Each golden's ``expected.json`` is an ``actuals`` record, so the
test is the reconciliation itself: every line the golden states must match the engine within the
golden's tolerance (a cent, except where its JSON says otherwise), and lines marked ``xfail`` (a tax
feature Plan 31 adds) must still differ, so they are noticed when the feature lands.

See ``goldens/households/README.md`` for the format and how to add a golden.
"""

import json
import re
import unittest
from pathlib import Path

from ..reconciliation import RED, reconcile
from ..spec import load
from ..spec.actuals import ActualRecords

GOLDENS = Path(__file__).parent / "goldens" / "households"
SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "household_goldens.py"
HOUSEHOLDS = (
    "single_renter",
    "married_homeowners",
    "head_of_household",
    "retiree_couple",
    "early_retiree",
    "married_separately",
    # Plan 31: credits, deductions and regimes
    "eitc_head_of_household",
    "dependent_care_mfj",
    "education_aotc_mfj",
    "savers_credit_single",
    "iso_amt_single",
    "self_employed_single",
    "kiddie_tax_mfj",
    "appreciated_stock_gift",
    "qcd_retiree",
    "ira_deduction_phaseout",
    "student_loan_phaseout",
    # Plan 31 tasks 6-7: payments, the premium tax credit, filing statuses
    "withholding_single",
    "estimated_payments_penalty",
    "aca_ptc_early_retirees",
    "qss_widow",
    "hoh_dependent_parent",
)
#: Goldens that need a prior year (the minimum tax credit after an ISO exercise), or whose state rules are
#: packed for 2025 and 2026 only (part-year residency, one golden per Plan 31 state pack): 2025 and 2026.
FOLLOW_ON = (
    "iso_amt_credit",
    "part_year_mover",
    *(f"state_{code}" for code in ("oh", "ga", "nc", "mi", "nj", "va", "az", "tn", "in", "mo", "md")),
)


def goldens() -> list[Path]:
    return sorted(path for path in GOLDENS.iterdir() if (path / "expected.json").is_file())


def run_golden(directory: Path, actuals: dict | None = None):
    expected = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
    spec = load(directory / "spec.yaml")
    records = ActualRecords.model_validate(actuals if actuals is not None else expected["actuals"])
    report = reconcile(spec, expected["year"], actuals=records, checks="strict")
    return expected, report


def line_key(item) -> str:
    """The golden's key for a report line: ``[filer/]section:line`` (W-2 lines: ``W-2:box 1@person``)."""
    prefix = ""
    match = re.match(r"return of (\w+)", item.source or "")
    if match:
        prefix = f"{match.group(1)}/"
    key = f"{prefix}{item.section}:{item.line}"
    if item.section == "W-2":
        key += "@" + item.source.split(" / ")[-1]
    return key


class TestHouseholdGoldens(unittest.TestCase):
    def test_coverage(self):
        names = {path.name for path in goldens()}
        for household in HOUSEHOLDS:
            for year in (2024, 2025, 2026):
                self.assertIn(f"{household}_{year}", names)
        for household in FOLLOW_ON:
            for year in (2025, 2026):
                self.assertIn(f"{household}_{year}", names)

    def test_every_golden_matches_the_engine(self):
        for directory in goldens():
            with self.subTest(golden=directory.name):
                expected, report = run_golden(directory)
                tolerances = expected["tolerance"]
                xfail = expected["xfail"]
                compared = 0
                for item in report.lines:
                    key = line_key(item)
                    self.assertIsNotNone(item.simulated, f"{key}: the engine has no value for a golden line")
                    tolerance = tolerances.get(key, tolerances["default"])
                    difference = abs(item.simulated - item.actual)
                    if key in xfail:
                        self.assertGreater(difference, tolerance, f"{key} now matches: remove its xfail ({xfail[key]})")
                    else:
                        self.assertLessEqual(
                            difference,
                            tolerance,
                            f"{key}: engine {item.simulated:,.2f}, golden {item.actual:,.2f} ({item.label})",
                        )
                    compared += 1
                self.assertGreater(compared, 25)

    def test_exact_rate_schedule_tax(self):
        """Line 16 by the exact rate schedule (the engine never uses the Tax Table) to the cent."""
        for directory in goldens():
            expected, report = run_golden(directory)
            for key, value in expected["exact"].items():
                filer, _, line = key.rpartition("/")
                with self.subTest(golden=directory.name, line=key):
                    item = report.find("1040", line.split(":")[1], source=f"return of {filer}" if filer else None)
                    engine_tax = item.simulated
                    if f"exact:{key}" in expected["xfail"]:
                        self.assertNotAlmostEqual(engine_tax, value, places=2)
                    else:
                        self.assertAlmostEqual(engine_tax, value, places=2)

    def test_reconciling_a_golden_against_itself_has_no_red_lines(self):
        for directory in goldens():
            with self.subTest(golden=directory.name):
                expected, report = run_golden(directory)
                red = {line_key(item) for item in report.red}
                # A golden with no expected failures reconciles with zero red lines; one with xfails is
                # red only on those lines.
                self.assertLessEqual(red, set(expected["xfail"]))

    def test_a_perturbed_golden_names_the_line_and_cause(self):
        directory = GOLDENS / "head_of_household_2025"
        expected = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
        actuals = json.loads(json.dumps(expected["actuals"]))
        # The filed return reports $1,500 more interest (a 1099-INT the spec is missing) and a $1,000
        # child and dependent care credit the engine does not compute (Schedule 3 line 2).
        for line in ("2b", "9", "11a", "11b", "15"):
            actuals["form_1040"][line] += 1500
        actuals["form_1040"]["20"] = 1000
        actuals["form_1040"]["21"] += 1000
        actuals["schedules"]["3"] = {"2": 1000, "8": 1000}
        _, report = run_golden(directory, actuals)
        interest = report.find("1040", "2b")
        self.assertEqual((interest.status, interest.cause), (RED, "missing_income_source"))
        self.assertEqual(report.find("1040", "9").cause, "propagated")
        self.assertIn("follows 1040 line 2b", report.find("1040", "15").note)
        self.assertEqual(report.find("schedule 3", "2").cause, "unmodeled_credit")
        self.assertEqual(report.find("1040", "20").cause, "propagated")  # follows Schedule 3 line 8

    def test_worksheets_are_independent_of_the_library(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"^\s*(from|import)\s+life_model", "the golden worksheets must not use the library")
        self.assertNotIn("from life_model", source)


if __name__ == "__main__":
    unittest.main()
