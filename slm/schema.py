# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Versioned dataset schema for the adviser.

``schema_version = 2`` (v2: decisions are compositional plan tokens, scored candidates carry paired
gaps to the best and gains over the default plan, households carry retirement-income context). The models reuse the repository's ``StrictModel`` convention
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

from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field

from life_model.config.models import StrictModel

if TYPE_CHECKING:
    from life_model.spec import HouseholdSpec

SCHEMA_VERSION = 2


class ChatMessage(StrictModel):
    """One chat turn. The tokenizer's own chat template is applied at train time."""

    role: Literal["system", "user", "assistant"]
    content: str


class HouseholdProfile(StrictModel):
    """Structured household state at the decision point: the LM-facing subset of a ``HouseholdSpec``.

    The household composition (ages, salary, spending, balances, children, healthcare, Social
    Security) is a projection of the episode's :class:`life_model.spec.HouseholdSpec`
    (:meth:`from_household_spec` / :meth:`to_household_spec`). The plan context the adviser reasons
    about but core cannot express yet (the scenario label, the employer match offer and the
    retirement spending ratio, all applied by the RL environment) travels alongside it.
    """

    scenario: str
    person_start_age: int = Field(ge=0)
    person_retirement_age: int = Field(ge=0)
    person_gender: str
    initial_salary: float = Field(ge=0)
    initial_bank_balance: float
    initial_spending: float = Field(ge=0)
    economy_scenario: str | None = None
    # Household composition. ``children_ages`` are the ages (at the start year) of modeled child
    # dependents; ``models_healthcare`` marks that age-banded medical costs and Medicare premiums
    # are priced for the person. Defaults keep older/simple households unchanged.
    children_ages: list[int] = Field(default_factory=list)
    models_healthcare: bool = False
    # Retirement-income context (all default to "absent" so older rows still validate):
    # Social Security claiming age (None = not modeled), the employer 401k match offer, and the
    # starting invested balances.
    ss_claim_age: int | None = None
    # Base spending in retirement as a share of working spending (1.0 = unchanged).
    retirement_spending_ratio: float = Field(default=1.0, gt=0)
    employer_match_rate: float = Field(default=0.0, ge=0)
    employer_match_cap: float = Field(default=0.0, ge=0)
    initial_401k_pretax: float = Field(default=0.0, ge=0)
    initial_401k_roth: float = Field(default=0.0, ge=0)
    initial_brokerage: float = Field(default=0.0, ge=0)

    def to_household(self) -> dict[str, Any]:
        """The RL environment household dict (``FinancialLifeEnv`` config keys) for this profile."""
        from life_model.people.person import GenderAtBirth

        household: dict[str, Any] = {
            "person_start_age": self.person_start_age,
            "person_retirement_age": self.person_retirement_age,
            "person_gender": GenderAtBirth[self.person_gender.upper()],
            "initial_salary": self.initial_salary,
            "initial_bank_balance": self.initial_bank_balance,
            "initial_spending": self.initial_spending,
            "children_ages": list(self.children_ages),
            "models_healthcare": self.models_healthcare,
            "ss_claim_age": self.ss_claim_age,
            "retirement_spending_ratio": self.retirement_spending_ratio,
            "employer_match_rate": self.employer_match_rate,
            "employer_match_cap": self.employer_match_cap,
            "initial_401k_pretax": self.initial_401k_pretax,
            "initial_401k_roth": self.initial_401k_roth,
            "initial_brokerage": self.initial_brokerage,
        }
        if self.economy_scenario is not None:
            household["economy_scenario"] = self.economy_scenario
        return household

    def to_household_spec(self) -> "HouseholdSpec":
        """The profile's household as a ``HouseholdSpec`` (the RL episode household it describes).

        ``ss_claim_age=None`` (Social Security not modeled) builds a spec without Social Security.
        """
        from deepqlearning.envs.financial.scenarios import household_spec

        env_config: dict[str, Any] = {"household_scenario": self.scenario}
        if self.ss_claim_age is None:
            env_config["social_security"] = False
        return household_spec(self.to_household(), env_config)

    @classmethod
    def from_household_spec(
        cls,
        spec: "HouseholdSpec",
        *,
        scenario: str | None = None,
        retirement_spending_ratio: float = 1.0,
        employer_match_rate: float = 0.0,
        employer_match_cap: float = 0.0,
    ) -> "HouseholdProfile":
        """Project a single-person ``HouseholdSpec`` onto the adviser's profile.

        Reads the person's age, retirement age, gender, first job's salary, spending, first bank
        account, 401k and brokerage balances, children (ages at the start year), healthcare flag and
        Social Security claiming age, and ``meta.scenario`` as the economic outlook. The plan context
        (``scenario`` label, match offer, retirement spending ratio) is passed in.
        """
        if len(spec.people) != 1:
            raise ValueError(f"HouseholdProfile describes one person; the spec has {len(spec.people)}")
        (person,) = spec.people

        def first(kind: str):
            return next((a for a in person.accounts if a.kind == kind), None)

        bank, k401, brokerage = first("bank"), first("401k"), first("brokerage")
        ss = person.social_security
        return cls(
            scenario=scenario if scenario is not None else spec.meta.name,
            person_start_age=person.age,
            person_retirement_age=int(person.retirement_age),
            person_gender=person.gender.capitalize(),
            initial_salary=person.jobs[0].salary_annual if person.jobs else 0.0,
            initial_bank_balance=bank.balance if bank is not None else 0.0,
            initial_spending=person.spending.amount_annual,
            economy_scenario=spec.meta.scenario,
            children_ages=[spec.meta.start_year - child.birth_year for child in person.children],
            models_healthcare=bool(person.healthcare is not None and person.healthcare.medical_costs),
            ss_claim_age=int(ss.claim_age) if ss is not None and ss.claim_age is not None else None,
            retirement_spending_ratio=retirement_spending_ratio,
            employer_match_rate=employer_match_rate,
            employer_match_cap=employer_match_cap,
            initial_401k_pretax=k401.pretax_balance if k401 is not None else 0.0,
            initial_401k_roth=k401.roth_balance if k401 is not None else 0.0,
            initial_brokerage=(brokerage.balance or 0.0) if brokerage is not None else 0.0,
        )


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
    # Paired comparison with the household's best candidate (highest mean return) on the same
    # trials: the mean per-trial return shortfall ``best - this`` and its bootstrap 95% CI. A
    # candidate is in the top set when that CI does not exclude zero (it is within noise of the
    # best). Defaults keep rows written before these fields existed valid.
    return_std: float = 0.0
    gap_to_best: float = 0.0
    gap_ci_low: float = 0.0
    gap_ci_high: float = 0.0
    in_top_set: bool = True
    # Paired gain over the default plan (``this - default`` per trial) and its bootstrap 95% CI;
    # zero when the default plan is not among the scored candidates. The label moves a lever off
    # its default only on a gain whose CI excludes zero (slm.scoring.label_plan).
    gain_vs_default: float = 0.0
    gain_ci_low: float = 0.0
    gain_ci_high: float = 0.0


class Provenance(StrictModel):
    """Per-example provenance stamp (advice provenance is auditable)."""

    generation_seed: int
    simulator_commit: str
    config_hash: str
    n_trials: int = Field(ge=1)
    reward_preset: str


class AdviceExample(StrictModel):
    """One dataset row: an in-scope decision example or an out-of-scope refusal example."""

    schema_version: Literal[2] = SCHEMA_VERSION
    example_id: str
    kind: Literal["decision", "refusal"]

    # In-scope decision examples carry the household + scoring; refusals leave them empty.
    household: HouseholdProfile | None = None
    household_text: str | None = None
    question: str
    decision_space: list[str] = Field(default_factory=list)
    chosen_decision: str | None = None
    # How decisively the scores pick the label (slm.scoring.decision_basis): "clear", "equivalent",
    # or "no_viable" (the label is then slm.strategies.NO_LEVER). None on refusals.
    decision_basis: Literal["clear", "equivalent", "no_viable"] | None = None
    scored_alternatives: list[ScoredCandidate] = Field(default_factory=list)

    rationale: str
    out_of_scope: bool = False
    messages: list[ChatMessage]
    provenance: Provenance | None = None


class Datasheet(StrictModel):
    """Dataset-level provenance and statistics (Datasheets-for-Datasets style).

    Records exactly what is needed to reproduce and to detect staleness: the generation seed, the
    simulator commit, the config hash, the trial counts, and the teacher-gating decision (whether
    the DQN was eligible to prune candidates per the RL protocol).
    """

    schema_version: Literal[2] = SCHEMA_VERSION
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
    household_scenarios: list[str]
    decision_space: list[str]
    teacher_gating: str
    scale_note: str
    created_utc: str
    # Label composition after balancing, and how many decision examples balancing dropped.
    label_counts: dict[str, int] = Field(default_factory=dict)
    decision_basis_counts: dict[str, int] = Field(default_factory=dict)
    max_label_share: float | None = None
    n_dropped_for_balance: int = 0
    # Calibration of the household distribution, per scenario, over the kept decision examples:
    # mean best-lever success rate, the share of households whose best lever is solvent in at most
    # half the trials, and the share with no viable lever (slm.households documents the targets).
    solvency_by_scenario: dict[str, dict[str, float]] = Field(default_factory=dict)
    # Adaptive scoring: trials start at ``min_trials_per_candidate`` and double, up to
    # ``n_trials_per_candidate``, while the top options are within noise (None = fixed count).
    min_trials_per_candidate: int | None = None
