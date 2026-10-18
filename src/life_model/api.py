# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""One-call functions over a household spec: run, validate, explain, compare, Monte Carlo.

These are what the ``life-model`` command line, the MCP server and an LLM tool definition wrap.
Each takes a household spec in any form :func:`load_spec` accepts (a
:class:`~life_model.spec.HouseholdSpec`, a dict, YAML/JSON text, or a path) and is a thin layer over
:mod:`life_model.spec` (build, validate) and :class:`~life_model.results.RunResult` (outputs). The
spec's JSON Schema (``life_model.spec.json_schema()``) is their input schema.

::

    import life_model

    result = life_model.run("my-models/household.yaml", seed=1)   # RunResult
    print(life_model.explain(result, 2035))                       # markdown account of 2035
    findings = life_model.validate("my-models/household.yaml")    # list[Finding]
    delta = life_model.compare("h.yaml", {"people": {"sam": {"retirement_age": 62}}})
    print(delta.to_dict()["deltas"])

Errors: a spec that fails the schema or the validator raises
:class:`~life_model.spec.SpecValidationError` (``.findings`` lists every problem); other bad input
(an unknown example or scenario, a year outside the run, a bad ``--set`` path) raises
:class:`InputError`. Both are ``ValueError`` subclasses. The command line maps them to exit code 2
and anything else to exit code 1.
"""

import contextlib
import copy
import math
import os
import re
import secrets
import warnings
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .montecarlo import MonteCarloResult
    from .results import RunResult
    from .spec import Finding, HouseholdSpec

#: A household spec in any form :func:`load_spec` accepts.
SpecLike = Any
#: ``checks`` modes: ``strict`` fails on validator warnings and conservation residuals, ``warn``
#: (default) fails on validator errors and warns on the rest, ``off`` skips the validator (only
#: not-yet-supported fields are rejected) and the conservation check.
Checks = Literal["strict", "warn", "off"]
CHECK_MODES = ("strict", "warn", "off")

#: Model-frame columns shown in summaries (when present).
SUMMARY_COLUMNS = ("Year", "Income", "Taxes", "Spending", "Housing", "Bank Balance", "Debt", "Net Worth")
#: Event kind that marks a year the household could not pay its bills (carried as new debt).
SHORTFALL_KIND = "shortfall_debt"


class InputError(ValueError):
    """Bad input other than an invalid spec: unknown example or scenario, year outside the run, bad
    change path, refused output location."""


class CheckWarning(UserWarning):
    """A post-run invariant check (money conservation) failed under ``checks="warn"``."""


@contextlib.contextmanager
def collected_warnings() -> Iterator[list[str]]:
    """Collect the warnings life-model emits inside the block (validator ``SpecWarning``,
    :class:`CheckWarning`, and any other ``UserWarning`` raised from life-model code) into the yielded
    list of messages (deduplicated, in order). Other warnings are re-emitted unchanged."""
    from .spec import SpecWarning

    package = str(Path(__file__).resolve().parent)
    messages: list[str] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            yield messages
        finally:
            others = []
            for warning in caught:
                ours = issubclass(warning.category, (SpecWarning, CheckWarning)) or (
                    issubclass(warning.category, UserWarning) and str(warning.filename).startswith(package)
                )
                if ours:
                    if str(warning.message) not in messages:
                        messages.append(str(warning.message))
                else:
                    others.append(warning)
    for warning in others:
        warnings.warn_explicit(warning.message, warning.category, warning.filename, warning.lineno)


# --------------------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------------------


def _looks_like_text(value: str) -> bool:
    stripped = value.lstrip()
    return "\n" in value or stripped.startswith(("{", "spec_version"))


def load_spec(spec: SpecLike) -> "HouseholdSpec":
    """Return a :class:`~life_model.spec.HouseholdSpec` from a spec, a dict, YAML/JSON text, or a
    ``.yaml``/``.yml``/``.json`` path.

    Raises:
        SpecValidationError: The data does not match the schema (``findings`` lists every error).
        FileNotFoundError: A path that does not exist.
    """
    from pydantic import ValidationError

    from .spec import HouseholdSpec, SpecValidationError, load, loads
    from .spec.validate import _schema_findings

    if isinstance(spec, HouseholdSpec):
        return spec
    try:
        if isinstance(spec, Mapping):
            return HouseholdSpec.model_validate(dict(spec))
        if isinstance(spec, str) and _looks_like_text(spec):
            return loads(spec)
        if isinstance(spec, (str, os.PathLike)):
            path = Path(spec)
            if not path.is_file():
                raise FileNotFoundError(f"No such spec file: {path}")
            return load(path)
    except ValidationError as error:
        raise SpecValidationError(_schema_findings(error)) from None
    raise TypeError(f"Cannot read a household spec from {type(spec).__name__}")


def example_spec(name: str) -> "HouseholdSpec":
    """A shipped synthetic example spec (``life_model.spec.EXAMPLES``)."""
    from .spec import EXAMPLES, load_example

    if name not in EXAMPLES:
        raise InputError(f"Unknown example {name!r}; expected one of: {', '.join(EXAMPLES)}")
    return load_example(name)


def list_examples() -> list[dict[str, Any]]:
    """The shipped example specs: name, description, file path and whether the engine can run it
    today (an example may use a not-yet-supported field to show its shape)."""
    from .spec import ERROR, EXAMPLES, example_path, validate_spec

    rows = []
    for name in EXAMPLES:
        spec = example_spec(name)
        errors = [f for f in validate_spec(spec) if f.level == ERROR]
        rows.append(
            {
                "name": name,
                "title": spec.meta.name,
                "description": " ".join((spec.meta.description or "").split()),
                "path": str(example_path(name)),
                "runnable": not errors,
                "blocked_by": [f"{f.path}: {f.message}" for f in errors],
            }
        )
    return rows


def _replace_meta(spec: "HouseholdSpec", **updates: Any) -> "HouseholdSpec":
    """``spec`` with ``meta`` fields replaced (``None`` values are skipped), re-validated."""
    from .spec import HouseholdSpec, to_data

    updates = {k: v for k, v in updates.items() if v is not None}
    if not updates:
        return spec
    data = to_data(spec)
    data["meta"] = {**data["meta"], **updates}
    return HouseholdSpec.model_validate(data)


def _scenario_findings(spec: "HouseholdSpec") -> "list[Finding]":
    from .config.scenarios import list_scenarios
    from .spec import ERROR, Finding

    name = spec.meta.scenario
    if name is None or name in list_scenarios():
        return []
    return [
        Finding(
            ERROR,
            "meta.scenario",
            f"unknown scenario {name!r}",
            f"use one of: {', '.join(list_scenarios())}",
            "unknown_scenario",
        )
    ]


def prepare_spec(
    spec: SpecLike,
    *,
    years: int | None = None,
    end_year: int | None = None,
    scenario: str | None = None,
) -> "HouseholdSpec":
    """Load ``spec`` and apply the run overrides: ``years`` (number of simulated years, so
    ``end_year = start_year + years - 1``) or ``end_year``, and ``scenario`` (a packaged or
    user scenario name, replacing ``meta.scenario``)."""
    from .spec import SpecValidationError

    spec = load_spec(spec)
    if years is not None and end_year is not None:
        raise InputError("Pass years or end_year, not both")
    if years is not None:
        if years < 1:
            raise InputError("years must be at least 1")
        end_year = spec.meta.start_year + years - 1
    spec = _replace_meta(spec, end_year=end_year, scenario=scenario)
    findings = _scenario_findings(spec)
    if findings:
        raise SpecValidationError(findings)
    return spec


# --------------------------------------------------------------------------------------------------
# Validate, build, run
# --------------------------------------------------------------------------------------------------


def validate(spec: SpecLike, *, scenario: str | None = None) -> "list[Finding]":
    """Every validator finding for ``spec`` (schema errors included; never raises for a bad spec).

    Returns:
        list[Finding]: ``level`` ``"error"`` or ``"warning"``, ``path``, ``message``, ``fix``,
        ``code``. Empty when nothing is wrong.
    """
    from .spec import SpecValidationError, validate_spec

    try:
        loaded = load_spec(spec)
        if scenario is not None:
            loaded = _replace_meta(loaded, scenario=scenario)
    except SpecValidationError as error:
        return list(error.findings)
    return _scenario_findings(loaded) + list(validate_spec(loaded))


def build(spec: SpecLike, *, seed: int | None = None, checks: Checks = "warn", collect_data: bool = True):
    """Build a ready-to-run :class:`~life_model.model.LifeModel` from ``spec`` (see :func:`run` for
    ``checks``)."""
    from .spec import WARNING, SpecValidationError, build_model, validate_spec

    if checks not in CHECK_MODES:
        raise InputError(f"checks must be one of {CHECK_MODES}, got {checks!r}")
    spec = load_spec(spec)
    findings = _scenario_findings(spec)
    if findings:
        raise SpecValidationError(findings)
    if checks == "strict":
        strict = [f for f in validate_spec(spec) if f.level == WARNING]
        if strict:
            raise SpecValidationError(strict)
    return build_model(spec, seed=seed, check=checks != "off", collect_data=collect_data)


def _check_conservation(result: "RunResult", checks: Checks) -> None:
    from .checks import ConservationError

    if checks == "off":
        return
    failures = [record for record in result.conservation() if not record.ok()]
    if not failures:
        return
    years = ", ".join(str(record.year) for record in failures[:10])
    message = f"money conservation failed in {len(failures)} year(s): {years} (see RunResult.conservation())"
    if checks == "strict":
        raise ConservationError(message)
    warnings.warn(message, CheckWarning, stacklevel=3)


def run(
    spec: SpecLike,
    *,
    seed: int | None = None,
    years: int | None = None,
    end_year: int | None = None,
    scenario: str | None = None,
    real_dollars: bool = False,
    checks: Checks = "warn",
) -> "RunResult":
    """Build and run a household; returns its :class:`~life_model.results.RunResult`.

    Args:
        spec: A spec, dict, YAML/JSON text or path (see :func:`load_spec`).
        seed: Overrides ``meta.seed`` (stochastic economy, mortality and other draws).
        years: Number of simulated years (``end_year = start_year + years - 1``).
        end_year: Last simulated year (inclusive); exclusive with ``years``.
        scenario: Named scenario (``life_model.config.scenarios.list_scenarios()``), replacing
            ``meta.scenario``.
        real_dollars: Return the result in start-year dollars (``RunResult.real_dollars()``).
        checks: ``"warn"`` (default): validator errors raise, validator warnings are emitted as
            ``SpecWarning`` and a failed money-conservation check as :class:`CheckWarning`.
            ``"strict"``: warnings raise too (``SpecValidationError`` / ``ConservationError``).
            ``"off"``: no validator (only not-yet-supported fields are rejected) and no check.

    Raises:
        SpecValidationError: The spec is invalid (``findings`` lists why).
        InputError: Bad overrides (unknown scenario, ``years`` and ``end_year`` both set...).
    """
    spec = prepare_spec(spec, years=years, end_year=end_year, scenario=scenario)
    model = build(spec, seed=seed, checks=checks)
    result = model.run()
    _check_conservation(result, checks)
    return result.real_dollars() if real_dollars else result


def explain(spec_or_result: "SpecLike | RunResult", year: int, **run_kwargs: Any) -> str:
    """A markdown account of ``year`` (income, bills, how they were paid, tax returns, net worth,
    events). ``spec_or_result`` is a :class:`~life_model.results.RunResult` or anything :func:`run`
    accepts (``run_kwargs`` are passed to it)."""
    from .results import RunResult

    result = spec_or_result if isinstance(spec_or_result, RunResult) else run(spec_or_result, **run_kwargs)
    years = result.years
    if year not in years:
        span = f"{years[0]}-{years[-1]}" if years else "no years"
        raise InputError(f"Year {year} is outside the simulated years ({span})")
    return result.explain(year)


# --------------------------------------------------------------------------------------------------
# Summaries
# --------------------------------------------------------------------------------------------------


def _number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(number) else number


def shortfall_years(result: "RunResult") -> list[int]:
    """Years in which the household could not pay its bills and carried the gap as new debt."""
    events = result.events
    if events.empty:
        return []
    return sorted({int(y) for y in events.loc[events["kind"] == SHORTFALL_KIND, "year"]})


def _balance_columns(frame) -> list[str]:
    columns = [c for c in frame.columns if c.endswith(" Balance") and c != "Useable Balance"]
    return columns + [c for c in ("Home Equity", "Debt", "Mortgage Principal") if c in frame.columns]


def summarize(result: "RunResult", *, yearly: bool = True) -> dict[str, Any]:
    """A JSON-ready summary of a run: span, seed, final-year net worth and balances, run totals,
    shortfall years, conservation status and (with ``yearly``) the key columns per year."""
    frame = result.model_frame
    spec = result.spec
    name = None
    if spec is not None:
        meta = getattr(spec, "meta", None)
        name = getattr(meta, "name", None) if meta is not None else (spec.get("meta") or {}).get("name")
    summary: dict[str, Any] = {
        "household": name,
        "seed": result.seed,
        "dollars": "real" if result.real else "nominal",
        "years": [result.years[0], result.years[-1]] if result.years else [],
    }
    if frame is None or frame.empty:
        return summary
    last = frame.iloc[-1]
    summary["final_year"] = int(last["Year"])
    summary["final_net_worth"] = _number(last.get("Net Worth"))
    summary["final_balances"] = {c: _number(last[c]) for c in _balance_columns(frame) if _number(last[c]) != 0}
    summary["totals"] = {
        c: _number(frame[c].sum()) for c in ("Income", "Taxes", "Spending", "Housing", "Interest Paid") if c in frame
    }
    summary["shortfall_years"] = shortfall_years(result)
    failures = [record.year for record in result.conservation() if not record.ok()]
    summary["conservation_failures"] = failures
    if yearly:
        columns = [c for c in SUMMARY_COLUMNS if c in frame.columns]
        summary["yearly"] = [
            {c: (int(row[c]) if c == "Year" else round(_number(row[c]), 2)) for c in columns}
            for _, row in frame[columns].iterrows()
        ]
    return summary


# --------------------------------------------------------------------------------------------------
# Changes (JSON merge patch + path assignments)
# --------------------------------------------------------------------------------------------------


def _find_item(items: list, key: Any, what: str) -> int:
    if isinstance(key, int) or (isinstance(key, str) and key.lstrip("-").isdigit()):
        index = int(key)
        if -len(items) <= index < len(items):
            return index % len(items)
        raise InputError(f"{what}: index {index} out of range ({len(items)} item(s))")
    for index, item in enumerate(items):
        if isinstance(item, Mapping) and item.get("id") == key:
            return index
    ids = [item.get("id") for item in items if isinstance(item, Mapping) and item.get("id")]
    raise InputError(f"{what}: no item with id {key!r} (ids: {', '.join(map(str, ids)) or 'none'})")


def merge_patch(target: Any, patch: Any, *, where: str = "") -> Any:
    """Apply a JSON merge patch (RFC 7386) to ``target`` and return the result (inputs untouched).

    Objects merge key by key, ``null`` deletes a key, anything else replaces. Two extensions for
    the spec's lists, which RFC 7386 can only replace whole:

    * ``key+: [items]`` (a key ending in ``+``) appends the items to the list ``key``;
    * an object patched onto a list patches list items by ``id`` (or by integer index):
      ``people: {sam: {retirement_age: 62}}``; ``null`` removes that item.
    """
    if not isinstance(patch, Mapping):
        return copy.deepcopy(patch)
    if isinstance(target, list):
        items = copy.deepcopy(target)
        removals = []
        for key, value in patch.items():
            index = _find_item(items, key, where or "list")
            if value is None:
                removals.append(index)
            else:
                items[index] = merge_patch(items[index], value, where=f"{where}[{key}]")
        return [item for i, item in enumerate(items) if i not in removals]
    result = copy.deepcopy(dict(target)) if isinstance(target, Mapping) else {}
    for key, value in patch.items():
        if isinstance(key, str) and key.endswith("+"):
            name = key[:-1]
            existing = result.get(name) or []
            if not isinstance(existing, list):
                raise InputError(f"{where}.{name}: '+' appends to a list, but the value is not a list")
            additions = value if isinstance(value, list) else [value]
            result[name] = existing + copy.deepcopy(additions)
        elif value is None:
            result.pop(key, None)
        else:
            result[key] = merge_patch(result.get(key), value, where=f"{where}.{key}" if where else str(key))
    return result


_PATH_TOKEN = re.compile(r"([^.\[\]]+)|\[([^\]]*)\]")


def _path_tokens(path: str) -> list[tuple[str, bool]]:
    """``a.b[0][+].c`` -> [("a", False), ("b", False), ("0", True), ("+", True), ("c", False)]."""
    tokens = []
    position = 0
    for match in _PATH_TOKEN.finditer(path):
        if match.start() != position and path[position : match.start()] != ".":
            raise InputError(f"Cannot parse change path {path!r}")
        position = match.end()
        tokens.append((match.group(1), False) if match.group(1) is not None else (match.group(2), True))
    if not tokens or position != len(path):
        raise InputError(f"Cannot parse change path {path!r}")
    return tokens


def set_path(data: dict, path: str, value: Any) -> dict:
    """Return a copy of ``data`` with ``value`` assigned at ``path``.

    Paths are dotted keys with list selectors: ``meta.end_year``, ``people[0].age``,
    ``people[sam].retirement_age`` or ``people.sam.retirement_age`` (an item by ``id``), and
    ``events[+]`` to append. Missing objects along the way are created.
    """
    data = copy.deepcopy(data)
    tokens = _path_tokens(path)
    node: Any = data
    for depth, (token, _) in enumerate(tokens):
        last = depth == len(tokens) - 1
        if isinstance(node, list):
            if token == "+":
                if not last:
                    node.append({})
                    node = node[-1]
                    continue
                node.append(value)
                return data
            index = _find_item(node, token, path)
            if last:
                node[index] = value
                return data
            node = node[index]
            continue
        if not isinstance(node, dict):
            raise InputError(f"{path}: cannot descend into a {type(node).__name__} at {token!r}")
        key: Any = int(token) if token.isdigit() and int(token) in node else token
        if last:
            node[key] = value
            return data
        if node.get(key) is None:
            next_token = tokens[depth + 1][0]
            node[key] = [] if next_token == "+" else {}
        node = node[key]
    return data


def parse_assignment(text: str) -> tuple[str, Any]:
    """``"path=value"`` -> (path, value), the value read as YAML (numbers, booleans, null, strings,
    and flow collections such as ``{action: retire, ...}``)."""
    import yaml

    if "=" not in text:
        raise InputError(f"Expected PATH=VALUE, got {text!r}")
    path, raw = text.split("=", 1)
    try:
        value = yaml.safe_load(raw) if raw.strip() else ""
    except yaml.YAMLError as error:
        raise InputError(f"Cannot read the value of {path!r}: {error}") from None
    return path.strip(), value


def apply_change(
    spec: SpecLike, change: Mapping | None = None, *, sets: Iterable[str | tuple[str, Any]] = ()
) -> "HouseholdSpec":
    """``spec`` with a merge patch (:func:`merge_patch`) and then ``sets`` (``"path=value"``
    strings or ``(path, value)`` pairs, see :func:`set_path`) applied, re-validated."""
    from pydantic import ValidationError

    from .spec import HouseholdSpec, SpecValidationError, to_data
    from .spec.validate import _schema_findings

    data = to_data(load_spec(spec))
    if change:
        if not isinstance(change, Mapping):
            raise InputError("A change must be a mapping (a JSON merge patch)")
        data = merge_patch(data, change)
    for item in sets:
        path, value = parse_assignment(item) if isinstance(item, str) else item
        data = set_path(data, path, value)
    try:
        return HouseholdSpec.model_validate(data)
    except ValidationError as error:
        raise SpecValidationError(_schema_findings(error)) from None


def load_change(path: "str | os.PathLike") -> dict:
    """Read a change file (YAML or JSON merge patch)."""
    import yaml

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"No such change file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise InputError(f"{path}: a change file must hold a mapping (a JSON merge patch)")
    return dict(data)


# --------------------------------------------------------------------------------------------------
# Monte Carlo
# --------------------------------------------------------------------------------------------------


class _SpecModelFactory:
    """Picklable ``factory(seed) -> LifeModel`` for :class:`~life_model.montecarlo.MonteCarlo`."""

    def __init__(self, spec: "HouseholdSpec"):
        self.spec = spec

    def __call__(self, seed: int):
        from .spec import build_model

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return build_model(self.spec, seed=seed, check=False)


def run_montecarlo(
    spec: SpecLike,
    *,
    n: int = 1000,
    seed: int | None = None,
    workers: int | None = None,
    years: int | None = None,
    end_year: int | None = None,
    scenario: str | None = None,
    checks: Checks = "warn",
) -> "MonteCarloResult":
    """Run ``n`` trials of ``spec`` (validated once) that differ only in their seeds; events are
    kept so :func:`montecarlo_summary` can report the success rate. Trials only differ when the spec
    has random draws: ``economy.mode: stochastic`` (or ``scenario="stochastic"``), stochastic
    mortality, or long-term-care need."""
    from .montecarlo import MonteCarlo

    spec = prepare_spec(spec, years=years, end_year=end_year, scenario=scenario)
    build(spec, checks=checks, collect_data=False)  # validate once, up front
    return MonteCarlo(_SpecModelFactory(spec), n=n, seed=seed, workers=workers, keep_events=True).run()


def montecarlo_summary(result: "MonteCarloResult", *, percentiles: Sequence[float] = (10, 50, 90)) -> dict:
    """Success rate (share of trials with no shortfall year), final-year net worth percentiles and
    whether the trials differed at all."""
    import numpy as np

    final = np.array([_number(frame["Net Worth"].iloc[-1]) for frame in result.frames])
    if result.events is not None:
        successes = sum(1 for events in result.events if not (events["kind"] == SHORTFALL_KIND).any())
    else:
        successes = sum(1 for value in final if value > 0)
    return {
        "trials": result.num_trials,
        "years": [result.years[0], result.years[-1]],
        "success_rate": successes / result.num_trials,
        "success_definition": "share of trials in which the household never carried unpaid bills as new debt",
        "final_net_worth": {f"p{int(p)}": float(np.percentile(final, p)) for p in percentiles},
        "trials_differ": bool(final.size > 1 and np.ptp(final) > 0),
    }


# --------------------------------------------------------------------------------------------------
# Compare
# --------------------------------------------------------------------------------------------------


@dataclass
class Comparison:
    """A base run and a changed run of the same household, with their deltas (changed - base)."""

    base_spec: "HouseholdSpec"
    changed_spec: "HouseholdSpec"
    base: "RunResult"
    changed: "RunResult"
    deltas: dict[str, Any]
    montecarlo: dict[str, Any] | None = None
    #: What changed: ``{"patch": merge patch or None, "sets": ["path=value", ...]}``.
    changes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready: both summaries (without yearly rows), the deltas, and the Monte Carlo block."""
        return {
            "seed": self.base.seed,
            "changes": copy.deepcopy(self.changes),
            "base": summarize(self.base, yearly=False),
            "changed": summarize(self.changed, yearly=False),
            "deltas": self.deltas,
            "montecarlo": self.montecarlo,
        }


def _deltas(base: dict, changed: dict) -> dict[str, Any]:
    balances = sorted(set(base.get("final_balances", {})) | set(changed.get("final_balances", {})))
    return {
        "final_net_worth": changed.get("final_net_worth", 0.0) - base.get("final_net_worth", 0.0),
        "total_taxes": changed.get("totals", {}).get("Taxes", 0.0) - base.get("totals", {}).get("Taxes", 0.0),
        "final_balances": {
            column: changed.get("final_balances", {}).get(column, 0.0) - base.get("final_balances", {}).get(column, 0.0)
            for column in balances
        },
        "shortfall_years": len(changed.get("shortfall_years", [])) - len(base.get("shortfall_years", [])),
    }


def compare(
    spec: SpecLike,
    change: Mapping | None = None,
    *,
    sets: Iterable[str | tuple[str, Any]] = (),
    seed: int | None = None,
    years: int | None = None,
    end_year: int | None = None,
    scenario: str | None = None,
    real_dollars: bool = False,
    checks: Checks = "warn",
    montecarlo: int = 0,
    workers: int | None = None,
) -> Comparison:
    """Run ``spec`` and ``spec`` with a change, and report the differences.

    Args:
        spec: The base household (anything :func:`load_spec` accepts).
        change: A JSON merge patch applied to the spec (:func:`merge_patch`, with the ``key+``
            append and patch-by-id extensions).
        sets: ``"path=value"`` assignments applied after the patch (:func:`set_path`).
        montecarlo: With ``N > 0``, also run ``N`` paired trials of each (same master seed) and
            report both success rates and their difference.
        Other arguments: as for :func:`run`, applied to both runs.

    Returns:
        :class:`Comparison`; ``deltas`` holds the change in final-year net worth, total taxes over
        the run, final-year balances and the number of shortfall years.
    """
    base_spec = prepare_spec(spec, years=years, end_year=end_year, scenario=scenario)
    sets = list(sets)
    if not change and not sets:
        raise InputError("compare needs a change (a merge patch or at least one path=value)")
    changed_spec = apply_change(base_spec, change, sets=sets)
    changed_spec = prepare_spec(changed_spec)
    if seed is None:
        seed = base_spec.meta.seed
    if seed is None:
        # Both runs must share their random draws, so an unseeded spec gets one seed for both.
        seed = secrets.randbelow(2**31)
    kwargs = {"seed": seed, "real_dollars": real_dollars, "checks": checks}
    base = run(base_spec, **kwargs)
    changed = run(changed_spec, **kwargs)
    deltas = _deltas(summarize(base, yearly=False), summarize(changed, yearly=False))
    described = {
        "patch": copy.deepcopy(dict(change)) if change else None,
        "sets": [s if isinstance(s, str) else f"{s[0]}={s[1]!r}" for s in sets],
    }
    mc = None
    if montecarlo:
        mc_seed = seed
        mc_base = montecarlo_summary(
            run_montecarlo(base_spec, n=montecarlo, seed=mc_seed, workers=workers, checks=checks)
        )
        mc_changed = montecarlo_summary(
            run_montecarlo(changed_spec, n=montecarlo, seed=mc_seed, workers=workers, checks=checks)
        )
        mc = {
            "base": mc_base,
            "changed": mc_changed,
            "success_rate_delta": mc_changed["success_rate"] - mc_base["success_rate"],
        }
    return Comparison(base_spec, changed_spec, base, changed, deltas, mc, described)


def finding_dict(finding: "Finding") -> dict[str, Any]:
    """A validator finding as a JSON-ready dict."""
    return asdict(finding)
