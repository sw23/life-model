# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Slow/manual SFT smoke test.

Fine-tunes a ~135M-parameter instruct model over ~50 generated examples through the real HF
backend, proving the training code path end-to-end on tiny compute. Skips gracefully when the
transformers/peft/trl stack is not installed or Hugging Face is unreachable (network downloads are
allowed but not required) — so CI, which never installs the training stack, simply skips it.

Run manually:  pytest slm/tests/test_train_smoke_slow.py -m slow
"""

import pytest

from slm.generate_data import examples_to_jsonl, generate_examples

pytestmark = pytest.mark.slow


def _require_training_stack():
    try:
        import datasets  # noqa: F401
        import peft  # noqa: F401
        import transformers  # noqa: F401
        import trl  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"training stack not installed: {exc}")


def test_smoke_sft_runs(tmp_path):
    _require_training_stack()
    from slm.train import TrainConfig, train

    examples = generate_examples(["basic", "low_earner"], n_per_scenario=25, n_trials=4, generation_seed=3)
    dataset = tmp_path / "smoke.jsonl"
    dataset.write_text(examples_to_jsonl(examples))

    config = TrainConfig(
        model_id="HuggingFaceTB/SmolLM2-135M-Instruct",
        dataset_path=str(dataset),
        output_dir=str(tmp_path / "out"),
        max_examples=50,
        epochs=1,
        per_device_batch_size=1,
        grad_accum=4,
        seq_len=512,
        precision="fp32",
    )

    try:
        out = train(config)
    except Exception as exc:  # pragma: no cover - network/hardware dependent
        msg = str(exc).lower()
        if any(k in msg for k in ("connection", "offline", "couldn't", "could not", "resolve", "hf", "timeout")):
            pytest.skip(f"Hugging Face unreachable / model unavailable: {exc}")
        raise

    import os

    assert os.path.isdir(out)
    assert os.path.exists(os.path.join(out, "train_config.json"))
