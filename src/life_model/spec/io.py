# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Load and dump household specs as YAML or JSON.

The dumped form omits fields at their defaults, writes whole-dollar floats as integers and keeps
the schema's field order, so ``dumps(loads(dumps(spec))) == dumps(spec)`` byte for byte in both
formats. Comments in hand-written YAML are not preserved.
"""

import json
from pathlib import Path
from typing import Any, Literal

import yaml

from .schema import SPEC_VERSION, HouseholdSpec, json_schema

Format = Literal["yaml", "json"]

__all__ = ["dump", "dumps", "json_schema", "load", "loads", "to_data"]


def _clean(value: Any) -> Any:
    """Plain YAML/JSON-safe data: tuples become lists, whole floats become ints."""
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return int(value)
    return value


def to_data(spec: HouseholdSpec) -> dict[str, Any]:
    """The spec as plain data (defaults omitted, ``spec_version`` always first)."""
    data = spec.model_dump(mode="python", exclude_defaults=True)
    data.pop("spec_version", None)
    return {"spec_version": SPEC_VERSION, **_clean(data)}


def _format_for(path: str | Path, fmt: Format | None) -> Format:
    if fmt is not None:
        return fmt
    return "json" if str(path).lower().endswith(".json") else "yaml"


def loads(text: str, fmt: Format | None = None) -> HouseholdSpec:
    """Parse a spec from YAML or JSON text (JSON when ``fmt`` is unset and the text starts with ``{``)."""
    if fmt is None:
        fmt = "json" if text.lstrip().startswith("{") else "yaml"
    data = json.loads(text) if fmt == "json" else yaml.safe_load(text)
    return HouseholdSpec.model_validate(data)


def load(path: str | Path, fmt: Format | None = None) -> HouseholdSpec:
    """Load a spec from a ``.yaml``/``.yml`` or ``.json`` file."""
    return loads(Path(path).read_text(encoding="utf-8"), _format_for(path, fmt))


def dumps(spec: HouseholdSpec, fmt: Format = "yaml") -> str:
    """Serialize a spec to YAML (default) or JSON text."""
    data = to_data(spec)
    if fmt == "json":
        return json.dumps(data, indent=2) + "\n"
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False, width=100)


def dump(spec: HouseholdSpec, path: str | Path, fmt: Format | None = None) -> None:
    """Write a spec to ``path`` (format from the suffix unless ``fmt`` is given)."""
    Path(path).write_text(dumps(spec, _format_for(path, fmt)), encoding="utf-8")
