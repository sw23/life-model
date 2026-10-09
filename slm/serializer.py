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
from typing import Any

from .schema import HouseholdProfile


def _fmt_money(value: float) -> str:
    """Whole-dollar money with thousands separators (deterministic)."""
    return f"${round(value):,}"


def _fmt_pct(fraction: float) -> str:
    """A fraction as a whole percentage (deterministic; 0.5 -> "50%")."""
    return f"{round(fraction * 100)}%"


def _savings_clause(profile: HouseholdProfile) -> str:
    return (
        f"Invested savings: {_fmt_money(profile.initial_401k_pretax)} in a pre-tax 401k, "
        f"{_fmt_money(profile.initial_401k_roth)} in a Roth 401k, and "
        f"{_fmt_money(profile.initial_brokerage)} in a taxable brokerage account. "
    )


def _match_clause(profile: HouseholdProfile) -> str:
    if profile.employer_match_rate > 0 and profile.employer_match_cap > 0:
        return (
            f"The employer matches {_fmt_pct(profile.employer_match_rate)} of 401k deferrals "
            f"up to {_fmt_pct(profile.employer_match_cap)} of pay. "
        )
    return "The employer offers no 401k match. "


def _retirement_spending_clause(profile: HouseholdProfile) -> str:
    if profile.retirement_spending_ratio == 1.0:
        return "Spending is planned to stay at its working level in retirement. "
    return f"Spending is planned to fall to {_fmt_pct(profile.retirement_spending_ratio)} of its working level in retirement. "


def _social_security_clause(profile: HouseholdProfile) -> str:
    if profile.ss_claim_age is None:
        return "Social Security is not modeled. "
    return (
        f"Social Security is modeled, claimed at age {profile.ss_claim_age}, from an earnings record "
        f"assumed flat in real terms since age 22. "
    )


def starting_outlay(profile: HouseholdProfile) -> float:
    """Start-year total outlay: base spending plus the simulator's own start-year child and medical
    costs (the generator carves both out of the sampled spending, so the stated spending excludes them)."""
    from life_model.config.financial_config import default_financial_config
    from life_model.dependents.child import Child

    cfg = default_financial_config()
    child = 0.0
    for age in profile.children_ages:
        if age < cfg.dependents.adult_age:
            child += (
                cfg.dependents.childcare_annual_cost
                if age < Child.CHILDCARE_END_AGE
                else cfg.dependents.school_age_annual_cost
            )
    medical = 0.0
    if profile.models_healthcare:
        medical = next(
            (float(b.annual_cost) for b in cfg.healthcare.medical_cost_bands if profile.person_start_age <= b.max_age),
            0.0,
        )
    return profile.initial_spending + child + medical


def _ratios_clause(profile: HouseholdProfile) -> str:
    """Derived key ratios (each a deterministic function of the stated fields), so a reader need not
    divide dollar figures to see how stretched the household is."""
    salary = max(profile.initial_salary, 1.0)
    outlay = starting_outlay(profile)
    invested = profile.initial_401k_pretax + profile.initial_401k_roth + profile.initial_brokerage
    months = profile.initial_bank_balance / max(outlay / 12.0, 1.0)
    return (
        f"Key ratios: total outlay (spending plus starting child and medical costs) is "
        f"{round(100 * outlay / salary)}% of salary, invested savings are {invested / salary:.1f}x salary, "
        f"and cash covers {months:.1f} months of outlay. "
    )


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
        f"{_savings_clause(profile)}"
        f"{_match_clause(profile)}"
        f"{_retirement_spending_clause(profile)}"
        f"{_social_security_clause(profile)}"
        f"{_ratios_clause(profile)}"
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
_PRETAX_RE = re.compile(r"\$([\d,]+) in a pre-tax 401k")
_ROTH_RE = re.compile(r"\$([\d,]+) in a Roth 401k")
_BROKERAGE_RE = re.compile(r"\$([\d,]+) in a taxable brokerage")
_MATCH_RE = re.compile(r"matches (\d+)% of 401k deferrals up to (\d+)% of pay")
_RETIREMENT_SPENDING_RE = re.compile(r"fall to (\d+)% of its working level in retirement")
_SS_RE = re.compile(r"Social Security is modeled, claimed at age (\d+)")


def _money(text: str, pattern: re.Pattern) -> int:
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"could not recover field matching {pattern.pattern!r} from rendered text")
    return int(match.group(1).replace(",", ""))


def _optional_money(text: str, pattern: re.Pattern) -> int:
    match = pattern.search(text)
    return 0 if match is None else int(match.group(1).replace(",", ""))


def parse_household(text: str) -> dict[str, Any]:
    """Recover the household fields from rendered text (inverse of :func:`render_household`).

    The economy is returned as ``None`` when the outlook is the ``baseline`` (no named scenario),
    matching how :func:`render_household` renders a missing ``economy_scenario``. Children and
    healthcare default to "none"/"not modeled" when the text omits those clauses (and savings,
    match, and Social Security to "absent"), so text produced by an older renderer still parses.
    """
    economy = _ECONOMY_RE.search(text).group(1)
    children_match = _CHILDREN_RE.search(text)
    children_ages = [int(a) for a in children_match.group(1).split(",")] if children_match is not None else []
    healthcare_match = _HEALTHCARE_RE.search(text)
    models_healthcare = healthcare_match is not None and healthcare_match.group(1) is None
    match_offer = _MATCH_RE.search(text)
    ss_match = _SS_RE.search(text)
    retirement_spending = _RETIREMENT_SPENDING_RE.search(text)
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
        "ss_claim_age": int(ss_match.group(1)) if ss_match is not None else None,
        "retirement_spending_ratio": int(retirement_spending.group(1)) / 100 if retirement_spending else 1.0,
        "employer_match_rate": int(match_offer.group(1)) / 100 if match_offer is not None else 0.0,
        "employer_match_cap": int(match_offer.group(2)) / 100 if match_offer is not None else 0.0,
        "initial_401k_pretax": _optional_money(text, _PRETAX_RE),
        "initial_401k_roth": _optional_money(text, _ROTH_RE),
        "initial_brokerage": _optional_money(text, _BROKERAGE_RE),
    }
