# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Shared helpers for the household-spec tests."""

import copy
from pathlib import Path

from ..config.financial_config import FinancialConfig
from ..spec import HouseholdSpec

FIXTURE_CONFIG = Path(__file__).parent / "fixtures" / "test_config.yaml"


def fixture_config() -> FinancialConfig:
    """The frozen test config (dollar assertions must not drift with refreshed constants)."""
    return FinancialConfig(config_file=str(FIXTURE_CONFIG))


def minimal(**person_overrides) -> dict:
    """A minimal valid spec as raw data: one person with a bank account and a job.

    The person is born in January of the year that makes them ``age`` in January 2026 (the same exact
    ages as an age-only spec, without the validator's ``birth_assumed`` warning); pass ``birth=None``
    to leave the birth month out.
    """
    person = {
        "id": "alex",
        "name": "Alex",
        "age": 40,
        "retirement_age": 65,
        "spending": {"amount_annual": 30000, "growth_pct": "economy"},
        "jobs": [{"id": "job", "company": "Co", "salary_annual": 80000, "raise_pct": "economy"}],
        "accounts": [{"kind": "bank", "balance": 20000}],
    }
    person.update(person_overrides)
    if "birth" not in person_overrides:
        person["birth"] = f"{2026 - person['age']:04d}-01"
    elif person["birth"] is None:
        del person["birth"]
    return {"meta": {"name": "test", "start_year": 2026, "end_year": 2030}, "people": [person]}


def spec_of(data: dict) -> HouseholdSpec:
    return HouseholdSpec.model_validate(copy.deepcopy(data))
