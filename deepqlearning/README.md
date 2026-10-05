# Reinforcement Learning on the Life Model

Train an agent to make financial decisions over a person's lifetime. Three algorithms (DQN,
REINFORCE, PPO) are implemented from scratch in PyTorch behind one interface, and every household
scenario is reachable by name.

```bash
python -m deepqlearning.train --env financial:basic      --algo dqn --total-env-steps 200000 --num-envs 8
python -m deepqlearning.train --env financial:mid_career --algo ppo --total-env-steps 200000
```

## 📦 Layout

```
deepqlearning/
├── train.py                  # unified CLI: any environment x any algorithm
├── envs/                     # name -> environment registry
│   ├── registry.py           # EnvSpec, make_env, make_vector_env
│   ├── masks.py              # optional legal-action mask protocol
│   └── financial/            # the life-model environment: environment, actions, rewards, scenarios
├── algos/                    # from-scratch PyTorch algorithms
│   ├── base.py               # the Algorithm interface (act / observe / update / anneal)
│   ├── networks.py           # MLP, DuelingMLP, encoder + Q-network builders
│   ├── replay.py             # Experience, replay buffers, n-step accumulation
│   └── dqn.py, reinforce.py, ppo.py
├── training/                 # collection loops
│   ├── rollout.py            # one episode
│   ├── episode_trainer.py    # episode-count budget (notebooks, smoke tests)
│   └── trainer.py            # vectorized env-step budget (real runs)
├── evaluation/               # financial-domain only
│   ├── protocol.py           # the statistical evaluation protocol
│   ├── baselines.py          # scripted planner heuristics — the bar to beat
│   ├── analyze_policy.py     # policy heatmap / schedule / lifetime trace
│   └── benchmark_env.py      # throughput harness
└── tests/                    # mirrors the package: tests/envs, tests/algos, tests/training, ...
```

Everything is imported as a package (`from deepqlearning.envs.registry import make_env`). Run from
the **repo root**, which must be on `sys.path` — the test conftest, the notebook, and each script
entry point arrange that themselves.

## 🌍 Environments

| Name | Domain | Observation | Actions | Notes |
|------|--------|-------------|---------|-------|
| `financial` (= `financial:basic`) | financial | `Box(34,)` | `Discrete(52)` | one simulated year per step |
| `financial:high_earner`, `financial:low_earner`, `financial:mid_career` | financial | " | " | different point households |

```python
from deepqlearning.envs.registry import make_env, make_vector_env

env = make_env("financial:basic", {"reward_preset": "wealth_max"})
venv = make_vector_env("financial:mid_career", {}, num_envs=8, backend="sync")
```

Adding an environment is one `register_env(EnvSpec(...))` call; the factory is imported lazily, so
importing the registry never costs an import of `life_model`. An environment that needs an
optional package lists it in `EnvSpec.requires`, and `make_env` then fails with an install hint
instead of an import traceback.

### Legal-action masking is optional

The financial environment restricts which of its 52 actions are valid each year.
`envs/masks.py:legal_actions_of` resolves that in three steps: `info["legal_mask"]` (the only form
that survives an async vector backend), then `env.get_legal_actions()`, then "everything is legal".
An environment that declares nothing is treated as having no restriction, so a new environment
needs no masking support to be trainable.

## 🧠 Algorithms

All three implement `Algorithm` (`algos/base.py`), which is **batched**: a trainer hands the
algorithm `N >= 1` environment streams and calls `act` → `observe` → `update` every step. The
trainer never learns which algorithm it is driving — `update` simply returns `None` until the
algorithm has enough data.

| `--algo` | Family | Learns from | Key config |
|----------|--------|-------------|------------|
| `dqn` | off-policy value | replay buffer, every step | `hidden_sizes`, `use_dueling`, `use_double_dqn`, `use_prioritized_replay`, `n_step`, `epsilon_*`, `target_update_freq` |
| `reinforce` | on-policy policy gradient | whole episodes | `baseline` (`none`/`mean`/`value`), `batch_episodes`, `entropy_coef`, `normalize_returns` |
| `ppo` | on-policy, clipped surrogate | fixed rollout, reused for several epochs | `n_steps`, `epochs`, `minibatches`, `clip_range`, `gae_lambda`, `value_coef`, `entropy_coef` |

Networks are MLPs sized from the observation space alone, so nothing in an algorithm knows which
environment it is training on.

**Learning quality is open work.** The tests check that every algorithm trains end to end
without diverging; none asserts that an algorithm learns a good policy, since the financial
environment has no known optimal policy. Observed learning on it is weak so far, and more
exploration is the expected next step.

## 🎯 The financial objective — what "good" means

The reward is **not** "maximize net worth" (whose optimal policy is to hoard and never spend). It
is a utility-based objective defined in `envs/financial/rewards.py`:

- **Per-year consumption utility** `u(c_t)` — CRRA utility of the year's **real**
  (inflation-deflated) spending. Concave, so *smoothing* consumption is optimal — actual financial
  planning, not accumulation.
- **Terminal bequest** `b(W)` — a warm-glow CRRA term on the real net worth left at death.
- **Terminal ruin penalty** — a large negative applied when the episode ends in bankruptcy,
  aligned with the environment's `BANKRUPTCY_THRESHOLD`.

Time preference is the algorithm's `gamma` alone (no double discounting inside the reward).
Risk-aversion, bequest weight, and ruin penalty are **configuration**, pinned by three presets and
recorded in every eval report:

| Preset | Character |
|--------|-----------|
| `retirement_security` (**default**) | Ruin-avoidance dominant: a large ruin penalty over a lifetime of O(1) consumption utilities makes "don't run out of money" first-order. |
| `wealth_max` | Bequest-dominant wealth-accumulation objective; a comparison point for the consumption-based presets. |
| `smooth_consumption` | High CRRA risk aversion; pushes toward a smooth lifetime consumption path. |

Select a preset with `--reward-preset` (CLI) or `reward_preset` in the env config.

### Domain randomization

`env.reset(seed=..., options={"randomize": True, "scenario": "basic"})` draws the episode's
household — start age, retirement age, salary, spending, bank balance, gender — from seeded
distributions around the scenario's point values (`EpisodeSampler` in
`envs/financial/scenarios.py`). The same seed always reproduces the same household and trajectory;
without options the fixed point household is reproduced exactly. A scenario can also carry named
economy scenarios (e.g. `recession`) to sample per episode as a curriculum knob.

## 🎮 How the financial environment works

Each step is one simulated year: the agent picks one flat discrete action, then the underlying
`life_model` simulation advances a year (income, account growth, RMDs, taxes, death).

**Fidelity notes:**

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
much" is part of the policy. `encode_flat_action`/`decode_flat_action` are the exact inverse
indexers (round-trip tested).

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
`envs/financial/environment.py` for the authoritative list; summary:

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

The terminal `info` also publishes `bankrupt`, so a trainer can report how episodes ended without
reaching into the environment.

## 🛠️ Training options

```bash
# Install
pip install -r ../requirements.txt -r requirements-rl.txt

# Vectorized step budget (the default mode)
python -m deepqlearning.train --env financial:basic --algo dqn \
    --total-env-steps 200000 --num-envs 8 --reward-preset retirement_security --protocol-eval

# Episode budget, single environment
python -m deepqlearning.train --env financial:high_earner --algo ppo --episodes 1500

# Continue from a checkpoint, or evaluate one without training
python -m deepqlearning.train --env financial:basic --algo dqn \
    --load-model models/financial_basic_dqn.pt --episodes 500
python -m deepqlearning.train --env financial:basic --algo dqn --eval-only \
    --load-model models/financial_basic_dqn.pt --compare-baselines
```

| Flag | Meaning |
|------|---------|
| `--env`, `--algo` | Registered environment name; `dqn`, `reinforce`, or `ppo` |
| `--total-env-steps`, `--num-envs`, `--backend` | Vectorized trainer budget and parallelism (`sync`/`async`) |
| `--episodes` | Use the episodic trainer instead |
| `--load-model`, `--eval-only`, `--eval-episodes` | Checkpoint loading and final evaluation |
| `--tensorboard <dir>`, `--plot-results`, `--save-plots` | Optional logging and figures |
| `--set SECTION.KEY=VALUE` | Repeatable config override; `SECTION` is `algo` (default), `env`, or `train` |
| `--reward-preset`, `--protocol-eval`, `--protocol-n-eval`, `--compare-baselines` | **Financial only** — rejected on other environments |

`--set` values are parsed as JSON when possible, so types come through:
`--set learning_rate=3e-4 --set hidden_sizes='[256,256]' --set use_dueling=false --set env.economy_mode=fixed`.

Outputs are keyed `{env}_{algo}` under `models/`, `results/`, and `plots/`, so runs of different
pairings never overwrite each other.

> **Checkpoint compatibility:** DQN checkpoints carry `MODEL_VERSION` (currently **4**) and the
> environment's `obs_version`, saved as tensor-only `.pt` files plus a `.history.json` sidecar so
> they load under modern PyTorch defaults (`torch.load(..., weights_only=True)`). Loading a
> checkpoint from a different version **fails with a clear error** — a checkpoint's weights are tied
> to a specific observation layout, action space, and reward scale. An environment with no versioned
> observation layout leaves `obs_version` unset and the gate off. REINFORCE and
> PPO checkpoints record their algorithm name and refuse to load into a different one.

### Interactive tutorial

```bash
jupyter notebook Training_Example.ipynb
```

## 📊 Baselines & the bar (financial)

`evaluation/baselines.py` provides planner-grade heuristics an advisor would recognize — these are
the bar the agent must beat, not "do nothing":

- `contribution_waterfall` — fill scarce tax-advantaged room (HSA → IRA, gated by the observed
  room features) then route the rest to the 401k, then a taxable brokerage, keeping a cash reserve.
- `age_glide` — a savings-rate glide path that steps up the contribution fraction with age.
- `four_percent_drawdown` — accumulate while working, then draw the portfolio down in retirement
  with Roth-last ordering (matching `PaymentService` priorities).
- `emergency_fund_first` — fill a 6-month cash buffer before investing.

Each is a deterministic function of the seeded state that emits only legal actions (tested on 50
random seeds). The simple `do_nothing` / `always_max_401k` / `save_25_percent` policies remain as
regression detectors.

## 🔬 Evaluation protocol & reading the report

`evaluation/protocol.py`'s `EvalProtocol` runs the agent and every baseline on **identical**
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

## 🏋️ Training-stack features

- **Prioritized experience replay** — proportional sampling, IS-weight correction, TD-error
  priority updates (DQN).
- **N-step returns** (`n_step=3` by default) accumulated per environment stream inside
  `DQNAgent.observe`, with a per-transition discount.
- **GAE(λ)** with the truncation-vs-termination distinction handled correctly (PPO).
- **Vectorized collection** — `Trainer` drives `N` `gymnasium.vector` envs (sync default; async
  optional) feeding one learner, handling `NEXT_STEP` autoreset; per-env seeds derive from a base
  seed so collection is reproducible.
- **LR schedule** (cosine/step) + **early stopping** on eval-plateau, keeping the best checkpoint.
- `--tensorboard <logdir>` logs return/loss/eval scalars via `torch.utils.tensorboard` (soft
  import; absent → training still runs).

### SB3 cross-check

`sb3/cross_check.py` trains an external Stable-Baselines3 DQN/PPO on the same financial env as an
independent sanity bound. Gated behind `requirements-rl-sb3.txt`, which nothing in the trainer,
env, or test suite imports:

```bash
pip install -r requirements-rl.txt -r requirements-rl-sb3.txt
python sb3/cross_check.py --algo dqn --timesteps 200000
```

## 🔎 Policy analysis (financial)

```bash
python -m deepqlearning.evaluation.analyze_policy \
    --checkpoint models/financial_basic_dqn.pt --reward-preset retirement_security
```

It writes a **policy heatmap** (dominant action over an age × wealth-decile grid), a
**contribution/withdrawal schedule by age**, and an annotated **lifetime trace** (JSON + net-worth
figure). `Training_Example.ipynb` renders them inline. Committed examples live under
`reports/retirement_security/`.

## ⚡ Performance

```bash
python -m deepqlearning.evaluation.benchmark_env --num-envs 8
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

> **Honest note on the ≥3× target.** The vectorized trainer targets ≥3× env-steps/sec from
> vectorization. On this workload that is **not reached**: each simulated year is cheap (~1 ms), so
> `gymnasium` `AsyncVectorEnv`'s per-step multiprocessing IPC/synchronization overhead dominates and
> caps the speedup at ~1.6–2.0× (confirmed to persist even with an empty `info` payload). The
> vectorized collector is correct, reproducible, and enables batched inference; the raw throughput
> ceiling is a property of the cheap per-step sim, reported as measured rather than inflated.

## 🔁 Reproducing a full-scale run

```bash
python -m deepqlearning.train --env financial:basic --algo dqn --num-envs 8 \
    --total-env-steps 2000000 --reward-preset retirement_security \
    --protocol-eval --protocol-n-eval 200 --tensorboard runs/basic

python -m deepqlearning.evaluation.analyze_policy --checkpoint models/financial_basic_dqn.pt \
    --reward-preset retirement_security --episodes 200
```

Checkpoints are **not** committed (see `.gitignore`); reports/PNGs/JSON under `reports/` are. A
larger `--total-env-steps` (and `--protocol-n-eval`, which tightens the CIs) is what turns the
overlapping-CI result into a statistically separated one.

## 🔧 Extending

- **New environment** — write a factory and `register_env(EnvSpec(name=..., factory=..., domain=...))`
  in `envs/registry.py`. Declare optional dependencies in `requires` so a missing one produces a
  friendly install message instead of an import traceback.
- **New algorithm** — subclass `Algorithm` (`act` / `observe` / `update`, plus `checkpoint_state` /
  `restore_checkpoint`) and add it to `ALGORITHMS` in `algos/__init__.py`. Both trainers and the
  CLI pick it up with no further changes.
- **New scenario / objective** — edit `envs/financial/scenarios.py` (point values + randomization
  spreads) or add a preset to `REWARD_PRESETS` in `envs/financial/rewards.py`. The reward function
  is pure and unit-tested — edit `rewards.py`, not the environment.
- **New action** — extend `envs/financial/actions.py`: add the `ActionType`, implement its
  `can_execute`/`execute` (withdrawals must route through a person-level helper so taxes settle
  through the model), and make sure the environment creates any account it needs. Amount-bearing
  actions are picked up by the flat indexer automatically; the round-trip and property tests will
  flag inconsistencies.

## 🧪 Tests

```bash
tox -e deepqlearning         # fast suite
tox -e deepqlearning-slow    # 150-episode financial training smoke
```
