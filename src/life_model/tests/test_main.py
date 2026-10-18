# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import subprocess
import sys
import unittest

import life_model


class TestMainModule(unittest.TestCase):
    def test_run_demo(self):
        """`python -m life_model run --example ...` runs a shipped example and prints a table."""
        result = subprocess.run(
            [sys.executable, "-m", "life_model", "run", "--example", "single_renter", "--years", "3"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Year", result.stdout)
        self.assertIn("Net Worth", result.stdout)

    def test_version_flag(self):
        """`python -m life_model --version` reports the package version."""
        result = subprocess.run(
            [sys.executable, "-m", "life_model", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(life_model.__version__, result.stdout)

    def test_bare_invocation_prints_help(self):
        """`python -m life_model` with no command lists the subcommands."""
        result = subprocess.run([sys.executable, "-m", "life_model"], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("run", result.stdout)
        self.assertIn("explain", result.stdout)

    def test_exit_code_for_invalid_input(self):
        """Validation failures exit 2 from the real process, too."""
        result = subprocess.run(
            [sys.executable, "-m", "life_model", "run", "--example", "self_employed"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("not yet supported", result.stderr)


if __name__ == "__main__":
    unittest.main()
