# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The one-call functions: life_model.run/validate/explain/compare and helpers."""

import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

import life_model

from .. import api
from ..checks import ConservationError, ConservationRecord
from ..results import RunResult
from ..spec import HouseholdSpec, SpecValidationError, SpecWarning, dumps, example_path, load_example, to_data


def _spec() -> HouseholdSpec:
    return load_example("married_homeowners")


class TestLoadSpec(unittest.TestCase):
    def test_accepts_every_form(self):
        spec = _spec()
        self.assertIs(api.load_spec(spec), spec)
        self.assertEqual(api.load_spec(to_data(spec)), spec)
        self.assertEqual(api.load_spec(dumps(spec)), spec)
        self.assertEqual(api.load_spec(dumps(spec, "json")), spec)
        self.assertEqual(api.load_spec(example_path("married_homeowners")), spec)
        self.assertEqual(api.load_spec(str(example_path("married_homeowners"))), spec)

    def test_errors(self):
        with self.assertRaises(FileNotFoundError):
            api.load_spec("does/not/exist.yaml")
        with self.assertRaises(SpecValidationError) as caught:
            api.load_spec({"spec_version": 1, "meta": {"name": "x", "start_year": 2026}, "people": [{"id": "a"}]})
        self.assertTrue(all(f.code.startswith("schema.") for f in caught.exception.findings))
        with self.assertRaises(TypeError):
            api.load_spec(42)

    def test_examples(self):
        self.assertEqual(api.example_spec("single_renter").meta.name, "Single renter")
        with self.assertRaises(api.InputError):
            api.example_spec("nope")
        rows = {row["name"]: row for row in api.list_examples()}
        self.assertTrue(rows["single_renter"]["runnable"])
        # Every packaged example is buildable, the self-employed one included.
        self.assertTrue(rows["self_employed"]["runnable"])
        self.assertFalse(rows["self_employed"]["blocked_by"])


class TestRun(unittest.TestCase):
    def test_top_level_functions_are_the_api(self):
        self.assertIs(life_model.run, api.run)
        self.assertIs(life_model.compare, api.compare)
        self.assertIs(life_model.validate, api.validate)
        self.assertIs(life_model.explain, api.explain)

    def test_run_matches_build_model(self):
        from ..spec import build_model

        spec = api.prepare_spec(_spec(), years=5)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SpecWarning)
            direct = build_model(spec, seed=4).run()
            result = life_model.run(_spec(), years=5, seed=4)
        self.assertIsInstance(result, RunResult)
        self.assertEqual(result.years, [2026, 2027, 2028, 2029, 2030])
        self.assertTrue(result.model_frame.equals(direct.model_frame))

    def test_years_end_year_and_scenario(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SpecWarning)
            self.assertEqual(life_model.run(_spec(), end_year=2027).years, [2026, 2027])
            stochastic = life_model.run(_spec(), years=3, scenario="stochastic", seed=1)
        self.assertEqual(stochastic.spec.meta.scenario, "stochastic")
        with self.assertRaises(api.InputError):
            api.prepare_spec(_spec(), years=2, end_year=2030)
        with self.assertRaises(api.InputError):
            api.prepare_spec(_spec(), years=0)
        with self.assertRaises(SpecValidationError):
            api.prepare_spec(_spec(), scenario="nope")

    def test_real_dollars(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SpecWarning)
            result = life_model.run(_spec(), years=3, real_dollars=True)
        self.assertTrue(result.real)

    def test_checks(self):
        with self.assertRaises(api.InputError):
            api.build(_spec(), checks="loud")
        with self.assertRaises(SpecValidationError):
            life_model.run(_spec(), years=2, checks="strict")  # events after the end year warn
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            life_model.run(_spec(), years=2, checks="off")
        self.assertFalse([w for w in caught if issubclass(w.category, SpecWarning)])

    def test_conservation_failures(self):
        bad = [ConservationRecord(year=2026, opening_net_worth=0, closing_net_worth=10, inflows=0, outflows=0)]
        spec = api.apply_change(_spec(), {"events": None})  # no events, so no validator warnings
        with mock.patch.object(RunResult, "conservation", return_value=bad):
            with self.assertWarns(api.CheckWarning):
                life_model.run(spec, years=1)
            with self.assertRaises(ConservationError):
                life_model.run(spec, years=1, checks="strict")
            life_model.run(spec, years=1, checks="off")

    def test_collected_warnings(self):
        with api.collected_warnings() as messages:
            life_model.run(_spec(), years=2)
        self.assertTrue(any("after end_year" in m for m in messages))
        self.assertEqual(len(messages), len(set(messages)))


class TestValidateExplain(unittest.TestCase):
    def test_validate(self):
        self.assertEqual(life_model.validate(_spec()), [])
        from .spec_helpers import not_yet_supported

        findings = life_model.validate(not_yet_supported())
        self.assertEqual([f.code for f in findings if f.level == "error"], ["not_yet_supported"])
        self.assertEqual(life_model.validate(example_path("self_employed")), [])
        schema = life_model.validate({"spec_version": 1})
        self.assertTrue(all(f.level == "error" for f in schema))
        self.assertEqual(life_model.validate(_spec(), scenario="nope")[0].code, "unknown_scenario")

    def test_explain(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SpecWarning)
            result = life_model.run(_spec(), years=3, seed=2)
            text = life_model.explain(result, 2027)
            self.assertEqual(text, result.explain(2027))
            self.assertEqual(life_model.explain(_spec(), 2027, years=3, seed=2), text)
        with self.assertRaises(api.InputError):
            life_model.explain(result, 2040)


class TestChanges(unittest.TestCase):
    def test_rfc7386_examples(self):
        # RFC 7386 section 3 and appendix A.
        target = {"a": "b", "c": {"d": "e", "f": "g"}}
        self.assertEqual(api.merge_patch(target, {"a": "z", "c": {"f": None}}), {"a": "z", "c": {"d": "e"}})
        self.assertEqual(api.merge_patch({"a": "b"}, {"a": "c"}), {"a": "c"})
        self.assertEqual(api.merge_patch({"a": "b"}, {"b": "c"}), {"a": "b", "b": "c"})
        self.assertEqual(api.merge_patch({"a": "b"}, {"a": None}), {})
        self.assertEqual(api.merge_patch({"a": ["b"]}, {"a": "c"}), {"a": "c"})
        self.assertEqual(api.merge_patch({"a": "c"}, {"a": ["b"]}), {"a": ["b"]})
        self.assertEqual(api.merge_patch({"a": [{"b": "c"}]}, {"a": [1]}), {"a": [1]})
        self.assertEqual(api.merge_patch(["a", "b"], ["c", "d"]), ["c", "d"])
        self.assertEqual(api.merge_patch({"a": "b"}, ["c"]), ["c"])
        self.assertEqual(api.merge_patch({"a": "foo"}, None), None)
        self.assertEqual(api.merge_patch({}, {"a": {"bb": {"ccc": None}}}), {"a": {"bb": {}}})
        self.assertEqual(api.merge_patch({"e": None}, {"a": 1}), {"e": None, "a": 1})

    def test_inputs_are_not_mutated(self):
        target = {"a": {"b": [1]}}
        api.merge_patch(target, {"a": {"b+": [2], "c": 3}})
        self.assertEqual(target, {"a": {"b": [1]}})

    def test_list_extensions(self):
        data = {"people": [{"id": "a", "age": 1}, {"id": "b", "age": 2}], "events": [{"id": "e1"}]}
        patched = api.merge_patch(data, {"people": {"b": {"age": 5}}, "events+": [{"id": "e2"}]})
        self.assertEqual(patched["people"][1], {"id": "b", "age": 5})
        self.assertEqual([e["id"] for e in patched["events"]], ["e1", "e2"])
        self.assertEqual(api.merge_patch(data, {"people": {"a": None}})["people"], [{"id": "b", "age": 2}])
        self.assertEqual(api.merge_patch(data, {"people": {1: {"age": 9}}})["people"][1]["age"], 9)
        self.assertEqual(api.merge_patch({}, {"events+": {"id": "x"}}), {"events": [{"id": "x"}]})
        with self.assertRaises(api.InputError):
            api.merge_patch(data, {"people": {"zz": {"age": 1}}})
        with self.assertRaises(api.InputError):
            api.merge_patch({"a": 1}, {"a+": [2]})

    def test_set_path(self):
        data = {"meta": {"name": "x"}, "people": [{"id": "a", "jobs": [{"salary": 1}]}], "events": []}
        self.assertEqual(api.set_path(data, "meta.name", "y")["meta"]["name"], "y")
        self.assertEqual(api.set_path(data, "people[0].age", 40)["people"][0]["age"], 40)
        self.assertEqual(api.set_path(data, "people[a].jobs[0].salary", 2)["people"][0]["jobs"][0]["salary"], 2)
        self.assertEqual(api.set_path(data, "people.a.age", 41)["people"][0]["age"], 41)
        self.assertEqual(api.set_path(data, "people[-1].age", 42)["people"][0]["age"], 42)
        self.assertEqual(api.set_path(data, "events[+]", {"id": "e"})["events"], [{"id": "e"}])
        self.assertEqual(api.set_path(data, "events[+].id", "f")["events"], [{"id": "f"}])
        self.assertEqual(api.set_path(data, "economy.inflation_pct", 4)["economy"], {"inflation_pct": 4})
        self.assertEqual(api.set_path(data, "relationships.marriages[+]", 1)["relationships"], {"marriages": [1]})
        self.assertEqual(data["meta"]["name"], "x")
        for bad in ("", "a..b", "people[zz].age", "people[5].age", "meta.name.x", "a]b"):
            with self.subTest(path=bad), self.assertRaises(api.InputError):
                api.set_path(data, bad, 1)

    def test_parse_assignment(self):
        self.assertEqual(api.parse_assignment("a.b=62"), ("a.b", 62))
        self.assertEqual(api.parse_assignment("a=economy"), ("a", "economy"))
        self.assertEqual(api.parse_assignment("a=null"), ("a", None))
        self.assertEqual(api.parse_assignment("a={x: 1}"), ("a", {"x": 1}))
        self.assertEqual(api.parse_assignment("a="), ("a", ""))
        for bad in ("novalue", "a={x: [1"):
            with self.subTest(text=bad), self.assertRaises(api.InputError):
                api.parse_assignment(bad)

    def test_apply_change(self):
        changed = api.apply_change(_spec(), {"people": {"jane": {"retirement_age": 62}}}, sets=["meta.end_year=2040"])
        self.assertEqual(changed.people[1].retirement_age, 62)
        self.assertEqual(changed.meta.end_year, 2040)
        self.assertEqual(api.apply_change(_spec(), sets=[("people[john].age", 45)]).people[0].age, 45)
        with self.assertRaises(SpecValidationError):
            api.apply_change(_spec(), sets=["people[john].age=-1"])
        with self.assertRaises(api.InputError):
            api.apply_change(_spec(), ["not", "a", "mapping"])

    def test_load_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.yaml"
            path.write_text("people:\n  jane:\n    retirement_age: 62\n")
            self.assertEqual(api.load_change(path), {"people": {"jane": {"retirement_age": 62}}})
            path.write_text("")
            self.assertEqual(api.load_change(path), {})
            path.write_text("- 1\n")
            with self.assertRaises(api.InputError):
                api.load_change(path)
            with self.assertRaises(FileNotFoundError):
                api.load_change(Path(tmp) / "missing.yaml")


class TestCompareAndMonteCarlo(unittest.TestCase):
    def test_compare(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SpecWarning)
            comparison = life_model.compare(_spec(), sets=["people[jane].retirement_age=50"], years=8)
        self.assertEqual(comparison.base.seed, comparison.changed.seed)
        self.assertEqual(comparison.changed_spec.people[1].retirement_age, 50)
        document = comparison.to_dict()
        self.assertEqual(document["seed"], comparison.base.seed)
        self.assertLess(document["deltas"]["final_net_worth"], 0)
        self.assertIn("Bank Balance", document["deltas"]["final_balances"])
        self.assertNotIn("yearly", document["base"])
        with self.assertRaises(api.InputError):
            life_model.compare(_spec())

    def test_montecarlo(self):
        result = api.run_montecarlo(_spec(), n=3, seed=5, years=4, scenario="stochastic", workers=1)
        summary = api.montecarlo_summary(result)
        self.assertEqual(summary["trials"], 3)
        self.assertEqual(summary["years"], [2026, 2029])
        self.assertTrue(summary["trials_differ"])
        again = api.montecarlo_summary(
            api.run_montecarlo(_spec(), n=3, seed=5, years=4, scenario="stochastic", workers=1)
        )
        self.assertEqual(summary, again)
        result.events = None  # the fallback definition (final net worth above zero)
        self.assertEqual(api.montecarlo_summary(result)["success_rate"], 1.0)

    def test_summarize(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SpecWarning)
            result = life_model.run(_spec(), years=3, seed=1)
        summary = api.summarize(result)
        self.assertEqual(summary["household"], "Married homeowners")
        self.assertEqual(summary["final_year"], 2028)
        self.assertEqual([row["Year"] for row in summary["yearly"]], [2026, 2027, 2028])
        self.assertEqual(summary["shortfall_years"], [])
        self.assertEqual(api.shortfall_years(result), [])
        with tempfile.TemporaryDirectory() as tmp:
            loaded = RunResult.load(result.to_csv(Path(tmp) / "csv"))
            self.assertEqual(api.summarize(loaded)["household"], "Married homeowners")


if __name__ == "__main__":
    unittest.main()
