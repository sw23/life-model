# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Size-agnostic SFT entrypoint driven by one YAML config.

The same code path fine-tunes a ~100M smoke model on a laptop and a multi-billion-parameter model
on a cluster — only the :class:`TrainConfig` YAML and the launcher differ (an intentional
LLM-readiness contract). The canonical backend is HF ``transformers`` + ``peft`` + ``trl``
(``SFTTrainer``); the transformers stack is imported lazily inside :func:`train`, so importing
this module (for config validation and data collation) never pulls in torch/transformers and CI
can run those parts with no weights.

Chat formatting uses the tokenizer's *own* chat template — no hardcoded prompt format — which is
exactly what keeps the generated data reusable across model families and sizes.

The ``lora`` vs ``full_finetune`` choice and the opaque ``fsdp``/``accelerate`` passthrough blocks
are validated here (mutually exclusive fine-tune mode; passthrough is free-form) but the FSDP path
is *validated, not executed*, in CI.

Quality controls (all CI-testable without weights):

* **Household split.** ``validation_fraction`` holds out decision examples by a hash of their id
  (one example = one household), so validation households never appear in training.
* **Label weighting.** ``clear_weight`` repeats ``clear`` examples; ``drop_equivalent`` removes
  examples whose label is a no-evidence default.
* **Regret-proxy early stopping.** Every ``regret_eval_steps`` the model answers
  ``regret_eval_examples`` validation households greedily; each answer's regret is read off the
  example's stored scores (an additive one-lever estimate for plans the search did not score). The
  best adapter is kept in ``<output_dir>/best`` and training stops after
  ``early_stopping_patience`` evaluations without improvement — no simulator in the loop.
* **DPO.** ``objective: dpo`` trains on preference pairs from the stored alternatives (the label's
  answer over the worst plan outside the top set), starting from ``init_adapter`` merged into the
  base model so the SFT model is the reference policy.
"""

import argparse
import hashlib
import json
from typing import Any

import yaml
from pydantic import Field, model_validator

from life_model.config.models import StrictModel

from .prompts import format_decision_answer, parse_decision
from .rationales import build_rationale
from .schema import AdviceExample
from .strategies import DEFAULT_PLAN, DIMENSIONS, NO_LEVER, Plan


class LoraSettings(StrictModel):
    """LoRA/QLoRA adapter hyperparameters."""

    rank: int = Field(default=16, ge=1)
    alpha: int = Field(default=32, ge=1)
    dropout: float = Field(default=0.05, ge=0.0, le=1.0)
    # Attention/MLP projection names common to Llama/Qwen/Mistral-family models.
    target_modules: list[str] = Field(
        default_factory=lambda: ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    )


class TrainConfig(StrictModel):
    """One-file training configuration. Size-agnostic: the same fields drive smoke and full runs.

    Exactly one fine-tuning mode must be selected: ``lora`` (adapter) OR ``full_finetune: true``.
    """

    model_id: str
    dataset_path: str
    output_dir: str = "slm/checkpoints/run"

    # Fine-tuning mode — exactly one of these (validated below).
    lora: LoraSettings | None = LoraSettings()
    full_finetune: bool = False

    # Optimization.
    seq_len: int = Field(default=2048, ge=8)
    epochs: float = Field(default=1.0, gt=0.0)
    per_device_batch_size: int = Field(default=1, ge=1)
    grad_accum: int = Field(default=8, ge=1)
    learning_rate: float = Field(default=2e-4, gt=0.0)
    warmup_ratio: float = Field(default=0.03, ge=0.0, le=1.0)
    weight_decay: float = Field(default=0.0, ge=0.0)
    gradient_checkpointing: bool = False
    packing: bool = False
    seed: int = 0
    max_examples: int | None = Field(default=None, ge=1)

    # Precision / attention / quantization.
    precision: str = Field(default="bf16", pattern="^(bf16|fp16|fp32)$")
    attn_implementation: str = "eager"
    quantization: str | None = Field(default=None, pattern="^(4bit|8bit)$")

    # Opaque passthrough blocks handed to accelerate / FSDP unchanged (the LLM-readiness knob).
    # Validated only as free-form mappings; never introspected by this module.
    fsdp: dict[str, Any] = Field(default_factory=dict)
    accelerate: dict[str, Any] = Field(default_factory=dict)
    report_to: str = "none"

    # Objective and data quality controls (see the module docstring).
    objective: str = Field(default="sft", pattern="^(sft|dpo)$")
    init_adapter: str | None = None
    dpo_beta: float = Field(default=0.1, gt=0.0)
    # Preference pairs over the decision line only ("DECISION: <plan>"), not the full answers: the
    # preference is about the plan, and dropping ~215 rationale tokens per completion keeps an MPS
    # run from exhausting unified memory (full-answer DPO on a 1.5B model hit ~37 GB wired).
    dpo_decision_only: bool = False
    validation_fraction: float = Field(default=0.0, ge=0.0, lt=1.0)
    clear_weight: int = Field(default=1, ge=1)
    drop_equivalent: bool = False
    regret_eval_examples: int = Field(default=0, ge=0)
    regret_eval_steps: int = Field(default=200, ge=1)
    early_stopping_patience: int | None = Field(default=None, ge=1)
    max_new_tokens: int = Field(default=320, ge=8)
    # Train on the assistant answer only (prompt/completion data). Off, the loss covers the whole
    # chat text, ~800 tokens of it an identical system prompt and menu, and the plan token is a few
    # dozen tokens of the remainder: a 1.5B run collapsed to one constant plan that way.
    completion_only_loss: bool = True
    # Loss multiplier on the decision line (the completion tokens through the first newline). The
    # plan token is ~12 of ~215 answer tokens and the rest is rationale numbers the model cannot know
    # without the simulator, so unweighted SFT barely moves the decision off the base model's prior
    # (Qwen2.5-1.5B puts ~80% on "save1..." before training). Requires completion_only_loss.
    decision_weight: float = Field(default=1.0, ge=1.0)

    @model_validator(mode="after")
    def _exactly_one_mode(self) -> "TrainConfig":
        if self.full_finetune and self.lora is not None:
            raise ValueError("Set either `lora` OR `full_finetune: true`, not both.")
        if not self.full_finetune and self.lora is None:
            raise ValueError("Set a fine-tuning mode: `lora` settings OR `full_finetune: true`.")
        return self

    @model_validator(mode="after")
    def _dpo_needs_lora(self) -> "TrainConfig":
        if self.objective == "dpo" and self.lora is None:
            raise ValueError("objective: dpo trains a LoRA adapter; set `lora`.")
        return self

    @classmethod
    def from_yaml(cls, path: str) -> "TrainConfig":
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Data collation — CI-testable without a tokenizer.
# ---------------------------------------------------------------------------


def load_chat_examples(path: str, max_examples: int | None = None) -> list[list[dict[str, str]]]:
    """Load a dataset JSONL into per-example chat message lists (schema-validated).

    Each row is validated against :class:`~slm.schema.AdviceExample`, then reduced to its
    ``messages`` (list of ``{"role", "content"}``) — the tokenizer applies the chat template at
    train time. Both decision and refusal rows are included, so scope discipline is trained.
    """
    out: list[list[dict[str, str]]] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            example = AdviceExample.model_validate_json(line)
            out.append([{"role": m.role, "content": m.content} for m in example.messages])
            if max_examples is not None and len(out) >= max_examples:
                break
    return out


def load_rows(path: str, max_examples: int | None = None) -> list[AdviceExample]:
    """Load and schema-validate every row of a dataset JSONL."""
    rows: list[AdviceExample] = []
    with open(path) as fh:
        for line in fh:
            if line.strip():
                rows.append(AdviceExample.model_validate_json(line))
                if max_examples is not None and len(rows) >= max_examples:
                    break
    return rows


def is_validation(example_id: str, fraction: float) -> bool:
    """Deterministic household-level split: a stable hash of the example id below ``fraction``."""
    if fraction <= 0:
        return False
    bucket = int(hashlib.sha256(example_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return bucket < fraction


def split_rows(
    rows: list[AdviceExample], fraction: float, clear_weight: int = 1, drop_equivalent: bool = False
) -> tuple[list[AdviceExample], list[AdviceExample]]:
    """(train, validation) rows. Refusals always train; decision rows split by household; the
    training side then drops ``equivalent`` labels (if asked) and repeats ``clear`` ones."""
    train_rows: list[AdviceExample] = []
    val_rows: list[AdviceExample] = []
    for row in rows:
        if row.kind == "decision" and is_validation(row.example_id, fraction):
            val_rows.append(row)
            continue
        if row.kind == "decision" and drop_equivalent and row.decision_basis == "equivalent":
            continue
        repeats = clear_weight if row.kind == "decision" and row.decision_basis == "clear" else 1
        train_rows.extend([row] * repeats)
    return train_rows, val_rows


def proxy_regret(answer: str, row: AdviceExample) -> float:
    """Normalized regret of ``answer`` on ``row``, read off its stored scores (no simulation).

    The executed plan is the answer's plan (the default plan for ``no_plan_lever`` or an unparseable
    answer). A plan the search did not score is estimated additively: the default plan's return
    plus each changed lever's stored one-lever gain over the default. Regret is the best stored
    return minus the executed return, divided by the best-to-worst span (0 when all tie).
    """
    by_name = {c.decision: c for c in row.scored_alternatives}
    best = max(c.mean_return for c in row.scored_alternatives)
    worst = min(c.mean_return for c in row.scored_alternatives)
    decision = parse_decision(answer)
    executed = DEFAULT_PLAN.name if decision in (None, NO_LEVER) else decision
    if executed in by_name:
        value = by_name[executed].mean_return
    elif DEFAULT_PLAN.name in by_name and (plan := Plan.parse(executed)) is not None:
        value = by_name[DEFAULT_PLAN.name].mean_return
        for dim in DIMENSIONS:
            variant = DEFAULT_PLAN.with_value(dim.name, getattr(plan, dim.name)).name
            if variant != DEFAULT_PLAN.name and variant in by_name:
                value += by_name[variant].gain_vs_default
    else:
        value = worst
    span = best - worst
    return float(max(0.0, best - value) / span) if span > 1e-9 else 0.0


def dpo_pairs(rows: list[AdviceExample], decision_only: bool = False) -> list[dict[str, Any]]:
    """Conversational preference pairs: the label's answer over the worst-returning plan that is
    outside the top set (worse than the best beyond noise). Households with no such plan, refusals
    and no-viable rows give no pair."""
    pairs = []
    for row in rows:
        if row.kind != "decision" or row.chosen_decision == NO_LEVER:
            continue
        losers = [c for c in row.scored_alternatives if not c.in_top_set]
        if not losers:
            continue
        rejected = min(losers, key=lambda c: c.mean_return)
        prompt = [{"role": m.role, "content": m.content} for m in row.messages if m.role != "assistant"]
        chosen = [m for m in row.messages if m.role == "assistant"][-1].content
        if decision_only:
            pairs.append(
                {
                    "prompt": prompt,
                    "chosen": [{"role": "assistant", "content": f"DECISION: {row.chosen_decision}"}],
                    "rejected": [{"role": "assistant", "content": f"DECISION: {rejected.decision}"}],
                }
            )
            continue
        pairs.append(
            {
                "prompt": prompt,
                "chosen": [{"role": "assistant", "content": chosen}],
                "rejected": [
                    {
                        "role": "assistant",
                        "content": format_decision_answer(
                            rejected.decision, build_rationale(row.scored_alternatives, rejected.decision)
                        ),
                    }
                ],
            }
        )
    return pairs


def render_chat_texts(examples: list[list[dict[str, str]]], apply_chat_template) -> list[str]:
    """Render each example's messages to a single training string via a chat-template callable.

    ``apply_chat_template`` has the ``tokenizer.apply_chat_template`` signature
    (``messages, tokenize=False, ...``); passing a stub makes collation testable without weights.
    """
    return [apply_chat_template(messages, tokenize=False) for messages in examples]


# ---------------------------------------------------------------------------
# HF backend — lazily imported; never touched by CI.
# ---------------------------------------------------------------------------


def _torch_dtype(precision: str):
    import torch

    return {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[precision]


def _messages(row: AdviceExample) -> list[dict[str, str]]:
    return [{"role": m.role, "content": m.content} for m in row.messages]


def prompt_completion(row: AdviceExample) -> dict[str, list[dict[str, str]]]:
    """A conversational prompt/completion pair: every turn before the final assistant answer, and that answer."""
    messages = _messages(row)
    return {"prompt": messages[:-1], "completion": messages[-1:]}


def decision_loss_weights(labels, newline_id: int, weight: float):
    """Per-token loss weights for shifted ``labels`` (-100 = ignored): ``weight`` on each sequence's
    decision line (its first labeled token through the first newline), 1 on the rest, 0 on ignored."""
    import torch

    weights = (labels != -100).to(torch.float32)
    if weight == 1.0:
        return weights
    for i in range(labels.size(0)):
        labeled = (labels[i] != -100).nonzero()
        if labeled.numel() == 0:
            continue
        start = int(labeled[0])
        newline = (labels[i, start:] == newline_id).nonzero()
        end = start + (int(newline[0]) + 1 if newline.numel() else min(16, labels.size(1) - start))
        weights[i, start:end] *= weight
    return weights


def _decision_weighted_trainer(base_cls, newline_id: int, weight: float):
    """``base_cls`` (an SFTTrainer) with a cross-entropy loss up-weighting the decision line."""
    import torch
    import torch.nn.functional as F

    class DecisionWeightedTrainer(base_cls):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # The custom loss ignores num_items_in_batch, so the Trainer must scale for accumulation.
            self.model_accepts_loss_kwargs = False

        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            labels = inputs["labels"]
            model_inputs = {k: v for k, v in inputs.items() if k in ("input_ids", "attention_mask")}
            outputs = model(**model_inputs)
            logits = outputs.logits[:, :-1, :].float()
            targets = labels[:, 1:]
            weights = decision_loss_weights(targets, newline_id, weight)
            token_loss = F.cross_entropy(
                logits.reshape(-1, logits.size(-1)), targets.clamp(min=0).reshape(-1), reduction="none"
            ).view_as(targets)
            loss = (token_loss * weights).sum() / weights.sum().clamp(min=torch.finfo(torch.float32).eps)
            return (loss, outputs) if return_outputs else loss

    return DecisionWeightedTrainer


def _regret_callback(config: TrainConfig, tokenizer, val_rows: list[AdviceExample]):
    """A TrainerCallback that early-stops on the validation regret proxy and keeps the best adapter."""
    import torch
    from transformers import TrainerCallback

    rows = [r for r in val_rows if r.kind == "decision"][: config.regret_eval_examples]

    class RegretCallback(TrainerCallback):
        def __init__(self):
            self.best = float("inf")
            self.bad_evals = 0
            self.history: list[dict[str, float]] = []

        def _evaluate(self, model) -> float:
            was_training = model.training
            model.eval()
            regrets = []
            with torch.no_grad():
                for row in rows:
                    prompt = [m for m in _messages(row) if m["role"] != "assistant"]
                    inputs = tokenizer.apply_chat_template(
                        prompt, add_generation_prompt=True, return_tensors="pt", return_dict=True
                    ).to(model.device)
                    out = model.generate(
                        **inputs,
                        max_new_tokens=config.max_new_tokens,
                        do_sample=False,
                        pad_token_id=tokenizer.pad_token_id,
                    )
                    answer = tokenizer.decode(out[0][inputs["input_ids"].shape[-1] :], skip_special_tokens=True)
                    regrets.append(proxy_regret(answer, row))
            if was_training:
                model.train()
            return float(sum(regrets) / max(len(regrets), 1))

        def on_step_end(self, args, state, control, model=None, **kwargs):
            if not rows or state.global_step % config.regret_eval_steps != 0:
                return control
            regret = self._evaluate(model)
            self.history.append({"step": state.global_step, "proxy_regret": regret})
            print(f"[regret-proxy] step {state.global_step}: {regret:.4f} (best {self.best:.4f})")
            if regret < self.best - 1e-6:
                self.best = regret
                self.bad_evals = 0
                model.save_pretrained(f"{config.output_dir}/best")
                tokenizer.save_pretrained(f"{config.output_dir}/best")
            else:
                self.bad_evals += 1
                if config.early_stopping_patience is not None and self.bad_evals >= config.early_stopping_patience:
                    control.should_training_stop = True
            return control

    return RegretCallback()


def _load_model(config: TrainConfig):
    """Base model (quantized if configured), with ``init_adapter`` merged in when set."""
    from transformers import AutoModelForCausalLM

    model_kwargs: dict[str, Any] = {
        "attn_implementation": config.attn_implementation,
        "torch_dtype": _torch_dtype(config.precision),
    }
    if config.quantization is not None:
        from transformers import BitsAndBytesConfig

        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=config.quantization == "4bit",
            load_in_8bit=config.quantization == "8bit",
            bnb_4bit_compute_dtype=_torch_dtype(config.precision),
            bnb_4bit_quant_type="nf4",
        )
    model = AutoModelForCausalLM.from_pretrained(config.model_id, **model_kwargs)
    if config.init_adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, config.init_adapter).merge_and_unload()
    return model


def train(config: TrainConfig):
    """Fine-tune per ``config`` (SFT or DPO) using the HF backend and save the model/adapter.

    Lazy-imports transformers/peft/trl/datasets so this file imports cleanly without them. Returns
    the output directory. Intended to be exercised by the slow/manual smoke test and by real runs.
    """
    import inspect

    import torch  # noqa: F401
    from datasets import Dataset
    from transformers import AutoTokenizer

    rows = load_rows(config.dataset_path, config.max_examples)
    if not rows:
        raise ValueError(f"No training examples found in {config.dataset_path}")
    train_rows, val_rows = split_rows(rows, config.validation_fraction, config.clear_weight, config.drop_equivalent)

    tokenizer = AutoTokenizer.from_pretrained(config.model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = _load_model(config)

    peft_config = None
    if config.lora is not None:
        from peft import LoraConfig

        peft_config = LoraConfig(
            r=config.lora.rank,
            lora_alpha=config.lora.alpha,
            lora_dropout=config.lora.dropout,
            target_modules=config.lora.target_modules,
            task_type="CAUSAL_LM",
        )

    common: dict[str, Any] = {
        "output_dir": config.output_dir,
        "num_train_epochs": config.epochs,
        "per_device_train_batch_size": config.per_device_batch_size,
        "gradient_accumulation_steps": config.grad_accum,
        "learning_rate": config.learning_rate,
        "warmup_ratio": config.warmup_ratio,
        "weight_decay": config.weight_decay,
        "gradient_checkpointing": config.gradient_checkpointing,
        "seed": config.seed,
        "report_to": config.report_to,
        "save_strategy": "epoch",
    }
    callbacks = []
    regret_cb = None
    if config.regret_eval_examples and val_rows:
        regret_cb = _regret_callback(config, tokenizer, val_rows)
        callbacks.append(regret_cb)

    if config.objective == "dpo":
        from trl import DPOConfig, DPOTrainer

        pairs = dpo_pairs(train_rows, decision_only=config.dpo_decision_only)
        if not pairs:
            raise ValueError("No DPO preference pairs in the training rows")
        dataset = Dataset.from_list(pairs)
        dpo_kwargs = {**common, "beta": config.dpo_beta, "max_length": config.seq_len}
        dpo_params = set(inspect.signature(DPOConfig.__init__).parameters)
        trainer = DPOTrainer(
            model=model,
            args=DPOConfig(**{k: v for k, v in dpo_kwargs.items() if k in dpo_params}),
            train_dataset=dataset,
            processing_class=tokenizer,
            peft_config=peft_config,
            callbacks=callbacks,
        )
        n_train = len(pairs)
    else:
        from trl import SFTConfig, SFTTrainer

        if config.completion_only_loss:
            dataset = Dataset.from_list([prompt_completion(r) for r in train_rows])
            sft_kwargs = {**common, "packing": config.packing, "completion_only_loss": True}
        else:
            texts = render_chat_texts([_messages(r) for r in train_rows], tokenizer.apply_chat_template)
            dataset = Dataset.from_dict({"text": texts})
            sft_kwargs = {**common, "packing": config.packing, "dataset_text_field": "text"}
        # trl renamed max_seq_length -> max_length in newer releases; support both so the same code
        # path runs across the version range in requirements-slm.txt.
        sft_params = set(inspect.signature(SFTConfig.__init__).parameters)
        sft_kwargs["max_length" if "max_length" in sft_params else "max_seq_length"] = config.seq_len
        trainer_cls = SFTTrainer
        if config.decision_weight > 1.0 and config.completion_only_loss:
            newline_id = tokenizer.convert_tokens_to_ids(tokenizer.tokenize("\n")[0])
            trainer_cls = _decision_weighted_trainer(SFTTrainer, newline_id, config.decision_weight)
        trainer = trainer_cls(
            model=model,
            args=SFTConfig(**sft_kwargs),
            train_dataset=dataset,
            peft_config=peft_config,
            callbacks=callbacks,
        )
        n_train = len(dataset)

    print(f"Training {config.objective}: {n_train} train rows, {len(val_rows)} validation households")
    trainer.train()
    trainer.save_model(config.output_dir)
    tokenizer.save_pretrained(config.output_dir)

    summary = {
        "config": config.model_dump(mode="json"),
        "n_train_rows": n_train,
        "n_validation_households": len(val_rows),
        "regret_proxy_history": regret_cb.history if regret_cb is not None else [],
        "best_regret_proxy": regret_cb.best if regret_cb is not None and regret_cb.history else None,
    }
    with open(f"{config.output_dir}/train_config.json", "w") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)
    return config.output_dir


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fine-tune the SLM adviser.")
    parser.add_argument("config", help="Path to the TrainConfig YAML.")
    parser.add_argument(
        "--validate-only", action="store_true", help="Validate the config (and dataset presence) without training."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    config = TrainConfig.from_yaml(args.config)
    print(
        f"Validated TrainConfig: model_id={config.model_id} "
        f"mode={'full_finetune' if config.full_finetune else 'lora'} "
        f"precision={config.precision} quantization={config.quantization}"
    )
    if args.validate_only:
        return
    out = train(config)
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
