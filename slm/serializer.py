# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Household <-> natural-language serialization.

:func:`render_household` turns a structured :class:`~slm.schema.HouseholdProfile` into a compact,
faithful English profile the model reads. :func:`parse_household` recovers the numeric fields from
that text; the two are inverse on every numeric field, which the round-trip test asserts — the
text never states a number that disagrees with the structured state.

Rendering is deterministic (fixed field order, fixed number formatting), so the same profile
always serializes to byte-identical text — a prerequisite for byte-identical JSONL under seed.
"""

import re
from typing import Any, Dict

from .schema import HouseholdProfile


def _fmt_money(value: float) -> str:
    """Whole-dollar money with thousands separators (deterministic)."""
    return f"${round(value):,}"


def render_household(profile: HouseholdProfile) -> str:
    """Render a household profile as a faithful natural-language paragraph."""
    years_to_retirement = max(0, profile.person_retirement_age - profile.person_start_age)
    economy = profile.economy_scenario or "baseline"
    if profile.children_ages:
        n = len(profile.children_ages)
        noun = "child" if n == 1 else "children"
        ages_word = "age" if n == 1 else "ages"
        ages = ", ".join(str(a) for a in profile.children_ages)
        children_clause = f"The household has {n} {noun} ({ages_word} {ages}). "
    else:
        children_clause = "The household has no children. "
    healthcare_clause = (
        "Healthcare costs (age-related medical spending and Medicare) are modeled."
        if profile.models_healthcare
        else "Healthcare costs are not modeled."
    )
    return (
        f"Household profile ({profile.scenario} scenario). "
        f"A {profile.person_start_age}-year-old {profile.person_gender.lower()} person "
        f"planning to retire at age {profile.person_retirement_age} "
        f"({years_to_retirement} years away). "
        f"Current salary is {_fmt_money(profile.initial_salary)} per year, "
        f"annual spending is {_fmt_money(profile.initial_spending)}, "
        f"and the starting bank balance is {_fmt_money(profile.initial_bank_balance)}. "
        f"Economic outlook: {economy}. "
        f"{children_clause}"
        f"{healthcare_clause}"
    )


# Regexes anchored to the rendered phrasing above. Each captures one field so the round-trip test
# can confirm the text states exactly the structured values, and so the tool-loop adviser
# (:mod:`slm.advise`) can reconstruct a scoring-ready household from the rendered text alone.
_SCENARIO_RE = re.compile(r"Household profile \(([A-Za-z0-9_]+) scenario\)")
_START_AGE_RE = re.compile(r"A (\d+)-year-old")
_GENDER_RE = re.compile(r"-year-old (\w+) person")
_RETIRE_AGE_RE = re.compile(r"retire at age (\d+)")
_SALARY_RE = re.compile(r"salary is \$([\d,]+)")
_SPENDING_RE = re.compile(r"spending is \$([\d,]+)")
_BANK_RE = re.compile(r"bank balance is \$([\d,]+)")
_ECONOMY_RE = re.compile(r"Economic outlook: ([A-Za-z0-9_]+)")
_CHILDREN_RE = re.compile(r"has \d+ (?:child|children) \(ages? ([\d, ]+)\)")
_HEALTHCARE_RE = re.compile(r"Healthcare costs[^.]* are (not )?modeled")


def _money(text: str, pattern: re.Pattern) -> int:
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"could not recover field matching {pattern.pattern!r} from rendered text")
    return int(match.group(1).replace(",", ""))


def parse_household(text: str) -> Dict[str, Any]:
    """Recover the household fields from rendered text (inverse of :func:`render_household`).

    The economy is returned as ``None`` when the outlook is the ``baseline`` (no named scenario),
    matching how :func:`render_household` renders a missing ``economy_scenario``. Children and
    healthcare default to "none"/"not modeled" when the text omits those clauses, so text produced
    by an older renderer still parses.
    """
    economy = _ECONOMY_RE.search(text).group(1)
    children_match = _CHILDREN_RE.search(text)
    children_ages = (
        [int(a) for a in children_match.group(1).split(",")] if children_match is not None else []
    )
    healthcare_match = _HEALTHCARE_RE.search(text)
    models_healthcare = healthcare_match is not None and healthcare_match.group(1) is None
    return {
        "scenario": _SCENARIO_RE.search(text).group(1),
        "person_start_age": int(_START_AGE_RE.search(text).group(1)),
        "person_retirement_age": int(_RETIRE_AGE_RE.search(text).group(1)),
        "person_gender": _GENDER_RE.search(text).group(1),
        "initial_salary": _money(text, _SALARY_RE),
        "initial_spending": _money(text, _SPENDING_RE),
        "initial_bank_balance": _money(text, _BANK_RE),
        "economy_scenario": None if economy == "baseline" else economy,
        "children_ages": children_ages,
        "models_healthcare": models_healthcare,
    }
