# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Household <-> natural-language serialization (Plan 20 task 1).

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
    return (
        f"Household profile ({profile.scenario} scenario). "
        f"A {profile.person_start_age}-year-old {profile.person_gender.lower()} person "
        f"planning to retire at age {profile.person_retirement_age} "
        f"({years_to_retirement} years away). "
        f"Current salary is {_fmt_money(profile.initial_salary)} per year, "
        f"annual spending is {_fmt_money(profile.initial_spending)}, "
        f"and the starting bank balance is {_fmt_money(profile.initial_bank_balance)}. "
        f"Economic outlook: {economy}."
    )


# Regexes anchored to the rendered phrasing above. Each captures one numeric field so the
# round-trip test can confirm the text states exactly the structured values.
_START_AGE_RE = re.compile(r"A (\d+)-year-old")
_RETIRE_AGE_RE = re.compile(r"retire at age (\d+)")
_SALARY_RE = re.compile(r"salary is \$([\d,]+)")
_SPENDING_RE = re.compile(r"spending is \$([\d,]+)")
_BANK_RE = re.compile(r"bank balance is \$([\d,]+)")


def _money(text: str, pattern: re.Pattern) -> int:
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"could not recover field matching {pattern.pattern!r} from rendered text")
    return int(match.group(1).replace(",", ""))


def parse_household(text: str) -> Dict[str, Any]:
    """Recover the numeric household fields from rendered text (inverse of :func:`render_household`)."""
    return {
        "person_start_age": int(_START_AGE_RE.search(text).group(1)),
        "person_retirement_age": int(_RETIRE_AGE_RE.search(text).group(1)),
        "initial_salary": _money(text, _SALARY_RE),
        "initial_spending": _money(text, _SPENDING_RE),
        "initial_bank_balance": _money(text, _BANK_RE),
    }
