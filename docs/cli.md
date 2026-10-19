# Command line, Python functions and MCP server

Three thin layers over the same functions drive the simulator from a
[household spec](household-spec.md): the `life-model` command line, the `life_model.run` /
`validate` / `explain` / `compare` Python functions, and an optional MCP server for Claude Code,
Claude Desktop and other MCP clients. None of them contains simulation logic; they load the spec,
build it with `life_model.spec.build_model`, run it and read the
[`RunResult`](outputs.md).

## Command line

`pip install life-model` installs the `life-model` console script; `python -m life_model` is the
same program. `life-model --version` prints the version; `life-model COMMAND --help` lists a
command's flags.

```bash
life-model examples --copy married_homeowners h.yaml
life-model validate h.yaml
life-model run h.yaml --out out --format json
life-model explain h.yaml --year 2035
life-model reconcile h.yaml --year 2025 --actuals my-models/2025-actuals.yaml
life-model compare h.yaml --set 'people[john].retirement_age=58'
life-model montecarlo h.yaml --scenario stochastic --n 1000 --seed 7 --out mc
```

### Common flags

Every command that runs a household takes the spec as a positional `SPEC` path (`.yaml`, `.yml`
or `.json`) or `--example NAME` (a shipped synthetic example), plus:

| Flag | Meaning |
|---|---|
| `--seed N` | Random seed; overrides `meta.seed`. An unseeded run draws a seed and reports it. |
| `--years N` | Number of simulated calendar years: `end_year = start_year + N - 1` (a spec whose `meta.start` is mid-year counts its part first year as one). |
| `--end-year Y` | Last simulated year (inclusive); overrides `meta.end_year`. Exclusive with `--years`. |
| `--scenario NAME` | A named scenario (`life-model examples` lists them), replacing `meta.scenario`. `stochastic` draws random returns and inflation each year. |
| `--checks strict\|warn\|off` | `warn` (default): validator errors fail; validator warnings, invariant violations (the checker in `life_model.invariants`, run at each year end: yearly and monthly conservation, no negative month-end balances, contribution limits, RMDs, FICA, ...; see [reconciliation.md](reconciliation.md)) and a failed money-conservation check are reported. `strict`: those fail too, with exit code 2 for validator warnings and 1 for an invariant or conservation failure, with or without `--real-dollars` (on `montecarlo` every trial runs the invariant checker). Warnings whose code is in `meta.accepted_warnings` are kept on purpose and do not fail. `off`: skip the validator (fields the engine does not support are still rejected) and every check. |
| `--real-dollars` | Report money in start-year dollars (`RunResult.real_dollars()`; on `montecarlo` each trial by its own inflation). The conservation check always runs on nominal money, so it gives the same answer either way. |
| `--json` | Print exactly one JSON object to stdout (every command, see below). |

### `run`

`life-model run SPEC [--out DIR] [--format json|csv|parquet] [--collect year|month]`

Builds and runs the household and prints the key columns per year (Year, Income, Taxes, Spending,
Housing, Bank Balance, Debt, Net Worth) and a summary: the span (`2026-05 to 2030-12` when
`meta.start` is mid-year; `start` in the JSON summary), final net worth, run totals, the net-worth
peak and the lowest year-end cash (each in nominal and start-year dollars, and the lowest cash after
the last worker reaches `retirement_age`: `net_worth_peak`, `lowest_cash`, `lowest_cash_retired`),
the years with unpaid bills (`shortfall years ...: none` when there are none) and the conservation
line (`conservation check: passed in every year`, or the years that failed, a model bug to report). `--collect month` also
collects a row per month end (`RunResult.monthly_frame`: `Year`, `Month` and the model columns, flows
for the year to date; `months` in the JSON summary), written as `monthly_frame` in `result.json` or
`monthly.csv` / `monthly.parquet`. `--out DIR` writes
the whole result: `--format json` (default) writes `DIR/result.json` (one document: seed,
deflators, the spec, every tax return, the model and agent frames, the ledger, the events and the
balance sheets); `csv` writes `model.csv`, `agents.csv`, `ledger.csv`, `events.csv`,
`balance_sheets.csv`, `tax_returns.csv` and `meta.json`; `parquet` writes the same tables as
Parquet (needs `pip install 'life-model[parquet]'`; `RunResult.load(DIR)` reads it back). See
[outputs.md](outputs.md) for every column. `--out` refuses a directory inside `src/` or inside the
installed package: outputs describe a household and belong in a git-ignored place such as
`my-models/`.

### `validate`

`life-model validate SPEC [--scenario NAME]`

Prints every finding as `[level] path: message Fix: ...` (or `no findings`) and exits 2 when any
finding is an error. Warnings the spec keeps on purpose (`meta.accepted_warnings: [code, ...]`) are
left out and noted on a last line (`accepted` in the JSON payload); errors cannot be accepted. The
assumption warnings (a costly default left in place: `default_child_costs`, `no_health_coverage`,
`cash_not_invested`, `ss_estimate_assumes_work`, `child_birth_month_assumed`) come from these
functions and the command line; the lower-level `life_model.spec.validate_spec` returns them only
with `include_assumptions=True`. Schema errors (unknown keys, wrong types), validator errors (an unknown state,
an event before the start year, a field the engine cannot simulate yet) and warnings (0% spending
growth, a rate that looks like a fraction) all come back with a stable `code`.

### `explain`

`life-model explain SPEC --year Y`

Runs the household and prints the markdown account of year `Y`: income by source, growth, bills by
category, how they were paid (every forced sale and pre-tax withdrawal and its cause, and the 529
and HSA withdrawals that paid college and medical costs), savings moves (each with its target
account), each tax return line by line, the change in net worth, and the year's events
(`RunResult.explain`). A year outside the run exits 2.

### `reconcile`

`life-model reconcile SPEC --year Y [--actuals FILE]`

Runs the household through year `Y` and compares the year with the household's real documents:
the filed Form 1040 and schedule lines (by that year's line numbers), W-2 and 1099 boxes, paystub
amounts, the state return and year-end statement balances. The records come from the spec's
`actuals` block or from `--actuals FILE` (YAML/JSON: `{2025: records}`, or one year's records).
Every line shows simulated vs actual, the difference, a status (`green` within rounding, `yellow`,
`red`, `not_modeled` for lines the engine has no equivalent for, such as withholding) and the
likely cause of a difference (`missing_income_source`, `input_difference`, `unmodeled_credit`,
`unmodeled_deduction`, `unit_mismatch`, `timing`, `missing_input`, `propagated`). Describe the
household as of January 1 of `Y` (`meta.start_year: Y`) for the cleanest comparison (a `meta.start`
inside `Y` reconciles a part year: only the simulated months, as the report notes); a year before
`meta.start_year` exits 2, and `--years`/`--end-year` do not apply. `--json` returns the report as
`report` (`counts`, `lines`, `notes`). See [reconciliation.md](reconciliation.md).

### `compare`

`life-model compare SPEC (--change FILE | --set PATH=VALUE)... [--montecarlo N] [--workers N]`

Runs the household as written and with a change, on the same seed, and prints the deltas
(changed minus base): final-year net worth, total taxes over the run, each final-year balance, the
number of shortfall years (always printed, `0 -> 0 (+0)` included), each run's net-worth peak and
lowest cash with their years (nominal and start-year dollars), and with `--montecarlo N` both success
rates over `N` paired trials and their difference (use `--scenario stochastic` so trials differ; `--workers N` sets the Monte Carlo
worker processes).

A change is a **JSON merge patch** ([RFC 7386](https://www.rfc-editor.org/rfc/rfc7386)) on the spec,
written in YAML or JSON, with two extensions for lists:

```yaml
# change.yaml
people:
  jane:                      # an object patched onto a list patches the item with id "jane"
    retirement_age: 62
    spending: {growth_pct: economy}
events+:                     # "key+" appends to the list "key"
  - id: kitchen
    at: {year: 2030}
    person: jane
    action: one_time_expense
    amount: 40000
```

`null` deletes a key (or, in the by-id form, the list item); anything else replaces. `--change`
may be repeated (patches merge in order). `--set PATH=VALUE` assigns one value after the patches:
the path is dotted keys with list selectors (`people[0].age`, `people[jane].age` or
`people.jane.age` for the item with that id, `events[+]` to append), and the value is read as YAML
(`62`, `economy`, `null`, `'{action: retire, ...}'`). Examples:
`--set 'people[jane].accounts[0].balance=25000'`, `--set meta.end_year=2060`,
`--set 'events[+]={id: early, at: {year: 2030}, person: john, action: retire}'`.

### `montecarlo`

`life-model montecarlo SPEC [--n 1000] [--seed N] [--workers N] [--real-dollars] [--out DIR] [--format auto|parquet|csv]`

Runs `--n` trials (default 1000; `--workers N` worker processes, automatic by default, `1` runs
them in this process) that differ only in their seeds (per-trial seeds derive from `--seed`, so a study is
reproducible) and prints the success rate (the share of trials in which the household never carried
unpaid bills as new debt) and the 10th/50th/90th percentile of final-year net worth. Trials only
differ when the household has random draws: a stochastic economy (`--scenario stochastic` or
`economy.mode: stochastic`), stochastic mortality or long-term-care need; otherwise the output says
every trial was identical. `--out DIR` writes every trial's yearly frame and events (`model.parquet`
/ `events.parquet` with `Trial` and `Seed` columns, or `.csv`) plus `meta.json` and `summary.json`.

### `schema`

`life-model schema` prints the household spec's JSON Schema: the input schema of every function
and tool on this page.

### `examples`

`life-model examples` lists the shipped synthetic example specs (marking any that use a field the
engine cannot simulate yet) and the scenario names. `--show NAME` prints one; `--copy NAME DEST`
copies it to `DEST` (a file, or a directory to copy `NAME.yaml` into; `--force` overwrites).

### `mcp`

`life-model mcp` serves the tools below over MCP on stdio (needs `pip install 'life-model[mcp]'`).

### JSON output and exit codes

With `--json`, stdout is exactly one JSON object. Success:

```json
{"ok": true, "command": "run", "summary": {"...": "..."}, "files": [], "warnings": []}
```

Failure:

```json
{"ok": false, "command": "run",
 "error": {"kind": "validation", "message": "1 validation error(s)",
           "findings": [{"level": "error", "path": "people[0].state", "message": "...",
                         "fix": "...", "code": "unknown_state"}]}}
```

| Exit code | Meaning | `error.kind` |
|---|---|---|
| 0 | Success | (none) |
| 2 | Invalid input: the spec fails the schema or the validator, an unknown example or scenario, a year outside the run, a bad change path, a refused output path, bad flags | `validation` |
| 1 | Any other error while running | `runtime` |

Payloads: `run` has `summary` (`household`, `seed`, `dollars`, `years`, `final_year`,
`final_net_worth`, `final_balances`, `totals`, `shortfall_years`, `conservation_failures`,
`net_worth_peak`, `lowest_cash`, `lowest_cash_retired`, `yearly`) and `files`; `validate` has
`valid`, `error_count`, `warning_count`, `findings` and `accepted`;
`explain` has `year` and `markdown`; `compare` has `seed`, `changes`, `base` and `changed`
summaries (each with its `yearly` rows), `deltas` and `montecarlo`; `montecarlo` has `summary` (`trials`, `dollars`, `years`,
`success_rate`, `success_definition`, `final_net_worth` percentiles, `trials_differ`) and `files`;
`schema` has `schema`; `examples` has `examples` and `scenarios`. Every success also lists the
validator and engine `warnings` raised while running.

## Python functions

The same operations as one-call functions (`life_model/api.py`), for scripts and for LLM tool
definitions (whose input schema is `life_model.spec.json_schema()`):

```python
import life_model
from life_model import api

result = life_model.run("my-models/h.yaml", seed=1, years=30)    # RunResult
findings = life_model.validate("my-models/h.yaml")               # list[Finding]
print(life_model.explain(result, 2035))                          # markdown
comparison = life_model.compare("my-models/h.yaml", {"people": {"jane": {"retirement_age": 62}}})
print(comparison.to_dict()["deltas"])
mc = api.run_montecarlo("my-models/h.yaml", n=500, scenario="stochastic", seed=7)
print(api.montecarlo_summary(mc)["success_rate"])
report = life_model.reconcile("my-models/h.yaml", 2025)           # ReconciliationReport
print(report.to_markdown())
```

A spec argument may be a `HouseholdSpec`, a dict, YAML/JSON text or a path. `run`, `explain`,
`compare` and `api.run_montecarlo` take `seed`, `years` or `end_year`, `scenario` and `checks` like
the command line (`run`, `compare` and `api.run_montecarlo` also `real_dollars`). Errors: `SpecValidationError`
(`.findings`) for an invalid spec, `api.InputError` for other bad input; both are `ValueError`s.
`api.summarize(result)`, `api.apply_change(spec, patch, sets=[...])`, `api.merge_patch` and
`api.set_path` are the building blocks the command line uses.

## MCP server

`life_model/mcp.py` exposes the functions as MCP tools over stdio, using the official MCP Python
SDK (the optional `mcp` extra):

```bash
pip install 'life-model[mcp]'
claude mcp add life-model -- life-model mcp       # Claude Code; or python -m life_model.mcp
```

| Tool | Does |
|---|---|
| `run_household` | Run a spec; returns the `run` summary and warnings. |
| `validate_household` | The validator's findings and `valid`. |
| `compare_change` | Base vs changed run (`change` merge patch and/or `sets`), deltas, optional `montecarlo`. |
| `explain_year` | The markdown account of one year. |
| `reconcile_household` | A simulated year against the actual records (`actuals` / `actuals_path`, or the spec's). |
| `get_schema` | The household spec JSON Schema. |
| `list_examples` | The example specs (`include_spec` for their YAML) and the scenarios. |

Each tool takes the household as exactly one of `spec` (an object or YAML/JSON text), `spec_path`
(a file the server can read) or `example`, and returns an object with `ok`, mirroring `--json`
(a failure carries `error.kind`, `error.message` and `findings`).
