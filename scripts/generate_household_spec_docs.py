# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Regenerate docs/household-spec.md from the HouseholdSpec schema.

Run from the repository root after changing life_model/spec/schema.py:

    python scripts/generate_household_spec_docs.py

``--check`` exits non-zero when the committed file is stale (the test suite runs the same check).
"""

import argparse
import sys
from pathlib import Path

from life_model.spec.docs import render_markdown

DOC_PATH = Path(__file__).resolve().parent.parent / "docs" / "household-spec.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed file is stale")
    args = parser.parse_args(argv)
    text = render_markdown()
    if args.check:
        current = DOC_PATH.read_text(encoding="utf-8") if DOC_PATH.exists() else ""
        if current != text:
            print(f"{DOC_PATH} is stale; run python scripts/generate_household_spec_docs.py", file=sys.stderr)
            return 1
        return 0
    DOC_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {DOC_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
