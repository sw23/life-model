---
name: implement-change
description: Guidance for implementing a substantial change to the simulation using tests-first and re-baselining conventions. Use when making a non-trivial change to the engine, accounts, taxes, or other money-flow code that needs new/adjusted tests and deliberate output re-baselining.
---

# Implementing a substantial change

Use these conventions when a change is large enough to touch multiple modules, alter simulation
outputs, or require new tests. The goal is to keep the repo working at every step and to change
expected values only on purpose.

## Workflow

1. **Work in dependency order.** Sequence the work so partial execution leaves the repo in a
   working state. Handle upstream modules before the code that depends on them, and run the full
   test suite between logical task groups.
2. **Tests first.** For every bug fix or behavior change, write the failing test first, run it,
   watch it fail, then implement the fix. Never adjust an existing test's expected values to make
   it pass unless that test is explicitly there to pin buggy/stale behavior.
3. **Dollar assertions use the frozen fixture config.** Money assertions must load
   `src/life_model/tests/fixtures/test_config.yaml`, never the live defaults, so results don't
   drift when real-world constants are refreshed. Tax changes must also keep the household goldens
   (`src/life_model/tests/goldens/households/`, hand-worked IRS returns) green.
4. **Re-baseline deliberately.** Bug fixes change simulation outputs. When `ExampleSimulation.ipynb`,
   golden frames or a household golden shift, re-execute and inspect the delta — confirm it matches the fix's
   expected direction (e.g. "married couples now pay housing" lowers their bank balance) before
   committing new baselines. Use the `verify-simulation` skill for money-flow changes.
5. **Tax/financial constants must be verified** against primary sources (IRS Rev. Proc.,
   ssa.gov) before hardcoding. Cite the source in a YAML comment (`# vintage: 2026, source: ...`).
   See the `refresh-financial-data` skill.

## Repo specifics

- Environment setup and test commands: see the `dev-setup` skill.
- Tests live in `src/life_model/tests/` (inside the package). Match existing test style.
- Line length 120 (ruff). The time step is one **month**: `model.step()` runs `pre_step` → `events` →
  `step` → `post_step`, with `on_year_start` before January and `on_year_end` (tax settlement,
  escalators, resets) after December. Within a stage agents run by `STEP_PRIORITY`, then construction
  order. Keep `step_year()` and a year-interval RL env step bit-identical (a twin-env test checks it).
- The dashboard (`dashboard/app.py`), RL env (`deepqlearning/envs/financial/environment.py`), the
  adviser (`slm/`) and the spec builder (`spec/builder.py`) construct core objects directly — keep
  constructor signatures backward-compatible (new params keyword-only, canonical `owner=` / `*_pct` /
  `*_annual` / `*_monthly` names; renames go through `deprecated_names.py`, never a silent break).
- A new household input needs a spec field too: add it to `spec/schema.py` with units and a
  description, map it in the builder and extractor, and regenerate the generated docs (see
  `dev-setup`). A new CLI subcommand is one handler plus one `Command(...)` in `cli.py` and a
  section in `docs/cli.md`.
- Keep `AGENTS.md` current when a change alters its architecture, conventions or landmines.
