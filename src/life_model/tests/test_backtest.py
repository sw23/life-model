# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The backtest harness (Plan 29 D5): the realized economy path and the synthetic 2020-2025 example,
whose statement balances ``scripts/backtest_example.py`` computes independently."""

import importlib.util
import unittest
from pathlib import Path

from ..backtest import backtest, realized_paths, realized_series
from ..config.financial_config import FinancialConfig
from ..spec import load

EXAMPLE = Path(__file__).parent / "goldens" / "backtest" / "synthetic_2020_2025.yaml"
SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "backtest_example.py"


class TestRealizedPath(unittest.TestCase):
    def test_paths(self):
        paths = realized_paths(2020, 2025)
        self.assertEqual(paths["equity_return_pct"][2022], -18.11)
        # Inflation for 2020 turns 2020 prices into 2021 prices: CPI-U 270.970 / 258.811 - 1.
        self.assertAlmostEqual(paths["inflation_pct"][2020], (270.970 / 258.811 - 1) * 100, places=5)
        self.assertAlmostEqual(paths["wage_growth_pct"][2024], (72800.33 / 69846.57 - 1) * 100, places=5)
        self.assertNotIn(2025, paths["inflation_pct"])  # no 2026 annual average yet

    def test_wage_index_matches_the_config_history(self):
        config = FinancialConfig().get_avg_wage_index_table()
        for year, value in realized_series()["avg_wage_index"].items():
            if year in config:
                self.assertAlmostEqual(value, config[year], places=2, msg=year)


class TestSyntheticExample(unittest.TestCase):
    def test_statements_are_current(self):
        spec_from = importlib.util.spec_from_file_location("backtest_example", SCRIPT)
        module = importlib.util.module_from_spec(spec_from)
        spec_from.loader.exec_module(module)
        spec = load(EXAMPLE)
        for year, balances in module.statements().items():
            self.assertEqual(spec.actuals[year].balances, balances, year)
        # The statements are plain arithmetic: only the report writer imports the library.
        independent = SCRIPT.read_text(encoding="utf-8").split("def write_report")[0]
        self.assertNotRegex(independent, r"(?m)^\s*(from|import)\s+life_model")

    def test_end_balances_within_one_percent(self):
        report = backtest(load(EXAMPLE))
        self.assertEqual(report.years, list(range(2020, 2026)))
        self.assertEqual(len(report.final()), 3)
        self.assertLess(report.max_relative_error(final_only=True), 0.01)
        self.assertLess(report.max_relative_error(), 0.01)
        self.assertIn("| 2025 | morgan_401k |", report.to_markdown())

    def test_without_the_realized_path_the_balances_miss(self):
        report = backtest(load(EXAMPLE), realized=False)  # the constant 7% economy instead
        self.assertGreater(report.max_relative_error(final_only=True), 0.05)


if __name__ == "__main__":
    unittest.main()
