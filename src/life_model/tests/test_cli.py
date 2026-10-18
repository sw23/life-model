# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The ``life-model`` command line (Plan 30 D1): subcommands, the --json contract, exit codes."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from .. import cli
from ..spec import example_path

REPO_ROOT = Path(__file__).resolve().parents[3]


def invoke(*argv: str) -> tuple[int, str, str]:
    """Run the CLI in-process; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def invoke_json(*argv: str) -> tuple[int, dict]:
    code, out, _ = invoke(*argv, "--json")
    return code, json.loads(out)


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.spec_path = self.tmp / "h.yaml"
        code, _, err = invoke("examples", "--copy", "married_homeowners", str(self.spec_path))
        self.assertEqual(code, 0, msg=err)

    def tearDown(self):
        self._tmp.cleanup()

    def write_spec(self, data: dict, name: str = "edited.yaml") -> Path:
        path = self.tmp / name
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return path

    def spec_data(self) -> dict:
        return yaml.safe_load(self.spec_path.read_text(encoding="utf-8"))


class TestRun(CliTestCase):
    def test_run_example_prints_a_table_and_summary(self):
        code, out, err = invoke("run", "--example", "single_renter", "--years", "3")
        self.assertEqual(code, 0, msg=err)
        self.assertIn("Year", out)
        self.assertIn("Net Worth", out)
        self.assertIn("2026-2028", out)
        self.assertIn("final net worth (2028)", out)

    def test_run_writes_json_result(self):
        out_dir = self.tmp / "out"
        code, payload = invoke_json("run", str(self.spec_path), "--years", "4", "--out", str(out_dir), "--seed", "3")
        self.assertEqual(code, 0, msg=payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "run")
        summary = payload["summary"]
        self.assertEqual(summary["years"], [2026, 2029])
        self.assertEqual(summary["seed"], 3)
        self.assertEqual(len(summary["yearly"]), 4)
        self.assertEqual(summary["conservation_failures"], [])
        document = json.loads((out_dir / "result.json").read_text())
        self.assertEqual(payload["files"], [str((out_dir / "result.json").resolve())])
        self.assertEqual(len(document["model_frame"]), 4)
        self.assertEqual(document["spec"]["meta"]["name"], "Married homeowners")

    def test_run_writes_csv_tables(self):
        out_dir = self.tmp / "csv"
        code, _, err = invoke("run", str(self.spec_path), "--years", "2", "--out", str(out_dir), "--format", "csv")
        self.assertEqual(code, 0, msg=err)
        for name in ("model", "agents", "ledger", "events", "balance_sheets", "tax_returns"):
            self.assertTrue((out_dir / f"{name}.csv").exists(), name)
        self.assertTrue((out_dir / "meta.json").exists())

    def test_run_writes_parquet_tables(self):
        try:
            import pyarrow  # noqa: F401
        except ImportError:  # pragma: no cover - depends on the environment
            self.skipTest("pyarrow not installed")
        out_dir = self.tmp / "pq"
        code, _, err = invoke("run", str(self.spec_path), "--years", "2", "--out", str(out_dir), "--format", "parquet")
        self.assertEqual(code, 0, msg=err)
        self.assertTrue((out_dir / "ledger.parquet").exists())

    def test_parquet_without_pyarrow_fails_before_writing(self):
        out_dir = self.tmp / "nopq"
        with mock.patch.dict("sys.modules", {"pyarrow": None}):
            code, payload = invoke_json("run", str(self.spec_path), "--out", str(out_dir), "--format", "parquet")
        self.assertEqual(code, cli.EXIT_RUNTIME)
        self.assertIn("life-model[parquet]", payload["error"]["message"])
        self.assertFalse(out_dir.exists())

    def test_real_dollars_and_end_year(self):
        code, payload = invoke_json("run", str(self.spec_path), "--end-year", "2028", "--real-dollars")
        self.assertEqual(code, 0, msg=payload)
        self.assertEqual(payload["summary"]["dollars"], "real")
        self.assertEqual(payload["summary"]["years"], [2026, 2028])

    def test_warnings_are_reported(self):
        code, payload = invoke_json("run", str(self.spec_path), "--years", "2")
        self.assertEqual(code, 0)
        self.assertTrue(any("after end_year" in w for w in payload["warnings"]), payload["warnings"])

    def test_spec_is_required(self):
        code, payload = invoke_json("run")
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertFalse(payload["ok"])
        self.assertIn("required", payload["error"]["message"])

    def test_spec_and_example_are_exclusive(self):
        code, _, err = invoke("run", str(self.spec_path), "--example", "single_renter")
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertIn("not both", err)

    def test_missing_file_is_invalid_input(self):
        code, payload = invoke_json("run", str(self.tmp / "nope.yaml"))
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertIn("No such spec file", payload["error"]["message"])

    def test_unknown_scenario_is_a_validation_error(self):
        code, payload = invoke_json("run", str(self.spec_path), "--scenario", "no_such_scenario")
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertEqual(payload["error"]["kind"], "validation")
        self.assertEqual(payload["error"]["findings"][0]["code"], "unknown_scenario")

    def test_validator_errors_exit_2_with_findings(self):
        code, payload = invoke_json("run", "--example", "self_employed")
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertEqual(payload["error"]["findings"][0]["code"], "not_yet_supported")
        self.assertNotIn("findings", {k for k in payload if k != "error"})

    def test_schema_errors_exit_2(self):
        data = self.spec_data()
        data["people"][0]["agee"] = 40
        code, payload = invoke_json("run", str(self.write_spec(data)))
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertTrue(payload["error"]["findings"][0]["code"].startswith("schema."))

    def test_strict_checks_fail_on_warnings(self):
        code, payload = invoke_json("run", str(self.spec_path), "--years", "2", "--checks", "strict")
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertTrue(all(f["level"] == "warning" for f in payload["error"]["findings"]))
        code, _ = invoke_json("run", str(self.spec_path), "--years", "2", "--checks", "off")
        self.assertEqual(code, 0)

    def test_runtime_errors_exit_1(self):
        with mock.patch("life_model.api.run", side_effect=RuntimeError("boom")):
            code, payload = invoke_json("run", str(self.spec_path))
        self.assertEqual(code, cli.EXIT_RUNTIME)
        self.assertEqual(payload["error"]["kind"], "runtime")
        self.assertIn("boom", payload["error"]["message"])
        with mock.patch("life_model.api.run", side_effect=RuntimeError("boom")):
            code, _, err = invoke("run", str(self.spec_path))
        self.assertEqual(code, cli.EXIT_RUNTIME)
        self.assertIn("error: RuntimeError: boom", err)

    def test_usage_errors_follow_the_json_contract(self):
        code, payload = invoke_json("run", "--bogus-flag")
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertFalse(payload["ok"])
        self.assertIn("unrecognized arguments", payload["error"]["message"])


class TestOutputGuard(CliTestCase):
    def test_refuses_out_inside_src(self):
        target = REPO_ROOT / "src" / "plan30-should-not-exist"
        code, payload = invoke_json("run", str(self.spec_path), "--years", "1", "--out", str(target))
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertIn("Refusing", payload["error"]["message"])
        self.assertFalse(target.exists())

    def test_refuses_out_inside_the_package(self):
        target = Path(cli.__file__).resolve().parent / "out"
        with self.assertRaises(ValueError):
            cli.check_output_path(target)
        self.assertFalse(target.exists())

    def test_refuses_copy_into_src(self):
        code, _, err = invoke("examples", "--copy", "single_renter", str(REPO_ROOT / "src" / "x.yaml"))
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertIn("Refusing", err)

    def test_allows_other_directories(self):
        self.assertEqual(cli.check_output_path(self.tmp / "out"), (self.tmp / "out").resolve())


class TestValidate(CliTestCase):
    def test_valid_spec(self):
        code, out, _ = invoke("validate", str(self.spec_path))
        self.assertEqual(code, 0)
        self.assertIn("no findings", out)
        code, payload = invoke_json("validate", str(self.spec_path))
        self.assertEqual(payload["valid"], True)
        self.assertEqual(payload["error_count"], 0)

    def test_invalid_spec_lists_findings_on_stdout(self):
        data = self.spec_data()
        data["people"][0]["state"] = "ZZ"
        code, out, _err = invoke("validate", str(self.write_spec(data)))
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertIn("no state tax pack", out)
        self.assertIn("[error]", out)
        code, payload = invoke_json("validate", str(self.write_spec(data)))
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["findings"][0]["code"], "unknown_state")
        self.assertEqual(payload["error"]["findings"], payload["findings"])

    def test_schema_error(self):
        path = self.tmp / "bad.yaml"
        path.write_text("spec_version: 1\nmeta: {name: x}\npeople: []\n")
        code, payload = invoke_json("validate", str(path))
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertEqual(payload["findings"][0]["path"], "meta.start_year")

    def test_scenario_is_checked(self):
        code, payload = invoke_json("validate", str(self.spec_path), "--scenario", "nope")
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertEqual(payload["findings"][0]["code"], "unknown_scenario")


class TestExplain(CliTestCase):
    def test_explain_a_year(self):
        code, out, err = invoke("explain", str(self.spec_path), "--year", "2027", "--years", "3")
        self.assertEqual(code, 0, msg=err)
        self.assertTrue(out.startswith("# 2027"))
        self.assertIn("## Tax returns", out)
        code, payload = invoke_json("explain", str(self.spec_path), "--year", "2027", "--years", "3")
        self.assertEqual(payload["year"], 2027)
        self.assertIn("## Net worth", payload["markdown"])

    def test_year_outside_the_run(self):
        code, payload = invoke_json("explain", str(self.spec_path), "--year", "1999", "--years", "2")
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertIn("outside the simulated years", payload["error"]["message"])

    def test_year_is_required(self):
        code, _, err = invoke("explain", str(self.spec_path))
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertIn("--year", err)


class TestCompare(CliTestCase):
    def test_set_retirement_age(self):
        code, payload = invoke_json(
            "compare", str(self.spec_path), "--years", "10", "--seed", "1", "--set", "people[john].retirement_age=50"
        )
        self.assertEqual(code, 0, msg=payload)
        self.assertEqual(payload["seed"], 1)
        self.assertEqual(payload["changes"]["sets"], ["people[john].retirement_age=50"])
        # Retiring years earlier means less pay, so less net worth and less tax.
        self.assertLess(payload["deltas"]["final_net_worth"], 0)
        self.assertLess(payload["deltas"]["total_taxes"], 0)
        self.assertIsNone(payload["montecarlo"])

    def test_change_file_appends_an_event(self):
        change = self.tmp / "change.yaml"
        change.write_text(
            "events+:\n"
            "  - id: kitchen\n"
            "    at: {year: 2027}\n"
            "    person: jane\n"
            "    action: one_time_expense\n"
            "    amount: 40000\n"
        )
        code, out, err = invoke("compare", str(self.spec_path), "--years", "4", "--seed", "1", "--change", str(change))
        self.assertEqual(code, 0, msg=err)
        self.assertIn("final net worth", out)
        code, payload = invoke_json(
            "compare", str(self.spec_path), "--years", "4", "--seed", "1", "--change", str(change)
        )
        self.assertLess(payload["deltas"]["final_net_worth"], -40000)
        self.assertEqual(payload["changes"]["patch"]["events+"][0]["id"], "kitchen")

    def test_a_noop_change_has_zero_deltas(self):
        code, payload = invoke_json("compare", str(self.spec_path), "--years", "5", "--set", "meta.name=Renamed")
        self.assertEqual(code, 0, msg=payload)
        self.assertEqual(payload["deltas"]["final_net_worth"], 0)
        self.assertEqual(payload["deltas"]["total_taxes"], 0)
        self.assertEqual(payload["base"]["seed"], payload["changed"]["seed"])

    def test_change_is_required(self):
        code, payload = invoke_json("compare", str(self.spec_path))
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertIn("needs a change", payload["error"]["message"])

    def test_bad_path_and_invalid_result(self):
        code, payload = invoke_json("compare", str(self.spec_path), "--set", "people[nobody].age=3")
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertIn("nobody", payload["error"]["message"])
        code, payload = invoke_json("compare", str(self.spec_path), "--set", "people[john].age=-3")
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertTrue(payload["error"]["findings"])

    def test_montecarlo_success_rates(self):
        code, out, err = invoke(
            "compare",
            "--example",
            "married_homeowners",
            "--years",
            "5",
            "--seed",
            "2",
            "--scenario",
            "stochastic",
            "--set",
            "people[jane].spending.amount_annual=15000",
            "--montecarlo",
            "3",
            "--workers",
            "1",
        )
        self.assertEqual(code, 0, msg=err)
        self.assertIn("success rate (3 trials)", out)


class TestMonteCarlo(CliTestCase):
    def test_stochastic_trials(self):
        out_dir = self.tmp / "mc"
        args = ("montecarlo", str(self.spec_path), "--n", "3", "--seed", "4", "--years", "5", "--workers", "1")
        code, payload = invoke_json(*args, "--scenario", "stochastic", "--out", str(out_dir), "--format", "csv")
        self.assertEqual(code, 0, msg=payload)
        summary = payload["summary"]
        self.assertEqual(summary["trials"], 3)
        self.assertTrue(summary["trials_differ"])
        self.assertTrue(0 <= summary["success_rate"] <= 1)
        self.assertEqual(set(summary["final_net_worth"]), {"p10", "p50", "p90"})
        for name in ("model.csv", "events.csv", "meta.json", "summary.json"):
            self.assertTrue((out_dir / name).exists(), name)

    def test_identical_trials_are_flagged(self):
        code, out, err = invoke("montecarlo", str(self.spec_path), "--n", "2", "--years", "2", "--workers", "1")
        self.assertEqual(code, 0, msg=err)
        self.assertIn("every trial was identical", out)

    def test_parquet_output(self):
        try:
            import pyarrow  # noqa: F401
        except ImportError:  # pragma: no cover - depends on the environment
            self.skipTest("pyarrow not installed")
        out_dir = self.tmp / "mcpq"
        code, _, err = invoke(
            "montecarlo", str(self.spec_path), "--n", "2", "--years", "2", "--workers", "1", "--out", str(out_dir)
        )
        self.assertEqual(code, 0, msg=err)
        self.assertTrue((out_dir / "model.parquet").exists())

    def test_n_must_be_positive(self):
        code, _ = invoke_json("montecarlo", str(self.spec_path), "--n", "0")
        self.assertEqual(code, cli.EXIT_INVALID)


class TestSchemaAndExamples(CliTestCase):
    def test_schema(self):
        code, out, _ = invoke("schema")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["title"], "HouseholdSpec")
        code, payload = invoke_json("schema")
        self.assertEqual(payload["schema"]["title"], "HouseholdSpec")

    def test_examples_list(self):
        code, payload = invoke_json("examples")
        self.assertEqual(code, 0)
        names = {row["name"]: row for row in payload["examples"]}
        self.assertIn("married_homeowners", names)
        self.assertTrue(names["married_homeowners"]["runnable"])
        self.assertFalse(names["self_employed"]["runnable"])
        self.assertIn("stochastic", payload["scenarios"])
        code, out, _ = invoke("examples")
        self.assertIn("not runnable yet", out)

    def test_show_and_copy(self):
        code, out, _ = invoke("examples", "--show", "single_renter")
        self.assertEqual(code, 0)
        self.assertEqual(out.rstrip(), example_path("single_renter").read_text().rstrip())
        code, _, err = invoke("examples", "--copy", "married_homeowners", str(self.spec_path))
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertIn("--force", err)
        code, _, _ = invoke("examples", "--copy", "married_homeowners", str(self.spec_path), "--force")
        self.assertEqual(code, 0)
        code, payload = invoke_json("examples", "--copy", "single_renter", str(self.tmp))
        self.assertEqual(payload["path"], str((self.tmp / "single_renter.yaml").resolve()))

    def test_unknown_example(self):
        code, payload = invoke_json("examples", "--show", "nope")
        self.assertEqual(code, cli.EXIT_INVALID)
        self.assertIn("Unknown example", payload["error"]["message"])


class TestEntryPoint(unittest.TestCase):
    def test_no_command_prints_help(self):
        code, out, _ = invoke()
        self.assertEqual(code, 0)
        self.assertIn("usage: life-model", out)

    def test_every_command_is_registered_once(self):
        names = [command.name for command in cli.COMMANDS]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(
            set(names),
            {"run", "validate", "explain", "reconcile", "compare", "montecarlo", "schema", "examples", "mcp"},
        )

    def test_console_script_is_declared(self):
        import tomllib

        project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]
        self.assertEqual(project["scripts"]["life-model"], "life_model.cli:main")
        self.assertIn("mcp", project["optional-dependencies"])


if __name__ == "__main__":
    unittest.main()
