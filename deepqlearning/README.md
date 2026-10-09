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
| `financial` (= `financial:basic`) | financial | `Box(38,)` | `Discrete(52)` | one simulated year per step |
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
environment has no known optimal policy. Pooled over five pre-registered seeds, neither DQN nor
PPO beats always maxing the pre-tax 401k (see the algorithm sweep below).

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
household — start age, retirement age, salary, spending, bank balance, gender, an employer match offer,
age-calibrated starting 401k/brokerage balances (a fraction of the "1x salary by 30 ... 8x by 60"
planner benchmark), and the retirement spending ratio — from seeded
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
  (seeded, reproducible); `{"economy_mode": "fixed"}` restores constant rates for unit tests.
  The 401k grows with the economy's equity return like every other account (it was pinned at a
  fixed 6%), spending grows with inflation, and wages with the economy's wage growth.
- **Named economy scenarios are overlays.** `economy_scenario` (e.g. `recession`) layers the
  scenario on the stochastic economy (`envs/financial/economy_overlay.py`): level overrides shift
  the draws for `scenario_regime_years` (default 10) and path overrides script their listed
  years, so trials still differ. `{"scenario_overlay": False}` restores the core semantics, where
  the scenario replaces the economy with a deterministic one.
- **Retirement income.** The person has Social Security (on by default; claimed at the
  retirement age clipped to 62-70, or `ss_claim_age`) from an earnings record synthesized back to
  `career_start_age` at today's salary indexed by the average wage index — a flat real career.
  Bank-to-401k deferrals earn the household's employer match (`employer_match_rate` per dollar on
  deferrals up to `employer_match_cap` x pay, deposited pre-tax, 415(c)-capped). Households can
  start with 401k / brokerage balances, and base spending steps down to
  `retirement_spending_ratio` of its working level at retirement.
- **After-tax terminal wealth.** With `bequest_pretax_tax_rate` set (0.22 in every named
  `financial:*` env; 0.0 in the bare `FinancialLifeEnv()` used by unit tests), the bequest the
  reward values and the terminal net worth the protocol reports count pre-tax 401k, traditional
  IRA and HSA balances net of that tax, since heirs pay it. Counting them at face value made
  deferring tax look like creating wealth. Ruin is still decided on raw net worth.
- **Savings boost.** `savings_boost_pct` cuts working-years spending by that many points of
  salary and restores it at retirement (a plan lever the SLM adviser uses).
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

### Observation space — `Box(38,)` (OBS_VERSION 4)

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
| Contribution room | IRA remaining-room fraction (one limit shared by Roth and Traditional), HSA remaining-room fraction; both reset each year |
| Market (realized, no lookahead) | time progress, last year's inflation, equity return, bond return (each %/100), log cumulative-inflation deflator |
| Retirement income | Social Security benefit (real $/100k: paid once claiming, else earned so far, in current wage-indexed dollars), years to the claim age (/50), employer match rate and cap |

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
| `--seed N` | Seed Python, NumPy, PyTorch and the training envs for a reproducible run; outputs get a `_s<N>` suffix |
| `--warm-start-teacher NAME`, `--warm-start-seeds K` | **Financial, DQN only** — seed the replay buffer with K episodes of a scripted baseline before training (off by default) |

`--set` values are parsed as JSON when possible, so types come through:
`--set learning_rate=3e-4 --set hidden_sizes='[256,256]' --set use_dueling=false --set env.economy_mode=fixed`.

Outputs are keyed `{env}_{algo}` under `models/`, `results/`, and `plots/`, so runs of different
pairings never overwrite each other.

> **Checkpoint compatibility:** DQN checkpoints carry `MODEL_VERSION` (currently **5**) and the
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
random seeds). `always_max_401k` is part of the bar too (`PLANNER_BASELINES`): it scored at least
as well as every planner heuristic, and a bar that leaves out the strongest scripted policy
certifies nothing. `do_nothing` / `save_25_percent` remain as regression detectors.

## 🔬 Evaluation protocol & reading the report

`evaluation/protocol.py`'s `EvalProtocol` runs the agent and every baseline on **identical**
`SeedSequence`-spawned seed sets across three conditions and writes a JSON report + a comparison
table (`--protocol-eval`):

- `train` — training-distribution seeds.
- `held_out_seeds` — disjoint same-distribution seeds (generalization to unseen draws).
- `held_out_scenario` — the same seeds under a named economy scenario not trained on (default
  `recession`) — the out-of-distribution test.

Per policy it reports **mean return ± bootstrap 95% CI, ruin rate, success rate** (stayed solvent
to the end of life), **terminal real net-worth percentiles**, and the per-episode returns.
"Intelligent" is defined operationally on the `train` condition for the default preset: the agent's
mean return exceeds every policy in the bar **and** the paired per-episode gap to the best of them
has a bootstrap 95% CI above zero (every policy runs on the same seeds, so the paired test is the
right one; whether the two unpaired CIs overlap is still reported). The held-out gap is reported,
not gated.

**Pooling pre-registered seeds.** One training seed cannot settle whether an algorithm works:
results vary more across training seeds than across evaluation episodes. Train with `--seed 0` ...
`--seed 4` (fixed in advance) and pool the protocol reports:

```bash
python -m deepqlearning.evaluation.pool_seeds results/protocol_report_financial_basic_ppo_s*_retirement_security.json \
    --out reports/retirement_security_ppo/pooled_report.json
```

The pooled verdict is a Student-t 95% interval over the per-seed paired gaps to the best policy in
the bar, so it carries training-seed variance.

### Committed reports and the algorithm sweep (default preset)

Every committed report was regenerated on the retirement-income world (Social Security, employer
match, starting balances, economy-linked 401k growth, scenario overlays, after-tax bequest; see the
fidelity notes above) with `--protocol-n-eval 200`. Seeds 0-4 were fixed before the sweep ran;
`reports/algorithm_sweep.txt` lists every run and the pooled verdicts, and
`reports/retirement_security/` (DQN) and `reports/retirement_security_ppo/` (PPO) hold the seed-0
protocol report, the pooled report, and the policy-analysis artifacts. Reproduce one run with

```bash
python -m deepqlearning.train --env financial:basic --algo dqn --total-env-steps 200000 \
    --num-envs 8 --reward-preset retirement_security --protocol-eval --protocol-n-eval 200 --seed 0
```

Train condition, mean return of the agent vs `always_max_401k` (33.50, the best policy in the bar),
with the paired-gap 95% CI:

| Seed | DQN | PPO |
|---|---|---|
| 0 | 34.48, gap [-0.61, +2.27] | 33.50, gap [-0.00, +0.01] |
| 1 | 33.20, gap [-0.37, -0.23] | 33.40, gap [-0.65, +0.23] |
| 2 | 33.59, gap [+0.02, +0.18] — passes | 33.42, gap [-0.61, +0.24] |
| 3 | 30.78, gap [-4.89, -0.76] | 33.44, gap [-0.07, -0.05] |
| 4 | 33.49, gap [-0.03, -0.00] | 34.30, gap [+0.63, +0.98] — passes |
| **Pooled (t95 over seeds)** | **-0.39 [-2.11, +1.33]: not intelligent** | **+0.11 [-0.36, +0.59]: not intelligent** |

One run per algorithm clears the paired per-run bar, and pooling over the pre-registered seeds says
neither algorithm reliably beats always maxing the 401k. Most runs converge to, or near, that
policy. Two runs that beat it on mean return did so partly by **spending more**: DQN seed 0 has the
highest mean return but a 4% ruin rate and a median estate of $564k against always-max's $966k
(`protocol_table.txt`). The objective rewards consumption, so that trade can be rational under it,
but it is not the "save smarter" behavior the planner bar is about.

An independent Stable-Baselines3 cross-check (`reports/sb3_cross_check/`, seed 0, 200k timesteps,
no action masking, n=50) agrees: SB3 PPO 34.49 and SB3 DQN 34.17, both with no ruin, against
always-max's 34.66 on the same 50 seeds.

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
# any algorithm: --algo ppo --checkpoint models/financial_basic_ppo_s0.pt
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
