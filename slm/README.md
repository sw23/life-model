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

Advice fidelity is capped by what the **pipeline actually scores**. Scored households now include
child dependents (age-banded childcare / school / college costs) and healthcare (the age-related
medical-cost curve plus Medicare premiums from the eligibility age), so the levers face the two
biggest lifetime household expenses rather than a bare single-earner. What is still *not* priced
here caps fidelity further: no spouse/second earner, no explicit housing purchase, and children are
drawn synthetically (0–3 dependents with plausible ages) rather than from real household
demographics. Every dataset stamps the simulator commit and config hash in its datasheet, so data
generated against an older configuration is detectable after the fact. **Treat any model distilled
from a pipeline-validation dataset as a pipeline-validation artifact, not a publishable adviser.**
The committed dataset sample and eval report in this directory are explicitly at
*pipeline-validation scale*, not a production run.

## Pipeline

| Stage | Module | What it does |
|---|---|---|
| Schema | `schema.py` | Versioned dataset schema (`schema_version=1`, pydantic StrictModel). |
| Serialize | `serializer.py` | Household ↔ faithful natural-language text (round-trip tested). |
| Decisions | `strategies.py`, `candidates.py` | The plan-level lever vocabulary → executable baseline policies. |
| Score | `scoring.py` | Shared-seed Monte Carlo scoring of each candidate on a household. |
| Households | `households.py` | SLM household distributions: the RL scenarios plus older households, varied economies, children budgeted inside spending. |
| Generate | `generate_data.py` | Seeded households → scored candidates → label (argmax or `no_plan_lever`) + basis-aware rationale + refusals → optional label cap → JSONL + datasheet. |
| Evaluate | `evaluate_adviser.py`, `faithfulness.py` | Execute the advised decision in the simulator; compare vs planner-grade heuristics; numeric-faithfulness + parse-rate + refusal metrics; oracle sanity check. |
| Train | `train.py` | Size-agnostic HF SFT (LoRA/QLoRA or full+FSDP) from one YAML `TrainConfig`. |
| Advise | `advise.py` | Draft → simulate → revise tool-loop; itself an `AdviserModel`. |
| Backends | `backends.py`, `adviser.py` | `AdviserModel` protocol + stub / HF / MLX / Anthropic-API implementations. |

## Households and labels

`households.py` widens the RL environment's four scenarios (ages 19–38) with `late_career` (46–54)
and `pre_retiree` (54–60), draws each household's economy (about half the stochastic baseline, the
rest boom / high-inflation / deflation / conservative / aggressive; `recession` is held out for
evaluation), and budgets children *inside* the sampled spending (child costs are carved out of it,
capped at half) instead of stacking them on a childless budget. Stacking made a third of households
insolvent under every strategy.

Each example records a `decision_basis` (`scoring.decision_basis`):

* **clear** — the argmax beats the runner-up's success rate by two standard errors and two trials,
  or, when success rates tie, its median terminal wealth by 10%;
* **equivalent** — the top options are within Monte Carlo noise; the rationale says so;
* **no_viable** — even the best lever is solvent in at most 10% of trials. The label is then
  `no_plan_lever` ("no menu strategy is sufficient; the gap is spending versus income") rather than
  the least-bad strategy. The eval harness executes it as the default plan
  (`contribution_waterfall`), so abstaining never beats a lever that helps.

`--max-label-share` caps any one label (dropping `equivalent` examples first). Refusals cover 8
out-of-scope topics × 6 phrasings with rotating wording; the eval uses 3 held-out phrasings.

## Teacher gating (why no RL policy is a teacher)

Per the committed protocol reports (`deepqlearning/reports/retirement_security/` for DQN and
`retirement_security_ppo/` for PPO, both `verdict_intelligent=false` at the committed seed 0), no
learned policy achieved CI-separated superiority over the planner heuristics at the seed fixed in
advance. A mediocre teacher silently caps the student, so the candidate set is **heuristics +
Roth/pre-tax levers only**, and each example's label is the candidate-grid argmax. PPO seed 1 does
clear the bar (`deepqlearning/reports/algorithm_sweep.txt`); promoting it would mean picking a seed
after seeing results, which the seed convention exists to prevent. A policy that passes at its
pre-registered seed should be added as a candidate.

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

* `slm/data/sample_dataset.jsonl` + `.datasheet.json` — 281 examples (233 decisions across the
  six household scenarios after a 35% label cap, 48 refusals), seed 20, 16 trials/candidate.
  Labels: `max_pretax_401k` 81, `max_roth_401k` 47, `age_glide` 35, `no_plan_lever` 27,
  `contribution_waterfall` 21, `four_percent_drawdown` 20, `emergency_fund_first` 2; basis 89
  clear / 117 equivalent / 27 no-viable. Regeneration is byte-identical, including across
  `--workers` values.
* `slm/reports/adviser_eval.json` (produced by `slm/reports/run_eval.py`) — oracle vs
  distilled-stub vs tool-loop on 32 held-out households (seed 777) plus the held-out
  `recession` economy, with per-condition heuristic baselines, parse/faithfulness/refusal rates.

Two honest caveats:

1. **Many near-ties.** About half the labels are `equivalent`: on many households the levers
   (especially pre-tax vs Roth, both maxing the same 402(g) room) land within Monte Carlo noise.
   The rationale says so instead of overstating the winner. `emergency_fund_first` rarely wins
   outright because it scores identically to `contribution_waterfall` whenever the 6-month cushion
   is already met (they are the RL planner baselines and are left as-is).
2. **Cross-seed faithfulness.** The eval harness re-scores households on its own seeds, so the
   numeric-faithfulness gate demands that cited numbers reproduce across independent Monte Carlo
   draws. At 16 trials the noise on dollar medians exceeds the strict 2% tolerance, which is why
   the tool-loop (whose numbers come from its own live run and are faithful-by-construction to
   it — unit-tested) scores low here. At production trial counts (≥64) the gate tightens into
   the intended anti-hallucination check.

An earlier version of this dataset was 81% `max_roth_401k`. The cause was in the RL action layer,
not the data: pre-tax 401k transfers were not deducted (taxed going in and coming out) and 401k
transfers were uncapped. Both are fixed; see `deepqlearning/envs/financial/actions.py`.

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
