# Reinforcement Learning on the Life Model

Train an agent to make financial decisions over a person's lifetime. Three algorithms (DQN,
REINFORCE, PPO) are implemented from scratch in PyTorch behind one interface, and every household
scenario is reachable by name.

```bash
python -m deepqlearning.train --env financial:basic      --algo dqn --total-env-steps 200000 --num-envs 8
python -m deepqlearning.train --env financial:mid_career --algo ppo --total-env-steps 200000
# the factored standing-policy actions, decided every quarter
python -m deepqlearning.train --env financial:basic --algo ppo --action-space factored --decision-interval quarter
```

## 📦 Layout

```
deepqlearning/
├── train.py                  # unified CLI: any environment x any algorithm
├── envs/                     # name -> environment registry
│   ├── registry.py           # EnvSpec, make_env, make_vector_env
│   ├── masks.py              # optional legal-action mask protocol
│   └── financial/            # the life-model environment: environment, actions (flat), policies
│                             # (factored standing policies), flatten (Discrete views for DQN),
│                             # rewards, scenarios
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
| `financial` (= `financial:basic`) | financial | `Box(40,)` (flat), `Box(51,)` (factored) | `Discrete(52)` (flat, default) or `MultiDiscrete([7,7,4,3,4,6,5,3,3,4])` (factored) | one simulated year per step by default (`decision_interval`) |
| `financial:high_earner`, `financial:low_earner`, `financial:mid_career` | financial | " | " | different point households |

Two env-config keys choose the decision problem:

- `action_space`: `"flat"` (default) is one one-off money move per decision (`Discrete(52)`, below);
  `"factored"` is a vector of **standing policies** that persist until changed (see
  [Factored action space](#factored-action-space--standing-policies)).
- `decision_interval`: `"year"` (default), `"quarter"` or `"month"` — how many monthly model steps one
  `env.step` simulates. `"year"` is one step per year (`max_age - start_age` steps; a test drives a
  twin env with `model.step_year()` and checks every reward and observation matches); quarterly and
  monthly episodes are 4x and 12x longer.

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
needs no masking support to be trainable. A `MultiDiscrete` (factored) env publishes its per-slot
masks concatenated (length `sum(nvec)`; index `sum(nvec[:i]) + v` is value `v` of slot `i`), which
the factored policy heads split back per slot.

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

**Factored actions.** PPO and REINFORCE consume a `MultiDiscrete` space natively: the policy head
emits `sum(nvec)` logits, one masked categorical per slot (`algos/base.py:FactoredCategorical`), the
joint log-probability is the sum of the slot log-probabilities and the entropy the sum of slot
entropies. DQN needs a `Discrete` space, so it trains on a factored env through
`envs/financial/flatten.py:FlattenPolicies` (`--flatten-policies auto` or env config
`flatten_policies`): joint enumeration only when the product of the slot sizes is at most 4,096 —
for the financial slots it is 2,540,160, so `auto` picks **sequential sub-steps**: each sub-step
stages one `(slot, value)` change or commits (`Discrete(37)`), at most `flatten_max_changes`
(default 3) changes per decision, reward on the commit only. Each staging sub-step costs one extra
`gamma`. The protocol scores such an agent on the raw env by replaying the staging
(`FlattenPolicies.agent_policy`).

**Learning quality is open work.** The tests check that every algorithm trains end to end
without diverging; none asserts that an algorithm learns a good policy, since the financial
environment has no known optimal policy. Pooled over five pre-registered seeds, flat DQN beats always
maxing the pre-tax 401k by a hair (+0.19, t95 [+0.01, +0.38]) and partly by spending more; PPO, flat or
factored, does not beat its bar (see the algorithm sweep below).

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

Each step is one decision: the agent picks an action (a flat action index, or a standing-policy
vector), then the underlying monthly `life_model` simulation advances one decision interval —
twelve months by default (income, account growth, RMDs, taxes, death), three or one with
`decision_interval="quarter"` / `"month"`.

**Reward over an interval.** A step earns the CRRA utility of the yearly spending rate in force at
the end of the interval (deflated to the start of the next month), weighted by `months / 12`, plus
the terminal bequest or ruin term. With yearly decisions the weight is 1, so a step earns the
year's utility. The spending rate is read from `Spending`, not from a flow stat, so
the December tax settlement and the year-end reset of flow stats inside a quarter cannot distort
it; four quarters at a constant real spending rate earn one year's utility. Two consequences when
comparing intervals: returns are only comparable within an interval (a quarterly episode stops
accruing consumption at the death quarter, a yearly one at the death year's end), and `gamma` is
per step, so use `gamma ** (1/4)` per quarter to keep the yearly discount.
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
  The 401k grows with the economy's equity return like every other account, spending grows with
  inflation, and wages with the economy's wage growth.
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
  IRA and HSA balances net of that tax, since heirs pay it. Counting them at face value would make
  deferring tax look like creating wealth. Ruin is still decided on raw net worth.
- **Savings boost.** `savings_boost_pct` cuts working-years spending by that many points of
  salary and restores it at retirement (a plan lever the SLM adviser uses).
- **Early-withdrawal penalties** (10% before age 59.5) are charged by the core model and settled
  with the year's taxes, except on Roth 401k withdrawals: the action deducts 10% of the whole
  withdrawal from the bank (a conservative stand-in for the pro-rata earnings rule; see
  `envs/financial/actions.py`).

### Flat action space — `Discrete(52)` (default)

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

### Factored action space — standing policies

`action_space="factored"` (`envs/financial/policies.py`) replaces the one-off moves with ten slots,
each a small discrete choice that **persists until changed**; index 0 of every slot is `NO_CHANGE`,
so "do nothing" is cheap. Each slot maps onto the core engine's standing-policy objects
(`life_model/policies.py`), so the engine carries the policy out month by month and posts every
dollar; nothing moves money at decision time.

| Slot | Values (after `no_change`) | Engine object |
|------|----------------------------|---------------|
| `pretax_401k_rate` | `0, 3, 6, 10, 15` (% of pay), `max` (402(g)) | `ContributionPlan(401k, pct_of_pay= / amount_annual="max", source="payroll", bucket="pretax")` |
| `roth_401k_rate` | same | same, `bucket="roth"` |
| `ira_contribution` | `none, traditional_max, roth_max` | `ContributionPlan(ira, amount_annual="max")` (from the bank) |
| `hsa_contribution` | `none, max` | `ContributionPlan(hsa, amount_annual="max", source="payroll")` |
| `sweep_policy` | `hold_cash, sweep_to_brokerage, sweep_to_bonds` | `SavingsPolicy(cash_floor=6 months of spending, sweep_to=brokerage / a bond fund)` (yearly, after taxes) |
| `spending_adjust` | `cut_10, cut_5, hold, raise_5, raise_10` | `Spending.base` (an impulse, scaled by the interval's share of a year) |
| `withdrawal_order` | `default, roth_first, pretax_first, brokerage_first` | `Family.withdrawal_order` (the household waterfall) |
| `retire` | `no, yes` | retire now (the household's retirement age stays the latest) |
| `claim_social_security` | `not_yet, now` | `SocialSecurity.withdrawal_start_age` = now (70 if never claimed) |
| `roth_conversion` | `none, to_bracket_12, to_bracket_22` | `RothConversionPolicy(fill_bracket_pct=)` (every December, from the traditional IRA or in-plan from the 401(k)) |

Per-slot legal masks: contributions need pay (401(k), IRA, HSA values other than `none` are legal
only while working; HSA also only before Medicare at 65) and the env drops those plans at
retirement; `retire` and `claim_social_security` are legal until they happen (claiming from 62).
The employer match moves into the 401(k) plan (`match_tiers`), since deferrals come from payroll.
Sizes: `nvec = [7,7,4,3,4,6,5,3,3,4]`, 46 mask entries, 2,540,160 joint actions, `Discrete(37)` under
sequential flattening. `info["policy_vector"]` reports the policies in force after each step, and
`env.describe_action(a)` the slots an action changes.

### Observation space — `Box(40,)` (OBS_VERSION 5)

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
| Decision timing | month of the upcoming decision ((month - 1)/12; always 0 with yearly decisions), months the step will simulate (/12) |
| Standing policies (factored only, `Box(51,)`) | each slot's value in force (`(index - 1)/(len(values) - 1)`), the bond fund's balance (real $M) |

The tax-position features are *projections* for the current calendar year (wages plus the year's
RMD): the income ledger is settled and cleared at each year end, and intra-year "income so far" is
not observed even at sub-year decisions.

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
| `--action-space`, `--decision-interval`, `--flatten-policies` | **Financial only** — `flat`/`factored`, `year`/`quarter`/`month`, and the DQN view of the factored space (`auto`/`joint`/`sequential`); a non-default space or interval adds `_{space}_{interval}` to the output names |
| `--reward-preset`, `--protocol-eval`, `--protocol-n-eval`, `--compare-baselines` | **Financial only** — rejected on other environments |
| `--seed N` | Seed Python, NumPy, PyTorch and the training envs for a reproducible run; outputs get a `_s<N>` suffix |
| `--warm-start-teacher NAME`, `--warm-start-seeds K` | **Financial, DQN only** — seed the replay buffer with K episodes of a scripted baseline before training (off by default) |

`--set` values are parsed as JSON when possible, so types come through:
`--set learning_rate=3e-4 --set hidden_sizes='[256,256]' --set use_dueling=false --set env.economy_mode=fixed`.

Outputs are keyed `{env}_{algo}` under `models/`, `results/`, and `plots/`, so runs of different
pairings never overwrite each other.

> **Checkpoint compatibility:** DQN checkpoints carry `MODEL_VERSION` (currently **5**) and the
> environment's `obs_version` (currently **5**: the layout above, including the two decision-timing
> features), saved as tensor-only `.pt` files plus a `.history.json` sidecar so they load under
> modern PyTorch defaults (`torch.load(..., weights_only=True)`). Loading a
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
random seeds). `FACTORED_BASELINES` expresses the same heuristics, under the same names, as
standing-policy vectors, and the protocol picks the set that matches the env's action space
(`baselines_for`), so a factored agent is compared with like: `always_max_401k` sets the pre-tax rate
to the highest one take-home pay carries (`max` when it can), `contribution_waterfall` funds HSA and
IRA to their limits plus that 401(k) rate and sweeps the rest to the brokerage, `age_glide` steps the
rate up with age, `four_percent_drawdown` accumulates and then draws taxable before pre-tax before
Roth (`brokerage_first`), `emergency_fund_first` holds cash below six months of spending. Every
factored baseline claims Social Security at the household's configured age, as the flat env does on
its own, so the factored `do_nothing` reproduces the flat `do_nothing` episode exactly (tested). `always_max_401k` is part of the bar too (`PLANNER_BASELINES`): it scored at least
as well as every planner heuristic, and a bar that leaves out the strongest scripted policy
certifies nothing. `do_nothing` / `save_25_percent` serve as regression detectors.

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

Every committed report except the SB3 cross-check comes from the monthly engine (an env step runs
twelve monthly model steps; the flat yearly env is bit-identical to driving the model with `step_year()`),
with `--protocol-n-eval 200`. Seeds 0-4 were fixed before the sweeps ran. `reports/algorithm_sweep.txt`
lists every run, the pooled verdicts and, for reference, a sweep on an earlier yearly-step engine;
`reports/retirement_security/` (flat DQN) and `reports/retirement_security_ppo/` (flat PPO) hold the
seed-0 protocol report, the pooled report and the policy-analysis artifacts;
`reports/factored_ppo_year/` and `reports/factored_ppo_quarter/` hold the same for PPO on the factored
space, with the **learned policy vector by age** instead of the action heatmap, and
`reports/factored_action_space.txt` summarizes them. Reproduce one run with

```bash
python -m deepqlearning.train --env financial:basic --algo dqn --total-env-steps 200000 \
    --num-envs 8 --reward-preset retirement_security --protocol-eval --protocol-n-eval 200 --seed 0
```

Train condition, pooled over the five seeds: the paired gap of the agent's mean return to the best
policy in the bar (flat bar: `always_max_401k`, 35.30; factored bar: `contribution_waterfall`, 35.31;
quarterly factored bar 34.94), Student-t 95% interval over seeds:

| Configuration | Pooled gap | Runs above the bar |
|---|---|---|
| DQN, flat, yearly | **+0.19 [+0.01, +0.38]: passes** | 4/5 |
| PPO, flat, yearly | -0.57 [-1.37, +0.22] | 0/5 |
| PPO, factored, yearly | -0.66 [-1.56, +0.24] | 1/5 |
| PPO, factored, quarterly | -0.79 [-2.65, +1.08] | 2/5 |

DQN's pooled interval clears zero, but narrowly, and the winning runs do it partly by **spending
more**: seed 0 has a 0.5% ruin rate and a median estate of $850k against
always-max's $1.07M (`protocol_table.txt`). Flat PPO lands just under the bar on every seed. Treat the
DQN pass as fragile: on the earlier yearly-step engine (same protocol and seeds) the verdicts were
reversed, DQN -0.39 [-2.11, +1.33] and PPO +0.11 [-0.36, +0.59] (`reports/algorithm_sweep.txt`).

**Factored space: not the default.** On the same engine, seeds and protocol, factored PPO scores like
flat PPO (mean agent return over the seeds 34.64 vs 34.72; the best factored and flat heuristics are
35.31 and 35.30) with a wider spread across seeds, and neither beats its bar, while flat DQN is the
only configuration whose pooled interval clears zero. What the factored space buys is interpretability
— the yearly agent's policy reads as "defer 15% pre-tax and 15% Roth, fund a traditional IRA, convert to
the top of the 22% bracket while working, claim at retirement, draw taxable before pre-tax before Roth"
(`reports/factored_ppo_year/policy_vector_by_age.txt`) — and the shared vocabulary with the adviser,
not return. It is opt-in (`--action-space factored`).

An independent Stable-Baselines3 cross-check (`reports/sb3_cross_check/`, produced on the earlier
yearly-step engine, so its returns are on that engine's scale; seed 0, 200k timesteps, no action masking,
n=50) found neither external algorithm above the bar: SB3 PPO 34.49 and SB3 DQN 34.17, both with no ruin,
against always-max's 34.66 on the same 50 seeds.

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
figure). For a factored checkpoint (`--action-space factored [--decision-interval quarter]`) it
writes the **policy vector by age** instead — per slot, the modal value in force at each age across
the greedy episodes and the share of decisions holding it (`policy_vector_by_age.txt/.json/.png`) —
and the lifetime trace carries the policy vector of every step. `Training_Example.ipynb` renders them inline. Committed examples live under
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
