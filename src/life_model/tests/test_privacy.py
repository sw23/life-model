# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Plan 30 D6: tracked example specs and test fixtures are synthetic by construction.

Real household data lives in the git-ignored ``my-models/``. Rather than grepping for real names
(a test that names a real person would itself leak it), every identifying string in the shipped
example specs and the test fixture YAML/JSON must come from the synthetic allowlists below:
people's names and ids, organization names (employers, banks, insurers, schools, businesses,
charities), and the proper nouns used in free text. Adding a synthetic name means adding it here.
"""

import json
import re
import unittest
from pathlib import Path

import yaml

PACKAGE = Path(__file__).resolve().parents[1]

#: Synthetic people (example specs, fixtures, the example notebook).
SYNTHETIC_PEOPLE = frozenset(
    {"Alex", "Ann", "Casey", "Jane", "John", "Junior", "Kit", "Lee", "Morgan", "Pat", "Riley", "Robin", "Sam"}
)
#: Synthetic organizations.
SYNTHETIC_ORGS = frozenset(
    {
        "Bank",
        "Bargain Ben",
        "Business Checking",
        "Community Bank",
        "Credit Union",
        "Example Analytics",
        "Example Brokerage",
        "Example Consulting LLC",
        "Example County",
        "Example Life",
        "Example Mutual",
        "Food Bank",
        "Neighborhood Credit Union",
        "Pizza Papa",
        "State University",
    }
)
#: Other capitalized words free text may use mid-sentence (product names, places, generic nouns).
GENERIC_PROPER_WORDS = frozenset(
    {
        "AGI",
        "Additional",
        "Analyst",
        "Form",
        "IRC",
        "IRMAA",
        "MAGI",
        "NIIT",
        "W-",
        "California",
        "Card",
        "Checking",
        "HSA",
        "House",
        "IRA",
        "IRAs",
        "Medicare",
        "Plan",
        "Roth",
        "Security",
        "Social",
    }
)
#: Keys whose value names an organization.
ORG_KEYS = frozenset({"company", "school", "business", "employer", "charity", "insurer", "trustee", "decedent_name"})
#: List keys whose items are people (their ``name`` is a person's name).
PERSON_LISTS = frozenset({"people", "children"})


def _tracked_data_files() -> list[Path]:
    files = sorted((PACKAGE / "spec" / "examples").glob("*.yaml"))
    fixtures = PACKAGE / "tests" / "fixtures"
    files += sorted(p for p in fixtures.rglob("*") if p.suffix in (".yaml", ".yml", ".json"))
    goldens = PACKAGE / "tests" / "goldens"
    files += sorted(p for p in goldens.rglob("*") if p.suffix in (".yaml", ".yml", ".json"))
    return files


def _load(path: Path):
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)


def _strings(node, path=()):
    """Yield (path, value) for every string in a YAML/JSON document."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, (*path, str(key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _strings(value, (*path, index))
    elif isinstance(node, str):
        yield path, node


def _list_key(path) -> str | None:
    """The key of the list that holds the innermost item on ``path`` (``people`` for
    ``('people', 0, 'name')``)."""
    for i in range(len(path) - 1, 0, -1):
        if isinstance(path[i], int):
            return path[i - 1] if isinstance(path[i - 1], str) else None
    return None


def _mid_sentence_proper_words(text: str) -> set[str]:
    words = set()
    for sentence in re.split(r"(?<=[.!?:;])\s+", text):
        tokens = re.findall(r"[A-Za-z][A-Za-z'\-]*", sentence)
        for token in tokens[1:]:
            if token[0].isupper():
                words.add(token.removesuffix("'s"))
    return words


class TestSyntheticData(unittest.TestCase):
    def test_there_is_something_to_check(self):
        files = _tracked_data_files()
        self.assertGreaterEqual(len(files), 4, msg=files)

    def test_people_and_organizations_are_synthetic(self):
        allowed_words = set(SYNTHETIC_PEOPLE) | set(GENERIC_PROPER_WORDS)
        for org in SYNTHETIC_ORGS:
            allowed_words.update(org.split())
        problems = []
        for file in _tracked_data_files():
            for path, value in _strings(_load(file)):
                key = path[-1] if path and isinstance(path[-1], str) else None
                where = f"{file.name}:{'.'.join(map(str, path))}"
                if key == "name" and _list_key(path) in PERSON_LISTS:
                    if value not in SYNTHETIC_PEOPLE:
                        problems.append(f"{where}: person name {value!r} is not in SYNTHETIC_PEOPLE")
                elif key == "id" and _list_key(path) == "people":
                    if value not in {name.lower() for name in SYNTHETIC_PEOPLE}:
                        problems.append(f"{where}: person id {value!r} is not a synthetic name")
                elif key in ORG_KEYS:
                    if value not in SYNTHETIC_ORGS:
                        problems.append(f"{where}: organization {value!r} is not in SYNTHETIC_ORGS")
                else:
                    unknown = _mid_sentence_proper_words(value) - allowed_words
                    if unknown:
                        problems.append(f"{where}: proper nouns {sorted(unknown)} are not in the allowlists")
        self.assertEqual(problems, [], msg="\n".join(problems))

    def test_the_check_catches_an_unlisted_name(self):
        """The walk sees person names, organizations and free-text names (guards the guard)."""
        document = {
            "people": [{"id": "zed", "name": "Zed", "jobs": [{"company": "Unlisted Corp"}]}],
            "events": [{"name": "Lunch with Quincy"}],
        }
        seen = {path[-1]: value for path, value in _strings(document)}
        self.assertEqual(seen["company"], "Unlisted Corp")
        self.assertEqual(_list_key(("people", 0, "name")), "people")
        self.assertEqual(_list_key(("people", 0, "jobs", 0, "company")), "jobs")
        self.assertEqual(_mid_sentence_proper_words("Lunch with Quincy"), {"Quincy"})


if __name__ == "__main__":
    unittest.main()
