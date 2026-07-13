# Deep Reinforcement Learning for Financial Planning

Train an AI agent to make financial decisions over a person's lifetime. The agent learns to
manage bank accounts, retirement funds, debt, and lifestyle choices to optimize a defensible,
utility-based financial-planning objective (Plan 19) — and is measured against planner-grade
heuristics with a proper statistical protocol.

## 🎯 The objective — what "good" means (Plan 19 D1)

The reward is **not** "maximize net worth" (whose optimal policy is to hoard and never spend). It
is a utility-based objective defined in `rewards.py`:

- **Per-year consumption utility** `u(c_t)` — CRRA utility of the year's **real**
  (inflation-deflated) spending. Concave, so *smoothing* consumption is optimal — actual financial
  planning, not accumulation.
- **Terminal bequest** `b(W)` — a warm-glow CRRA term on the real net worth left at death.
- **Terminal ruin penalty** — a large negative applied when the episode ends in bankruptcy,
  aligned with the environment's `BANKRUPTCY_THRESHOLD`.

Time preference is the DQN `gamma` alone (no double discounting inside the reward). Risk-aversion,
bequest weight, and ruin penalty are **configuration**, pinned by three presets and recorded in
every eval report:

| Preset | Character |
|--------|-----------|
| `retirement_security` (**default**) | Ruin-avoidance dominant: a large ruin penalty over a lifetime of O(1) consumption utilities makes "don't run out of money" first-order. |
| `wealth_max` | Bequest-dominant; approximates the legacy wealth-accumulation objective (kept for comparability). |
| `smooth_consumption` | High CRRA risk aversion; pushes toward a smooth lifetime consumption path. |

Select a preset with `--reward-preset` (trainer) or `reward_preset` in the env config.

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r ../requirements.txt -r requirements-rl.txt
```

### 2. Train Your First Agent
```bash
# Vectorized trainer (Plan 19 D4) on the default retirement_security objective
python train_financial_agent.py --scenario basic --vectorized --num-envs 8 \
    --total-env-steps 200000 --reward-preset retirement_security --protocol-eval

# Legacy single-env trainer, fixed episode count
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

> **Checkpoint compatibility:** checkpoints carry `MODEL_VERSION` (now **4** — bumped for the
> Plan 19 utility reward) and `OBS_VERSION`, saved as tensor-only `.pt` files plus a
> `.history.json` sidecar so they load under modern PyTorch defaults
> (`torch.load(..., weights_only=True)`). Loading a checkpoint from a different version **fails
> with a clear error** — the observation layout, action space (Plan 18), and reward scale (Plan 19)
> changed, so old weights would be silently misaligned. Retrain, or check out the code version that
> produced the checkpoint.

### Generate Training Plots
```bash
# Display training progress plots
python train_financial_agent.py --scenario basic --plot_results

# Save plots to file
python train_financial_agent.py --scenario basic --plot_results --save_plots plots/basic_training.png
```

## 📊 Baselines & the bar (Plan 19 D2)

`baselines.py` provides planner-grade heuristics an advisor would recognize — these are the bar
the agent must beat, not "do nothing":

- `contribution_waterfall` — fill scarce tax-advantaged room (HSA → IRA, gated by the observed
  room features) then route the rest to the 401k, then a taxable brokerage, keeping a cash reserve.
- `age_glide` — a savings-rate glide path that steps up the contribution fraction with age.
- `four_percent_drawdown` — accumulate while working, then draw the portfolio down in retirement
  with Roth-last ordering (matching `PaymentService` priorities).
- `emergency_fund_first` — fill a 6-month cash buffer before investing.

Each is a deterministic function of the seeded state that emits only legal actions (tested on 50
random seeds). The simple `do_nothing` / `always_max_401k` / `save_25_percent` policies remain as
regression detectors.

## 🔬 Evaluation protocol & reading the report (Plan 19 D3)

`evaluation.py`'s `EvalProtocol` runs the agent and every baseline on **identical**
`SeedSequence`-spawned seed sets across three conditions and writes a JSON report + a comparison
table (`--protocol-eval`):

- `train` — training-distribution seeds.
- `held_out_seeds` — disjoint same-distribution seeds (generalization to unseen draws).
- `held_out_scenario` — the same seeds under a named economy scenario not trained on (default
  `recession`) — the out-of-distribution test.

Per policy it reports **mean return ± bootstrap 95% CI, ruin rate, success rate** (stayed solvent
to the end of life), and **terminal real net-worth percentiles**. "Intelligent" is defined
operationally on the `train` condition for the default preset: the agent's mean return exceeds
every planner heuristic's **and** its CI does not overlap the best heuristic's. The held-out gap is
reported, not gated.

### Committed report (default preset)

`reports/retirement_security/` holds a full committed run (see `protocol_table.txt` /
`protocol_report.json`) from a **moderate** vectorized run — 40k env steps / 872 episodes / seed 0
/ ~43 s (labeled in the report's `run_metadata`). In that run the agent's **mean return beats every
planner heuristic on all three conditions** (train 31.5 vs 30.1 best heuristic; held-out seeds
+1.0; recession 30.1 vs 29.7), at 0% ruin and 100% success — **but the 95% CIs overlap at n=50, so
the strict statistical-separation verdict is `False`.** Tellingly, the agent reaches higher utility
with *lower* median net worth (~$335k vs ~$900k for the hoarding heuristics): under
`retirement_security` it consumes rather than hoards, which is exactly the behavior the utility
reward is meant to produce. This is an honest snapshot — a full-scale run (below) is expected to
widen the gap; the "beats every heuristic with separated CIs" claim will only be made here once a
committed report shows it.

## 🏋️ Training upgrades (Plan 19 D4)

The trainer stack (`agent.py`, `vector_trainer.py`) is modernized while staying dependency-light
(`requirements-rl.txt` is still gymnasium + torch only):

- **Prioritized experience replay** — really implemented now (the old `use_prioritized_replay`
  flag was dead): proportional sampling, IS-weight correction, TD-error priority updates.
- **N-step returns** (`n_step=3`) via `NStepAccumulator`, with a per-transition discount.
- **Vectorized collection** — `VectorizedTrainer` drives `N` `gymnasium.vector` envs (sync default;
  async optional) feeding one learner, handling `NEXT_STEP` autoreset; per-env seeds derive from a
  base seed so collection is reproducible.
- **LR schedule** (cosine/step) + **early stopping** on eval-plateau, keeping the best checkpoint.
- The dead `epsilon_decay` config keys are purged; epsilon decays per-episode over
  `epsilon_decay_fraction` of training.

### Optional integrations

- `--tensorboard <logdir>` — logs return/epsilon/loss/eval scalars via `torch.utils.tensorboard`
  (behind a soft import; absent → training still runs).
- **SB3 cross-check** (`sb3/cross_check.py`) trains an external Stable-Baselines3 DQN/PPO on the
  same env as an independent sanity bound. Gated behind `requirements-rl-sb3.txt`, which nothing in
  the trainer, env, or test suite imports:
  ```bash
  pip install -r requirements-rl.txt -r requirements-rl-sb3.txt
  python sb3/cross_check.py --algo dqn --timesteps 200000
  ```

## 🔎 Policy analysis (Plan 19 D5)

`analyze_policy.py` turns a checkpoint into human-checkable artifacts (headless Agg backend):

```bash
python analyze_policy.py --checkpoint models/financial_dqn_basic.pt --reward-preset retirement_security
```

It writes a **policy heatmap** (dominant action over an age × wealth-decile grid), a
**contribution/withdrawal schedule by age**, and an annotated **lifetime trace** (JSON + net-worth
figure). The `Training_Example.ipynb` notebook renders them inline. Committed examples live under
`reports/retirement_security/`.

## ⚡ Performance

`benchmark_env.py` measures model-only, single-env, and vectorized step rates:

```bash
python benchmark_env.py --num-envs 8
```

Reference (Apple Silicon, Python 3.12; env steps use random actions):

| Metric | steps/sec |
|--------|-----------|
| model-only, `collect_data=True` | ~2,650 |
| model-only, `collect_data=False` | ~2,840 (**1.07x**) |
| env (single, random legal actions) | ~850 |
| vector env, **sync**, 8 envs | ~1,270 (**1.0x** — sync is sequential) |
| vector env, **async**, 8 envs | ~1,900 (**~1.6x** single-env) |
| vector env, **async**, 16 envs | ~2,100 (**~1.7x** single-env) |

> **Honest note on the ≥3× target.** Plan 19 D4 targets ≥3× env-steps/sec from vectorization. On
> this workload that is **not reached**: each simulated year is cheap (~1 ms), so `gymnasium`
> `AsyncVectorEnv`'s per-step multiprocessing IPC/synchronization overhead dominates and caps the
> speedup at ~1.6–2.0× (confirmed to persist even with an empty `info` payload). The vectorized
> collector is correct, reproducible, and enables batched inference; the raw throughput ceiling is
> a property of the cheap per-step sim, reported as measured rather than inflated.

## 🔁 Reproducing a full-scale run

The committed report is a moderate (43 s) run. For a full-scale run that is expected to widen the
agent-vs-heuristic gap:

```bash
# Train (vectorized) + write the protocol report and policy-analysis artifacts.
python train_financial_agent.py --scenario basic --vectorized --num-envs 8 \
    --total-env-steps 2000000 --reward-preset retirement_security \
    --protocol-eval --protocol-n-eval 200 --tensorboard runs/basic

# Analyze a specific checkpoint after the fact.
python analyze_policy.py --checkpoint models/financial_dqn_basic.pt \
    --reward-preset retirement_security --episodes 200
```

Checkpoints are **not** committed (see `.gitignore`); reports/PNGs/JSON under `reports/` are. A
larger `--total-env-steps` (and `--protocol-n-eval`, which tightens the CIs) is what turns the
overlapping-CI result into a statistically separated one.

## 🔧 Customizing Training

### Modify Scenarios
Edit the household scenario definitions in `scenarios.py` (point values + randomization
spreads) and the training configurations in `train_financial_agent.py`.

### Adjust the objective
Change `--reward-preset`, or add a preset to `REWARD_PRESETS` in `rewards.py` (risk aversion,
bequest weight, ruin penalty are all configuration). The reward function is pure and unit-tested —
edit `rewards.py`, not the environment.

### Add New Actions
Extend the action space in `actions.py`: add the `ActionType`, implement its
`can_execute`/`execute` (withdrawals must route through a person-level helper so taxes settle
through the model), and make sure the environment creates any account it needs. Amount-bearing
actions are picked up by the flat indexer automatically; the round-trip and property tests will
flag inconsistencies.
