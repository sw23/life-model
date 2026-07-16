# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Provenance helpers: simulator commit and config hash (Plan 20 D2).

Advice provenance must be auditable and staleness must be detectable: the datasheet stamps the
simulator commit and a hash of the financial-config data the scoring ran against, so a dataset
generated before Plans 14/15 land (which change what the simulator prices) is identifiable after
the fact (Risks note).
"""

import hashlib
import os
import subprocess
from importlib.resources import files


def simulator_commit() -> str:
    """Current git commit of the simulator, or ``"unknown"`` outside a repo.

    Falls back to the ``SLM_SIMULATOR_COMMIT`` env var (so a packaged/CI run can stamp it
    explicitly) before giving up.
    """
    env = os.environ.get("SLM_SIMULATOR_COMMIT")
    if env:
        return env
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=here, stderr=subprocess.DEVNULL)
        return out.decode().strip()
    except Exception:
        return "unknown"


def config_hash() -> str:
    """Short SHA-256 of the packaged financial-defaults YAML the scoring runs against."""
    data_file = files("life_model.config") / "data" / "financial_defaults.yaml"
    digest = hashlib.sha256(data_file.read_bytes()).hexdigest()
    return digest[:16]
