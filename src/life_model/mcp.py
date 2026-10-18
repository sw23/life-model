# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""An MCP server exposing the household tools over stdio (optional extra: ``life-model[mcp]``).

Start it with ``life-model mcp`` or ``python -m life_model.mcp``. Register it with Claude Code::

    claude mcp add life-model -- life-model mcp

Tools (thin wrappers over :mod:`life_model.api`; no simulation logic lives here):

* ``run_household``: run a spec, return the summary (final net worth and balances, totals, shortfall
  years, key columns per year) and the warnings;
* ``validate_household``: the validator's findings;
* ``compare_change``: run a spec with and without a JSON merge patch / ``path=value`` changes, return
  the deltas (and Monte Carlo success rates with ``montecarlo=N``);
* ``explain_year``: the markdown account of one simulated year;
* ``reconcile_household``: a simulated year against the household's filed return and statements;
* ``get_schema``: the household spec JSON Schema;
* ``list_examples``: the shipped synthetic examples (optionally with their YAML) and the scenarios.

Every tool takes the household as exactly one of ``spec`` (an object or YAML/JSON text),
``spec_path`` (a file the server can read) or ``example`` (a shipped example name), and returns a
JSON object with ``ok``; a failure has ``error`` (``kind`` ``validation`` or ``runtime``,
``message``) and ``findings``, mirroring ``life-model --json``.
"""

import sys
from collections.abc import Callable
from typing import Any

from . import api

SERVER_NAME = "life-model"
INSTRUCTIONS = (
    "Simulate a household's finances year by year from a household spec (YAML/JSON; get_schema for "
    "the format, list_examples for synthetic examples). Validate first, then run, explain a year, or "
    "compare a change. Rates are percentages (4.5 = 4.5%); every flow says _annual or _monthly. "
    "Never invent balances: ask for the statement values that are missing."
)


def _spec_source(spec: Any = None, spec_path: str | None = None, example: str | None = None) -> Any:
    given = [value is not None for value in (spec, spec_path, example)]
    if sum(given) != 1:
        raise api.InputError("Pass exactly one of spec, spec_path or example")
    if example is not None:
        return api.example_spec(example)
    if spec_path is not None:
        return spec_path
    if isinstance(spec, str) and not api._looks_like_text(spec):
        raise api.InputError("spec text must be a YAML or JSON document (use spec_path for a file)")
    return spec


def _call(function: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run a tool body under the CLI's error contract."""
    from .spec import SpecValidationError

    try:
        with api.collected_warnings() as messages:
            payload = function()
        return {"ok": True, **payload, "warnings": messages}
    except SpecValidationError as error:
        findings = [api.finding_dict(f) for f in error.findings]
        return {
            "ok": False,
            "error": {"kind": "validation", "message": f"{len(findings)} validation error(s)"},
            "findings": findings,
        }
    except (api.InputError, FileNotFoundError) as error:
        return {"ok": False, "error": {"kind": "validation", "message": str(error)}, "findings": []}
    except Exception as error:  # noqa: BLE001 - every other failure is a runtime error
        return {
            "ok": False,
            "error": {"kind": "runtime", "message": f"{type(error).__name__}: {error}"},
            "findings": [],
        }


# --- Tool bodies (plain functions, testable without the mcp package) ------------------------------


def run_household(
    spec: dict[str, Any] | str | None = None,
    spec_path: str | None = None,
    example: str | None = None,
    seed: int | None = None,
    years: int | None = None,
    end_year: int | None = None,
    scenario: str | None = None,
    real_dollars: bool = False,
    checks: str = "warn",
    yearly: bool = True,
) -> dict[str, Any]:
    """Run a household spec and summarize it: final-year net worth and balances, run totals (income,
    taxes, spending, housing), years with unpaid bills, and key columns per year (``yearly``).
    ``years`` is the number of simulated years; ``scenario`` a named scenario such as 'stochastic'
    or 'recession'; ``checks`` 'warn' (default), 'strict' or 'off'."""

    def body() -> dict[str, Any]:
        result = api.run(
            _spec_source(spec, spec_path, example),
            seed=seed,
            years=years,
            end_year=end_year,
            scenario=scenario,
            real_dollars=real_dollars,
            checks=checks,  # type: ignore[arg-type]
        )
        return {"summary": api.summarize(result, yearly=yearly)}

    return _call(body)


def validate_household(
    spec: dict[str, Any] | str | None = None,
    spec_path: str | None = None,
    example: str | None = None,
    scenario: str | None = None,
) -> dict[str, Any]:
    """Validate a household spec: every finding (level 'error' or 'warning', path, message, fix,
    code). ``valid`` is false when any finding is an error."""

    def body() -> dict[str, Any]:
        findings = api.validate(_spec_source(spec, spec_path, example), scenario=scenario)
        return {
            "valid": not any(f.level == "error" for f in findings),
            "findings": [api.finding_dict(f) for f in findings],
        }

    return _call(body)


def compare_change(
    spec: dict[str, Any] | str | None = None,
    spec_path: str | None = None,
    example: str | None = None,
    change: dict[str, Any] | None = None,
    sets: list[str] | None = None,
    seed: int | None = None,
    years: int | None = None,
    end_year: int | None = None,
    scenario: str | None = None,
    real_dollars: bool = False,
    montecarlo: int = 0,
) -> dict[str, Any]:
    """Run a household with and without a change and return the deltas (changed minus base) in
    final net worth, total taxes, final balances and shortfall years. ``change`` is a JSON merge
    patch on the spec ('key+': [...] appends to a list; {'people': {'<id>': {...}}} patches a list
    item by id); ``sets`` are 'path=value' strings such as 'people[alex].retirement_age=62'.
    ``montecarlo=N`` adds N-trial success rates for both (use scenario='stochastic')."""

    def body() -> dict[str, Any]:
        comparison = api.compare(
            _spec_source(spec, spec_path, example),
            change,
            sets=sets or (),
            seed=seed,
            years=years,
            end_year=end_year,
            scenario=scenario,
            real_dollars=real_dollars,
            montecarlo=montecarlo,
        )
        return comparison.to_dict()

    return _call(body)


def explain_year(
    year: int,
    spec: dict[str, Any] | str | None = None,
    spec_path: str | None = None,
    example: str | None = None,
    seed: int | None = None,
    scenario: str | None = None,
    real_dollars: bool = False,
) -> dict[str, Any]:
    """Explain one simulated year in markdown: income by source, bills, how they were paid (forced
    sales, pre-tax withdrawals), each tax return, the change in net worth, and the year's events."""

    def body() -> dict[str, Any]:
        markdown = api.explain(
            _spec_source(spec, spec_path, example), year, seed=seed, scenario=scenario, real_dollars=real_dollars
        )
        return {"year": year, "markdown": markdown}

    return _call(body)


def reconcile_household(
    year: int,
    spec: dict[str, Any] | str | None = None,
    spec_path: str | None = None,
    example: str | None = None,
    actuals: dict[str, Any] | None = None,
    actuals_path: str | None = None,
    seed: int | None = None,
    scenario: str | None = None,
    checks: str = "warn",
) -> dict[str, Any]:
    """Compare a simulated tax year with the household's actual records (filed Form 1040 lines by that
    year's line numbers, W-2 boxes, 1099 boxes, paystub, year-end balances): per line simulated vs
    actual, difference, status (green/yellow/red/not_modeled) and likely cause. Records come from the
    spec's ``actuals`` or from ``actuals`` / ``actuals_path`` ({year: records} or one year's records)."""

    def body() -> dict[str, Any]:
        if actuals is not None and actuals_path is not None:
            raise api.InputError("Pass actuals or actuals_path, not both")
        report = api.reconcile(
            _spec_source(spec, spec_path, example),
            year,
            actuals=actuals if actuals is not None else actuals_path,
            seed=seed,
            scenario=scenario,
            checks=checks,  # type: ignore[arg-type]
        )
        return {"report": report.to_dict(), "markdown": report.to_markdown()}

    return _call(body)


def get_schema() -> dict[str, Any]:
    """The household spec JSON Schema (the input format of every other tool)."""
    from .spec import json_schema

    return _call(lambda: {"schema": json_schema()})


def list_examples(include_spec: bool = False) -> dict[str, Any]:
    """The shipped synthetic example households (name, description, whether the engine can run them
    today; their YAML with ``include_spec``) and the named scenarios."""
    from .config.scenarios import list_scenarios
    from .spec import example_path

    def body() -> dict[str, Any]:
        examples = api.list_examples()
        if include_spec:
            for row in examples:
                row["spec"] = example_path(row["name"]).read_text(encoding="utf-8")
        return {"examples": examples, "scenarios": list_scenarios()}

    return _call(body)


TOOLS: tuple[Callable[..., dict[str, Any]], ...] = (
    run_household,
    validate_household,
    compare_change,
    explain_year,
    reconcile_household,
    get_schema,
    list_examples,
)


def _server_class():
    try:  # mcp >= 2
        from mcp.server.mcpserver import MCPServer

        return MCPServer
    except ImportError:
        pass
    try:  # mcp 1.x
        from mcp.server.fastmcp import FastMCP

        return FastMCP
    except ImportError as error:
        raise ImportError(
            "The MCP server needs the official MCP Python SDK: pip install 'life-model[mcp]' (or pip install mcp)"
        ) from error


def create_server():
    """The MCP server with every tool in :data:`TOOLS` registered."""
    server = _server_class()(SERVER_NAME, instructions=INSTRUCTIONS)
    for tool in TOOLS:
        server.tool()(tool)
    return server


def main() -> None:
    """Serve over stdio until the client disconnects."""
    try:
        server = create_server()
    except ImportError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    server.run("stdio")


if __name__ == "__main__":
    main()
