# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""New stats, agent Name/Type/Owner columns and the pre-post_step snapshot."""

import unittest

from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount
from ..account.job401k import Job401kAccount
from ..ledger import household_balance_sheet
from ..model import EventKind, LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..work.job import Job, Salary
from .scenarios import married_homeowners, mortality_and_estate


class TestNewStats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = married_homeowners(years=12)
        cls.model.run()
        cls.frame = cls.model.datacollector.get_model_vars_dataframe().set_index("Year")

    def test_net_worth_is_the_balance_sheet(self):
        for year, balances in self.model.balance_sheets.items():
            self.assertAlmostEqual(self.frame.loc[year, "Net Worth"], balances.closing.net_worth, places=4)
        self.assertAlmostEqual(
            self.frame["Net Worth"].iloc[-1], household_balance_sheet(self.model).net_worth, places=4
        )

    def test_account_balances(self):
        people = {p.name: p for p in self.model.agents if isinstance(p, Person)}
        final = self.frame.iloc[-1]
        self.assertAlmostEqual(
            final["Traditional IRA Balance"], sum(a.balance for a in people["Jane"].traditional_iras)
        )
        self.assertAlmostEqual(final["Roth IRA Balance"], sum(a.balance for a in people["John"].roth_iras))
        self.assertAlmostEqual(final["HSA Balance"], sum(a.balance for a in people["Jane"].hsas))
        (home,) = people["John"].homes
        self.assertAlmostEqual(final["Home Value"], home.home_value)
        self.assertAlmostEqual(final["Mortgage Principal"], home.mortgage.principal)
        self.assertAlmostEqual(final["Home Equity"], home.home_value - home.mortgage.principal)
        self.assertGreater(self.frame["529 Balance"].iloc[0], 0)

    def test_tax_return_stats(self):
        for (year, _), tax_return in self.model.tax_returns.items():
            self.assertAlmostEqual(self.frame.loc[year, "AGI"], tax_return.agi, places=4)
            self.assertAlmostEqual(self.frame.loc[year, "Taxable Income"], tax_return.taxable_income, places=4)
            self.assertEqual(self.frame.loc[year, "Marginal Rate"], tax_return.marginal_rate)
            self.assertEqual(self.frame.loc[year, "Standard Deduction Taken"], tax_return.deduction_taken == "standard")

    def test_waterfall_stats_match_the_events(self):
        model = LifeModel(start_year=2026, end_year=2027)
        person = Person(Family(model), "Pat", 50, 65, Spending(model, base_annual=90000))
        BankAccount(person, company="Bank", balance=1000)
        BrokerageAccount(person, company="Broker", balance=30000)
        job = Job(person, company="Old", role="Retired", salary=Salary(model, base_annual=0))
        job.retired = True
        Job401kAccount(job, pretax_balance=400000)
        model.run()
        frame = model.datacollector.get_model_vars_dataframe().set_index("Year")
        for year in (2026, 2027):
            events = model.event_log.for_year(year)
            sold = sum(e.amount for e in events if e.kind == EventKind.FORCED_SALE)
            drawn = sum(e.amount for e in events if e.kind == EventKind.PRETAX_WITHDRAWAL)
            self.assertAlmostEqual(frame.loc[year, "Forced Sales"], sold, places=4)
            self.assertAlmostEqual(frame.loc[year, "Pre-tax Withdrawals"], drawn, places=4)
        self.assertGreater(frame.loc[2026, "Forced Sales"], 0)
        self.assertEqual(frame.loc[2027, "Forced Sales"], 0)  # the brokerage was emptied in 2026
        self.assertGreater(frame.loc[2027, "Pre-tax Withdrawals"], 0)

    def test_estate_stats_drop_with_the_decedent(self):
        model = mortality_and_estate(years=12)
        model.run()
        frame = model.datacollector.get_model_vars_dataframe().set_index("Year")
        self.assertTrue((frame["Annuity Balance"] > 0).all())
        self.assertGreater(frame.loc[2026, "Trust Balance"], 0)


class TestAgentFrameColumns(unittest.TestCase):
    def test_name_type_and_owner_replace_unique_id_joins(self):
        model = married_homeowners(years=3)
        model.add_agent_stat("Age", "age")
        model.run()
        agents = model.datacollector.get_agent_vars_dataframe()
        people = agents[agents["Type"] == "Person"]
        ages = people.pivot_table(index="Step", columns="Name", values="Age")
        self.assertEqual(ages.loc[1, "John"], 42)
        self.assertEqual(ages.loc[3, "Jane"], 42)
        accounts = agents[(agents["Type"] == "Job401kAccount") & (agents["Owner"] == "John")]
        self.assertEqual(len(accounts), 3)
        self.assertTrue((accounts["401k Balance"] > 0).all())
        banks = agents[agents["Type"] == "BankAccount"]
        self.assertEqual(set(banks["Name"]), {"Chase", "Ally"})

    def test_salary_and_spending_base_show_the_years_value(self):
        model = LifeModel(start_year=2026, end_year=2028)
        person = Person(Family(model), "Pat", 40, 65, Spending(model, base_annual=30000, growth_pct=10))
        BankAccount(person, company="Bank", balance=1000)
        Job(person, company="Co", role="Dev", salary=Salary(model, base_annual=100000, raise_pct=5))
        model.add_agent_stat("Base (post-escalation)", "base")
        model.add_agent_stat("Base (this year)", "base", pre_post=True)
        model.run()
        agents = model.datacollector.get_agent_vars_dataframe()
        salary = agents[agents["Type"] == "Salary"]
        self.assertEqual(salary["Owner"].unique().tolist(), ["Pat"])
        self.assertEqual([round(x) for x in salary["Salary"]], [100000, 105000, 110250])
        # The plain attribute reporter sees next year's (already escalated) value.
        self.assertEqual([round(x) for x in salary["Base (post-escalation)"]], [105000, 110250, 115762])
        self.assertEqual([round(x) for x in salary["Base (this year)"]], [100000, 105000, 110250])
        spending = agents[agents["Type"] == "Spending"]
        self.assertEqual([round(x) for x in spending["Spending Base"]], [30000, 33000, 36300])
        persons = agents[agents["Type"] == "Person"]
        self.assertEqual([round(x) for x in persons["Spending"]], [30000, 33000, 36300])


class TestOutputsDoc(unittest.TestCase):
    def test_docs_outputs_md_is_up_to_date(self):
        import importlib.util
        from pathlib import Path

        script = Path(__file__).resolve().parents[3] / "scripts" / "generate_outputs_doc.py"
        spec = importlib.util.spec_from_file_location("generate_outputs_doc", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(
            module.OUTPUT.read_text(),
            module.render(),
            "docs/outputs.md is stale: run python scripts/generate_outputs_doc.py",
        )

    def test_union_types_render_the_same_on_every_python(self):
        """Python 3.14 merged ``X | None`` into ``typing.Union`` (whose ``__name__`` is ``"Union"``);
        both spellings must render as the same text so the generated doc does not depend on the version."""
        import importlib.util
        import typing
        from pathlib import Path

        from ..tax.return_record import StateReturn

        script = Path(__file__).resolve().parents[3] / "scripts" / "generate_outputs_doc.py"
        spec = importlib.util.spec_from_file_location("generate_outputs_doc", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        expected = "StateReturn | None"
        self.assertEqual(module._type_text(StateReturn | None), expected)
        self.assertEqual(module._type_text(typing.Optional[StateReturn]), expected)  # noqa: UP045
        self.assertEqual(module._type_text(typing.Union[StateReturn, None]), expected)  # noqa: UP007
        self.assertEqual(module._type_text(dict[str, float]), "dict")
        self.assertEqual(module._type_text(float), "float")


if __name__ == "__main__":
    unittest.main()
