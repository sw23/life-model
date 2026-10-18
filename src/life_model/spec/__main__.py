# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Command line: ``python -m life_model.spec {schema,validate,examples}``."""

import argparse
import json
import sys

from . import EXAMPLES, example_path, json_schema, load, validate_spec
from .validate import ERROR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m life_model.spec", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("schema", help="print the HouseholdSpec JSON Schema")
    validate = sub.add_parser("validate", help="validate a spec file and print the findings")
    validate.add_argument("path", help="spec file (.yaml/.yml/.json)")
    sub.add_parser("examples", help="list the shipped example specs")
    args = parser.parse_args(argv)

    if args.command == "schema":
        print(json.dumps(json_schema(), indent=2))
        return 0
    if args.command == "examples":
        for name in EXAMPLES:
            print(f"{name}\t{example_path(name)}")
        return 0
    try:
        spec = load(args.path)
    except Exception as error:  # noqa: BLE001 - report any load/schema error as a finding
        from pydantic import ValidationError

        if isinstance(error, ValidationError):
            from .validate import _schema_findings

            for finding in _schema_findings(error):
                print(finding)
            return 1
        print(f"[error] {args.path}: {error}")
        return 1
    findings = validate_spec(spec)
    for finding in findings:
        print(finding)
    if not findings:
        print("no findings")
    return 1 if any(f.level == ERROR for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
