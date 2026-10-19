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

baseline = LifeModel()  # packaged defaults
high_tax = LifeModel(scenario="high_tax")  # a packaged scenario
custom = LifeModel(config=my_config)  # a FinancialConfig you built
```

Domain code reads configuration through the model:
`self.model.config.tax.state.tax_rate`, `self.model.config.accounts.hsa.
contribution_limit`, and so on. Module-level helpers (the tax functions such as
`federal_income_tax` and `get_income_taxes_due`, the `limits` helpers, the Social
Security table lookups, and the annuity pricing functions) accept an optional
`config` argument; agents pass `self.model.config` so the correct per-model values
are used. Called without `config`, a helper falls back to the packaged defaults
(`life_model.config.financial_config.default_financial_config()`).

### The deprecated global `config`

`life_model.config.config_manager.config` is deprecated and emits a
`DeprecationWarning` on use. It does not affect `LifeModel` instances, which own
their config; mutating it only changes the fallback used by helpers called without
`config`. Pass `LifeModel(config=..., scenario=...)` instead. It will be removed in
a future release.

### Typed access

Read values through the typed properties on `FinancialConfig`:

| Property | Returns |
| --- | --- |
| `config.tax` | federal / state / FICA parameters |
| `config.retirement` | retirement age, 401k & IRA limits, RMD table |
| `config.social_security` | Social Security tables and constants |
| `config.accounts` | bank / brokerage / HSA / 529 defaults |
| `config.insurance` | life insurance defaults |
| `config.debt` | credit card defaults |
| `config.equity_comp` | stock compensation vesting defaults |

There is no dot-notation accessor (`config.get("tax.state.tax_rate")`); use the
typed properties above.

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

The packaged scenarios are `aggressive`, `boom`, `conservative`, `deflation`,
`high_inflation`, `high_tax`, `low_tax`, `recession`, `stochastic` and
`tax_reform`; `life_model.config.scenarios.list_scenarios()` (or
`life-model examples`) lists them, user scenarios included.

You can point life-model at your own scenario directory with
`life_model.config.scenarios.set_scenario_directory(path)`; scenarios found there
take precedence over the packaged ones.

## State tax packs

State income tax is configured per state under `tax.state.packs`. Each pack
describes one state's tax; a person opts in with the keyword-only
`Person(..., state="CA")` argument (or a residency timeline,
`Person(..., residency=[("2026-07", "TX")])`). People without a `state` use
`tax.state.default_state` (packaged default: `DEFAULT`, the flat rate on the
federal-style base). `DEFAULT` is a deliberate choice: a state code without a
pack raises `UnknownStateError` when the person is built (and is a spec
validation error); nothing falls back silently. A married couple
files in the head-of-unit's state; a year in which the head moved files
part-year returns (below).

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
      NJ:
        years:                         # one full pack per tax year
          2025:
            brackets:                  # ... OR progressive [lower, upper, rate] rows
              single: [[0, 20000, 1.4], [20001, 35000, 1.75], ...]   # last upper .inf
              married_filing_jointly: [...]
              head_of_household: [...] # missing statuses fall back (below)
            standard_deduction: {single: 0, married_filing_jointly: 0}
            personal_exemption: 1000   # per filer (both spouses on a joint return)
            dependent_exemption: 1500  # per dependent
            additional_exemption_65: 1000
            retirement_exclusion:      # per person, or per_return; tiers by age / birth year
              - {amount_by_status: {single: 75000, married_filing_jointly: 100000}, min_age: 62,
                 per_return: true, income_limit: 150000}
          2026: ...
```

Rules enforced at load time (Pydantic `ValidationError`, not a tax-time surprise):
exactly one of `flat_rate`/`brackets` per pack (`flat_rate: 0` models a
no-income-tax state), bracket rows must be contiguous (`lower == previous upper +
1`, first row starts at 0), `brackets` must define at least `single`, pack keys
must be valid state codes, `default_state` must have a pack, and a pack with
`years` sets everything per year.

**Years.** A pack with `years` uses, for a simulated year, the latest entry at
or before it (the earliest entry before the table, the latest after it: state
amounts are not inflation-projected). The year's config view resolves it.

**Filing statuses.** `head_of_household` and `married_filing_separately` fall
back to `single` (brackets and standard deduction); a qualifying surviving
spouse uses `married_filing_jointly`.

**The base.** The state taxable-income base starts from the unit's income and
subtracts what the pack exempts (pre-tax retirement distributions when
`retirement_income_taxable: false`; the Social Security taxable portion unless
`ss_taxable: true`; gains with `capital_gains_taxable: false`; a partial
`retirement_exclusion` of distributions and pensions, or an age deduction against
any income with `applies_to: any` and `phaseout_start`), then the standard
deduction and exemptions (`personal_exemption`, `dependent_exemption`,
`additional_exemption_65`, `exemption_by_agi` bands, a per-child
`child_deduction` by AGI band). The tax is the flat rate or brackets
(`bracket_base_tax` for a schedule with jumps, Ohio's) less nonrefundable
credits (`personal_credit`, `senior_credit`, `dependent_credit`,
`other_dependent_credit`, phased out by `credit_phaseout`). State income tax
paid joins property tax in the federal SALT itemized deduction, subject to the
year's SALT cap (see below). The `DEFAULT` pack applies a single flat `tax_rate`
to the federal AGI base.

**Part-year residents.** Income entries carry the month they were booked in;
each month's income belongs to the head's state that month (wages by the
months worked there, investment income by residence at receipt). Each state
taxes its share by the income-ratio method of California's Form 540NR and New
York's IT-203: the tax as a full-year resident on the year's income, times the
state's share of the base (deductions, exemptions and credits prorated the same
way). `TaxReturn.state_return.parts` lists each state's share; states with
other part-year methods are approximated by this one.

**Packs.** CA, NY (2025 and 2026, with head-of-household schedules; California's
exemption credits) and eleven more (OH, GA, NC, MI, NJ, VA, AZ,
TN, IN, MO, MD: 2025 and 2026, from each state's revenue department; the ten
next-largest states by Census Bureau Vintage 2025 estimates, plus Maryland,
11th) are year-keyed; TX, FL, WA, PA, IL and MA are single 2025-vintage packs.
Every pack is stamped with its sources in the YAML; refresh them annually
alongside the federal data (see the `refresh-financial-data` checklist). Not
modeled: local, city and county income taxes (NYC, Ohio and Michigan cities,
Indiana and Maryland counties), state EITCs, New York's tax benefit recapture
and pension exclusion, Ohio's $20 exemption, joint filing and retirement credits,
Missouri's federal income tax deduction and per-spouse computation (its joint
rows double the thresholds), Arizona's dependent credit phase-out and public
pension subtraction, New Jersey's pension exclusion between $100,000 and $150,000
of income (the full cap applies to $150,000), Maryland's 2% capital gain surtax.
Georgia's retirement exclusion is applied to retirement income only (the state
also lets it cover investment income and $5,000 of wages). Pack items marked
`TODO(verify)` in the YAML are 2026 amounts the states had not published by
October 2026.

**State withholding** (with `payroll.withholding`): the pack's tax on each
paycheck's taxable wages annualized, a twelfth a month; bonuses and RSU vests at
the flat rate or the marginal rate at the annualized wages. An approximation of
each state's own withholding formula.

## Withholding, estimated tax and the premium tax credit

`tax_years.<year>.withholding` holds IRS Pub. 15-T's Worksheet 1A amounts and
annual percentage method tables (2024-2026; projected years derive the tables
from the year's brackets and standard deduction, which reproduces the published
2024 and 2026 tables; the 2025 tables were published before OBBBA's 2025
standard deduction) and Pub. 15's supplemental rates (22%, 37% over $1,000,000).
`tax.federal.estimated_tax` holds Form 2210's rules (90% / 100% / 110% over
$150,000 of prior-year AGI, the $1,000 threshold) and the IRS underpayment rates
by quarter (later quarters reuse the latest). `tax_years.<year>.premium_tax_credit`
holds Form 8962's applicable percentage bands, the poverty guideline the year's
return uses, the 400% cap (none 2021-2025) and the repayment limits (none from
2026); `qualifying_relative_income_limit` the §152(d)(1)(B) amount.

## Year-indexed tax parameters

A multi-decade simulation should not apply a single frozen year's brackets to
incomes decades later. The `tax_years` table in the YAML holds published values
for 2022–2026 (standard deduction, brackets, Social Security wage base, 401k/IRA/
HSA limits including the §415(c) annual-additions limit `limit_415c`, gift
exclusion, RMD start age), the long-term capital-gains brackets
(`capital_gains`, with married-filing-separately set explicitly), the Child Tax Credit
(`ctc_per_child`, `ctc_refundable_max`), the SALT cap (`salt: {cap,
phaseout_threshold}`), the OBBBA senior deduction (`senior_deduction_amount`), the
NIIT thresholds (`niit`) and the §63(f) additional standard deduction
(`additional_standard_deduction`). Each
was verified against the year's Rev. Proc. or the statute and carries its source
stamp in the YAML. Access them with:

```python
params = model.config.tax_year(2025)
params.standard_deduction.single  # 15750
params.ss_wage_base  # 176100
```

### Credits, deductions and regimes

The 2024-2026 entries also carry (each stamped with its Rev. Proc., IRS notice or OBBBA section):

| Key | What | Source |
|---|---|---|
| `eitc` | earned income credit: earned income amount, maximum credit, phase-out thresholds (joint and other) for 0-3+ children, the investment income limit | Rev. Proc. §32 table |
| `dependent_care` | §129 exclusion ($5,000; $7,500 from 2026) and the §21 rate schedule (35%-20%; OBBBA's 50%-35%-20% from 2026) | IRC §21, §129; OBBBA §§70404-70405 |
| `savers_credit` | §25B AGI ceilings of the 50/20/10% tiers | IRS notices (Notice 2025-67 for 2026) |
| `ira_phaseouts` | traditional IRA deduction (covered single / joint / spouse covered) and Roth contribution ranges | IRS notices |
| `student_loan_phaseout` | §221 MAGI range (single, joint) | Rev. Proc. |
| `amt` | exemption, phase-out start and rate (25%; 50% from 2026), 26/28% breakpoint | Rev. Proc.; OBBBA §70107 |
| `qbi` | §199A thresholds, phase-in widths (75k/150k and the $400 minimum from 2026) | Rev. Proc.; OBBBA §70105 |
| `kiddie_tax` | §1(g) base amount (Form 8814) | Rev. Proc. |
| `qcd_limit` | §408(d)(8) qualified charitable distribution limit | IRS notices |
| `ltc_premium_limits` | §213(d)(10) long-term care premium limits by age | Rev. Proc. |
| `compensation_limit` | §401(a)(17) (caps the pay a SEP / solo 401(k) contribution is figured on) | IRS notices |

`FinancialConfig.year_view` copies them onto `tax.federal` for the year. They have no static mirror
(read them through `model.year_config`), and a config without them, such as the frozen test fixture,
leaves the feature off. Statutory, unindexed rules sit outside the year table: the charitable limits
and OBBBA's 2026 changes (`tax.federal.charitable`: the 30% limit on appreciated property, the
non-itemizer deduction, the 0.5% floor, the §68 2/37 limit), the education credits
(`tax.federal.credits.education`), the saver's credit sunset after 2026 (`credits.savers_credit_last_year`,
SECURE 2.0 §103), the credit for other dependents and the additional child tax credit formula
(`dependents.odc_per_dependent`, `actc_earned_income_threshold`), and self-employment tax
(`tax.self_employment`). Past 2026 each indexed amount is scaled by inflation and rounded the way its
statute rounds the yearly adjustment (EITC amounts to $10, IRA ranges down to $1,000, the student-loan
range down to $5,000, AMT amounts to $100, the QCD limit down to $1,000, the compensation limit down
to $5,000; see `life_model/config/financial_config.py`).

**Refreshing them** (add these rows to the annual refresh): the Rev. Proc. sections on the earned
income credit (§32), AMT exemptions (§55), the kiddie tax (§1(g)), qualified business income
(§199A), long-term care premiums (§213(d)(10)) and education loan interest (§221); the IRS
retirement-limits notice for the IRA and Roth phase-outs, saver's credit ceilings, the QCD limit and
§401(a)(17). The §25A phase-outs, §21/§129 amounts and the 2026 charitable rules are statutory.

### Payroll and contribution limits

| Key | What | Source |
|---|---|---|
| `limit_401k_catch_up_60_63` | §414(v)(2)(E) catch-up at ages 60-63 ($11,250 in 2025 and 2026; the regular catch-up otherwise) | IRS Notices 2024-80, 2025-67 |
| `limit_health_fsa` | §125(i) health FSA salary-reduction limit ($3,200 / $3,300 / $3,400 for 2024-2026) | Rev. Procs. 2023-34 §3.16, 2024-40, 2025-32 |
| `limit_commuter_monthly` | §132(f) monthly transit / parking exclusion ($315 / $325 / $340) | Rev. Procs. 2023-34 §3.17, 2024-40, 2025-32 |

`limit_ira_catch_up` (§219(b)(5)(B), $1,000; $1,100 from 2026) is added to the IRA limit from age 50.
Statutory rules sit in the code: the §423(b)(8) $25,000 ESPP limit and the §423(b)(6) 15%
maximum discount (`work/stock.py`), and the I bond rules from TreasuryDirect (12-month lock, the
three-month interest forfeiture before five years, 30-year maturity, the composite rate formula;
`account/fixed_income.py`). Past 2026 the IRA catch-up is rounded down to $100 (§219(b)(5)(C)), the
health FSA down to $50 (§125(i)(2)) and the commuter limit down to $5 (§132(f)(6)); the 60-63 catch-up
is rounded to $500 (`TODO(verify)`: its post-2025 rounding rule). The keys
`accounts.brokerage.default_growth_rate`, `accounts.bank.default_interest_rate`,
`retirement.ira.default_growth_rate` and `accounts.plan_529.default_growth_rate` are deprecated and
ignored (growth follows the economy or the account's own rate); they are not in the packaged defaults,
and an overlay that still sets them is accepted for one release.

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

### Parameters deliberately outside the projection path

Some thresholds are written into the statute and have never been inflation-indexed.
Indexing them would silently erase the real fiscal drag they create, so the projection
leaves them fixed even where the year table carries them:

- `niit` — the §1411 surtax rate and its $200k/$250k ($125k separate) MAGI thresholds.
- `senior_deduction_amount` — $6,000 per person 65+, 2025–2028 only (the sunset years are
  `tax.federal.senior_deduction.first_year`/`last_year`).
- `tax.federal.capital_loss_ordinary_offset` — the $3,000 annual capital-loss
  deduction against ordinary income, unchanged since 1978.

The SALT cap follows its own statute past the table (`tax.federal.salt_cap_statute`):
OBBBA §70120 raises the cap and the phase-down threshold 1% a year through 2029, and from
2030 the cap is $10,000 with no phase-down. The cap is per return (a joint return caps the
spouses' combined state and local taxes once), reduced by 30% of MAGI over the threshold
but not below $10,000; a separate return gets half of each. The Child Tax Credit amounts
are indexed (rounded down to $100, §24(i)); its $200k/$400k phase-out is not.

## Capital gains and dividends

`tax.federal.capital_gains` holds the preferential rate schedule for long-term
capital gains and qualified dividends, in the same `[lower, upper, rate]` shape as
the ordinary brackets. The gain is stacked *above* ordinary income: ordinary income
fills the 0% and 15% bands first, and the gain is taxed only in the band space that
remains.

`accounts.brokerage.dividend_yield` splits a brokerage account's return into untaxed
price appreciation and a taxable qualified dividend that is reinvested at full basis.
The yield is carved *out of* the total return rather than added on top, so total
return is unchanged — only the tax character of that slice moves. It is `0` in the
packaged defaults, which keeps accounts pure-appreciation. A spec brokerage account's
`dividend_yield_pct` overrides it per account, and an account that leaves
`dividend_yield_pct` unset uses this configured value (so 0% unless a config or
scenario changes it).

States tax capital gains as ordinary income by default; set `capital_gains_taxable:
false` on a state pack for the exceptions.

## Retirement and health accounts

Contribution limits are enforced per person per year and reset at year end:

- `retirement.job_401k_contrib_limit` — the 402(g) elective-deferral limit (`base`, plus
  `catch_up_amount` from `catch_up_age`, or the larger `super_catch_up_amount` at ages 60-63), shared
  across all of a person's jobs, and the 415(c) `annual_additions_limit` that caps employee plus
  employer money (including after-tax contributions) per plan.
- `retirement.ira.contribution_limit` — one limit shared by a person's Roth and Traditional
  IRAs, plus the year's `limit_ira_catch_up` from age 50.
- `accounts.hsa` — `contribution_limit` (self-only) or `contribution_limit_family`, plus
  `catch_up_amount` from `catch_up_age`. Employer contributions count against the same limit.

Tax treatment follows the account type. Traditional IRA and personal HSA contributions are
deductible; pre-tax 401k, Traditional IRA and RMD distributions are ordinary income. Two
statutory additional taxes are settled as federal tax with the year's return:

- `retirement.early_withdrawal_penalty_rate` (10%) on pre-tax distributions and non-qualified
  Roth IRA earnings taken before `retirement.federal_retirement_age` (59.5). Exceptions such as
  age-55 separation and substantially equal payments are not modeled.
- `accounts.hsa.non_medical_penalty_rate` (20%) on non-medical HSA distributions before
  `accounts.hsa.non_medical_penalty_age` (65).

When a year's bills exceed the bank balance, settlement redeems non-reserve fixed income, sells
brokerage holdings, then draws pre-tax 401ks and Traditional IRAs, sizing the draw to cover the tax and
penalty it triggers; emergency reserves come last. A traditional IRA distribution (or Roth conversion) is
tax-free in proportion to the owner's Form 8606 basis (`nondeductible_basis`) over the value of all their
traditional IRAs (the pro-rata rule); after-tax 401(k) money and Roth 401(k) money before 59.5 are taxed
on their earnings share.

## Stock compensation

`equity_comp.default_schedule` names the vesting preset a `StockPlan` uses when it is
given no explicit schedule (`four_year`, `three_year`, `front_loaded`, `back_loaded`,
or `even`, which spans `equity_comp.default_vesting_years`). These are modeling
conventions rather than published figures, so they carry no `vintage` stamp.

## Housing, insurance and Social Security statement rules

| Config path | What it sets | Source |
|---|---|---|
| `tax.federal.mortgage_interest_debt_limit`, `mortgage_interest_grandfathered_debt_limit`, `mortgage_interest_grandfather_date` | $750,000 acquisition-debt limit; $1,000,000 for debt incurred on or before 2017-12 (months are compared) | IRC §163(h)(3) |
| `housing.pmi_ltv_threshold`, `housing.pmi_termination_ltv` | PMI cancellation at 80% of the original value (by balance), automatic termination at 78% of the original schedule (and at the term's midpoint) | 12 U.S.C. 4901-4902 |
| `social_security.full_retirement_age_by_birth_year` | `[first birth year, years, months]` rows, used with `SocialSecurity(fra_from_birth_year=True)` | SSA OACT NRA table |
| `social_security.spousal_benefit_percent` | half of the worker's PIA (reduced 25/36 of 1% a month for 36 months, 5/12 beyond) | 42 U.S.C. 402(b), 402(q) |
| `social_security.earnings_test` | exempt amounts by year, the projection bases and the $1-for-$2 / $1-for-$3 ratios | SSA OACT rtea.html, rtdet.html |
| `insurance.pension.simplified_method_single`, `simplified_method_joint` | anticipated payments for recovering an employee's after-tax pension basis | IRS Pub. 575 Tables 1-2 |
| `insurance.pension.lump_sum_interest_rate` | rate for a lump sum's present value and the actuarial survivor reduction when a plan states neither (assumption) | — |

## Economy (inflation & returns)

A single `EconomyModel` per simulation supplies the year's economic rates —
inflation, wage growth, and the returns on cash, bonds, equities, and homes — to
every account, salary, spending, and housing object, so one coherent economic
assumption drives every rate. Configure it in
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

- **`fixed`** — every year returns these constants.
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
  The packaged `stochastic` scenario (`LifeModel(scenario="stochastic")`,
  `meta.scenario: stochastic` in a household spec, or `--scenario stochastic` on
  the command line) switches the mode on with these default parameters.

Each account/salary/spending/housing object still accepts an explicit rate that
overrides the economy (constructor argument wins); pass `None` to defer to the
economy.

Query rates directly with `model.economy.equity_return(year)`,
`model.economy.inflation(year)`, etc. Report balances in start-year dollars with
`model.get_yearly_stat_df(..., real_dollars=True)`, which deflates every money
column by the economy's cumulative inflation, or with `model.run().real_dollars()`,
which deflates everything a run produced (model and agent frames, ledger, events
and tax returns). See [the outputs glossary](outputs.md) for every output.

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
result.success_rate(lambda row: row["Bank Balance"] > 0)  # probability of not running out
result.percentiles("Bank Balance", [10, 50, 90])  # fan-chart frames
result.fan_chart("Bank Balance")  # matplotlib fan chart
```

For a household spec, the command line does this in one step:
`life-model montecarlo SPEC --scenario stochastic --n 1000 --seed 42` (or
`life_model.api.run_montecarlo(spec, n=1000, scenario="stochastic", seed=42)`);
see [the command line reference](cli.md).

Per-trial seeds are derived deterministically from the master `seed`, so a study
is reproducible; `result.seeds[i]` rebuilds trial `i`. Pass `keep_agent_frames=True`
and/or `keep_events=True` to keep each trial's agent frame and events, convert with
`result.real_dollars()`, and save with `result.to_parquet(directory)` (needs the
`parquet` extra) / `MonteCarloResult.load(directory)`.
