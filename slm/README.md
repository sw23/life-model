# slm — Simulation-Grounded Language-Model Adviser

A product directory (like `deepqlearning/`), fully isolated from the core `life_model` package and
**excluded from the published wheel**. It turns the life-model simulator into a *data generator*
and *verifier* for language-model financial advice: the simulator scores any proposed decision, so
generated rationales are certified by Monte Carlo simulation rather than asserted.

> **This is not financial advice.** Outputs are **simulation-grounded educational decision
> support**: they describe outcomes the life-model simulator projects for a household under stated
> assumptions, carry the simulator's version provenance, and inherit the package's
> use-at-your-own-risk posture. They are not fiduciary or personalized advice and are not a
> recommendation to buy or sell any security. The model is trained to **refuse** questions about
> anything the simulator does not model (cryptocurrency, individual securities, options, unmodeled
> insurance products, specific real-estate deals). See `slm/prompts.py::SYSTEM_PROMPT`.

## Fidelity ceiling (read before trusting any numbers)

Advice fidelity is capped by what the **pipeline actually scores**. Scored households include
Social Security (an earnings record synthesized at today's salary — a flat real career), an
employer 401k match, age-calibrated starting 401k/brokerage balances, child dependents
(age-banded costs) and healthcare (the medical-cost curve plus Medicare), and the economy is
stochastic with named scenarios layered on as regimes or shocks. Terminal wealth values
tax-deferred balances after a 22% tax. What is still *not* priced caps fidelity further: no
spouse/second earner, no housing purchase, no leisure value (so retirement age is not a lever), no
Social Security earnings test (so claiming is never before retirement), and out-of-pocket medical
costs compound at CPI + 2 points for the whole horizon (a core-config assumption that makes low
earners marginal). Every dataset stamps the simulator commit and config hash in its datasheet, so
data generated against an older configuration is detectable. **Treat any model distilled from a
pipeline-validation dataset as a pipeline-validation artifact, not a publishable adviser.**

## Pipeline

| Stage | Module | What it does |
|---|---|---|
| Schema | `schema.py` | Versioned dataset schema (`schema_version=2`, pydantic StrictModel). |
| Serialize | `serializer.py` | Household ↔ faithful natural-language text (round-trip tested). |
| Decisions | `strategies.py`, `candidates.py` | The compositional plan vocabulary → executable plans; the RL planner heuristics as reference policies. |
| Score | `scoring.py` | Shared-seed paired Monte Carlo scoring, coordinate search over the plan grid, adaptive trials. |
| Households | `households.py` | SLM household distributions: the RL scenarios plus older households, varied economies, children and medical costs budgeted inside spending. |
| Generate | `generate_data.py` | Seeded households → searched plans → evidence-backed label (or `no_plan_lever`) + counterfactual rationale + refusals → optional label cap → JSONL + datasheet. |
| Evaluate | `evaluate_adviser.py`, `faithfulness.py` | Execute the advised plan in the simulator; regret vs the oracle and vs every constant answer and reference heuristic, with CIs; top-set agreement; exact faithfulness and noise-aware consistency; parse and refusal rates. |
| Train | `train.py` | Size-agnostic HF SFT (LoRA/QLoRA or full+FSDP) from one YAML `TrainConfig`. |
| Advise | `advise.py` | Draft → simulate → revise tool-loop; itself an `AdviserModel`. |
| Backends | `backends.py`, `adviser.py` | `AdviserModel` protocol + stub / HF / MLX / Anthropic-API implementations. |

## Plans, households and labels

**The decision is a plan**: one value on each of four independent levers, written as one token
`<savings>_<routing>_<claim>_<drawdown>`, e.g. `save5_roth_claim70_bracketfill`:

| Lever | Values |
|---|---|
| savings | `save0` keep spending · `save5` / `save10` save 5 / 10 more points of salary while working |
| routing | `pretax` · `roth` · `split` (pre-tax on pay above the 12% bracket, Roth on the rest); savings beyond the 402(g) room go to brokerage above a 3-month cash reserve |
| claim | `claimret` at retirement · `claimfra` at full retirement age · `claim70` at 70 (never before retirement) |
| drawdown | `conventional` (the simulator's default order) · `bracketfill` (draw pre-tax savings up to the top of the 12% bracket each retired year) |

The old menu (four planner heuristics plus max pre-tax / max Roth) had two near-duplicate pairs and
none of the levers advice actually turns on; those heuristics remain as **reference policies** the
eval scores on the same seeds, not answers.

`households.py` widens the RL environment's four scenarios (ages 19–38) with `late_career` (46–54)
and `pre_retiree` (54–60), draws each household's economy (about half the stochastic baseline,
the rest boom / high-inflation / deflation / conservative / aggressive as overlays; `recession` is
held out for evaluation), and budgets children and the start-year medical cost *inside* the sampled
spending. Its low earner spends 75% of gross (the RL point's 83% left nothing after taxes).

**Scoring** (`scoring.py`) runs every candidate on the same trial seeds and compares them pairwise
on the mean utility return of the reward preset (ruin-avoidance first, then after-tax wealth left
at death). A coordinate search scores the default plan (`save0_pretax_claimret_conventional`),
each one-lever variant of it, and two combinations — 8 to 10 plans instead of 54. Trials start at
`--min-trials` and double while some lever beats the default on average without yet being
significant.

**The label is evidence-backed**: a lever moves off its default only when that one-lever change
beats the default plan on paired trials with a bootstrap 95% CI above zero; the label combines the
proven changes (and falls back to the argmax if that combination is not within noise of the best).
Each example records a `decision_basis`:

* **clear** — the label changes at least one lever with evidence, or the default beats every
  one-lever change beyond noise;
* **equivalent** — no change is proven but some is not ruled out; the label stays at the default
  and the rationale says so;
* **no_viable** — even the best plan is solvent in at most 10% of trials. The label is then
  `no_plan_lever`; the eval executes it as the default plan, so abstaining never beats a plan that
  helps.

`--max-label-share` caps any one label (dropping `equivalent` examples first). Refusals cover 8
out-of-scope topics × 6 phrasings with rotating wording; the eval uses 3 held-out phrasings.

## Teacher gating (why no RL policy is a teacher)

No learned policy has cleared the RL protocol's pre-registered bar (see
`deepqlearning/README.md`; the bar now includes `always_max_401k` and pools five pre-registered
seeds). A mediocre teacher silently caps the student, so the candidates are the searched plans
only. A policy that passes the pooled verdict can be added as a candidate.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .                       # core life_model (editable)
pip install -r deepqlearning/requirements-rl.txt   # gymnasium (scoring reuses the RL env)
pip install -r slm/requirements-slm.txt            # schema/yaml (+ training stack, commented)
```

The schema / serializer / scoring / eval / tool-loop paths need only the core simulator +
gymnasium + pydantic. The **training** stack (`transformers`, `peft`, `trl`, `datasets`,
`accelerate`) is required only for `slm.train` and for running a real local model.

## Committed artifacts (pipeline-validation scale)

> The sample dataset, datasheet and eval reports in `data/` and `reports/` predate dataset
> schema v2 (the compositional plan menu) and are regenerated in the next commit.


## Reproduce

Everything is deterministic under a seed (same seed → byte-identical JSONL).

```bash
# 1. Generate the committed dataset (pipeline-validation scale — ~5 min of Monte Carlo scoring).
python -m slm.generate_data --per-scenario 40 --n-trials 16 --seed 20 --workers 4 \
    --max-label-share 0.35 --out slm/data/sample_dataset.jsonl \
    --scale-note "pipeline-validation scale (not a publishable adviser)"

# 2. Produce the committed eval report (oracle / distilled-stub / tool-loop; no weights needed).
python slm/reports/run_eval.py

# 3. (Optional, needs the training stack) Smoke-fine-tune a ~135M model over ~50 examples —
#    also runnable as the slow test: pytest slm/tests/test_train_smoke_slow.py -m slow
python -m slm.train slm/configs/train_smoke.yaml

# 4. Validate the full-run / LLM-readiness configs without executing them.
python -m slm.train slm/configs/train_default_qlora.yaml --validate-only
python -m slm.train slm/configs/train_full_fsdp.yaml     --validate-only
```

### Apple-silicon run (`configs/train_mac_lora.yaml`)

Qwen2.5-0.5B-Instruct with LoRA (rank 16) in bf16 on MPS, one epoch over the full local dataset
(`--per-scenario 500 --n-trials 64 --max-label-share 0.35`: 2,833 decisions + 48 refusals, ~80 min
to generate with 14 workers). Training took 26 min on an M5 Pro (loss 3.64 -> 0.09). Evaluated with
`--adviser hf --seed 777` (60 held-out households per condition, 16 trials) —
`reports/adviser_eval_mac_lora.json`:

| Adviser | Held-out seeds success | Recession success | Label agreement |
|---|---|---|---|
| Mac LoRA (0.5B) | 0.592 | 0.603 | 0.40 / 0.37 |
| always `max_pretax_401k` | 0.596 | 0.605 | 0.43 / 0.42 |
| always `max_roth_401k` | 0.574 | 0.590 | 0.18 / 0.17 |
| best planner heuristic | 0.574 | 0.590 | — |
| oracle (argmax) | 0.609 | 0.606 | — |

Parse rate and held-out refusal rate are both 1.00, so format and scope discipline transfer. **The
decision itself does not yet beat the majority lever**: the 0.5B model matches "always max the
pre-tax 401k", which on its own beats every planner heuristic, and it never answers
`no_plan_lever` (5-7% of held-out labels). Its rationale numbers are written without a simulator
in the loop, so numeric faithfulness is 0.08-0.13 — use the tool-loop (`advise.py`) when cited
numbers matter. Success rate also leaves little headroom (the oracle is 1.3 points above the
majority lever) because most label differences are in terminal wealth, not solvency. Next levers:
a larger base model or more epochs, more held-out households, and an outcome metric that weighs
terminal wealth.

### Full local run (out of session scope — documented, not executed here)

```bash
# Generate O(10^4-10^5) examples (Monte Carlo scoring dominates cost — use collect_data=False,
# modest trial counts for ranking, and workers for parallelism):
python -m slm.generate_data --per-scenario 4000 --n-trials 64 --seed 20 --workers 8 \
    --out slm/data/dataset.jsonl

# QLoRA-train the default SLM (Qwen2.5-7B-Instruct, Apache-2.0), then evaluate on held-out
# households + a held-out economy scenario and commit the report (not the weights):
python -m slm.train slm/configs/train_default_qlora.yaml
python -m slm.evaluate_adviser --seed 777 --out slm/reports/adviser_eval.json   # via slm.backends for a real model
```

## Model license

The default target `Qwen/Qwen2.5-7B-Instruct` is **Apache-2.0** (redistributable and
fine-tunable). The smoke target `HuggingFaceTB/SmolLM2-135M-Instruct` is **Apache-2.0**. Record the
license of any model you swap in here. **Weights are never committed** — only configs and reports,
plus a small representative dataset sample (< 5 MB). The datasheet records the generation seed,
simulator commit, config hash, and trial counts so any run is auditable and reproducible.

## Deferred

RL fine-tuning (GRPO with a Monte Carlo reward), DPO on the stored scored alternatives, multi-turn
advising dialogues, and RAG over tax documents. The schema already stores scored alternatives per
example, so DPO/GRPO can consume this data later without regeneration.
