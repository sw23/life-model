# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The factored, persistent action space (Plan 32 D8): standing policies the agent sets and keeps.

The flat ``Discrete(52)`` space is one-off money moves ("transfer 25% of the bank to the 401k"). People
set *rates and rules* that persist, so the factored space is a vector of standing policies, one small
discrete slot each. A slot's value stays in force until the agent changes it; every slot has a
``NO_CHANGE`` value (index 0), so "do nothing" is one cheap choice per slot. The slots map onto the
core engine's own standing-policy objects (Plan 27 D4, :mod:`life_model.policies`), so the RL agent, the
household spec and the adviser share one vocabulary:

=========================  ====================================================  ==========================
Slot                       Values (after ``no_change``)                          Engine object
=========================  ====================================================  ==========================
``pretax_401k_rate``       0, 3, 6, 10, 15 (% of pay), max                       ``ContributionPlan``
``roth_401k_rate``         0, 3, 6, 10, 15, max                                  (payroll, 401(k) bucket)
``ira_contribution``       none, traditional_max, roth_max                       ``ContributionPlan`` (bank)
``hsa_contribution``       none, max                                             ``ContributionPlan`` (payroll)
``sweep_policy``           hold_cash, sweep_to_brokerage, sweep_to_bonds         ``SavingsPolicy``
``spending_adjust``        cut_10, cut_5, hold, raise_5, raise_10                ``Spending.base``
``withdrawal_order``       default, roth_first, pretax_first, brokerage_first    ``Family.withdrawal_order``
``retire``                 no, yes                                               ``Job.retire``
``claim_social_security``  not_yet, now                                          ``SocialSecurity``
``roth_conversion``        none, to_bracket_12, to_bracket_22                    ``RothConversionPolicy``
=========================  ====================================================  ==========================

Semantics worth knowing:

* **Contributions need pay.** 401(k), IRA and HSA contributions require compensation (an HSA also
  stops at Medicare), so their non-``none`` values are legal only while the person is working (and,
  for the HSA, under the Medicare age). When the person retires the env drops those plans and the
  slots read ``0`` / ``none``.
* **``spending_adjust`` is an impulse,** not a level: it scales the household's adjustable spending
  once — the uncategorized base and the discretionary (``essential=False``) category lines, never the
  essential ones — by the slot's percentage times the decision interval's share of a year (so a
  monthly agent cannot move spending twelve times faster than a yearly one). Its standing value reads
  ``hold`` after the step.
* **Retirement and claiming only move earlier.** The household's retirement age stays the latest
  retirement (``retire=yes`` retires now). Social Security is claimed by the agent: ``now`` claims at
  the current exact age (62 at the earliest); a household that never claims starts benefits at the
  maximum delayed-credit age (70), the SSA's practical backstop. ``no`` / ``not_yet`` restate the
  default and are legal only before retirement / claiming.
* **Sweeps run once a year** after taxes (the engine's ``SweepRunner``), keeping a cash floor of
  :data:`SWEEP_FLOOR_MONTHS` of current spending (refreshed at every decision); ``sweep_to_bonds``
  sweeps into a bond fund the env opens for the household (in the ``fixed_income`` waterfall step).
* **Roth conversions run every December** before taxes, filling ordinary income to the top of the
  12% or 22% bracket, from the traditional IRA when it holds money and otherwise as an in-plan
  conversion of the 401(k)'s pre-tax money.

Nothing here moves money at decision time: the engine carries out every policy inside
``model.step()``, posting each dollar to the ledger, so RL rollouts pass the strict invariant checker.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from life_model.account.fixed_income import FixedIncomeHolding
from life_model.insurance.social_security import get_max_delayed_retirement_credit_age, get_min_early_retirement_age
from life_model.people.tax_unit import DEFAULT_WITHDRAWAL_ORDER, validate_withdrawal_order
from life_model.policies import MAX, ContributionPlan, RothConversionPolicy, SavingsPolicy

if TYPE_CHECKING:
    from .environment import FinancialLifeEnv

#: Index 0 of every slot: keep the standing value.
NO_CHANGE = "no_change"

#: Months of current base spending a sweep keeps in the bank.
SWEEP_FLOOR_MONTHS = 6

#: Distribution yield (percent a year) of the bond fund ``sweep_to_bonds`` buys; the fund's total
#: return follows the economy's bond return and the yield is carved out of it as taxable interest.
BOND_FUND_YIELD_PCT = 3.0


@dataclass(frozen=True)
class PolicySlot:
    """One standing-policy slot: its name, its values (``NO_CHANGE`` excluded) and its initial value."""

    name: str
    values: tuple[str, ...]
    default: str
    description: str

    @property
    def choices(self) -> tuple[str, ...]:
        """Every action value of the slot, ``NO_CHANGE`` first (the MultiDiscrete index order)."""
        return (NO_CHANGE, *self.values)

    @property
    def size(self) -> int:
        return len(self.values) + 1

    def index(self, value: str) -> int:
        """The action index of ``value`` (``NO_CHANGE`` is 0)."""
        return self.choices.index(value)


_RATES = ("0", "3", "6", "10", "15", "max")

SLOTS: tuple[PolicySlot, ...] = (
    PolicySlot("pretax_401k_rate", _RATES, "0", "Pre-tax 401(k) deferral, percent of pay (max: the 402(g) limit)"),
    PolicySlot("roth_401k_rate", _RATES, "0", "Roth 401(k) deferral, percent of pay (max: the 402(g) limit)"),
    PolicySlot(
        "ira_contribution", ("none", "traditional_max", "roth_max"), "none", "Fund an IRA to the limit from the bank"
    ),
    PolicySlot("hsa_contribution", ("none", "max"), "none", "Fund the HSA to the limit through payroll"),
    PolicySlot(
        "sweep_policy",
        ("hold_cash", "sweep_to_brokerage", "sweep_to_bonds"),
        "hold_cash",
        "Yearly sweep of cash above a six-month floor",
    ),
    PolicySlot(
        "spending_adjust",
        ("cut_10", "cut_5", "hold", "raise_5", "raise_10"),
        "hold",
        "One-time change to base spending (scaled by the decision interval)",
    ),
    PolicySlot(
        "withdrawal_order",
        ("default", "roth_first", "pretax_first", "brokerage_first"),
        "default",
        "Order the household waterfall draws savings in",
    ),
    PolicySlot("retire", ("no", "yes"), "no", "Retire now (the household's retirement age is the latest)"),
    PolicySlot("claim_social_security", ("not_yet", "now"), "not_yet", "Claim Social Security now (70 at the latest)"),
    PolicySlot(
        "roth_conversion",
        ("none", "to_bracket_12", "to_bracket_22"),
        "none",
        "Convert pre-tax money to Roth each December, filling a bracket",
    ),
)

SLOT_NAMES: tuple[str, ...] = tuple(slot.name for slot in SLOTS)
SLOT_BY_NAME: dict[str, PolicySlot] = {slot.name: slot for slot in SLOTS}
#: The MultiDiscrete ``nvec``.
NVEC: tuple[int, ...] = tuple(slot.size for slot in SLOTS)

#: ``spending_adjust`` value -> fractional change per year of decision interval.
SPENDING_CHANGES: dict[str, float] = {"cut_10": -0.10, "cut_5": -0.05, "hold": 0.0, "raise_5": 0.05, "raise_10": 0.10}

#: ``withdrawal_order`` value -> the household waterfall (every step of ``DEFAULT_WITHDRAWAL_ORDER``).
WITHDRAWAL_ORDERS: dict[str, tuple[str, ...]] = {
    # bank, bonds, taxable, Roth basis (penalty-free young), pre-tax, Roth earnings, reserves.
    "default": DEFAULT_WITHDRAWAL_ORDER,
    # Tax-free money first: preserves pre-tax balances (and their deferral) longest.
    "roth_first": ("bank", "fixed_income", "roth_basis", "roth_earnings", "brokerage", "pretax", "reserve"),
    # Pre-tax first: draws ordinary income early, e.g. to shrink later RMDs.
    "pretax_first": ("bank", "fixed_income", "pretax", "brokerage", "roth_basis", "roth_earnings", "reserve"),
    # The textbook order: taxable, then tax-deferred, then Roth last (bonds after stocks are sold).
    "brokerage_first": ("bank", "brokerage", "fixed_income", "pretax", "roth_basis", "roth_earnings", "reserve"),
}
for _order in WITHDRAWAL_ORDERS.values():
    validate_withdrawal_order(_order)

_ROTH_BRACKETS = {"to_bracket_12": 12, "to_bracket_22": 22}


def scale_discretionary_spending(spending, factor: float) -> None:
    """Scale what a household can adjust: the uncategorized ``base`` and every discretionary
    (``essential=False``) categorized line (Plan 27 D6). Essential lines — the needs a household
    itemized — are left alone."""
    spending.base *= factor
    for line in getattr(spending, "categories", {}).values():
        if not line.essential:
            line.amount *= factor


def joint_action_count() -> int:
    """Size of the joint (enumerated) action space: the product of the slot sizes."""
    return int(np.prod(NVEC, dtype=np.int64))


def no_change_vector() -> np.ndarray:
    """The all-``NO_CHANGE`` action."""
    return np.zeros(len(SLOTS), dtype=np.int64)


def encode_policy_action(changes: dict[str, str] | None = None) -> np.ndarray:
    """The action vector setting ``changes`` (slot name -> value) and ``NO_CHANGE`` elsewhere."""
    vector = no_change_vector()
    for name, value in (changes or {}).items():
        vector[SLOT_NAMES.index(name)] = SLOT_BY_NAME[name].index(value)
    return vector


def decode_policy_action(action) -> dict[str, str]:
    """``{slot name: value}`` of an action vector (``NO_CHANGE`` slots included)."""
    vector = np.asarray(action, dtype=np.int64).reshape(-1)
    if vector.shape != (len(SLOTS),):
        raise ValueError(f"A policy action has {len(SLOTS)} slots, got shape {vector.shape}")
    out = {}
    for slot, index in zip(SLOTS, vector):
        if not 0 <= index < slot.size:
            raise ValueError(f"{slot.name} index {index} out of range [0, {slot.size})")
        out[slot.name] = slot.choices[int(index)]
    return out


def split_mask(flat_mask) -> list[np.ndarray]:
    """Split a concatenated per-slot mask (length ``sum(NVEC)``) into one boolean array per slot."""
    flat = np.asarray(flat_mask, dtype=bool)
    offsets = np.cumsum((0, *NVEC))
    return [flat[offsets[i] : offsets[i + 1]] for i in range(len(SLOTS))]


class StandingPolicies:
    """The standing policies of one episode's agent, bound to the environment's household.

    ``state`` holds each slot's value in force. :meth:`apply` carries out an action vector (ignoring
    ``NO_CHANGE`` slots and, defensively, values the masks call illegal), :meth:`slot_masks` gives the
    per-slot legal-action masks, and :meth:`sync` re-derives what the engine changed on its own
    (retirement ends contributions, a claim starts benefits).
    """

    def __init__(self, env: "FinancialLifeEnv"):
        self.env = env
        self.person = env.person
        self.state: dict[str, str] = {slot.name: slot.default for slot in SLOTS}
        self._bond_fund: FixedIncomeHolding | None = None

        # Employer match through the 401(k) plan itself (payroll deferrals earn it per paycheck), the
        # same formula the flat space's bank-to-401k transfers apply at the action level.
        match = env.employer_match
        if match.active:
            env.job401k.match_tiers = env.job401k._validate_tiers(((match.rate * 100, match.cap * 100),))

        # The agent owns the claim; never claiming starts benefits at the delayed-credit maximum.
        ss = self.person.social_security
        if ss is not None and not ss.is_claiming:
            ss.withdrawal_start_age = max(ss.withdrawal_start_age, self._max_claim_age)
            ss._pia_by_year.clear()
        self.sync()

    # --- facts the masks need -----------------------------------------------------------------

    @property
    def _config(self):
        return self.person.model.config

    @property
    def _max_claim_age(self) -> float:
        return float(get_max_delayed_retirement_credit_age(self._config))

    @property
    def working(self) -> bool:
        """Whether the person has pay to contribute from (alive, not retired, a job still active)."""
        person = self.person
        if person.is_deceased or person.is_retired:
            return False
        return any(not job.retired for job in person.jobs)

    @property
    def hsa_eligible(self) -> bool:
        """HSA contributions stop with Medicare enrollment (age 65)."""
        medicare_age = self._config.healthcare.medicare.eligibility_age
        return self.working and self.person.age_years_fractional < medicare_age

    @property
    def can_claim(self) -> bool:
        ss = self.person.social_security
        if ss is None or self.person.is_deceased or ss.is_claiming:
            return False
        return self.person.age_years_fractional >= get_min_early_retirement_age(self._config)

    def legal_values(self, slot: PolicySlot) -> list[str]:
        """The slot's values (``NO_CHANGE`` included) that are legal now."""
        person = self.person
        name = slot.name
        if person.is_deceased:
            return [NO_CHANGE]
        if name in ("pretax_401k_rate", "roth_401k_rate", "ira_contribution"):
            return list(slot.choices) if self.working else [NO_CHANGE]
        if name == "hsa_contribution":
            return list(slot.choices) if self.hsa_eligible else [NO_CHANGE]
        if name == "retire":
            return list(slot.choices) if not person.is_retired else [NO_CHANGE]
        if name == "claim_social_security":
            ss = person.social_security
            if ss is None or ss.is_claiming:
                return [NO_CHANGE]
            return list(slot.choices) if self.can_claim else [NO_CHANGE, "not_yet"]
        return list(slot.choices)

    def slot_masks(self) -> list[np.ndarray]:
        """One boolean legal mask per slot, in ``SLOTS`` order (``NO_CHANGE`` is always legal)."""
        masks = []
        for slot in SLOTS:
            legal = set(self.legal_values(slot))
            masks.append(np.array([value in legal for value in slot.choices], dtype=bool))
        return masks

    def flat_mask(self) -> np.ndarray:
        """The per-slot masks concatenated (length ``sum(NVEC)``), the ``info["legal_mask"]`` form."""
        return np.concatenate(self.slot_masks())

    def vector(self) -> np.ndarray:
        """The standing values as slot indices (``NO_CHANGE`` never appears)."""
        return np.array([SLOT_BY_NAME[name].index(self.state[name]) for name in SLOT_NAMES], dtype=np.int64)

    def normalized(self) -> np.ndarray:
        """The standing values as ``(index - 1) / (len(values) - 1)`` in ``[0, 1]``, for observations."""
        return np.array(
            [
                (SLOT_BY_NAME[name].index(self.state[name]) - 1) / max(1, SLOT_BY_NAME[name].size - 2)
                for name in SLOT_NAMES
            ],
            dtype=np.float32,
        )

    # --- carrying out an action ---------------------------------------------------------------

    def apply(self, action, *, interval_months: int = 12) -> dict[str, str]:
        """Carry out an action vector; returns ``{slot: value}`` of the slots it changed.

        A ``NO_CHANGE`` slot keeps its value. An illegal value (one the slot's mask rules out) is
        ignored, so a caller that skips masking cannot break the household.
        """
        decoded = decode_policy_action(action)
        changed: dict[str, str] = {}
        for slot in SLOTS:
            value = decoded[slot.name]
            if value == NO_CHANGE or value not in self.legal_values(slot):
                continue
            getattr(self, f"_set_{slot.name}")(value, interval_months)
            changed[slot.name] = value
        self.refresh()
        return changed

    def refresh(self) -> None:
        """Re-derive decision-time quantities (the sweep's cash floor, the conversion's source)."""
        policy = self.person.savings_policy
        if policy is not None:
            policy.cash_floor = self._cash_floor()
        conversion = self.person.roth_conversion_policy
        if conversion is not None:
            conversion.source = self._conversion_source()

    def sync(self) -> None:
        """Bring ``state`` in line with what the engine did on its own between decisions."""
        person = self.person
        if not self.working:
            for name, account in (
                ("pretax_401k_rate", self.env.job401k),
                ("roth_401k_rate", self.env.job401k),
            ):
                if self.state[name] != "0":
                    bucket = "pretax" if name.startswith("pretax") else "roth"
                    if not person.is_deceased:
                        person.remove_contribution_plan(account, bucket=bucket)
                    self.state[name] = "0"
            if self.state["ira_contribution"] != "none":
                self._set_ira_contribution("none", 12)
        if not self.hsa_eligible and self.state["hsa_contribution"] != "none":
            self._set_hsa_contribution("none", 12)
        if person.is_retired:
            self.state["retire"] = "yes"
        ss = person.social_security
        if ss is not None and ss.is_claiming:
            self.state["claim_social_security"] = "now"
        self.state["spending_adjust"] = "hold"

    # --- slot setters -------------------------------------------------------------------------

    def _set_401k(self, bucket: str, value: str) -> None:
        account = self.env.job401k
        if value == "0":
            self.person.remove_contribution_plan(account, bucket=bucket)
        elif value == "max":
            self.person.add_contribution_plan(
                ContributionPlan(account, amount_annual=MAX, source="payroll", bucket=bucket)
            )
        else:
            self.person.add_contribution_plan(
                ContributionPlan(account, pct_of_pay=float(value), source="payroll", bucket=bucket)
            )

    def _set_pretax_401k_rate(self, value: str, _interval: int) -> None:
        self._set_401k("pretax", value)
        self.state["pretax_401k_rate"] = value

    def _set_roth_401k_rate(self, value: str, _interval: int) -> None:
        self._set_401k("roth", value)
        self.state["roth_401k_rate"] = value

    def _set_ira_contribution(self, value: str, _interval: int) -> None:
        env = self.env
        for ira in (env.traditional_ira, env.roth_ira):
            self.person.remove_contribution_plan(ira)
        if value == "traditional_max":
            self.person.add_contribution_plan(ContributionPlan(env.traditional_ira, amount_annual=MAX))
        elif value == "roth_max":
            self.person.add_contribution_plan(ContributionPlan(env.roth_ira, amount_annual=MAX))
        self.state["ira_contribution"] = value

    def _set_hsa_contribution(self, value: str, _interval: int) -> None:
        hsa = self.env.hsa
        if value == "max":
            self.person.add_contribution_plan(ContributionPlan(hsa, amount_annual=MAX, source="payroll"))
        else:
            self.person.remove_contribution_plan(hsa)
        self.state["hsa_contribution"] = value

    def _cash_floor(self) -> float:
        return self.person.spending.base * SWEEP_FLOOR_MONTHS / 12.0

    def bond_fund(self) -> FixedIncomeHolding:
        """The household's bond fund (opened, empty, the first time it is needed)."""
        if self._bond_fund is None:
            self._bond_fund = FixedIncomeHolding(
                self.person, kind="bond_fund", face=0.0, rate_pct=BOND_FUND_YIELD_PCT, reserve=False, name="Bond fund"
            )
        return self._bond_fund

    def _set_sweep_policy(self, value: str, _interval: int) -> None:
        if value == "hold_cash":
            self.person.savings_policy = None
        else:
            target = self.env.brokerage if value == "sweep_to_brokerage" else self.bond_fund()
            self.person.savings_policy = SavingsPolicy(cash_floor=self._cash_floor(), sweep_to=target)
        self.state["sweep_policy"] = value

    def _set_spending_adjust(self, value: str, interval_months: int) -> None:
        change = SPENDING_CHANGES[value] * interval_months / 12.0
        scale_discretionary_spending(self.person.spending, max(0.0, 1.0 + change))
        self.state["spending_adjust"] = value

    def _set_withdrawal_order(self, value: str, _interval: int) -> None:
        self.env.family.withdrawal_order = WITHDRAWAL_ORDERS[value]
        self.state["withdrawal_order"] = value

    def _set_retire(self, value: str, _interval: int) -> None:
        if value == "yes":
            person = self.person
            person.retirement_age = person.age
            for job in person.jobs:
                job.retire()
            self.sync()
        self.state["retire"] = value

    def _set_claim_social_security(self, value: str, _interval: int) -> None:
        if value == "now":
            ss = self.person.social_security
            ss.withdrawal_start_age = max(
                self.person.age_years_fractional, float(get_min_early_retirement_age(self._config))
            )
            ss._pia_by_year.clear()
        self.state["claim_social_security"] = value

    def _conversion_source(self):
        """The traditional IRA when it holds money, else the 401(k) (an in-plan conversion)."""
        env = self.env
        if env.traditional_ira.balance > 0 or env.job401k.pretax_balance <= 0:
            return env.traditional_ira
        return env.job401k

    def _set_roth_conversion(self, value: str, _interval: int) -> None:
        if value == "none":
            self.person.roth_conversion_policy = None
        else:
            self.person.roth_conversion_policy = RothConversionPolicy(
                fill_bracket_pct=_ROTH_BRACKETS[value], source=self._conversion_source(), target=self.env.roth_ira
            )
        self.state["roth_conversion"] = value

    # --- reporting ----------------------------------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        """The standing values (a copy)."""
        return dict(self.state)
