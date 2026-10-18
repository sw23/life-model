# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""RunResult, exports, explain() and Monte Carlo outputs (Plan 28, task 6)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount
from ..account.job401k import Job401kAccount
from ..model import EventKind, LifeModel
from ..montecarlo import MonteCarlo, MonteCarloResult
from ..people.family import Family
from ..people.person import Person, Spending
from ..results import RunResult, _require_parquet
from ..work.job import Job, Salary
from .scenarios import married_homeowners, stochastic_retiree


def _early_retiree(start_year=2026, years=5) -> LifeModel:
    """Spends more than the bank holds: the waterfall sells brokerage, then draws pre-tax money."""
    model = LifeModel(start_year=start_year, end_year=start_year + years - 1, seed=3)
    person = Person(Family(model), "Pat", 50, 50, Spending(model, base_annual=80000))
    BankAccount(person, company="Bank", balance=5000)
    BrokerageAccount(person, company="Broker", balance=60000)
    job = Job(person, company="Old", role="Retired", salary=Salary(model, base_annual=0))
    job.retired = True
    Job401kAccount(job, pretax_balance=600000)
    return model


def _build_stochastic(seed: int) -> LifeModel:
    return stochastic_retiree(seed=seed, years=8)


class TestRunReturnsAResult(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = married_homeowners(years=10)
        cls.result = cls.model.run()

    def test_result_contents(self):
        result = self.result
        self.assertIsInstance(result, RunResult)
        self.assertEqual(result.seed, 1)
        self.assertEqual(result.years, list(range(2026, 2036)))
        pd.testing.assert_frame_equal(
            result.model_frame, self.model.datacollector.get_model_vars_dataframe().reset_index(drop=True)
        )
        self.assertEqual(len(result.ledger), len(self.model.ledger))
        self.assertEqual(len(result.events), len(self.model.event_log.list))
        self.assertEqual(set(result.tax_returns), set(self.model.tax_returns))
        self.assertEqual(result.deflators[2026], 1.0)
        self.assertIn("Net Worth", result.money_columns)
        self.assertNotIn("Marginal Rate", result.money_columns)
        self.assertIn("2026-2035", repr(result))

    def test_agent_frame_has_years_and_names(self):
        agents = self.result.agent_frame
        self.assertEqual(list(agents.columns[:4]), ["Year", "Step", "AgentID", "Name"])
        john = agents[(agents["Type"] == "Person") & (agents["Name"] == "John")]
        self.assertEqual(john["Year"].tolist(), list(range(2026, 2036)))

    def test_conservation_from_the_result(self):
        records = self.result.conservation()
        self.assertEqual(len(records), 10)
        self.assertTrue(all(record.ok() for record in records))

    def test_collect_data_false_still_returns_a_result(self):
        model = LifeModel(start_year=2026, end_year=2027, collect_data=False)
        person = Person(Family(model), "Pat", 40, 65, Spending(model, base_annual=1000))
        BankAccount(person, company="Bank", balance=5000)
        result = model.run()
        self.assertIsNone(result.model_frame)
        self.assertIsNone(result.agent_frame)
        self.assertGreater(len(result.ledger), 0)
        self.assertEqual(result.years, [2026, 2027])


class TestExports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = married_homeowners(years=6).run()

    def test_parquet_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            self.result.to_parquet(directory)
            self.assertTrue((Path(directory) / "model.parquet").exists())
            loaded = RunResult.load(directory)
        for name in ("model_frame", "agent_frame", "ledger", "events", "balance_sheets"):
            with self.subTest(name):
                pd.testing.assert_frame_equal(
                    getattr(loaded, name).reset_index(drop=True),
                    getattr(self.result, name).reset_index(drop=True),
                    check_dtype=False,
                )
        self.assertEqual(loaded.tax_returns, self.result.tax_returns)
        self.assertEqual(loaded.deflators, self.result.deflators)
        self.assertEqual(loaded.seed, self.result.seed)
        self.assertEqual(loaded.money_columns, self.result.money_columns)
        self.assertEqual(loaded.explain(2028), self.result.explain(2028))

    def test_json_and_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.result.to_json(Path(directory) / "run.json")
            document = json.loads(path.read_text())
            self.assertEqual(len(document["model_frame"]), 6)
            self.assertEqual(len(document["tax_returns"]), 6)
            self.assertEqual(len(document["ledger"]), len(self.result.ledger))
            self.result.to_csv(Path(directory) / "csv")
            names = sorted(p.name for p in (Path(directory) / "csv").iterdir())
            self.assertEqual(
                names,
                [
                    "agents.csv",
                    "balance_sheets.csv",
                    "events.csv",
                    "ledger.csv",
                    "meta.json",
                    "model.csv",
                    "monthly_balance_sheets.csv",  # Plan 32: the monthly conservation inputs
                    "tax_returns.csv",
                ],
            )
            loaded = RunResult.load(Path(directory) / "csv")
            self.assertEqual(len(loaded.model_frame), 6)
            self.assertEqual(len(loaded.monthly_balance_sheets), 6 * 12)
            self.assertEqual(loaded.tax_returns, self.result.tax_returns)

    def test_parquet_needs_pyarrow(self):
        with patch.dict(sys.modules, {"pyarrow": None}), self.assertRaisesRegex(ImportError, r"life-model\[parquet\]"):
            _require_parquet()


class TestRealDollars(unittest.TestCase):
    def test_every_money_column_is_deflated(self):
        result = stochastic_retiree(seed=4, years=6).run()
        real = result.real_dollars()
        self.assertTrue(real.real)
        self.assertIs(real.real_dollars(), real)
        year = 2030
        factor = result.deflators[year]
        self.assertGreater(factor, 1.0)
        row = result.model_frame[result.model_frame["Year"] == year].iloc[0]
        real_row = real.model_frame[real.model_frame["Year"] == year].iloc[0]
        for column in ("Net Worth", "Taxes", "Spending", "Brokerage Balance"):
            self.assertAlmostEqual(real_row[column], row[column] / factor, places=6)
        self.assertEqual(real_row["Year"], year)
        agents = result.agent_frame
        real_agents = real.agent_frame
        mask = (agents["Year"] == year) & (agents["Type"] == "Person")
        self.assertAlmostEqual(
            real_agents[mask]["Net Worth"].iloc[0], agents[mask]["Net Worth"].iloc[0] / factor, places=6
        )
        nominal_ledger = result.ledger[result.ledger["year"] == year]["amount"].sum()
        self.assertAlmostEqual(real.ledger[real.ledger["year"] == year]["amount"].sum(), nominal_ledger / factor)
        (key,) = [k for k in result.tax_returns if k[0] == year]
        self.assertAlmostEqual(real.tax_returns[key].total_tax, result.tax_returns[key].total_tax / factor)
        self.assertEqual(real.tax_returns[key].marginal_rate, result.tax_returns[key].marginal_rate)


class TestExplain(unittest.TestCase):
    def test_explain_names_every_forced_sale_and_pretax_withdrawal_with_its_cause(self):
        model = _early_retiree()
        result = model.run()
        checked = 0
        for year in result.years:
            text = result.explain(year)
            self.assertTrue(text.startswith(f"# {year}"))
            for event in model.event_log.for_year(year):
                if event.kind in (EventKind.FORCED_SALE, EventKind.PRETAX_WITHDRAWAL):
                    self.assertIn(event.message, text)
                    self.assertIn(event.cause, text)
                    checked += 1
        self.assertGreaterEqual(checked, 3)
        text = result.explain(2026)
        for heading in (
            "## Income",
            "## Bills",
            "## How they were paid",
            "## Tax returns",
            "## Net worth",
            "## Events",
        ):
            self.assertIn(heading, text)
        self.assertIn("solver target", text)
        self.assertIn("fund 2026 taxes", text)  # Plan 32: bills are paid monthly, taxes in December

    def test_explain_married_homeowners(self):
        text = married_homeowners(years=6).run().explain(2030)
        self.assertIn("wage from Acme (John)", text)
        self.assertIn("child tax credit", text)
        self.assertIn("mortgage on John's house", text)


class TestYearlyStatFrame(unittest.TestCase):
    def test_columns_argument_is_not_mutated_and_styled_is_optional(self):
        model = married_homeowners(years=3)
        model.run()
        columns = ["Year", "Taxes"]
        extra = ["Net Worth"]
        frame = model.get_yearly_stat_df(columns=columns, extra_columns=extra, styled=False)
        self.assertEqual(columns, ["Year", "Taxes"])
        self.assertEqual(extra, ["Net Worth"])
        self.assertIsInstance(frame, pd.DataFrame)
        self.assertEqual(list(frame.columns), ["Year", "Net Worth", "Taxes"])
        self.assertIsInstance(model.get_yearly_stat_df(columns=columns), pd.io.formats.style.Styler)


class TestMonteCarloOutputs(unittest.TestCase):
    def test_seeds_frames_events_parquet_and_real_dollars(self):
        result = MonteCarlo(_build_stochastic, n=3, seed=9, workers=1, keep_agent_frames=True, keep_events=True).run()
        self.assertEqual(len(result.seeds), 3)
        rebuilt = _build_stochastic(result.seeds[1])
        rebuilt.run()
        pd.testing.assert_frame_equal(
            rebuilt.datacollector.get_model_vars_dataframe().reset_index(drop=True), result.frames[1]
        )
        self.assertEqual(len(result.agent_frames), 3)
        self.assertEqual(len(result.events), 3)
        with tempfile.TemporaryDirectory() as directory:
            result.to_parquet(directory)
            loaded = MonteCarloResult.load(directory)
        self.assertEqual(loaded.seeds, result.seeds)
        for mine, theirs in zip(loaded.frames, result.frames, strict=True):
            pd.testing.assert_frame_equal(mine, theirs, check_dtype=False)
        real = result.real_dollars()
        last = real.frames[0]["Year"].iloc[-1]
        factor = result.deflators[0][int(last)]
        self.assertAlmostEqual(
            real.frames[0]["Net Worth"].iloc[-1], result.frames[0]["Net Worth"].iloc[-1] / factor, places=6
        )
        self.assertEqual(real.percentiles("Net Worth").shape, (8, 3))


if __name__ == "__main__":
    unittest.main()


class TestMonthlyFrames(unittest.TestCase):
    """Plan 32: RunResult carries the monthly model frame (collect="month") and monthly balance sheets."""

    def test_monthly_frame_and_balance_sheets(self):
        model = LifeModel(start="2026-07", end_year=2027, collect="month")
        person = Person(Family(model), "Pat", 40, 70, Spending(model, base_annual=12000))
        BankAccount(person, company="Bank", balance=50000, interest_pct=0)
        result = model.run()
        self.assertEqual(len(result.monthly_frame), 6 + 12)
        self.assertEqual(result.monthly_frame[["Year", "Month"]].iloc[0].tolist(), [2026, 7])
        sheets = result.monthly_balance_sheets
        self.assertEqual(len(sheets), 18)
        self.assertAlmostEqual(sheets["outflows"].sum(), 6000 + 12000, places=6)
        real = result.real_dollars()
        self.assertEqual(len(real.monthly_frame), 18)
        with tempfile.TemporaryDirectory() as directory:
            result.to_csv(Path(directory) / "csv")
            loaded = RunResult.load(Path(directory) / "csv")
            self.assertEqual(len(loaded.monthly_frame), 18)
        self.assertIsNone(LifeModel(start_year=2026, end_year=2026).run().monthly_frame)
