---
name: dev-setup
description: Set up a working Python environment and run tests, lint and docs for this repo. Use before running any pytest/tox/ruff/sphinx command, when imports or interpreters fail, or when asked to run the test suite.
---

# Dev environment & test commands for life-model

## Setup (once per session)

The commands below write the working venv as `.venv/` (gitignored), as AGENTS.md does. If a local
note (an untracked `CLAUDE.md`) names a different working env, use that one instead. Check it before
creating one:

```bash
.venv/bin/python -c "import life_model, mesa; print(mesa.__version__)" && .venv/bin/life-model --version
```

If it is missing or broken (a venv whose interpreter was removed has dangling symlinks: recreate it,
don't patch it):

```bash
# Find a usable interpreter (need >=3.12; mesa 3.5+ requires it):
which python3.12 python3.13 python3.14 || ls /opt/homebrew/bin/python3.* /usr/local/bin/python3.* 2>/dev/null
# If none exists, ask the user to install one (e.g. `brew install python@3.12`) — do not guess.

PY=python3.12  # whichever was found
$PY -m venv .venv
.venv/bin/pip install -e . -r requirements.txt -r requirements-dev.txt
```

If only `life-model` is missing (the venv predates the console script), `.venv/bin/pip install
-e . --no-deps` adds it; `.venv/bin/python -m life_model` is equivalent.

Dashboard work additionally needs `-r dashboard/requirements-dash.txt`; RL and adviser (`slm/`) work
needs `-r deepqlearning/requirements-rl.txt` (heavy — torch; skip unless needed). The MCP server
needs the `mcp` extra (`pip install -e '.[mcp]'`), docs the `docs` extra.

Worktrees can share one venv with `PYTHONPATH=<worktree>/src` (the editable install's `.pth` is
a plain path, so `PYTHONPATH` wins).

## Running tests

Run from the repo root (docs-staleness tests read `docs/`).

```bash
.venv/bin/python -m pytest src/life_model/tests -m "not notebooks"           # core suite (~1,450 tests)
.venv/bin/python -m pytest src/life_model/tests -m notebooks                 # ExampleSimulation.ipynb, slow
.venv/bin/python -m pytest src/life_model/tests/test_bank.py -x              # single file
.venv/bin/python -m pytest src/life_model/tests/test_household_goldens.py    # hand-worked IRS returns
.venv/bin/python -m pytest dashboard/tests deepqlearning/tests slm/tests -m "not slow and not notebooks"
```

Don't run `-m slow` tests or RL training casually: they are long and memory-hungry (enough to
exhaust a laptop's memory). Check with the user first.

`deepqlearning/tests/algos/test_checkpoint.py::test_locally_trained_checkpoint_still_loads` fails
locally while the git-ignored `deepqlearning/models/financial_basic_dqn.pt` is from an older
observation version; it skips in a clean checkout.

## Generated docs

`docs/household-spec.md`, `docs/outputs.md` and `docs/constructor-cheatsheet.md` are generated and
tests fail while they are stale. After changing the spec schema, output columns/ledger/event kinds or
a core constructor:

```bash
.venv/bin/python scripts/generate_household_spec_docs.py
.venv/bin/python scripts/generate_outputs_doc.py
.venv/bin/python scripts/generate_cheatsheet.py
```

## Lint / docs

```bash
# ruff is the CI linter (pinned in tox.ini and .pre-commit-config.yaml); line length 120
.venv/bin/ruff check src/life_model dashboard deepqlearning && .venv/bin/ruff format --check src/life_model dashboard deepqlearning
.venv/bin/sphinx-build -W -b html docs <scratchpad>/life-model-docs   # needs the docs extra
```

## CI parity

CI = `.github/workflows/python-tox.yml` → tox `py312`/`py313`/`py314` plus `lint` (ruff), `type`
(mypy, non-blocking), `notebooks`, `dashboard`, `deepqlearning`, `deepqlearning-slow`, `pre-commit`
and `build-and-smoke` (builds the wheel, installs it in a clean venv, runs the `life-model` console
script); `docs.yml` builds Sphinx with `-W`. The `slm` tox env is not in CI. If tox is unavoidable,
run it with a fresh interpreter (`.venv/bin/pip install tox && .venv/bin/tox -e py312
--recreate`) — the cached `.tox/` envs are broken (see above).
