# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Training config-validation and data-collation tests (Plan 20 task 4, CI — no weights).

Covers the LLM-readiness contract: the shipped smoke / default / full-FSDP configs all validate
from the same schema, the lora-vs-full_finetune modes are mutually exclusive, and the JSONL
collates into per-example chat message lists renderable by any chat-template callable.
"""

import os

import pytest
from pydantic import ValidationError

from slm.generate_data import examples_to_jsonl, generate_examples
from slm.train import LoraSettings, TrainConfig, load_chat_examples, render_chat_texts

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "configs")


def _base(**overrides):
    data = {"model_id": "tiny/model", "dataset_path": "d.jsonl"}
    data.update(overrides)
    return data


def test_shipped_configs_validate():
    for name in ("train_smoke.yaml", "train_default_qlora.yaml", "train_full_fsdp.yaml"):
        cfg = TrainConfig.from_yaml(os.path.join(_CONFIG_DIR, name))
        assert cfg.model_id


def test_full_fsdp_config_is_full_finetune_with_passthrough():
    cfg = TrainConfig.from_yaml(os.path.join(_CONFIG_DIR, "train_full_fsdp.yaml"))
    assert cfg.full_finetune is True
    assert cfg.lora is None
    # Opaque FSDP/accelerate passthrough survives validation untouched.
    assert cfg.fsdp["sharding_strategy"] == "FULL_SHARD"
    assert cfg.accelerate["num_processes"] == 8


def test_default_config_is_qlora():
    cfg = TrainConfig.from_yaml(os.path.join(_CONFIG_DIR, "train_default_qlora.yaml"))
    assert cfg.quantization == "4bit"
    assert cfg.lora is not None and cfg.lora.rank == 16


def test_lora_and_full_finetune_mutually_exclusive():
    with pytest.raises(ValidationError):
        TrainConfig.model_validate(_base(full_finetune=True, lora=LoraSettings().model_dump()))


def test_a_mode_is_required():
    with pytest.raises(ValidationError):
        TrainConfig.model_validate(_base(full_finetune=False, lora=None))


def test_unknown_key_forbidden():
    with pytest.raises(ValidationError):
        TrainConfig.model_validate(_base(bogus=1))


def test_precision_and_quantization_patterns():
    with pytest.raises(ValidationError):
        TrainConfig.model_validate(_base(precision="int4"))
    with pytest.raises(ValidationError):
        TrainConfig.model_validate(_base(quantization="2bit"))


def test_lora_default_targets_present():
    cfg = TrainConfig.model_validate(_base())
    assert "q_proj" in cfg.lora.target_modules


def test_collation_from_jsonl(tmp_path):
    examples = generate_examples(["basic"], n_per_scenario=2, n_trials=4, generation_seed=1)
    path = tmp_path / "d.jsonl"
    path.write_text(examples_to_jsonl(examples))

    chats = load_chat_examples(str(path))
    assert len(chats) == len(examples)
    # Every decision example is a 3-turn system/user/assistant chat.
    decision_chats = [c for c in chats if len(c) == 3]
    assert decision_chats
    for chat in decision_chats:
        assert [m["role"] for m in chat] == ["system", "user", "assistant"]

    # Renderable by any chat-template callable (here a stub) — no tokenizer needed.
    def stub_template(messages, tokenize=False, **kwargs):
        return "\n".join(f"<{m['role']}>{m['content']}" for m in messages)

    texts = render_chat_texts(chats, stub_template)
    assert len(texts) == len(chats)
    assert "<assistant>" in texts[0]


def test_collation_respects_max_examples(tmp_path):
    examples = generate_examples(["basic"], n_per_scenario=3, n_trials=4, generation_seed=1)
    path = tmp_path / "d.jsonl"
    path.write_text(examples_to_jsonl(examples))
    assert len(load_chat_examples(str(path), max_examples=2)) == 2
