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
"""

import argparse
import json
from typing import Any, Dict, List, Optional

import yaml
from pydantic import Field, model_validator

from life_model.config.models import StrictModel

from .schema import AdviceExample


class LoraSettings(StrictModel):
    """LoRA/QLoRA adapter hyperparameters."""

    rank: int = Field(default=16, ge=1)
    alpha: int = Field(default=32, ge=1)
    dropout: float = Field(default=0.05, ge=0.0, le=1.0)
    # Attention/MLP projection names common to Llama/Qwen/Mistral-family models.
    target_modules: List[str] = Field(
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
    lora: Optional[LoraSettings] = LoraSettings()
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
    max_examples: Optional[int] = Field(default=None, ge=1)

    # Precision / attention / quantization.
    precision: str = Field(default="bf16", pattern="^(bf16|fp16|fp32)$")
    attn_implementation: str = "eager"
    quantization: Optional[str] = Field(default=None, pattern="^(4bit|8bit)$")

    # Opaque passthrough blocks handed to accelerate / FSDP unchanged (the LLM-readiness knob).
    # Validated only as free-form mappings; never introspected by this module.
    fsdp: Dict[str, Any] = Field(default_factory=dict)
    accelerate: Dict[str, Any] = Field(default_factory=dict)
    report_to: str = "none"

    @model_validator(mode="after")
    def _exactly_one_mode(self) -> "TrainConfig":
        if self.full_finetune and self.lora is not None:
            raise ValueError("Set either `lora` OR `full_finetune: true`, not both.")
        if not self.full_finetune and self.lora is None:
            raise ValueError("Set a fine-tuning mode: `lora` settings OR `full_finetune: true`.")
        return self

    @classmethod
    def from_yaml(cls, path: str) -> "TrainConfig":
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Data collation — CI-testable without a tokenizer.
# ---------------------------------------------------------------------------


def load_chat_examples(path: str, max_examples: Optional[int] = None) -> List[List[Dict[str, str]]]:
    """Load a dataset JSONL into per-example chat message lists (schema-validated).

    Each row is validated against :class:`~slm.schema.AdviceExample`, then reduced to its
    ``messages`` (list of ``{"role", "content"}``) — the tokenizer applies the chat template at
    train time. Both decision and refusal rows are included, so scope discipline is trained.
    """
    out: List[List[Dict[str, str]]] = []
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


def render_chat_texts(examples: List[List[Dict[str, str]]], apply_chat_template) -> List[str]:
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


def train(config: TrainConfig):
    """Fine-tune per ``config`` using the HF SFT backend and save the model/adapter.

    Lazy-imports transformers/peft/trl/datasets so this file imports cleanly without them. Returns
    the output directory. Intended to be exercised by the slow/manual smoke test and by real runs.
    """
    import torch  # noqa: F401
    from datasets import Dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer

    examples = load_chat_examples(config.dataset_path, config.max_examples)
    if not examples:
        raise ValueError(f"No training examples found in {config.dataset_path}")

    tokenizer = AutoTokenizer.from_pretrained(config.model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    texts = render_chat_texts(examples, tokenizer.apply_chat_template)
    dataset = Dataset.from_dict({"text": texts})

    model_kwargs: Dict[str, Any] = {
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

    import inspect

    from trl import SFTConfig, SFTTrainer

    sft_kwargs: Dict[str, Any] = dict(
        output_dir=config.output_dir,
        num_train_epochs=config.epochs,
        per_device_train_batch_size=config.per_device_batch_size,
        gradient_accumulation_steps=config.grad_accum,
        learning_rate=config.learning_rate,
        warmup_ratio=config.warmup_ratio,
        weight_decay=config.weight_decay,
        gradient_checkpointing=config.gradient_checkpointing,
        packing=config.packing,
        seed=config.seed,
        report_to=config.report_to,
        dataset_text_field="text",
    )
    # trl renamed max_seq_length -> max_length in newer releases; support both so the same code
    # path runs across the version range in requirements-slm.txt.
    sft_params = set(inspect.signature(SFTConfig.__init__).parameters)
    sft_kwargs["max_length" if "max_length" in sft_params else "max_seq_length"] = config.seq_len

    sft_config = SFTConfig(**sft_kwargs)
    trainer = SFTTrainer(model=model, args=sft_config, train_dataset=dataset, peft_config=peft_config)
    trainer.train()
    trainer.save_model(config.output_dir)
    tokenizer.save_pretrained(config.output_dir)

    with open(f"{config.output_dir}/train_config.json", "w") as fh:
        json.dump(config.model_dump(mode="json"), fh, indent=2, sort_keys=True)
    return config.output_dir


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fine-tune the SLM adviser.")
    parser.add_argument("config", help="Path to the TrainConfig YAML.")
    parser.add_argument(
        "--validate-only", action="store_true", help="Validate the config (and dataset presence) without training."
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
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
