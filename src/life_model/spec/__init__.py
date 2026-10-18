# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Declarative household specification: schema, builder, validator, IO and extraction.

Typical use::

    from life_model.spec import build_model, load

    model = build_model(load("my-models/household.yaml"))
    model.run()

``python -m life_model.spec schema`` prints the JSON Schema (for LLM tool definitions);
``python -m life_model.spec validate FILE`` prints the validator's findings. See
``docs/household-spec.md`` for every field.
"""

from importlib.resources import files
from pathlib import Path

from .builder import (
    BuiltHousehold,
    SpecValidationError,
    SpecWarning,
    build_household,
    build_model,
    canonical,
    create_model,
    populate_model,
)
from .extract import spec_from_model
from .io import dump, dumps, load, loads, to_data
from .schema import EVENT_ACTIONS, SPEC_VERSION, HouseholdSpec, json_schema
from .validate import ERROR, WARNING, Finding, validate_model, validate_spec

#: Names of the synthetic example specs shipped in ``life_model/spec/examples``.
EXAMPLES = ("single_renter", "married_homeowners", "retiree_couple", "self_employed")


def example_path(name: str) -> Path:
    """Path of a shipped example spec (``name`` from :data:`EXAMPLES`)."""
    if name not in EXAMPLES:
        raise KeyError(f"Unknown example {name!r}; expected one of {EXAMPLES}")
    return Path(str(files("life_model.spec") / "examples" / f"{name}.yaml"))


def load_example(name: str) -> HouseholdSpec:
    """Load a shipped example spec."""
    return load(example_path(name))


__all__ = [
    "ERROR",
    "EVENT_ACTIONS",
    "EXAMPLES",
    "SPEC_VERSION",
    "WARNING",
    "BuiltHousehold",
    "Finding",
    "HouseholdSpec",
    "SpecValidationError",
    "SpecWarning",
    "build_household",
    "build_model",
    "canonical",
    "create_model",
    "dump",
    "dumps",
    "example_path",
    "json_schema",
    "load",
    "load_example",
    "loads",
    "populate_model",
    "spec_from_model",
    "to_data",
    "validate_model",
    "validate_spec",
]
