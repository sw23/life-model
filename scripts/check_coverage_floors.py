#!/usr/bin/env python3
# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Enforce per-package coverage floors from a coverage.py JSON report.

coverage.py's ``fail_under`` is a single global threshold. The money-critical packages (taxes, the
payment/tax services, and the people/tax-unit settlement code) carry stricter floors, configured in
``[tool.life_model.coverage_floors]`` in pyproject.toml as ``package = percent``. Coverage is the
same combined line + branch figure coverage.py reports.

Usage: python scripts/check_coverage_floors.py coverage.json
"""

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def package_coverage(report: dict) -> dict[str, float]:
    """Combined line+branch coverage percent per top-level ``life_model`` subpackage."""
    totals: dict[str, list[int]] = {}
    for path, data in report["files"].items():
        relative = path.replace("\\", "/").split("life_model/")[-1]
        package = relative.split("/")[0] if "/" in relative else ""
        summary = data["summary"]
        bucket = totals.setdefault(package, [0, 0])
        bucket[0] += summary["covered_lines"] + summary.get("covered_branches", 0)
        bucket[1] += summary["num_statements"] + summary.get("num_branches", 0)
    return {package: 100.0 * covered / total for package, (covered, total) in totals.items() if total}


def main(report_path: str) -> int:
    floors = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["life_model"]["coverage_floors"]
    coverage = package_coverage(json.loads(Path(report_path).read_text()))
    failures = []
    for package, floor in sorted(floors.items()):
        actual = coverage.get(package)
        status = "missing" if actual is None else f"{actual:.1f}%"
        print(f"{package:12s} {status:>8s} (floor {floor}%)")
        if actual is None or actual < floor:
            failures.append(package)
    if failures:
        print(f"Coverage below the floor for: {', '.join(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
