# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Simulation-grounded language-model adviser.

An SLM-first, LLM-ready product directory (like ``deepqlearning/``): it turns the life-model
simulator into a data generator and verifier for language-model financial *advice*. Nothing here
enters the core ``life_model`` package or the published wheel; dependencies live in
``slm/requirements-slm.txt``.

The pipeline:

* :mod:`slm.schema` — versioned dataset schema (``schema_version=1``, pydantic StrictModel).
* :mod:`slm.serializer` — renders a structured household into faithful natural-language text.
* :mod:`slm.strategies` — the decision vocabulary (plan-level levers the adviser recommends).
* :mod:`slm.adviser` — the ``AdviserModel`` protocol and deterministic stub implementations.
* :mod:`slm.candidates` / :mod:`slm.scoring` — Monte Carlo scoring of candidate decisions.
* :mod:`slm.generate_data` — simulator-verified decision pairs with counterfactual rationales.
* :mod:`slm.evaluate_adviser` — outcome-based evaluation extending the RL-policy evaluation protocol.
* :mod:`slm.train` — size-agnostic SFT entrypoint (HF backend) driven by a YAML ``TrainConfig``.
* :mod:`slm.advise` — the draft → simulate → revise tool-loop adviser.

Framing: outputs are *simulation-grounded educational decision support*, not fiduciary
advice. See :data:`slm.prompts.SYSTEM_PROMPT` and the README.
"""

SCHEMA_VERSION = 1
