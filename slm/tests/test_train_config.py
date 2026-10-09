# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Training config-validation and data-collation tests (CI — no weights).

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
    for name in (
        "train_smoke.yaml",
        "train_default_qlora.yaml",
        "train_full_fsdp.yaml",
        "train_mac_lora.yaml",
        "train_mac_dpo.yaml",
    ):
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


# --- quality controls: household split, label weighting, regret proxy, DPO pairs ----------------

from slm.prompts import format_decision_answer
from slm.schema import ScoredCandidate
from slm.strategies import DEFAULT_PLAN
from slm.train import dpo_pairs, is_validation, proxy_regret, split_rows


@pytest.fixture(scope="module")
def rows():
    return generate_examples(["basic"], n_per_scenario=6, n_trials=4, generation_seed=2)


def test_household_split_is_deterministic_and_disjoint(rows):
    train_rows, val_rows = split_rows(rows, 0.5)
    assert {r.example_id for r in train_rows}.isdisjoint({r.example_id for r in val_rows})
    assert all(r.kind == "decision" for r in val_rows)
    assert all(is_validation(r.example_id, 0.5) for r in val_rows)
    assert split_rows(rows, 0.5) == (train_rows, val_rows)
    assert split_rows(rows, 0.0)[1] == []


def test_clear_weight_and_drop_equivalent(rows):
    base, _ = split_rows(rows, 0.0)
    weighted, _ = split_rows(rows, 0.0, clear_weight=3)
    n_clear = sum(r.decision_basis == "clear" for r in base)
    assert len(weighted) == len(base) + 2 * n_clear
    dropped, _ = split_rows(rows, 0.0, drop_equivalent=True)
    assert all(r.decision_basis != "equivalent" for r in dropped)


def _scored(name, mean_return, gain=0.0, top=True):
    return ScoredCandidate(
        decision=name,
        success_rate=1.0,
        mean_return=mean_return,
        net_worth_p10=0.0,
        net_worth_p50=0.0,
        net_worth_p90=0.0,
        n_trials=4,
        gain_vs_default=gain,
        in_top_set=top,
    )


def test_proxy_regret(rows):
    row = next(r for r in rows if r.kind == "decision")
    roth = DEFAULT_PLAN.with_value("routing", "roth").name
    claim70 = DEFAULT_PLAN.with_value("claim", "claim70").name
    scored = [_scored(DEFAULT_PLAN.name, 10.0), _scored(roth, 12.0, gain=2.0), _scored(claim70, 11.0, gain=1.0)]
    row = row.model_copy(update={"scored_alternatives": scored})
    assert proxy_regret(format_decision_answer(roth, "x"), row) == 0.0
    assert proxy_regret(format_decision_answer(DEFAULT_PLAN.name, "x"), row) == pytest.approx(1.0)
    assert proxy_regret("gibberish", row) == pytest.approx(1.0)  # unparseable runs the default plan
    # An unscored combination is estimated additively: 10 + 2 + 1 = 13 > best -> no regret.
    combo = DEFAULT_PLAN.with_value("routing", "roth").with_value("claim", "claim70").name
    assert proxy_regret(format_decision_answer(combo, "x"), row) == 0.0


def test_dpo_pairs_reject_a_plan_outside_the_top_set(rows):
    pairs = dpo_pairs(rows)
    by_id = {r.example_id: r for r in rows}
    assert all(p["chosen"][0]["content"] != p["rejected"][0]["content"] for p in pairs)
    for p in pairs:
        assert p["prompt"][-1]["role"] == "user"
    eligible = [
        r for r in by_id.values() if r.kind == "decision" and any(not c.in_top_set for c in r.scored_alternatives)
    ]
    assert len(pairs) == len([r for r in eligible if r.chosen_decision != "no_plan_lever"])


def test_dpo_requires_lora():
    with pytest.raises(ValidationError):
        TrainConfig.model_validate(_base(objective="dpo", full_finetune=True, lora=None))


def test_prompt_completion_splits_off_the_answer(rows):
    from slm.train import prompt_completion

    pair = prompt_completion(next(r for r in rows if r.kind == "decision"))
    assert [m["role"] for m in pair["prompt"]] == ["system", "user"]
    assert pair["completion"][0]["role"] == "assistant"
    assert pair["completion"][0]["content"].startswith("DECISION:")


def test_decision_loss_weights():
    torch = pytest.importorskip("torch")
    from slm.train import decision_loss_weights

    nl = 9
    labels = torch.tensor([[-100, -100, 5, 6, nl, 7, 8], [-100, 1, 2, 3, 4, 5, 6]])
    w = decision_loss_weights(labels, nl, 10.0)
    assert w[0].tolist() == [0, 0, 10, 10, 10, 1, 1]
    # No newline: the first 16 labeled tokens (here all 6) are the decision span.
    assert w[1].tolist() == [0, 10, 10, 10, 10, 10, 10]
    assert decision_loss_weights(labels, nl, 1.0).tolist() == (labels != -100).float().tolist()


def test_decision_only_dpo_pairs(rows):
    pairs = dpo_pairs(rows, decision_only=True)
    assert pairs
    for p in pairs:
        assert p["chosen"][0]["content"].startswith("DECISION: ")
        assert "\n" not in p["chosen"][0]["content"] and "\n" not in p["rejected"][0]["content"]
