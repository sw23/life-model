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

## Committed artifacts

* `data/sample_dataset.jsonl` + `.datasheet.json` — pipeline-validation scale: 240 decisions (40
  households per scenario, adaptive 8-32 trials, 35% label cap) + 48 refusals, seed 20. Basis 159
  clear / 80 equivalent / 1 no-viable.
* `reports/adviser_eval.json` + `adviser_eval_summary.txt` — every adviser on the same 72 held-out
  households (seed 777, 12 per scenario) under held-out seeds and the held-out `recession`
  overlay, 32 shared trials per plan, produced by `reports/run_eval.py`.

The local training set (`data/dataset.jsonl`, gitignored, regenerable byte-for-byte): 700
households per scenario, adaptive 16-64 trials, 4,200 decisions + 48 refusals. Basis 3,122 clear
(74%) / 1,065 equivalent (25%) / 13 no-viable (0.3%); the most common label is the default plan at
18%. Per-scenario mean best-plan success is 0.92-0.99 except `low_earner` (0.69).

## Results

Normalized regret = (best scored plan's return − the answer's) / (best − worst), averaged over
households; "vs best constant" is the paired regret advantage over the best single answer given to
every household (`save10_pretax_claimret_conventional`, mean regret 2.51 on held-out seeds), with
a household-bootstrap 95% CI (* = above zero).

| Adviser | Normalized regret (seeds / recession) | vs best constant (seeds) | Top-set agreement | Parse | Refusal |
|---|---|---|---|---|---|
| oracle (best scored plan) | 0.000 / 0.000 | +2.51* | 1.00 | 1.00 | 1.00 |
| **tabular** (gradient-boosted trees on the household fields) | **0.142 / 0.138** | **+1.90*** | 0.78 | 1.00 | 1.00 |
| **tool loop** (fixed stub + simulator in the loop) | 0.225 / 0.241 | +1.13* | 0.75 | 1.00 | 1.00 |
| fixed stub (`save0_roth_claim70_conventional`) | 0.351 / 0.324 | −1.45 | 0.64 | 1.00 | 1.00 |
| SFT, Qwen2.5-1.5B LoRA | 0.387 / 0.321 | −1.16 | 0.39 | 1.00 | 1.00 |
| SFT + DPO, Qwen2.5-1.5B LoRA | 0.379 / 0.391 | −1.29 | 0.60 | 1.00 | 0.83 |
| zero-shot Qwen2.5-1.5B | 0.524 / 0.383 | −1.47 | 0.00 | 0.99 | 0.12 |
| zero-shot Qwen2.5-0.5B | 0.387 / 0.321 (never parses; runs the default plan) | −1.16 | 0.00 | 0.00 | 0.00 |

What this says:

1. **The labels carry learnable signal.** A small tabular model reading the same facts the language
   model reads cuts regret by more than half against every constant answer, in both conditions.
   The world (Social Security, match, balances, overlays), the evidence-backed labels and the plan
   menu do what they were meant to: the decision now depends on the household.
2. **The simulator in the loop works.** The tool loop starts from a fixed, mediocre plan and lands
   within noise of the best plan for 75% of households.
3. **The fine-tuned 1.5B model does not beat a constant answer.** SFT converged to the default plan
   for every household (its regret is identical to always-default); DPO on decision pairs moved
   answers around but not toward lower regret, and cost some refusal discipline. Format and scope
   discipline transfer (parse 1.00, SFT refusal 1.00). The hosted upper bound (`--advisers api`)
   was not run: no API key in the run environment.

How the SFT runs failed, so the next run does not repeat it:

* **Full-text loss** (the default before this change): the 1.5B model emitted one constant plan,
  switching which one between checkpoints. Training only on the answer (`completion_only_loss`)
  did not change that.
* **The plan token is a few percent of the answer.** Before training, Qwen2.5-1.5B puts ~80% on
  `save1…` after `DECISION: save`; after 100 unweighted steps it was still ~60%. The rationale's
  simulator numbers dominate the loss. `decision_weight: 10` fixed the prior (the model learned
  the majority answer) but over 500 steps it never started conditioning on the household, and
  the regret-proxy early stop kept the always-default adapter.
* **What carries the signal is non-linear.** A spending-share threshold rule predicts the savings
  lever 78% of the time against 75% for the majority, and the scenario's most common label is no
  better than the default plan; the tabular model's gain comes from interactions across fields.
  Roughly 4,000 examples is little data for a 1.5B model to learn that from text.
* **Full-answer DPO on MPS exhausted unified memory** (~37 GB wired, 70 s/step) and was stopped;
  decision-only pairs with `PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.5` and gradient checkpointing ran
  at ~18 s/step under the cap.

Next levers, in the order the evidence points: much more data (generation, not training, is the
bottleneck: ~40 core-seconds per household), a decision-first target (decide, then a short
rationale, or let the tool loop write the rationale), the tabular adviser's prediction as a tool
the language model can call, and a larger base model on a CUDA machine
(`train_default_qlora.yaml`, not run here).

## Reproduce

Everything is deterministic under a seed (same seed → byte-identical JSONL).

```bash
# 1. The committed sample (pipeline-validation scale, ~15 min on 3 workers).
python -m slm.generate_data --per-scenario 40 --n-trials 32 --min-trials 8 --seed 20 --workers 3 \
    --max-label-share 0.35 --out slm/data/sample_dataset.jsonl \
    --scale-note "pipeline-validation scale (not a publishable adviser)"

# 2. The local training set (~4 h on 10 workers).
python -m slm.generate_data --per-scenario 700 --n-trials 64 --min-trials 16 --seed 20 --workers 10 \
    --max-label-share 0.35 --out slm/data/dataset.jsonl

# A serializer change needs no new simulation: re-render the stored profiles.
python -m slm.generate_data --rerender slm/data/dataset.jsonl --out /tmp/dataset.jsonl

# 3. SFT then DPO on Apple silicon (Qwen2.5-1.5B-Instruct, LoRA r16). Cap MPS memory for DPO.
python -m slm.train slm/configs/train_mac_lora.yaml
PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.5 PYTORCH_MPS_LOW_WATERMARK_RATIO=0.4 \
    python -m slm.train slm/configs/train_mac_dpo.yaml

# 4. The committed report (needs scikit-learn for the tabular adviser; ~2.5 h, mostly generation).
PYTHONPATH=src:. python slm/reports/run_eval.py --workers 8 --advisers "oracle,stub,tool_loop,tabular,api,\
hf:zero_shot_0.5b=Qwen/Qwen2.5-0.5B-Instruct,hf:zero_shot_1.5b=Qwen/Qwen2.5-1.5B-Instruct,\
hf:sft_1.5b=Qwen/Qwen2.5-1.5B-Instruct@slm/checkpoints/mac_lora/best,\
hf:sft_dpo_1.5b=Qwen/Qwen2.5-1.5B-Instruct@slm/checkpoints/mac_lora/best+slm/checkpoints/mac_dpo/best"

# 5. Smoke-fine-tune a ~135M model, and validate the CUDA / LLM-readiness configs.
python -m slm.train slm/configs/train_smoke.yaml
python -m slm.train slm/configs/train_default_qlora.yaml --validate-only
python -m slm.train slm/configs/train_full_fsdp.yaml     --validate-only
```

Training writes `<output_dir>/best` (the adapter with the lowest validation regret proxy: answers
on held-out training households scored against their stored Monte Carlo results, no simulation)
and a `train_config.json` with the proxy history.

## Model license

The default target `Qwen/Qwen2.5-7B-Instruct` and the Mac target `Qwen/Qwen2.5-1.5B-Instruct` are
**Apache-2.0** (redistributable and fine-tunable; Qwen2.5-3B is not — it carries the Qwen research
license). The smoke target `HuggingFaceTB/SmolLM2-135M-Instruct` is **Apache-2.0**. Record the
license of any model you swap in here. **Weights are never committed** — only configs and reports,
plus a small representative dataset sample (< 5 MB). The datasheet records the generation seed,
simulator commit, config hash, and trial counts so any run is auditable and reproducible.

## Deferred

RL fine-tuning (GRPO with a Monte Carlo reward), multi-turn advising dialogues, and RAG over tax
documents. DPO on the stored scored alternatives is implemented (`objective: dpo`); GRPO can
consume the same stored alternatives without regeneration.
