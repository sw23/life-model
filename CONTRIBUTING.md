# Contributing to life-model

Thanks for your interest in improving life-model! This guide covers the local
development setup and the tox targets used by CI.

## Development setup

life-model uses a `src/` layout and requires **Python 3.12+**. Create a virtual
environment and install the package with its dev dependencies:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e . -r requirements.txt -r requirements-dev.txt
```

The financial config ships inside the package and is loaded with
`importlib.resources`, so the package works from any directory; run pytest from
the repo root anyway, since the generated-docs tests read `docs/`.

[AGENTS.md](AGENTS.md) summarizes the architecture, conventions and known
landmines; read it before a substantial change.

Install the pre-commit hooks once per clone so lint/format run automatically:

```bash
pip install pre-commit
pre-commit install
```

## Running checks

We use [tox](https://tox.wiki) as the local and CI runner. Common targets:

| Command | What it does |
| --- | --- |
| `tox` | Unit tests on the current Python (`py312`–`py314`), excludes notebooks |
| `tox -e lint` | `ruff check` + `ruff format --check` on `src`, `dashboard`, `deepqlearning` |
| `tox -e type` | `mypy` type check (lenient; non-blocking for now) |
| `tox -e notebooks` | Executes `ExampleSimulation.ipynb` end-to-end (slow) |
| `tox -e dashboard` | Solara dashboard tests |
| `tox -e deepqlearning` | Reinforcement-learning tests (installs torch) |
| `tox -e docs` | Builds the Sphinx HTML docs with warnings treated as errors |
| `tox -e slm` | Language-model adviser tests (stub model; no weights) |

CI also builds the wheel, installs it into a clean virtual environment and runs
the `life-model` console script end to end (`build-and-smoke`).

Some docs are generated from the code; regenerate them after changing their
sources (`make -C docs generated`, or the three `scripts/generate_*.py`
scripts); tests fail while they are stale.

To run the fast unit suite directly:

```bash
pytest src/life_model/tests/ -m "not notebooks" --cov
```

## Code style

- Line length is **120**. Formatting and linting are handled by
  [ruff](https://docs.astral.sh/ruff/); run `ruff format` and `ruff check --fix`
  (or just `pre-commit run --all-files`) before pushing.
- Notebook outputs are stripped by `nbstripout` on commit, so committed
  notebooks (including `ExampleSimulation.ipynb`) carry no cell outputs.

## Making changes

Write a failing test first for every bug fix, and don't change an existing
test's expected values to make a test pass unless that test was deliberately
pinning buggy or stale behavior. Money-flow changes should be validated with a
probe simulation and conservation checks, not just a green suite.

## Releasing

Versions are derived from git tags by `setuptools-scm`. Publishing is triggered
by manually dispatching the `Publish` workflows from a `vX.Y.Z` tag; the build
is validated (metadata, wheel contents, smoke install) before upload.
