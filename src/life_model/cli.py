# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The ``life-model`` command line (also ``python -m life_model``).

Subcommands (``life-model <command> --help`` for the flags)::

    life-model run SPEC [--seed N] [--years N | --end-year Y] [--scenario NAME] [--real-dollars]
                        [--out DIR --format json|csv|parquet] [--checks strict|warn|off]
    life-model validate SPEC
    life-model explain SPEC --year Y
    life-model reconcile SPEC --year Y [--actuals FILE]
    life-model compare SPEC (--change CHANGE.yaml | --set PATH=VALUE)... [--montecarlo N]
    life-model montecarlo SPEC [--n 1000] [--seed N] [--out DIR]
    life-model schema
    life-model examples [--show NAME | --copy NAME DEST]
    life-model mcp                      # stdio MCP server (needs the 'mcp' extra)

``SPEC`` is a household spec file (YAML or JSON, see docs/household-spec.md); every command that
takes one also accepts ``--example NAME`` to use a shipped synthetic example instead.

Every command accepts ``--json``: stdout is then exactly one JSON object, ``{"ok": true,
"command": ..., ...}`` on success or ``{"ok": false, "command": ..., "error": {"kind":
"validation"|"runtime", "message": ..., "findings": [...]}}`` on failure.

Exit codes: 0 success; 2 invalid input (the spec fails the schema or the validator, an unknown
example or scenario, a year outside the run, a refused output path, bad flags); 1 any other error.

Adding a subcommand is one handler function plus one ``Command(...)`` line in :data:`COMMANDS`
(see :class:`Command`).
"""

import argparse
import json
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__, api

EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_INVALID = 2


class CommandFailed(Exception):
    """A handler's controlled failure: ``payload`` is reported and the process exits ``code``."""

    def __init__(self, message: str, code: int = EXIT_INVALID, payload: dict | None = None, text: str = ""):
        super().__init__(message)
        self.code = code
        self.payload = payload or {}
        self.text = text


@dataclass(frozen=True)
class Command:
    """One subcommand: ``add_arguments(parser)`` declares its flags, ``handler(args)`` does the work
    and returns ``(payload, text)``: the JSON payload for ``--json`` and the human-readable text.

    A handler raises :class:`CommandFailed` (or lets a ``SpecValidationError`` /
    ``api.InputError`` / any other exception escape) to fail; :func:`main` maps that to the
    output contract and exit code.
    """

    name: str
    help: str
    add_arguments: Callable[[argparse.ArgumentParser], None]
    handler: Callable[[argparse.Namespace], tuple[dict[str, Any], str]]


# --------------------------------------------------------------------------------------------------
# Shared arguments and helpers
# --------------------------------------------------------------------------------------------------


def _spec_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("spec", nargs="?", help="household spec file (.yaml/.yml/.json)")
    parser.add_argument("--example", metavar="NAME", help="use a shipped example spec instead of SPEC")


def _run_arguments(parser: argparse.ArgumentParser, *, real_dollars: bool = True) -> None:
    _spec_arguments(parser)
    parser.add_argument("--seed", type=int, help="random seed (overrides meta.seed)")
    span = parser.add_mutually_exclusive_group()
    span.add_argument("--years", type=int, help="number of simulated years (end = start + N - 1)")
    span.add_argument("--end-year", type=int, help="last simulated year (inclusive; overrides meta.end_year)")
    parser.add_argument("--scenario", help="named scenario (overrides meta.scenario; see life-model examples)")
    parser.add_argument(
        "--checks",
        choices=api.CHECK_MODES,
        default="warn",
        help="validator and yearly invariant checks: strict: warnings and violations fail; warn (default): "
        "errors fail, warnings and violations reported; off: skip checks",
    )
    if real_dollars:
        parser.add_argument("--real-dollars", action="store_true", help="report money in start-year dollars")


def _spec_source(args: argparse.Namespace) -> Any:
    if args.spec and args.example:
        raise api.InputError("Pass a spec file or --example, not both")
    if args.example:
        return api.example_spec(args.example)
    if not args.spec:
        raise api.InputError("A spec file (or --example NAME) is required")
    return args.spec


def _run_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    kwargs = {
        "seed": args.seed,
        "years": args.years,
        "end_year": args.end_year,
        "scenario": args.scenario,
        "checks": args.checks,
    }
    if hasattr(args, "real_dollars"):
        kwargs["real_dollars"] = args.real_dollars
    return kwargs


def _package_dir() -> Path:
    return Path(__file__).resolve().parent


def check_output_path(path: str | Path) -> Path:
    """Refuse to write outputs into the package sources: inside the installed ``life_model``
    package, or inside any ``src/`` directory holding a ``life_model`` package (a checkout). Run
    outputs describe a household and belong in an ignored directory such as ``my-models/``."""
    resolved = Path(path).expanduser().resolve()
    package = _package_dir()
    candidates = [resolved, *resolved.parents]
    if package in candidates:
        raise api.InputError(f"Refusing to write {path} inside the life_model package ({package})")
    for directory in candidates:
        if directory.name == "src" and (directory / "life_model").is_dir():
            raise api.InputError(
                f"Refusing to write {path} inside {directory}: outputs describe a household and must not land in "
                "the package sources (use my-models/ or another git-ignored directory)"
            )
    return resolved


def _money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def _signed(value: float) -> str:
    return ("+" if value > 0 else "") + _money(value)


def _table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    columns = list(rows[0])
    cells = [[str(r[c]) if c == "Year" else _money(r[c]) for c in columns] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(columns)]
    lines = ["  ".join(c.rjust(w) for c, w in zip(columns, widths, strict=True))]
    lines += ["  ".join(v.rjust(w) for v, w in zip(row, widths, strict=True)) for row in cells]
    return "\n".join(lines)


def _summary_text(summary: dict[str, Any]) -> str:
    span = f"{summary['years'][0]}-{summary['years'][-1]}"
    if summary.get("start"):
        span = f"{summary['start']} to {summary['years'][-1]}-12"
    lines = [
        (
            f"{summary.get('household') or 'household'}: {span}, "
            f"seed {summary.get('seed')}, {summary['dollars']} dollars"
        ),
    ]
    if summary.get("months"):
        lines.append(f"month-end rows: {summary['months']}")
    if "final_net_worth" in summary:
        lines.append(f"final net worth ({summary['final_year']}): {_money(summary['final_net_worth'])}")
        totals = ", ".join(f"{k.lower()} {_money(v)}" for k, v in summary.get("totals", {}).items())
        lines.append(f"totals: {totals}")
        lines += _extremes_text(summary)
        shortfalls = summary.get("shortfall_years", [])
        lines.append(f"shortfall years (bills carried as debt): {shortfalls if shortfalls else 'none'}")
        failures = summary.get("conservation_failures", [])
        if failures:
            lines.append(f"conservation check failed in: {failures} (a model bug: please report it)")
        else:
            lines.append("conservation check: passed in every year (checked in nominal dollars)")
    return "\n".join(lines)


def _extremes_text(summary: dict[str, Any]) -> list[str]:
    """The net-worth peak and lowest-cash lines of a run summary (both in nominal and start-year dollars)."""
    lines = []
    for key, label in (
        ("net_worth_peak", "net worth peak"),
        ("lowest_cash", "lowest cash (year-end bank balance)"),
        ("lowest_cash_retired", "lowest cash after everyone retires"),
    ):
        block = summary.get(key)
        if not block:
            continue
        nominal, real = block["nominal"], block["real"]
        lines.append(
            f"{label}: {_money(nominal['amount'])} in {nominal['year']} (nominal); "
            f"{_money(real['amount'])} in {real['year']} (start-year dollars)"
        )
    return lines


# --------------------------------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------------------------------


def _run_add(parser: argparse.ArgumentParser) -> None:
    _run_arguments(parser)
    parser.add_argument("--out", metavar="DIR", help="write the full result to DIR")
    parser.add_argument(
        "--format",
        choices=("json", "csv", "parquet"),
        default="json",
        help="output format for --out: json (DIR/result.json), csv or parquet (one file per table)",
    )
    parser.add_argument(
        "--collect",
        choices=("year", "month"),
        default="year",
        help="rows to collect: year (default) or month (also a row per month end: monthly_frame in result.json, "
        "monthly.csv / monthly.parquet)",
    )


def _run(args: argparse.Namespace) -> tuple[dict, str]:
    out = check_output_path(args.out) if args.out else None
    if out is not None and args.format == "parquet":
        from .results import _require_parquet

        _require_parquet()  # fail before running, and before creating DIR
    result = api.run(_spec_source(args), collect=args.collect, **_run_kwargs(args))
    summary = api.summarize(result)
    files: list[str] = []
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        if args.format == "json":
            files.append(str(result.to_json(out / "result.json")))
        elif args.format == "csv":
            result.to_csv(out)
            files = sorted(str(p) for p in out.iterdir() if p.suffix in (".csv", ".json"))
        else:
            result.to_parquet(out)
            files = sorted(str(p) for p in out.iterdir() if p.suffix in (".parquet", ".json"))
    payload = {"summary": summary, "files": files}
    text = _table(summary.get("yearly", [])) + "\n\n" + _summary_text(summary)
    if files:
        text += "\nwrote: " + ", ".join(files)
    return payload, text


def _validate_add(parser: argparse.ArgumentParser) -> None:
    _spec_arguments(parser)
    parser.add_argument("--scenario", help="named scenario to check (overrides meta.scenario)")


def _validate(args: argparse.Namespace) -> tuple[dict, str]:
    from .spec import ERROR

    source = _spec_source(args)
    findings = api.validate(source, scenario=args.scenario)
    everything = api.validate(source, scenario=args.scenario, include_accepted=True)
    accepted = [f for f in everything if f not in findings]
    errors = [f for f in findings if f.level == ERROR]
    payload = {
        "valid": not errors,
        "error_count": len(errors),
        "warning_count": len(findings) - len(errors),
        "findings": [api.finding_dict(f) for f in findings],
        "accepted": [api.finding_dict(f) for f in accepted],
    }
    text = "\n".join(str(f) for f in findings) or "no findings"
    if accepted:
        codes = sorted({f.code for f in accepted})
        text += f"\n({len(accepted)} warning(s) accepted in meta.accepted_warnings: {', '.join(codes)})"
    if errors:
        raise CommandFailed(f"{len(errors)} validation error(s)", EXIT_INVALID, payload, text)
    return payload, text


def _explain_add(parser: argparse.ArgumentParser) -> None:
    _run_arguments(parser)
    parser.add_argument("--year", type=int, required=True, help="the simulated year to explain")


def _explain(args: argparse.Namespace) -> tuple[dict, str]:
    markdown = api.explain(_spec_source(args), args.year, **_run_kwargs(args))
    return {"year": args.year, "markdown": markdown}, markdown.rstrip()


def _compare_add(parser: argparse.ArgumentParser) -> None:
    _run_arguments(parser)
    parser.add_argument(
        "--change",
        metavar="FILE",
        action="append",
        default=[],
        help="YAML/JSON merge patch applied to the spec (repeatable; 'key+: [...]' appends to a list, "
        "'people: {ID: {...}}' patches a list item by id)",
    )
    parser.add_argument(
        "--set",
        metavar="PATH=VALUE",
        action="append",
        default=[],
        dest="sets",
        help="assign one value, e.g. people[sam].retirement_age=62 or 'events[+]={...}' (repeatable)",
    )
    parser.add_argument("--montecarlo", type=int, default=0, metavar="N", help="also compare N-trial success rates")
    parser.add_argument("--workers", type=int, help="Monte Carlo worker processes (default: automatic)")


def _compare(args: argparse.Namespace) -> tuple[dict, str]:
    change: dict = {}
    for path in args.change:
        change = api.merge_patch(change, api.load_change(path)) if change else api.load_change(path)
    kwargs = _run_kwargs(args)
    comparison = api.compare(
        _spec_source(args), change or None, sets=args.sets, montecarlo=args.montecarlo, workers=args.workers, **kwargs
    )
    payload = comparison.to_dict(yearly=True)
    deltas = payload["deltas"]
    changes = payload["changes"]
    described = ([f"patch {json.dumps(changes['patch'], default=str)}"] if changes.get("patch") else []) + [
        f"set {item}" for item in changes.get("sets", [])
    ]
    lines = [f"changes (seed {payload['seed']}): " + "; ".join(described)]
    base, changed = payload["base"], payload["changed"]
    lines.append(
        f"final net worth: {_money(base.get('final_net_worth', 0))} -> {_money(changed.get('final_net_worth', 0))} "
        f"({_signed(deltas['final_net_worth'])})"
    )
    lines.append(
        f"total taxes: {_money(base.get('totals', {}).get('Taxes', 0))} -> "
        f"{_money(changed.get('totals', {}).get('Taxes', 0))} ({_signed(deltas['total_taxes'])})"
    )
    for column, delta in deltas["final_balances"].items():
        if abs(delta) >= 0.5:
            lines.append(f"final {column}: {_signed(delta)}")
    lines.append(
        f"shortfall years: {len(base.get('shortfall_years', []))} -> {len(changed.get('shortfall_years', []))} "
        f"({deltas['shortfall_years']:+d})"
    )
    for key, label in (
        ("net_worth_peak", "net worth peak"),
        ("lowest_cash", "lowest cash"),
        ("lowest_cash_retired", "lowest cash after everyone retires"),
    ):
        if key not in base or key not in changed:
            continue
        for dollars, unit in (("nominal", "nominal"), ("real", "start-year dollars")):
            old, new = base[key][dollars], changed[key][dollars]
            lines.append(
                f"{label} ({unit}): {_money(old['amount'])} in {old['year']} -> {_money(new['amount'])} in "
                f"{new['year']} ({_signed(new['amount'] - old['amount'])})"
            )
    for name, block in (("base", base), ("changed", changed)):
        if block.get("conservation_failures"):
            lines.append(f"conservation check failed in the {name} run: {block['conservation_failures']}")
    mc = payload.get("montecarlo")
    if mc:
        lines.append(
            f"success rate ({mc['base']['trials']} trials): {mc['base']['success_rate']:.1%} -> "
            f"{mc['changed']['success_rate']:.1%} ({mc['success_rate_delta']:+.1%})"
        )
        if not mc["base"]["trials_differ"]:
            lines.append("note: every trial was identical (the spec has no random draws; try --scenario stochastic)")
    return payload, "\n".join(lines)


def _montecarlo_add(parser: argparse.ArgumentParser) -> None:
    _run_arguments(parser)
    parser.add_argument("--n", type=int, default=1000, help="number of trials (default 1000)")
    parser.add_argument("--workers", type=int, help="worker processes (default: automatic; 1 = sequential)")
    parser.add_argument("--out", metavar="DIR", help="write every trial's yearly frame and events to DIR")
    parser.add_argument(
        "--format",
        choices=("auto", "parquet", "csv"),
        default="auto",
        help="output format for --out (auto: parquet when pyarrow is installed, else csv)",
    )


def _write_montecarlo(result, directory: Path, fmt: str, summary: dict) -> list[str]:
    directory.mkdir(parents=True, exist_ok=True)
    if fmt == "auto":
        try:
            import pyarrow  # noqa: F401

            fmt = "parquet"
        except ImportError:
            fmt = "csv"
    if fmt == "parquet":
        result.to_parquet(directory)
    else:
        result._stack(result.frames, result.seeds).to_csv(directory / "model.csv", index=False)
        if result.events is not None:
            result._stack(result.events, result.seeds).to_csv(directory / "events.csv", index=False)
        (directory / "meta.json").write_text(json.dumps({"seeds": result.seeds, "real": result.real}))
    (directory / "summary.json").write_text(json.dumps(summary, indent=2))
    return sorted(str(p) for p in directory.iterdir())


def _montecarlo(args: argparse.Namespace) -> tuple[dict, str]:
    out = check_output_path(args.out) if args.out else None
    if args.n < 1:
        raise api.InputError("--n must be at least 1")
    kwargs = _run_kwargs(args)
    result = api.run_montecarlo(_spec_source(args), n=args.n, workers=args.workers, **kwargs)
    summary = api.montecarlo_summary(result)
    files = _write_montecarlo(result, out, args.format, summary) if out is not None else []
    payload = {"summary": summary, "files": files}
    pct = ", ".join(f"{k} {_money(v)}" for k, v in summary["final_net_worth"].items())
    text = (
        f"{summary['trials']} trials, {summary['years'][0]}-{summary['years'][1]}, {summary['dollars']} dollars\n"
        f"success rate: {summary['success_rate']:.1%} ({summary['success_definition']})\n"
        f"final net worth: {pct}"
    )
    if not summary["trials_differ"]:
        text += "\nnote: every trial was identical (the spec has no random draws; try --scenario stochastic)"
    if files:
        text += "\nwrote: " + ", ".join(files)
    return payload, text


def _schema_add(parser: argparse.ArgumentParser) -> None:
    pass


def _schema(args: argparse.Namespace) -> tuple[dict, str]:
    from .spec import json_schema

    schema = json_schema()
    return {"schema": schema}, json.dumps(schema, indent=2)


def _examples_add(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--show", metavar="NAME", help="print an example spec")
    group.add_argument("--copy", nargs=2, metavar=("NAME", "DEST"), help="copy an example spec to DEST")
    parser.add_argument("--force", action="store_true", help="overwrite DEST with --copy")


def _examples(args: argparse.Namespace) -> tuple[dict, str]:
    from .config.scenarios import list_scenarios
    from .spec import example_path

    if args.show:
        api.example_spec(args.show)
        text = example_path(args.show).read_text(encoding="utf-8")
        return {"name": args.show, "spec": text}, text.rstrip()
    if args.copy:
        name, dest = args.copy
        api.example_spec(name)
        target = check_output_path(dest)
        if target.is_dir():
            target = target / f"{name}.yaml"
        if target.exists() and not args.force:
            raise api.InputError(f"{target} exists (pass --force to overwrite)")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(example_path(name), target)
        return {"name": name, "path": str(target)}, f"copied {name} to {target}"
    examples = api.list_examples()
    lines = []
    for row in examples:
        status = "" if row["runnable"] else "  [not runnable yet: " + "; ".join(row["blocked_by"]) + "]"
        lines.append(f"{row['name']}: {row['description']}{status}")
    scenarios = list_scenarios()
    lines += ["", "scenarios: " + ", ".join(scenarios)]
    return {"examples": examples, "scenarios": scenarios}, "\n".join(lines)


def _reconcile_add(parser: argparse.ArgumentParser) -> None:
    _run_arguments(parser, real_dollars=False)
    parser.add_argument("--year", type=int, required=True, help="the tax year to reconcile (the run ends there)")
    parser.add_argument(
        "--actuals",
        metavar="FILE",
        help="YAML/JSON actual records ({year: records}, or one year's records) instead of the spec's actuals",
    )


def _reconcile(args: argparse.Namespace) -> tuple[dict, str]:
    if args.years is not None or args.end_year is not None:
        raise api.InputError("reconcile runs through --year; --years/--end-year do not apply")
    report = api.reconcile(
        _spec_source(args), args.year, actuals=args.actuals, seed=args.seed, scenario=args.scenario, checks=args.checks
    )
    return {"report": report.to_dict()}, report.to_markdown().rstrip()


def _mcp_add(parser: argparse.ArgumentParser) -> None:
    pass


def _mcp(args: argparse.Namespace) -> tuple[dict, str]:  # pragma: no cover - exercised by test_mcp
    from .mcp import main as mcp_main

    mcp_main()
    return {}, ""


#: The subcommands, in ``--help`` order.
COMMANDS: list[Command] = [
    Command("run", "build and run a household spec", _run_add, _run),
    Command("validate", "validate a household spec and list the findings", _validate_add, _validate),
    Command("explain", "explain one simulated year (income, bills, payments, taxes)", _explain_add, _explain),
    Command(
        "reconcile",
        "compare a simulated year with the household's filed return, W-2s, 1099s and statements",
        _reconcile_add,
        _reconcile,
    ),
    Command("compare", "run a spec with and without a change and report the deltas", _compare_add, _compare),
    Command("montecarlo", "run many seeded trials and report the success rate", _montecarlo_add, _montecarlo),
    Command("schema", "print the household spec JSON Schema", _schema_add, _schema),
    Command("examples", "list, show or copy the shipped example specs", _examples_add, _examples),
    Command("mcp", "serve the tools over MCP on stdio (pip install 'life-model[mcp]')", _mcp_add, _mcp),
]


# --------------------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    """An ArgumentParser that raises instead of exiting, so usage errors follow the --json contract."""

    def error(self, message: str):
        raise CommandFailed(f"{self.prog}: {message}", EXIT_INVALID)


def get_parser() -> argparse.ArgumentParser:
    """The ``life-model`` argument parser."""
    parser = _Parser(
        prog="life-model",
        description="Run, validate, explain and compare household financial simulations.",
        epilog="Exit codes: 0 ok, 1 runtime error, 2 invalid input. See docs/cli.md.",
    )
    parser.add_argument("--version", "-v", action="version", version=f"%(prog)s {__version__}")
    common = _Parser(add_help=False)
    common.add_argument("--json", action="store_true", help="print one JSON object (machine-readable) to stdout")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", parser_class=_Parser)
    for command in COMMANDS:
        subparser = sub.add_parser(command.name, help=command.help, description=command.help, parents=[common])
        command.add_arguments(subparser)
    return parser


def _error_kind(code: int) -> str:
    return "validation" if code == EXIT_INVALID else "runtime"


def _emit(
    as_json: bool,
    command: str | None,
    payload: dict,
    text: str,
    code: int,
    message: str = "",
    *,
    stdout_text: bool = False,
    findings: list | None = None,
) -> None:
    """Print a result (``code == 0``) or a failure, as one JSON document or as text. A failure's
    text goes to stderr unless ``stdout_text`` (a handler's own output, e.g. validate's findings)."""
    if as_json:
        document = {"ok": code == EXIT_OK, "command": command, **payload}
        if code != EXIT_OK:
            document["error"] = {
                "kind": _error_kind(code),
                "message": message,
                "findings": payload.get("findings", []) if findings is None else findings,
            }
        print(json.dumps(document, indent=2, default=str))
        return
    if code == EXIT_OK:
        if text:
            print(text)
        for warning in payload.get("warnings", []):
            print(f"warning: {warning}", file=sys.stderr)
        return
    if text:
        print(text, file=sys.stdout if stdout_text else sys.stderr)
    print(f"error: {message}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Run the command line; returns the exit code (``sys.exit(main())`` in the console script)."""
    from .spec import SpecValidationError

    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    parser = get_parser()
    command = None
    try:
        args = parser.parse_args(argv)
        command = args.command
        if command is None:
            parser.print_help()
            return EXIT_OK
        handler = next(c.handler for c in COMMANDS if c.name == command)
        with api.collected_warnings() as messages:
            payload, text = handler(args)
        payload = {**payload, "warnings": messages}
        _emit(as_json, command, payload, text, EXIT_OK)
        return EXIT_OK
    except CommandFailed as failure:
        _emit(as_json, command, failure.payload, failure.text, failure.code, str(failure), stdout_text=True)
        return failure.code
    except SpecValidationError as error:
        findings = [api.finding_dict(f) for f in error.findings]
        text = "\n".join(str(f) for f in error.findings)
        message = f"{len(findings)} validation error(s)"
        _emit(as_json, command, {}, text, EXIT_INVALID, message, findings=findings)
        return EXIT_INVALID
    except (api.InputError, FileNotFoundError) as error:
        _emit(as_json, command, {}, "", EXIT_INVALID, str(error))
        return EXIT_INVALID
    except Exception as error:  # noqa: BLE001 - every other failure is a runtime error (exit 1)
        _emit(as_json, command, {}, "", EXIT_RUNTIME, f"{type(error).__name__}: {error}")
        return EXIT_RUNTIME


if __name__ == "__main__":
    sys.exit(main())
