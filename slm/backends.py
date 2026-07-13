# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Real ``AdviserModel`` backends (Plan 20 D5, task 7 — optional).

Three interchangeable implementations of the :class:`~slm.adviser.AdviserModel` protocol, all
behind lazy imports so this module (and CI) never loads weights or SDKs it doesn't use:

* :class:`HFAdviserModel` — a local Hugging Face ``transformers`` model (optionally with a LoRA
  adapter), the canonical local SLM path;
* :class:`MLXAdviserModel` — an Apple-silicon ``mlx-lm`` model, the nice-to-have local path;
* :class:`APIAdviserModel` — a hosted Claude model via the Anthropic SDK, evaluated as an
  *upper-bound baseline* on the same harness so the local SLM's numbers have context.

Each applies the tokenizer's / provider's own chat formatting — no hardcoded prompt template — so
the same dataset and eval harness drive every model family. CI uses the deterministic stubs in
:mod:`slm.adviser`; these are exercised only in manual/local runs.
"""

from typing import Dict, List, Optional

from .adviser import Messages

# Anthropic model used for the hosted upper-bound baseline (see slm/README.md; opus is the
# repo-standard default). Adaptive thinking is left at the model default.
DEFAULT_API_MODEL = "claude-opus-4-8"


class HFAdviserModel:
    """Local Hugging Face causal-LM adviser (optionally with a PEFT/LoRA adapter)."""

    def __init__(
        self,
        model_id: str,
        adapter_path: Optional[str] = None,
        max_new_tokens: int = 256,
        device_map: str = "auto",
        torch_dtype: str = "auto",
    ):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        dtype = getattr(torch, torch_dtype) if torch_dtype != "auto" else "auto"
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModelForCausalLM.from_pretrained(model_id, device_map=device_map, torch_dtype=dtype)
        if adapter_path:
            from peft import PeftModel

            self.model = PeftModel.from_pretrained(self.model, adapter_path)
        self.model.eval()
        self.max_new_tokens = max_new_tokens

    def generate(self, messages: Messages) -> str:
        import torch

        inputs = self.tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, return_tensors="pt"
        ).to(self.model.device)
        with torch.no_grad():
            output = self.model.generate(
                inputs, max_new_tokens=self.max_new_tokens, do_sample=False
            )
        # Decode only the newly generated tokens (strip the prompt).
        new_tokens = output[0][inputs.shape[-1]:]
        return self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


class MLXAdviserModel:
    """Local Apple-silicon adviser via ``mlx-lm`` (optional; not load-bearing per D3)."""

    def __init__(self, model_id: str, adapter_path: Optional[str] = None, max_new_tokens: int = 256):
        from mlx_lm import load

        self.model, self.tokenizer = load(model_id, adapter_path=adapter_path)
        self.max_new_tokens = max_new_tokens

    def generate(self, messages: Messages) -> str:
        from mlx_lm import generate as mlx_generate

        prompt = self.tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        return mlx_generate(
            self.model, self.tokenizer, prompt=prompt, max_tokens=self.max_new_tokens, verbose=False
        ).strip()


class APIAdviserModel:
    """Hosted-Claude adviser via the Anthropic SDK — an upper-bound baseline (D5).

    The system turn maps to the Messages API ``system`` parameter; the remaining turns map to
    ``messages``. Deterministic sampling is not guaranteed for hosted models, so the eval report
    should note this baseline is not bit-reproducible (unlike the local/stub paths).
    """

    def __init__(self, model: str = DEFAULT_API_MODEL, max_tokens: int = 512):
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def generate(self, messages: Messages) -> str:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        turns: List[Dict[str, str]] = [
            {"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"
        ]
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system or None,
            messages=turns,
        )
        return "".join(block.text for block in response.content if block.type == "text").strip()
