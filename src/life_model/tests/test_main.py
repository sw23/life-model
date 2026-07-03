# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import sys
import subprocess

import unittest

import life_model


class TestMainModule(unittest.TestCase):

    def test_run_demo(self):
        """`python -m life_model` runs the demo simulation and prints a table."""
        result = subprocess.run(
            [sys.executable, '-m', 'life_model', '--years', '3'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn('Year', result.stdout)

    def test_version_flag(self):
        """`python -m life_model --version` reports the package version."""
        result = subprocess.run(
            [sys.executable, '-m', 'life_model', '--version'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(life_model.__version__, result.stdout)


if __name__ == '__main__':
    unittest.main()
