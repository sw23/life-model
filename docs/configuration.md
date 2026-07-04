# Configuration

life-model's financial constants (tax brackets, contribution limits, Social
Security tables, account defaults, …) live in a single validated configuration.
This page documents the schema, how configuration is resolved per model, how to
author scenarios, and the year-table projection rule.

## Where the values live

The packaged defaults are in
`src/life_model/config/data/financial_defaults.yaml`. Every value is validated
against the Pydantic models in `src/life_model/config/models.py`
(`FinancialConfigModel` and its nested models). Validation is strict:
`extra='forbid'` is set on **every** nested model, so a misspelled or unknown key
— in the defaults *or* in a scenario override — raises a `ValidationError` at load
time instead of being silently dropped.

Field defaults live only in the YAML/Pydantic models; call sites no longer carry
their own hardcoded fallbacks. Each dated section of the YAML carries a
`# vintage: <year>, source: <doc>` comment citing the primary IRS/SSA source.

## Per-model configuration

Configuration is resolved when a `LifeModel` is constructed, not at import time
(importing `life_model` performs no file I/O). Each model owns its own
`FinancialConfig`, so two models can run different scenarios in the same process:

```python
from life_model.model import LifeModel

baseline = LifeModel()                     # packaged defaults
high_tax = LifeModel(scenario="high_tax")  # a packaged scenario
custom   = LifeModel(config=my_config)     # a FinancialConfig you built
```

Domain code reads configuration through the model:
`self.model.config.tax.state.tax_rate`, `self.model.config.accounts.hsa.
contribution_limit`, and so on. The tax functions
(`federal_income_tax`, `state_income_tax`, `social_security_tax`, `medicare_tax`,
`get_income_taxes_due`) accept an optional `config` argument; agents pass
`self.model.config` so the correct per-model values are used.

### Typed access vs. the deprecated `get()`

Prefer the typed properties on `FinancialConfig`:

| Property | Returns |
| --- | --- |
| `config.tax` | federal / state / FICA parameters |
| `config.retirement` | retirement age, 401k & IRA limits, RMD table |
| `config.social_security` | Social Security tables and constants |
| `config.accounts` | bank / brokerage / HSA / 529 defaults |
| `config.insurance` | life insurance defaults |
| `config.debt` | credit card defaults |

The legacy dot-notation accessor `config.get("tax.state.tax_rate")` still works
but emits a `DeprecationWarning`; it will be removed once all consumers are
migrated.

## Authoring scenarios

Scenarios are YAML files under
`src/life_model/config/data/scenarios/<name>.yaml` that override a subset of the
defaults. A scenario only needs to include the keys it changes; the rest are
inherited. Applying a scenario deep-merges it into the current configuration and
**re-validates through Pydantic**, so a typo or an out-of-range value fails
loudly:

```yaml
# high_tax.yaml (excerpt)
tax:
  state:
    tax_rate: 10.0
```

```python
LifeModel(scenario="high_tax")
```

You can point life-model at your own scenario directory with
`life_model.config.scenarios.set_scenario_directory(path)`; scenarios found there
take precedence over the packaged ones.

## Year-indexed tax parameters

A multi-decade simulation should not apply a single frozen year's brackets to
incomes decades later. The `tax_years` table in the YAML holds published values
for 2022–2026 (standard deduction, brackets, Social Security wage base, 401k/IRA/
HSA limits, gift exclusion, RMD start age). Access them with:

```python
params = model.config.tax_year(2025)
params.standard_deduction.single   # 15750
params.ss_wage_base                # 176100
```

### Projection rule for years outside the table

`tax_year(year)` never fails for an out-of-range year; it projects:

- **Before the earliest published year** → the earliest entry's values.
- **After the latest published year** → frozen at the latest entry's values.
- **A gap within the range** → the most recent published year at or before the
  requested year.

The returned object always has `year` stamped with the *requested* year. When a
future inflation series is available (see Plan 10), the "frozen at latest" rule
can be replaced by an inflation-projected one. Always verify new published values
against IRS Revenue Procedures and SSA fact sheets before extending the table.
