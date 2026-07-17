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

Advice fidelity is capped by what the simulator models. Until Plans 14–15 land, the simulator
prices **no children and no healthcare** — the two biggest household expenses — so a model
distilled from it will be confidently wrong about them. Every dataset stamps the simulator commit
and config hash in its datasheet, so stale data is detectable. **Treat all pre-14/15 models as
pipeline-validation artifacts, not publishable advisers.** The committed dataset sample and eval
report in this directory are explicitly at *pipeline-validation scale*, not a production run.

## Pipeline

| Stage | Module | What it does |
|---|---|---|
| Schema | `schema.py` | Versioned dataset schema (`schema_version=1`, pydantic StrictModel). |
| Serialize | `serializer.py` | Household ↔ faithful natural-language text (round-trip tested). |
| Decisions | `strategies.py`, `candidates.py` | The plan-level lever vocabulary → executable baseline policies. |
| Score | `scoring.py` | Shared-seed Monte Carlo scoring of each candidate on a household. |
| Generate | `generate_data.py` | Seeded households → scored candidates → argmax label + counterfactual rationale + refusals → JSONL + datasheet. |
| Evaluate | `evaluate_adviser.py`, `faithfulness.py` | Execute the advised decision in the simulator; compare vs planner-grade heuristics; numeric-faithfulness + parse-rate + refusal metrics; oracle sanity check. |
| Train | `train.py` | Size-agnostic HF SFT (LoRA/QLoRA or full+FSDP) from one YAML `TrainConfig`. |
| Advise | `advise.py` | Draft → simulate → revise tool-loop; itself an `AdviserModel`. |
| Backends | `backends.py`, `adviser.py` | `AdviserModel` protocol + stub / HF / MLX / Anthropic-API implementations. |

## Teacher gating (why the DQN isn't used)

Per the protocol report
(`deepqlearning/reports/retirement_security/protocol_report.json`: `verdict_intelligent=false`,
`ci_does_not_overlap_best=false`), the trained DQN did **not** achieve CI-separated superiority
over the planner heuristics. A mediocre teacher silently caps the student, so the candidate set is
**heuristics + Roth/pre-tax levers only**, and each example's label is the candidate-grid argmax —
the DQN is excluded. If a future DQN beats the heuristics per that protocol, add it as a candidate.

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

* `slm/data/sample_dataset.jsonl` + `.datasheet.json` — 175 examples (160 decisions across the
  four household scenarios, 15 refusals), seed 20, 16 trials/candidate. Regeneration is
  byte-identical, including across `--workers` values.
* `slm/reports/adviser_eval.json` (produced by `slm/reports/run_eval.py`) — oracle vs
  distilled-stub vs tool-loop on 32 held-out households (seed 777) plus the held-out
  `recession` economy, with per-condition heuristic baselines, parse/faithfulness/refusal rates.

Two honest caveats, both artifacts of pipeline-validation scale:

1. **Label skew.** At 16 trials nearly every candidate keeps these easy households solvent
   (success-rate ties), so the argmax falls through to the median-terminal-wealth tie-break and
   `max_roth_401k` wins 151/160 decision examples. A production dataset needs harder households
   (post-14/15 expenses), more trials, and scenario spreads wide enough to differentiate levers.
2. **Cross-seed faithfulness.** The eval harness re-scores households on its own seeds, so the
   numeric-faithfulness gate demands that cited numbers reproduce across independent Monte Carlo
   draws. At 16 trials the noise on dollar medians exceeds the strict 2% tolerance, which is why
   the tool-loop (whose numbers come from its own live run and are faithful-by-construction to
   it — unit-tested) scores low here. At production trial counts (≥64) the gate tightens into
   the intended anti-hallucination check.

## Reproduce

Everything is deterministic under a seed (same seed → byte-identical JSONL).

```bash
# 1. Generate the committed dataset (pipeline-validation scale — ~2 min of Monte Carlo scoring).
python -m slm.generate_data --scenarios basic,high_earner,low_earner,mid_career \
    --per-scenario 40 --n-trials 16 --seed 20 --workers 4 \
    --out slm/data/sample_dataset.jsonl \
    --scale-note "pipeline-validation scale (pre-Plans-14/15; not a publishable adviser)"

# 2. Produce the committed eval report (oracle / distilled-stub / tool-loop; no weights needed).
python slm/reports/run_eval.py

# 3. (Optional, needs the training stack) Smoke-fine-tune a ~135M model over ~50 examples —
#    also runnable as the slow test: pytest slm/tests/test_train_smoke_slow.py -m slow
python -m slm.train slm/configs/train_smoke.yaml

# 4. Validate the full-run / LLM-readiness configs without executing them.
python -m slm.train slm/configs/train_default_qlora.yaml --validate-only
python -m slm.train slm/configs/train_full_fsdp.yaml     --validate-only
```

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
