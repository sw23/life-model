# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Meta-tests that guard the test suite itself.

Two invariants are enforced:

* Every ``test_*.py`` module contains at least one test function. An empty ``pass``-only test
  class reads as "covered" while asserting nothing, so it is worse than no file at all.
* Every importable module under ``life_model`` (excluding the test package itself) is imported by
  at least one test — here, by this meta-test. Importing each module also guarantees the
  distribution has no import-time breakage.
"""

import ast
import importlib
import pkgutil
import unittest
from pathlib import Path

import life_model

TESTS_DIR = Path(__file__).parent
PACKAGE_ROOT = Path(life_model.__file__).parent


def _iter_test_modules():
    """Yield every ``test_*.py`` file in the tests directory."""
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        yield path


def _has_test_function(source: str) -> bool:
    """True if the module source defines at least one ``test*`` function."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            return True
    return False


def _iter_package_modules():
    """Yield the dotted name of every module under ``life_model`` except the test package."""
    for module_info in pkgutil.walk_packages([str(PACKAGE_ROOT)], prefix="life_model."):
        name = module_info.name
        if ".tests" in name or name.endswith("._version"):
            continue
        yield name


class TestNoEmptyTestModules(unittest.TestCase):
    """S6: an empty test module (no test functions) must fail CI, not silently pass."""

    def test_every_test_module_has_a_test_function(self):
        empty = []
        for path in _iter_test_modules():
            if path.name == Path(__file__).name:
                continue
            if not _has_test_function(path.read_text()):
                empty.append(path.name)
        self.assertEqual(empty, [], msg=f"Test modules with no test functions: {empty}")


class TestAllModulesImported(unittest.TestCase):
    """Every non-test module in the package is importable (and thereby imported by a test)."""

    def test_all_package_modules_import_cleanly(self):
        failures = {}
        for name in _iter_package_modules():
            try:
                importlib.import_module(name)
            except Exception as exc:  # pragma: no cover - only hit on genuine breakage
                failures[name] = repr(exc)
        self.assertEqual(failures, {}, msg=f"Modules that failed to import: {failures}")


if __name__ == "__main__":
    unittest.main()
