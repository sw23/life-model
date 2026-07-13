# Deep Reinforcement Learning for Financial Planning

Train an AI agent to make financial decisions over a person's lifetime. The agent learns to manage bank accounts, retirement funds, debt, and lifestyle choices to maximize long-term financial well-being.

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r ../requirements.txt -r requirements-rl.txt
```

### 2. Train Your First Agent
```bash
# Basic training scenario (recommended for beginners)
python train_financial_agent.py --scenario basic --episodes 1000

# High earner scenario
python train_financial_agent.py --scenario high_earner --episodes 1500
```

### 3. Interactive Tutorial
For a step-by-step walkthrough, open the Jupyter notebook:
```bash
jupyter notebook Training_Example.ipynb
```

## 🎯 Training Scenarios

Choose from pre-configured financial scenarios (defined in `scenarios.py`; the same definitions
anchor the domain randomizer, so fixed and randomized variants can never drift apart):

- **`basic`** - Standard middle-class income profile (great for learning)
- **`high_earner`** - High income with complex investment decisions
- **`low_earner`** - Limited income requiring careful budgeting
- **`mid_career`** - Starting training from age 35

### Domain randomization

`env.reset(seed=..., options={"randomize": True, "scenario": "basic"})` draws the episode's
household — start age, retirement age, salary, spending, bank balance, gender — from seeded
distributions around the scenario's point values (`EpisodeSampler` in `scenarios.py`). The same
seed always reproduces the same household and trajectory; without options the legacy fixed
household is reproduced exactly. A scenario can also carry named economy scenarios (e.g.
`recession`) to sample per episode as a curriculum knob.

## 🎮 How It Works

Each environment step is one simulated year: the agent picks one flat discrete action, then the
underlying `life_model` simulation advances a year (income, account growth, RMDs, taxes, death).

**Fidelity notes (Plan 18):**

- **Taxes are actually paid.** Withdrawals execute through the model's real money path: a
  pre-tax 401k or traditional IRA withdrawal records ordinary income on the person's ledger and
  is taxed at year-end settlement inside the same step. Pre-tax and Roth are genuinely
  different to the agent — the single most important retirement decision is learnable.
- **Mortality is model-native.** The person is simulated with stochastic mortality (SSA table,
  seeded via the model RNG); dying runs the model's full death machinery (life insurance,
  estate settlement) inside the reward-visible world.
- **The economy is stochastic by default.** Correlated equity/bond/inflation draws each year
  (seeded, reproducible); `{"economy_mode": "fixed"}` restores constant rates for unit tests,
  and `economy_scenario` applies a named scenario (e.g. `recession`).
- **Early-withdrawal penalties** (10% before age 59.5 on tax-advantaged accounts) are applied
  at the action level, pending the core penalty backlog item.

### Action space — `Discrete(52)`

Every amount-bearing action is crossed with amount buckets **{10%, 25%, 50%, 100%}** of the
balance available to that action (capped at `max_action_amount`, default $50k/year), so "how
much" is part of the policy. `actions.encode_flat_action`/`decode_flat_action` are the exact
inverse indexers (round-trip tested).

| Indices | Action | Buckets |
|---------|--------|---------|
| 0–3     | Transfer bank → 401k (pre-tax) | 10/25/50/100% of bank balance |
| 4–7     | Transfer bank → 401k (Roth) | " |
| 8–11    | Transfer bank → Traditional IRA (respects annual limit) | " |
| 12–15   | Transfer bank → Roth IRA (respects annual limit) | " |
| 16–19   | Transfer bank → brokerage | " |
| 20–23   | Transfer bank → HSA (respects annual limit) | " |
| 24–27   | Withdraw 401k pre-tax → bank (taxable; penalty < 59.5) | 10/25/50/100% of pre-tax balance |
| 28–31   | Withdraw 401k Roth → bank (penalty < 59.5) | 10/25/50/100% of Roth balance |
| 32–35   | Withdraw Traditional IRA → bank (taxable; penalty < 59.5) | 10/25/50/100% of balance |
| 36–39   | Withdraw Roth IRA → bank (penalty < 59.5) | " |
| 40–43   | Withdraw brokerage → bank | " |
| 44–47   | Withdraw HSA → bank (penalty < 59.5) | " |
| 48      | Increase spending (+5%) | — |
| 49      | Decrease spending (−5%) | — |
| 50      | Retire early | — |
| 51      | No action | — |

Legality is decided solely by each action's `can_execute` via `env.get_legal_actions()`; a
bucket that maps to $0 is illegal, and a property test enforces that every legal action
executes successfully.

### Observation space — `Box(34,)` (OBS_VERSION 2)

Finite, documented bounds; observations are clipped into them. Money features are in **real**
(inflation-deflated, start-of-episode) dollars normalized by $1M. See `OBS_SPEC` in
`environment.py` for the authoritative list; summary:

| Group | Features |
|-------|----------|
| Person | age/100, years to retirement/50, is_retired, mortality probability, life progress |
| Balances (real $M) | bank, 401k pre-tax, 401k Roth, traditional IRA, Roth IRA, HSA, brokerage, **real debt** (`outstanding_debt_balance` — loans + mortgages), annual income, annual spending |
| Derived | net worth, savings rate, debt/income, retirement readiness (4% rule), emergency-fund years, income/spending |
| Tax position | projected taxable income for the upcoming year (wages + RMD), $ headroom to the next federal bracket edge (/$100k), marginal rate |
| Retirement timing | years to 59.5 (/35), years to RMD start (/50), projected RMD (real $M) |
| Contribution room | IRA remaining-room fraction, HSA remaining-room fraction |
| Market (realized, no lookahead) | time progress, last year's inflation, equity return, bond return (each %/100), log cumulative-inflation deflator |

The tax-position features are *projections* for the upcoming year: the income ledger is settled
and cleared inside `model.step()`, so intra-year "income so far" is never observable at the
decision boundary.

## 🛠️ Training Options

### Basic Training
```bash
# Train with default settings
python train_financial_agent.py --scenario basic

# Train for specific number of episodes
python train_financial_agent.py --scenario high_earner --episodes 2000
```

### Continue Training from Saved Model
```bash
# Load and continue training an existing model
python train_financial_agent.py --scenario basic --load_model models/financial_dqn_basic.pt --episodes 500
```

### Evaluation Only
```bash
# Evaluate a trained model without additional training
python train_financial_agent.py --scenario basic --eval_only --load_model models/financial_dqn_basic.pt
```

> **Checkpoint compatibility:** checkpoints carry `MODEL_VERSION` and `OBS_VERSION` and are
> saved as tensor-only `.pt` files plus a `.history.json` sidecar, so they load under modern
> PyTorch defaults (`torch.load(..., weights_only=True)`). Loading a checkpoint from a
> different version **fails with a clear error** — the observation layout and action space were
> redesigned in Plan 18, so old weights would be silently misaligned. Retrain, or check out the
> code version that produced the checkpoint.

### Generate Training Plots
```bash
# Display training progress plots
python train_financial_agent.py --scenario basic --plot_results

# Save plots to file
python train_financial_agent.py --scenario basic --plot_results --save_plots plots/basic_training.png
```

## ⚡ Performance

`benchmark_env.py` measures model-only and full-env step rates:

```bash
python benchmark_env.py
```

Baseline (Plan 18, Apple Silicon, Python 3.12; env episodes use random legal actions):

| Metric | steps/sec |
|--------|-----------|
| model-only, `collect_data=True` | ~3,000 |
| model-only, `collect_data=False` | ~3,400 (**1.13–1.16x**) |
| env before Plan 18 D7 (`collect_data=True` inside env) | ~479 |
| env after Plan 18 (collector off, obs v2, flat actions, native mortality) | ~1,074 |

The environment constructs its `LifeModel` with `collect_data=False` (rollouts never read the
DataCollector frames). Re-run the benchmark and update this table when env internals change
materially.

## 🔧 Customizing Training

### Modify Scenarios
Edit the household scenario definitions in `scenarios.py` (point values + randomization
spreads) and the training configurations in `train_financial_agent.py`.

### Adjust Reward Function
Modify the reward calculation in `environment.py` to emphasize different objectives:
- Wealth accumulation vs. spending satisfaction
- Early retirement vs. financial security
- Risk tolerance levels

### Add New Actions
Extend the action space in `actions.py`: add the `ActionType`, implement its
`can_execute`/`execute` (withdrawals must route through a person-level helper so taxes settle
through the model), and make sure the environment creates any account it needs. Amount-bearing
actions are picked up by the flat indexer automatically; the round-trip and property tests will
flag inconsistencies.
