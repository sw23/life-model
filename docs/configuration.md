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

Field defaults live only in the YAML/Pydantic models; call sites do not carry
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

The dot-notation accessor `config.get("tax.state.tax_rate")` still works
but emits a `DeprecationWarning`; prefer the typed properties above.

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

## State tax packs

State income tax is configured per state under `tax.state.packs`. Each pack
describes one state's tax; a person opts in with the keyword-only
`Person(..., state="CA")` argument. People without a `state` use
`tax.state.default_state` (packaged default: `DEFAULT`, the legacy flat rate). A
married couple files in the head-of-unit's state; part-year and multi-state
filing are not modeled.

```yaml
tax:
  state:
    tax_rate: 6.0        # flat rate; becomes the DEFAULT pack
    default_state: DEFAULT
    packs:
      PA:                              # key: two-letter USPS code (or DEFAULT)
        flat_rate: 3.07                # EITHER flat_rate ...
        retirement_income_taxable: false   # exempt pre-tax 401k/IRA distributions & RMDs
        ss_taxable: false                  # exempt the taxable portion of Social Security
      CA:
        brackets:                      # ... OR progressive [lower, upper, rate] rows
          single:                      # per filing status; missing statuses fall back
            - [0, 10756, 1.0]          #   to `single`
            - [10757, 25499, 2.0]
            # ... last row's upper bound is .inf
        standard_deduction:            # state standard deduction (default 0)
          single: 5706
          married_filing_jointly: 11412
```

Rules enforced at load time (Pydantic `ValidationError`, not a tax-time surprise):
exactly one of `flat_rate`/`brackets` per pack (`flat_rate: 0` models a
no-income-tax state), bracket rows must be contiguous (`lower == previous upper +
1`, first row starts at 0), `brackets` must define at least `single`, pack keys
must be valid state codes, and `default_state` must have a pack.

The state taxable-income base starts from the unit's ordinary income and
subtracts categories the pack exempts (pre-tax retirement distributions when
`retirement_income_taxable: false`; the Social Security taxable portion unless
`ss_taxable: true`) plus the state standard deduction. State income tax paid
joins property tax in the federal SALT itemized deduction, subject to
`tax.federal.salt_deduction_cap`. The `DEFAULT` pack applies a single flat
`tax_rate` to the federal AGI base.

The packaged packs (CA, NY, TX, FL, WA, PA, IL, MA) are 2025-vintage and stamped
with their state DOR sources in the YAML; refresh them annually alongside the
federal data (see the `refresh-financial-data` checklist). Local/city income
taxes, state EITCs/credits, and state-specific exclusions (e.g. NY's $20k
retirement exclusion) are not modeled.

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

The returned object always has `year` stamped with the *requested* year. To index
future parameters by realized inflation instead of freezing them, pass an
`inflation_factor` (cumulative price growth from the last published year), or use
`model.tax_params_for_year(year)`, which computes that factor from the economy's
realized inflation and applies IRS-style rounding automatically:

```python
model.tax_params_for_year(2050).standard_deduction.single  # inflation-projected, not frozen
```

Always verify new published values against IRS Revenue Procedures and SSA fact
sheets before extending the table.

## Economy (inflation & returns)

A single `EconomyModel` per simulation supplies the year's economic rates —
inflation, wage growth, and the returns on cash, bonds, equities, and homes — to
every account, salary, spending, and housing object. This replaces the old
per-object rate constants with one coherent economic assumption. Configure it in
the `economy` section of the YAML (or via a scenario):

```yaml
economy:
  mode: fixed          # fixed | path | stochastic
  inflation: 3.0
  wage_growth: 3.0
  equity_return: 7.0   # brokerage / IRA / 529 default return
  bond_return: 3.0
  cash_yield: 0.0      # bank account default interest
  home_appreciation: 4.0
```

- **`fixed`** — every year returns these constants. The defaults reproduce the
  pre-economy per-object constants exactly, so existing simulations are unchanged.
- **`path`** — an explicit per-year series overrides individual years; unlisted
  years fall back to the fixed constants. Use it to model, e.g., a multi-year
  recession:

  ```yaml
  economy:
    mode: path
    paths:
      equity_return: {2027: -12.0, 2028: -4.0, 2029: 3.0}
  ```

- **`stochastic`** — equity, bond, and inflation are drawn as correlated normals
  (the rest independently) from the model's seeded RNG, so runs are reproducible
  under a fixed `seed`. Distribution parameters live under `economy.stochastic`.

Each account/salary/spending/housing object still accepts an explicit rate that
overrides the economy (constructor argument wins); pass `None` to defer to the
economy.

Query rates directly with `model.economy.equity_return(year)`,
`model.economy.inflation(year)`, etc. Report balances in start-year dollars with
`model.get_yearly_stat_df(..., real_dollars=True)`, which deflates every money
column by the economy's cumulative inflation.

## Monte Carlo studies

Run many trials that differ only in their random draws and aggregate the results
with the `MonteCarlo` runner. The factory must be a picklable top-level callable
so trials can run in worker processes (it falls back to sequential execution
otherwise):

```python
from life_model import MonteCarlo, LifeModel

def build(seed):
    model = LifeModel(seed=seed, scenario="stochastic")  # a stochastic-economy scenario
    # ... construct the family, jobs, and accounts ...
    return model

result = MonteCarlo(build, n=1000, seed=42).run()
result.success_rate(lambda row: row["Bank Balance"] > 0)   # probability of not running out
result.percentiles("Bank Balance", [10, 50, 90])           # fan-chart frames
result.fan_chart("Bank Balance")                           # matplotlib fan chart
```

Per-trial seeds are derived deterministically from the master `seed`, so a study
is reproducible.
