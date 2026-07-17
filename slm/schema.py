# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Versioned dataset schema for the adviser.

``schema_version = 1``. The models reuse the repository's ``StrictModel`` convention
(``extra='forbid'`` — a misspelled key fails validation at load time). The schema stores each
example in three redundant, cross-checkable forms:

* structured ``household`` (machine-readable) AND rendered ``household_text`` (what the model
  reads),
* the full ``decision_space`` and every ``scored_alternative`` (so the label and the rationale
  numbers are auditable — and so DPO/GRPO can consume the same file later without regeneration),
* the chat ``messages`` (system + user + target assistant) the trainer collates.

Every rationale figure is a copy of a number in ``scored_alternatives``, so faithfulness is
established at data-generation time, by construction.
"""

from typing import List, Literal, Optional

from pydantic import Field

from life_model.config.models import StrictModel

SCHEMA_VERSION = 1


class ChatMessage(StrictModel):
    """One chat turn. The tokenizer's own chat template is applied at train time."""

    role: Literal["system", "user", "assistant"]
    content: str


class HouseholdProfile(StrictModel):
    """Structured household state at the decision point (mirrors the RL episode household)."""

    scenario: str
    person_start_age: int = Field(ge=0)
    person_retirement_age: int = Field(ge=0)
    person_gender: str
    initial_salary: float = Field(ge=0)
    initial_bank_balance: float
    initial_spending: float = Field(ge=0)
    economy_scenario: Optional[str] = None


class ScoredCandidate(StrictModel):
    """Monte Carlo score of one candidate strategy on the household's shared trial seeds.

    All figures come straight from the scoring run, so any number the rationale cites is
    reproducible from this record (the anti-hallucination guarantee at data time).
    """

    decision: str
    success_rate: float = Field(ge=0.0, le=1.0)
    mean_return: float
    net_worth_p10: float
    net_worth_p50: float
    net_worth_p90: float
    n_trials: int = Field(ge=1)


class Provenance(StrictModel):
    """Per-example provenance stamp (advice provenance is auditable)."""

    generation_seed: int
    simulator_commit: str
    config_hash: str
    n_trials: int = Field(ge=1)
    reward_preset: str


class AdviceExample(StrictModel):
    """One dataset row: an in-scope decision example or an out-of-scope refusal example."""

    schema_version: Literal[1] = SCHEMA_VERSION
    example_id: str
    kind: Literal["decision", "refusal"]

    # In-scope decision examples carry the household + scoring; refusals leave them empty.
    household: Optional[HouseholdProfile] = None
    household_text: Optional[str] = None
    question: str
    decision_space: List[str] = Field(default_factory=list)
    chosen_decision: Optional[str] = None
    scored_alternatives: List[ScoredCandidate] = Field(default_factory=list)

    rationale: str
    out_of_scope: bool = False
    messages: List[ChatMessage]
    provenance: Optional[Provenance] = None


class Datasheet(StrictModel):
    """Dataset-level provenance and statistics (Datasheets-for-Datasets style).

    Records exactly what is needed to reproduce and to detect staleness: the generation seed, the
    simulator commit, the config hash, the trial counts, and the teacher-gating decision (whether
    the DQN was eligible to prune candidates per the RL protocol).
    """

    schema_version: Literal[1] = SCHEMA_VERSION
    name: str
    description: str
    generation_seed: int
    simulator_commit: str
    config_hash: str
    reward_preset: str
    n_trials_per_candidate: int
    n_examples: int
    n_decision_examples: int
    n_refusal_examples: int
    household_scenarios: List[str]
    decision_space: List[str]
    teacher_gating: str
    scale_note: str
    created_utc: str
