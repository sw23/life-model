# Contributing to life-model

Thanks for your interest in improving life-model! This guide covers the local
development setup, the tox targets used by CI, and the plan-document workflow.

## Development setup

life-model uses a `src/` layout and requires **Python 3.11+**. Create a virtual
environment and install the package with its dev dependencies:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e . -r requirements.txt -r requirements-dev.txt
```

The financial config YAML is loaded relative to the repository root at import
time, so run tests from the repo root.

Install the pre-commit hooks once per clone so lint/format run automatically:

```bash
pip install pre-commit
pre-commit install
```

## Running checks

We use [tox](https://tox.wiki) as the local and CI runner. Common targets:

| Command | What it does |
| --- | --- |
| `tox` | Unit tests on the current Python (`py311`–`py314`), excludes notebooks |
| `tox -e lint` | `ruff check` + `ruff format --check` on `src`, `dashboard`, `deepqlearning` |
| `tox -e type` | `mypy` type check (lenient; non-blocking for now) |
| `tox -e notebooks` | Executes `ExampleSimulation.ipynb` end-to-end (slow) |
| `tox -e dashboard` | Solara dashboard tests |
| `tox -e deepqlearning` | Reinforcement-learning tests (installs torch) |
| `tox -e docs` | Builds the Sphinx HTML docs with warnings treated as errors |

To run the fast unit suite directly:

```bash
pytest src/life_model/tests/ -m "not notebooks" --cov
```

## Code style

- Line length is **120**. Formatting and linting are handled by
  [ruff](https://docs.astral.sh/ruff/); run `ruff format` and `ruff check --fix`
  (or just `pre-commit run --all-files`) before pushing.
- Notebook outputs are stripped by `nbstripout` on commit, except
  `ExampleSimulation.ipynb`, which intentionally commits its executed outputs as
  a reviewable baseline.

## The plan-document workflow

Substantive changes should follow the implementation plans in
[`plans/`](plans/README.md). Each plan (`01`–`13`) states the problems it
addresses with `file:line` evidence, the design decisions, an ordered task
breakdown, and acceptance criteria. Execute plans in dependency order (see
`plans/README.md`), write a failing test first for every bug fix, and don't
change an existing test's expected values unless the plan says it pins
buggy/stale behavior.

## Releasing

Versions are derived from git tags by `setuptools-scm`. Publishing is triggered
by manually dispatching the `Publish` workflows from a `vX.Y.Z` tag; the build
is validated (metadata, wheel contents, smoke install) before upload.
