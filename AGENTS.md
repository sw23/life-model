# AGENTS.md

Guidance for coding agents (and humans) working in this repository. It is the tracked, durable
version of the project notes: architecture, conventions, landmines, how to run things, and the
household-modeling workflow. Keep it current when you change any of these.

## What this is

`life-model` is a Python package (src layout, import name `life_model`) for year-step
personal-finance simulation built on [Mesa 3](https://mesa.readthedocs.io/) agent-based modeling.
Auxiliary products live beside it: a Solara dashboard (`dashboard/app.py`), a reinforcement-learning
stack (`deepqlearning/`: environment registry, from-scratch DQN/REINFORCE/PPO, training loops) and
a simulation-grounded language-model adviser (`slm/`).

## Using the model (start here for household questions)

Describe a household as a **household spec** (YAML/JSON) and drive it with the `life-model`
command line or the matching Python functions. Do not read `src/` to model a household.

```bash
life-model examples --copy married_homeowners my-models/h.yaml   # start from a synthetic example
life-model validate my-models/h.yaml                             # errors and warnings, nothing runs
life-model run my-models/h.yaml --out my-models/out              # summary + out/result.json
life-model explain my-models/h.yaml --year 2035                  # one year in prose
life-model compare my-models/h.yaml --set 'people[john].retirement_age=58'
life-model montecarlo my-models/h.yaml --scenario stochastic --n 500
```

```python
import life_model

result = life_model.run("my-models/h.yaml", seed=1)   # RunResult
print(life_model.explain(result, 2035))
```

Every command takes `--json` (one JSON object on stdout) and exits 0 (ok), 2 (invalid input: the
spec, an unknown example/scenario, a year outside the run) or 1 (runtime error). Docs:

- [docs/modeling-a-household.md](docs/modeling-a-household.md): statements -> spec -> validate ->
  run -> explain -> compare, the agent checklist and the privacy rules.
- [docs/household-spec.md](docs/household-spec.md): every spec field (generated).
- [docs/units-and-conventions.md](docs/units-and-conventions.md): percent vs fraction, annual vs
  monthly, nominal vs real, APR, what `None` and `"economy"` mean.
- [docs/constructor-cheatsheet.md](docs/constructor-cheatsheet.md): silent defaults and every core
  constructor (generated).
- [docs/outputs.md](docs/outputs.md): every output column, ledger kind and event kind (generated).
- [docs/cli.md](docs/cli.md): the command line, the Python one-call functions and the MCP server.
- [docs/configuration.md](docs/configuration.md): financial constants, scenarios, the economy.

**Privacy.** Real household files live in `my-models/` (git-ignored). Never put a real person's
name, employer or balance in a tracked file, a test, a fixture, a commit message or a PR; refer to
household files by path. The CLI refuses to write outputs inside `src/`. Example specs and test
fixtures use only synthetic names (a test enforces an allowlist).

## Architecture

- **Model.** `LifeModel` (`src/life_model/model.py`) subclasses `mesa.Model`; every domain object
  (Person, Family, Job, accounts, homes, insurance, ...) is a `LifeModelAgent`.
- **Stages.** Each simulated year (`model.step()`) runs four stages over all agents:
  `pre_step` (ages advance, mortality, wages and benefits arrive, RMDs) -> `events` (scheduled
  `LifeEvents` fire, after income and before settlement) -> `step` (account growth, then tax-unit
  settlement) -> `post_step` (year-end resets and escalators). Within a stage, agents run by
  `STEP_PRIORITY` (ascending; e.g. the economy at -100 in `pre_step`), then construction order.
- **Settlement.** `Family.step` groups members into `TaxUnit`s (`people/tax_unit.py`): single filers
  and married couples (joint or separate). Each unit computes its return and pays bills plus taxes
  through one **household waterfall** (`Family(withdrawal_order=)`, default bank -> brokerage ->
  Roth basis -> pre-tax (sized for its own tax and penalty) -> Roth earnings) across every member;
  an unpaid gap becomes debt (`shortfall_debt` events). Settlement is order-independent:
  `tests/test_construction_order.py` builds households in shuffled construction orders and requires
  identical frames.
- **Construction.** The recommended path is the household spec (`life_model.spec`, Plan 25):
  `build_model(load(path))` validates, canonicalizes list order and constructs agents in a fixed
  order (`spec/builder.py` docstring). Direct constructors remain the low-level API; keep their
  changes keyword-only with defaults, since the dashboard and RL code call them directly.
- **Outputs.** `model.run()` returns a `RunResult` (`results.py`, Plan 28): model and agent frames,
  `tax_returns` (`TaxReturn` per unit and year), the cash-flow `ledger` (every money movement),
  typed `events`, balance sheets, `real_dollars()`, `explain(year)`, `conservation()`, and
  `to_json/to_csv/to_parquet/load`. `MonteCarlo` (`montecarlo.py`) runs seeded trials.
- **Registries and stats.** Ownership links live in per-type registries (`registry.py`) keyed by
  person `unique_id`, exposed as `Person` properties. Stats are `stat_*` attributes each agent class
  declares in `STATS_OWNED`; model reporters sum only over owners (a suite-wide fixture rejects
  undeclared writes).
- **Config.** Financial constants live in `src/life_model/config/data/financial_defaults.yaml`
  (loaded with `importlib.resources`, so it works from an installed wheel and any working
  directory), validated by Pydantic models in `config/models.py`. Each `LifeModel` owns a
  `FinancialConfig` (`model.config`); simulated years read brackets, deductions, wage base and
  contribution limits from `model.year_config` (the `tax_years` table, inflation-projected past the
  last published year). Module helpers take an optional `config=` that falls back to
  `default_financial_config()`. `config_manager.config` is a deprecated shim library code must not
  import (a test enforces it). Scenarios are YAML overlays in `config/data/scenarios/`
  (`list_scenarios()`; `stochastic` turns on random economy draws).
- **Agent interface.** `life_model/api.py` (one-call functions; `life_model.run/compare/validate/
  explain`), `life_model/cli.py` (the `life-model` console script and `python -m life_model`),
  `life_model/mcp.py` (optional stdio MCP server, extra `life-model[mcp]`). Keep these thin: no
  simulation logic outside the engine, spec and results modules.

## Development

```bash
python3.12 -m venv .venv                     # Python 3.12+ (CI runs 3.12, 3.13, 3.14)
.venv/bin/pip install -e . -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest src/life_model/tests -m "not notebooks"            # core suite
.venv/bin/python -m pytest src/life_model/tests -m notebooks                  # example notebook
.venv/bin/python -m pytest dashboard/tests deepqlearning/tests slm/tests -m "not slow and not notebooks"
.venv/bin/ruff check src/life_model dashboard deepqlearning && .venv/bin/ruff format --check src/life_model dashboard deepqlearning
.venv/bin/sphinx-build -W -b html docs /tmp/life-model-docs
```

Dashboard tests need `-r dashboard/requirements-dash.txt`; RL and adviser tests need
`-r deepqlearning/requirements-rl.txt` (torch). Tests live inside the package at
`src/life_model/tests/`; run pytest from the repo root (docs-staleness tests read `docs/`). CI
(`.github/workflows/python-tox.yml`) runs tox `py312`-`py314`, `lint` (ruff, pinned in `tox.ini`
and `.pre-commit-config.yaml`), `type` (mypy, non-blocking), `notebooks`, `dashboard`,
`deepqlearning`, a slow RL smoke job, and **build-and-smoke**, which builds the wheel, installs it in
a clean venv and runs the `life-model` console script end to end; `docs.yml` builds Sphinx with
warnings as errors. The `slm` tox env is not in CI: run `slm/tests` yourself when touching `slm/`. Don't run `-m slow` tests or RL
training casually: they are long and memory-hungry.

Generated docs (regenerate after changing their sources; tests fail while they are stale):
`python scripts/generate_household_spec_docs.py`, `python scripts/generate_outputs_doc.py`,
`python scripts/generate_cheatsheet.py` (or `make -C docs generated`).

## Conventions

- Line length 120; ruff (default rules + isort). Match the surrounding test style (mostly
  `unittest.TestCase`).
- **Tests first.** Write the failing test, watch it fail, then fix. Don't change an existing test's
  expected values to make it pass: several tests deliberately pin known behavior, and everything
  else is a regression. Dollar assertions use the frozen fixture config
  (`src/life_model/tests/fixtures/test_config.yaml`), not the live defaults.
- **Money-flow changes need more than a green suite**: run a probe simulation (a spec plus
  `life-model run`/`explain` works well), check `RunResult.conservation()` (net-worth change equals
  the ledger's net flow each year), sign and magnitude sanity, and year alignment; compare before
  and after in a scratch worktree, and explain every changed number. Re-baseline notebooks or golden
  frames deliberately, saying why the numbers moved (see `docs/rebaseline-plan-*.md`).
- **Financial constants** (brackets, limits, wage bases, premiums) must come from primary sources
  (IRS, SSA, CMS, state revenue departments) and carry `# vintage: <year>, source: <doc>` comments.
  Append year-keyed tables, never overwrite history; keep the static mirror of the latest
  `tax_years` entry consistent with the table.
- Core constructor changes stay keyword-only with defaults (dashboard, RL and adviser code construct
  core objects directly).
- New spec fields: add them to `spec/schema.py` with units and descriptions, map them in the builder
  and extractor, and regenerate `docs/household-spec.md`.
- New CLI subcommands: one handler plus one `Command(...)` line in `cli.py` (`COMMANDS`), and a
  section in `docs/cli.md` (a test checks every subcommand and flag is documented).

## Known landmines

- Results depend on `STEP_PRIORITY` then construction order within a stage. Settlement is
  order-independent, but a married unit files in its head's state (the first spouse constructed;
  the spec builder makes it the first spouse in `relationships.marriages`).
- Silent defaults: `Person` is immortal and files single unless told otherwise; `Spending` and
  `Salary` growth default to 0%; rent rises 5%; investments grow at 7%; cash earns 0%; an unknown
  state code silently falls back to a flat 6%. The spec validator warns or errors on these; direct
  construction does not. See [docs/constructor-cheatsheet.md](docs/constructor-cheatsheet.md).
- Historical simulation results had correctness bugs (married-couple housing, FICA on retirement
  income, the RMD age table, and more; see the re-baseline logs). Investigate surprising numbers
  rather than papering over them.
- The PyPI release can lag `main`; test against `pip install -e .`, or build the wheel the way CI's
  build-and-smoke job does.
- `ProcessPoolExecutor` Monte Carlo needs a picklable top-level factory; it silently falls back to
  sequential runs otherwise.
