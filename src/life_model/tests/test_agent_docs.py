# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Plan 30 D4/D7: the docs that travel with the repo stay true.

* every scenario name used in docs, the README and docstrings resolves via ``list_scenarios()``;
* the README lists every packaged scenario;
* the generated constructor cheat sheet is current;
* AGENTS.md, llms.txt and the docs link only to files that exist;
* docs/cli.md documents every subcommand and flag;
* the model-household skill has valid front matter.
"""

import argparse
import importlib.util
import re
import unittest
from pathlib import Path

import yaml

from .. import cli
from ..config.scenarios import list_scenarios

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE = REPO_ROOT / "src" / "life_model"

#: ``scenario="name"`` / ``scenario='name'`` in code and prose.
_SCENARIO_KWARG = re.compile(r"""scenario\s*=\s*["']([A-Za-z0-9_]+)["']""")
#: ``--scenario name`` on a command line.
_SCENARIO_FLAG = re.compile(r"--scenario[ =]([a-z0-9_]+)\b")
#: ``scenario: name`` as a YAML key line (a spec's meta.scenario).
_SCENARIO_YAML = re.compile(r"^\s*scenario:\s*([a-z0-9_]+)\s*$", re.MULTILINE)
#: ``get_scenario("name")`` / ``apply_scenario("name", get_scenario(...))``.
_GET_SCENARIO = re.compile(r"""get_scenario\(\s*["']([A-Za-z0-9_]+)["']""")


def _doc_files() -> list[Path]:
    files = sorted((REPO_ROOT / "docs").rglob("*.md")) + sorted((REPO_ROOT / "docs").glob("*.rst"))
    files = [f for f in files if "_build" not in f.parts and "_autosummary" not in f.parts]
    return files + [REPO_ROOT / "README.md", REPO_ROOT / "AGENTS.md", REPO_ROOT / "llms.txt"]


def _source_files() -> list[Path]:
    return sorted(p for p in PACKAGE.rglob("*.py") if "tests" not in p.relative_to(PACKAGE).parts)


def _scenario_mentions(text: str) -> set[str]:
    names = set()
    for pattern in (_SCENARIO_KWARG, _SCENARIO_FLAG, _SCENARIO_YAML, _GET_SCENARIO):
        names.update(pattern.findall(text))
    return names


class TestScenarioNames(unittest.TestCase):
    def test_every_documented_scenario_resolves(self):
        known = set(list_scenarios())
        seen: dict[str, list[str]] = {}
        for path in _doc_files() + _source_files() + sorted((PACKAGE / "spec" / "examples").glob("*.yaml")):
            for name in _scenario_mentions(path.read_text(encoding="utf-8")):
                seen.setdefault(name, []).append(str(path.relative_to(REPO_ROOT)))
        unknown = {name: where for name, where in seen.items() if name not in known}
        self.assertEqual(unknown, {}, msg=f"scenario names that do not resolve (known: {sorted(known)})")
        # Non-vacuous: the Monte Carlo docs and docstrings name the packaged stochastic scenario.
        self.assertIn("stochastic", seen)
        self.assertIn("src/life_model/montecarlo.py", seen["stochastic"])
        self.assertIn("docs/configuration.md", seen["stochastic"])

    def test_patterns(self):
        text = 'LifeModel(scenario="recession")\n--scenario stochastic\nmeta:\n  scenario: boom\nget_scenario("x")'
        self.assertEqual(_scenario_mentions(text), {"recession", "stochastic", "boom", "x"})
        self.assertEqual(_scenario_mentions("scenario=scenario, --scenario NAME"), set())

    def test_readme_lists_every_packaged_scenario(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        section = readme.split("### Configuration System", 1)[1].split("\n## ", 1)[0]
        missing = [name for name in list_scenarios() if f"`{name}`" not in section]
        self.assertEqual(missing, [])

    def test_readme_dashboard_claims(self):
        """The README describes the dashboard's real controls (no inflation slider exists)."""
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        section = readme.split("### Dashboard", 1)[1].split("\n### ", 1)[0]
        app = (REPO_ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("Inflation", app)
        self.assertIn("no separate inflation control", section)
        for control in ("Retirement Age", "Salary", "Bonus", "Children", "Home Price", "Mortgage Rate", "State"):
            self.assertIn(control, app)


class TestGeneratedCheatsheet(unittest.TestCase):
    def test_cheatsheet_is_current(self):
        script = REPO_ROOT / "scripts" / "generate_cheatsheet.py"
        spec = importlib.util.spec_from_file_location("generate_cheatsheet", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(
            module.OUTPUT.read_text(encoding="utf-8"),
            module.render(),
            "docs/constructor-cheatsheet.md is stale: run python scripts/generate_cheatsheet.py",
        )
        self.assertEqual(module.main(["--check"]), 0)


_LINK = re.compile(r"\]\(([^)\s#]+)(?:#[^)]*)?\)")


def _relative_links(path: Path) -> list[str]:
    links = _LINK.findall(path.read_text(encoding="utf-8"))
    return [link for link in links if not re.match(r"^[a-z]+:", link)]


class TestAgentDocs(unittest.TestCase):
    def test_links_resolve(self):
        files = [REPO_ROOT / "AGENTS.md", REPO_ROOT / "llms.txt", REPO_ROOT / "README.md"]
        files += sorted((REPO_ROOT / "docs").rglob("*.md"))
        broken = []
        for path in files:
            if "_build" in path.parts:
                continue
            for link in _relative_links(path):
                if not (path.parent / link).exists():
                    broken.append(f"{path.relative_to(REPO_ROOT)} -> {link}")
        self.assertEqual(broken, [])

    def test_llms_txt_points_at_the_agent_docs(self):
        links = set(_relative_links(REPO_ROOT / "llms.txt"))
        for required in (
            "AGENTS.md",
            "docs/modeling-a-household.md",
            "docs/cli.md",
            "docs/household-spec.md",
            "docs/units-and-conventions.md",
            "docs/constructor-cheatsheet.md",
            "docs/outputs.md",
        ):
            self.assertIn(required, links)
        self.assertTrue((REPO_ROOT / "llms.txt").read_text(encoding="utf-8").startswith("# life-model\n"))

    def test_skill_front_matter(self):
        text = (REPO_ROOT / "docs" / "agent-skills" / "model-household" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        front = yaml.safe_load(text.split("---\n", 2)[1])
        self.assertEqual(front["name"], "model-household")
        self.assertGreater(len(front["description"]), 50)
        self.assertIn("my-models", text)
        self.assertIn("Never invent", text)

    def test_cli_doc_covers_every_command_and_flag(self):
        doc = (REPO_ROOT / "docs" / "cli.md").read_text(encoding="utf-8")
        parser = cli.get_parser()
        subparsers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        missing = []
        for name, subparser in subparsers.choices.items():
            if f"### `{name}`" not in doc:
                missing.append(f"section for {name}")
            for action in subparser._actions:
                for option in action.option_strings:
                    if option.startswith("--") and option != "--help" and f"`{option}" not in doc:
                        missing.append(f"{name} {option}")
        self.assertEqual(missing, [])

    def test_agents_md_is_current(self):
        text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        # Plan 30 Problem 3: the stale claims are gone, the current ones are present.
        self.assertNotIn("relative to the repo root", text)
        self.assertIn("importlib.resources", text)
        self.assertIn("`pre_step` (", text)
        self.assertIn("`events`", text)
        self.assertIn("STEP_PRIORITY", text)
        self.assertIn("ruff", text)
        self.assertIn("3.14", text)


if __name__ == "__main__":
    unittest.main()
