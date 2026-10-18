# life-model (beta)
Python package for performing time step-based simulations of personal finances. Note that this package is still early in development and likely contains bugs. Use at your own risk!

## Overview
The package provides comprehensive models of people, jobs, accounts, insurance, debt, and more within a time step-based simulation framework. Built on the [Mesa](https://github.com/projectmesa/mesa) agent-based modeling framework, it includes an interactive dashboard, an example Jupyter Notebook, deep reinforcement learning capabilities for AI-driven financial planning, and can be used programmatically for in-depth financial studies.

## Key Features
- **Comprehensive Financial Modeling**: Model families, individuals, jobs, various account types, insurance policies, debt, taxes, and more
- **Interactive Dashboard**: Web-based interface using Solara for real-time financial simulations and visualizations
- **Deep Learning Integration**: Train reinforcement-learning agents (DQN, REINFORCE, PPO) to optimize financial decisions, and build a simulation-grounded language-model adviser whose advice is scored by the simulator
- **Flexible Configuration**: YAML-based configuration system for different economic scenarios

## Motivation
While impossible to predict the future, the goal of this package is to provide a robust framework for modeling financial outcomes based on various inputs. The best way to use this model is to change one variable at a time and evaluate how it impacts the outcome.

## Getting Started

### Quick Start
Check out the example simulation notebook:
- [Google Colab (interactive)](https://colab.research.google.com/github/sw23/life-model/blob/main/ExampleSimulation.ipynb)
- [GitHub](https://github.com/sw23/life-model/blob/main/ExampleSimulation.ipynb)

![Training Statistics](https://raw.githubusercontent.com/sw23/life-model/main/img/stats.png)

### Installation
```bash
python -m pip install life-model
```

### Command line
`life-model` runs a household spec from the shell (`python -m life_model` is the same program):
```bash
life-model examples --copy married_homeowners my-models/h.yaml   # a synthetic example to edit
life-model validate my-models/h.yaml                             # findings, exit code 2 on errors
life-model run my-models/h.yaml --out my-models/out              # yearly summary + out/result.json
life-model explain my-models/h.yaml --year 2035                  # one year: income, bills, taxes
life-model compare my-models/h.yaml --set 'people[john].retirement_age=58'
life-model montecarlo my-models/h.yaml --scenario stochastic --n 1000
```
Every command takes `--json` for machine-readable output. The same operations are Python one-liners
(`life_model.run`, `validate`, `explain`, `compare`), and `pip install 'life-model[mcp]'` adds an MCP
server (`life-model mcp`) for Claude Code and other MCP clients. See [docs/cli.md](docs/cli.md) and,
for the end-to-end workflow, [docs/modeling-a-household.md](docs/modeling-a-household.md). Coding
agents: start with [AGENTS.md](AGENTS.md).

### Describing a household
A household can be written as a YAML or JSON **household spec** (people, jobs, accounts, debts,
home, insurance, Social Security records and dated events) instead of Python:

```python
from life_model.spec import build_model, load, validate_spec

spec = load("my-models/household.yaml")   # my-models/ is git-ignored: keep real data there
for finding in validate_spec(spec):       # errors and warnings before anything runs
    print(finding)
model = build_model(spec)
model.run()
```

The engine steps one calendar month at a time (`model.step()`; `model.step_year()` runs to the next
year end); salaries, bills, growth and benefits flow monthly and taxes settle in December. See
[docs/units-and-conventions.md](docs/units-and-conventions.md).

Synthetic examples ship in `life_model/spec/examples/` (`life_model.spec.load_example("married_homeowners")`),
every field is documented in [docs/household-spec.md](docs/household-spec.md), and
`python -m life_model.spec schema` prints the JSON Schema.

### Interactive Dashboard
For a web-based interface to run simulations:
```bash
pip install -e . -r dashboard/requirements-dash.txt
solara run dashboard/app.py
```
Then open your browser to http://localhost:8765

![Dashboard Overview](https://raw.githubusercontent.com/sw23/life-model/main/img/dashboard.png)

### Reinforcement Learning
Train AI agents to make optimal financial decisions with DQN, REINFORCE, or PPO:
```bash
pip install -r deepqlearning/requirements-rl.txt
python -m deepqlearning.train --env financial:basic --algo dqn --episodes 1000
python -m deepqlearning.train --env financial:mid_career --algo ppo --total-env-steps 200000
```
See [deepqlearning/README.md](deepqlearning/README.md) for the environment registry, the algorithm
interface, and the evaluation protocol.

### Language-Model Adviser
[`slm/`](slm/README.md) turns the simulator into a data generator and verifier for a small language
model that gives household financial-decision advice: every candidate decision is scored by Monte
Carlo simulation, so rationales are certified by the simulator rather than asserted, and out-of-scope
questions are refused. It is educational decision support, not financial advice; see the
[slm README](slm/README.md) for the pipeline, evaluation, and training configurations.

## Modeling Status
This package supports a comprehensive range of financial modeling components:

### Core Components
- [x] **Family & Person Models** - Multi-person households with individual financial profiles
- [x] **Children** - Dependents with education and care costs
- [x] **Jobs** - Employment with salary progression and benefits
- [x] **Stock Compensation** - RSU grants with multi-year vesting schedules

### Accounts & Investments
- [x] **Bank Accounts** - Checking/savings with interest
- [x] **401k Plans** - Traditional and Roth with employer matching, one elective limit across jobs, 415(c) cap
- [x] **Traditional & Roth IRAs** - Deductible Traditional IRAs with RMDs; Roth IRAs drawn basis-first; one shared limit
- [x] **HSA** - Deductible, invested, family tier and catch-up; non-medical withdrawals taxed
- [x] **529 Plans** - Education savings accounts
- [x] **Brokerage Accounts** - Taxable investment accounts
- [x] **Pensions** - Defined benefit retirement plans with vesting, accrual formula, COLA and survivor elections
- [x] **Trust Accounts** - Revocable and irrevocable trusts for estate planning

### Insurance & Protection
- [x] **Life Insurance** - Term and whole life policies with loans
- [x] **General Insurance** - Health, auto, home, umbrella insurance
- [x] **Long Term Care Insurance** - Coverage for nursing home, assisted living, and in-home care
- [x] **Annuities** - Fixed and variable annuities with various payout options
- [x] **Social Security** - Comprehensive benefit calculations with timing strategies

### Debt Management
- [x] **Student Loans** - Education debt with various repayment options
- [x] **Car Loans** - Auto financing
- [x] **Credit Cards** - Revolving debt with interest calculations
- [x] **Mortgages** - Home loans (integrated with housing model)

### Tax System
- [x] **Federal Taxes** - Complete income tax calculations with brackets
- [x] **State Taxes** - Per-state tax packs (progressive brackets or flat rate, retirement/Social Security exemptions, SALT integration) with per-person residency
- [x] **FICA Taxes** - Social Security and Medicare taxes
- [x] **Capital Gains** - Short-term and long-term capital gains
- [x] **Required Minimum Distributions (RMDs)** - From 401ks and Traditional IRAs
- [x] **Early-Withdrawal Penalties** - 10% before 59½ on pre-tax and non-qualified Roth IRA draws; 20% on non-medical HSA draws before 65
- [x] **Deductions** - Standard deduction with the §63(f) amount for 65+, OBBBA senior deduction, itemized (SALT cap schedule, mortgage interest, medical with long-term care premiums, charity at 60% cash / 30% appreciated property with carryovers; 2026 floor, non-itemizer deduction and §68 limit), QBI (§199A), student loan interest and IRA deduction phase-outs
- [x] **Credits** - Child tax credit and credit for other dependents (Schedule 8812 with the additional child tax credit), earned income credit, child and dependent care credit with dependent-care FSAs, American opportunity / lifetime learning credits (529 coordination), saver's credit, prior-year minimum tax credit; each on its own Form 1040 / Schedule 3 line
- [x] **Alternative Minimum Tax** - Form 6251 with capital-gain rates, incentive stock option exercises, and the minimum tax credit carryforward
- [x] **Self-Employment** - Schedule C profit, self-employment tax sharing the wage base with W-2 wages, SEP and solo 401(k) contributions, QBI deduction
- [x] **Kiddie Tax** - A child's interest and dividends on the parents' return (Form 8814)
- [x] **Charitable Distributions** - Qualified charitable distributions from IRAs counting toward the RMD; gifts of appreciated shares at fair market value
- [ ] **Withholding & Estimated Payments** - Taxes settle as a year-end lump (Plan 31 task 6); no ACA premium tax credit yet

### Housing & Lifestyle
- [x] **Home Ownership** - Purchase, mortgage, appreciation, and selling
- [x] **Rental Housing** - Apartment leasing with rent increases
- [x] **Life Events** - Marriage, retirement, career changes, and mortality (stochastic or fixed-age death)

### Healthcare & Aging
- [x] **Medicare Coverage** - Part B and Part D premiums with IRMAA income surcharges (two-year MAGI lookback); Part A is premium-free
- [x] **Long-Term Care Services** - Seeded care-need hazard with care episodes and annual costs, offset by LTC insurance
- [x] **Medical Expense Modeling** - Age-related healthcare cost increases with medical inflation above CPI
- [x] **Chronic Care Management** - Ongoing medical conditions and treatment costs (modeled via the age-band cost curve)
- [x] **Prescription Drug Coverage** - Medicare Part D premium and IRMAA surcharge (modeled via Part D; supplemental plans not itemized)

### Giving & Legacy
- [x] **Charitable Giving** - Tax-deductible donations with itemized deduction support
- [x] **Donor Advised Funds** - Charitable investment accounts with growth, fees, and distributions
- [x] **Estate Planning** - Mortality-driven death, spousal/beneficiary estate transfer, per-account beneficiary designations, estate tax, revocable/irrevocable trusts, and the SECURE Act 10-year inherited-account rule (trust income is untaxed until distributed — no compressed trust brackets; annuity two-life survivor factor still backlog)
- [x] **End of Life Care** - Long-term care facilities and a final-year medical expense spike charged to the estate
- [x] **Funeral and Final Expenses** - Funeral cost charged against the estate before transfer and estate tax

### Advanced Features
- [x] **Economic Scenarios** - Configurable market conditions (recession, inflation, etc.)
- [x] **Payment Services** - Intelligent bill payment with account prioritization
- [x] **Tax Optimization** - Strategic withdrawal and contribution planning
- [x] **Reinforcement Learning** - DQN / REINFORCE / PPO agents (`deepqlearning/`) that learn an in-episode financial policy, evaluated against planner heuristics with an outcome-based protocol
- [x] **Simulation-Grounded Adviser** - A language-model adviser (`slm/`) that maps a household to a recommended retirement plan (savings rate, 401k routing, Social Security claiming age, drawdown) with a Monte-Carlo-certified rationale (educational decision support, not financial advice; see `slm/README.md`)

## Examples and Documentation

### Dashboard
The interactive dashboard simulates a two-person household (John and Jane) and charts income, bank
and 401k balances, debt, spending, 401k contributions and match, and income vs. taxes, with a
results table and CSV download. Its controls cover:
- Each person: include/exclude, age, retirement age, salary, bonus, spending, starting bank balance,
  401k (balance, contribution, employer match) and number of children
- Household: start and end year, state of residence, annual salary and spending increase, bank
  interest rate, an optional home (price, mortgage rate and term) and optional healthcare costs
- Economy: a packaged economic scenario (there is no separate inflation control; pick
  `high_inflation`, `deflation`, `stochastic`, ... to change inflation and returns)

### Reinforcement Learning
The deep learning module includes:
- A registry of financial environments (`financial`, plus `basic`, `high_earner`, `low_earner`, `mid_career` households) with domain randomization and a stochastic economy
- 16 financial action types (contributions, withdrawals, spending, early retirement), flattened into 52 discrete actions with amount buckets
- Utility-based reward presets for different objectives
- DQN, REINFORCE and PPO, planner-grade heuristic baselines, a statistical evaluation protocol, and policy-analysis reports
- The simulation-grounded language-model adviser in [`slm/`](slm/README.md), which uses the same environment as its data generator

### Configuration System
YAML scenario files packaged with life-model (in `src/life_model/config/data/scenarios/`) overlay the
default financial configuration; use one with `LifeModel(scenario="recession")`, `meta.scenario` in a
household spec, or `life-model run SPEC --scenario recession`:
- `conservative` - lower equity returns (5%)
- `aggressive` - higher equity returns (10%)
- `boom` - a multi-year run of elevated equity returns and cash yields (path economy)
- `recession` - a multi-year equity downturn, then recovery (path economy)
- `high_inflation` - 8% inflation, wages lagging, lower real returns
- `deflation` - falling prices with depressed returns
- `stochastic` - random, correlated equity/bond/inflation draws each year (for Monte Carlo)
- `high_tax`, `low_tax`, `tax_reform` - alternative federal brackets, deductions, state and payroll rates

See [docs/configuration.md](docs/configuration.md) for authoring your own.

## Contributing
This project is open source and welcomes contributions. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, the tox targets used by CI, and the `pre-commit install` step. The test suite in `src/life_model/tests/` shows examples of expected functionality.

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## How to Cite
If you use this package in your research, please cite it as follows:
```bibtex
@software{life_model,
  author = {Spencer Williams},
  title = {life-model: Personal Finance Simulation Framework},
  url = {https://github.com/sw23/life-model},
  version = {0.0.0},
  year = 2025
}
```
