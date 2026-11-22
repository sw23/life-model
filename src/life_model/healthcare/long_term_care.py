# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Long-term-care need as a seeded monthly hazard plus a care state.

``LongTermCare`` is an opt-in per-person agent. From a configured start age it draws care need each
month from an age-banded annual hazard table (converted to a monthly one). The draws come from the
agent's own random stream, seeded from the model seed and the person's name, birth month and gender, so a
seeded run is reproducible and does not depend on the order agents were constructed in. On onset the person enters a
care episode in a setting drawn from the configured entry shares (home care, assisted living, a
nursing home), lasting a whole number of months drawn from a geometric distribution with the
configured mean. While in care, a twelfth of the setting's annual cost (indexed by medical inflation)
is charged each month through ``person.spending.add_expense``, and the setting's mortality multiplier
raises the person's death hazard (see :meth:`Person.annual_mortality_chance`).

Active ``InsuranceType.LONG_TERM_CARE`` policies reimburse the year's care cost at the year end (or at
death): the care months after the policy's elimination period (met once, counted over every episode),
up to the year's benefit (the issued benefit grown by any inflation rider) and the policy's remaining
lifetime maximum. With ``medicaid=True``, Medicaid pays a care month once the person's countable assets
(with a spouse at home: the couple's, less the community spouse resource allowance) are at most the asset
limit; the person then pays only their income above the personal needs allowance (and above what a spouse
at home keeps up to the minimum monthly maintenance needs allowance).

Documented simplifications:

* At most one episode is active at a time; the setting is fixed for the episode (no move from home care
  to a facility).
* Living spending, housing and other bills continue unchanged while in care.
* Medicaid: every financial account and cash counts (the home, cars and pensions do not); the
  community spouse keeps the full resource allowance; no look-back period, home-equity limit or estate
  recovery. Income for the patient's share is last month's Social Security, pension, annuity and
  interest income.
"""

import math
import random
from typing import ClassVar, cast

from ..insurance.general_insurance import InsuranceType
from ..model import Event, LifeModel, LifeModelAgent, snap_money
from ..people.mortality import monthly_hazard
from ..people.person import Person
from ..tax.income import IncomeType
from .inflation import medical_inflation_factor

#: Income counted toward a Medicaid patient's share of the cost (benefits and investment income; not
#: withdrawals, which spend countable assets).
_PATIENT_INCOME_TYPES = frozenset(
    {
        IncomeType.PENSION,
        IncomeType.ORDINARY,
        IncomeType.INTEREST,
        IncomeType.TREASURY_INTEREST,
        IncomeType.TAX_EXEMPT_INTEREST,
        IncomeType.QUALIFIED_DIVIDEND,
    }
)


class LongTermCare(LifeModelAgent):
    """Long-term-care need and costs: an episode may start in any month (a monthly hazard); while in care
    a twelfth of the setting's annual cost is charged each month, and at the year end (or at death) the
    year's cost is claimed against LTC insurance."""

    STATS_OWNED = frozenset({"stat_medical_costs"})
    # The year's claim runs before the tax settlement (0), which deducts the net medical cost.
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"on_year_end": -5}

    def __init__(self, person: Person, *, medicaid: bool = False):
        """Model long-term-care need and costs for a person.

        Args:
            person: The person at risk of needing long-term care.
            medicaid: Medicaid pays care once countable assets are spent down to the configured limit
                (keyword-only; off by default: an unpaid care cost becomes debt).
        """
        super().__init__(cast(LifeModel, person.model))
        self.model: LifeModel = cast(LifeModel, self.model)
        self.person = person
        self.config = self.model.config.healthcare.long_term_care
        self.medicaid = medicaid
        self._stream: random.Random | None = None
        self.in_care = False
        self.care_months_remaining = 0
        self._setting = None
        self.episodes_started = 0
        #: ``(year, month)`` each episode started in.
        self.episode_starts: list[tuple[int, int]] = []
        #: Care months charged over every episode (the elimination period counts these).
        self.care_months_total = 0
        # This year's care months as ``(care month number, amount charged to the person)``.
        self._months_this_year: list[tuple[int, float]] = []
        self._charged_period = None
        self._gross_charged_total = 0.0
        # Last month's income counted toward a Medicaid patient's share.
        self._last_month_income = 0.0
        self._last_spouse_income = 0.0
        #: Care cost Medicaid paid this year.
        self.medicaid_paid_this_year = 0.0
        # Net (after insurance) care cost the person incurred this year; feeds the "Medical Costs"
        # stat and the unreimbursed-medical itemized deduction.
        self.stat_medical_costs = 0.0
        self.model.registries.long_term_care.register(person, self)

    # --- state ---

    @property
    def care_years_remaining(self) -> int:
        """The care months left, in whole years (rounded up)."""
        return math.ceil(self.care_months_remaining / 12)

    @care_years_remaining.setter
    def care_years_remaining(self, years: int) -> None:
        self.care_months_remaining = int(years) * 12

    @property
    def setting(self):
        """The current episode's care setting (the nursing home when care was set without one)."""
        if self._setting is not None:
            return self._setting
        return self._setting_named("nursing_home") or self.config.settings[-1]

    def _setting_named(self, name: str):
        return next((setting for setting in self.config.settings if setting.name == name), None)

    @property
    def mortality_multiplier(self) -> float:
        """The hazard ratio on the person's mortality: the setting's while in care, else 1."""
        return self.setting.mortality_multiplier if self.in_care else 1.0

    def receiving_benefits(self, elimination_months: int) -> bool:
        """Whether the person is in care with a policy's elimination period already met."""
        return self.in_care and self.care_months_total >= elimination_months

    # --- draws ---

    @property
    def _rng(self) -> random.Random:
        """The agent's own random stream (not ``model.random``, so which person draws first does not change
        the outcome): keyed by the model seed and the person, or drawn from the model RNG at the first draw
        in an unseeded run."""
        if self._stream is None:
            seed = self.model.initial_seed
            if seed is None:
                self._stream = random.Random(self.model.random.getrandbits(64))
            else:
                person = self.person
                key = (
                    f"{seed}|long_term_care|{person.name}|{person.birth_year}-{person.birth_month}|{person.gender.name}"
                )
                self._stream = random.Random(key)
        return self._stream

    def _annual_hazard(self, age: int) -> float:
        """Annual probability of a care episode starting at the given age."""
        if age < self.config.start_age:
            return 0.0
        bands = self.config.hazard_bands
        for band in bands:
            if age <= band.max_age:
                return band.annual_hazard
        return bands[-1].annual_hazard if bands else 0.0

    def _draw_episode_months(self) -> int:
        """Episode length in whole months: geometric with the configured mean (the ceiling of an
        exponential draw whose rate makes the rounded-up mean exact)."""
        mean_months = self.config.mean_duration_years * 12
        if mean_months <= 1:
            return 1
        rate = -math.log(1 - 1 / mean_months)
        return max(1, math.ceil(self._rng.expovariate(rate)))

    def _draw_setting(self):
        """The setting an episode starts in, by the configured entry shares."""
        draw = self._rng.random()
        cumulative = 0.0
        for setting in self.config.settings:
            cumulative += setting.entry_share
            if draw < cumulative:
                return setting
        return self.config.settings[-1]

    def _medical_inflation_factor(self) -> float:
        """Cumulative medical price level (CPI + premium) from the start year (cached per model)."""
        return medical_inflation_factor(self.model, self.model.year)

    def start_episode(self, setting: str | None = None, *, months: int | None = None) -> None:
        """Start a care episode now in ``setting`` (drawn when None) lasting ``months`` (drawn when None)."""
        chosen = self._draw_setting() if setting is None else self._setting_named(setting)
        if chosen is None:
            raise ValueError(f"unknown long-term-care setting {setting!r}")
        self._setting = chosen
        self.in_care = True
        self.care_months_remaining = self._draw_episode_months() if months is None else int(months)
        self.episodes_started += 1
        self.episode_starts.append((self.model.year, self.model.month))
        self.model.event_log.add(
            Event(
                f"{self.person.name} entered long-term care ({chosen.name.replace('_', ' ')}) at age "
                f"{self.person.age} ({self.care_months_remaining} month(s) expected)"
            )
        )

    # --- Medicaid ---

    def _countable_assets(self, person: Person) -> float:
        """Financial accounts, annuity balances and cash the person owns (the home is exempt)."""
        from ..base_classes import FinancialAccount
        from ..insurance.annuity import Annuity

        total = person.cash
        for registry in self.model.registries.iter_registries():
            for item in registry.get_items(person):
                if (isinstance(item, FinancialAccount) and item.IN_NET_WORTH) or (
                    isinstance(item, Annuity) and item.is_active
                ):
                    total += item.balance
        return total

    def _community_spouse(self) -> Person | None:
        """A living spouse who is not in care themselves."""
        spouse = self.person.spouse
        if spouse is None or spouse.is_deceased:
            return None
        if any(agent.in_care for agent in spouse.long_term_care):
            return None
        return spouse

    def medicaid_eligible(self) -> bool:
        """Whether countable assets are within Medicaid's limit: the person's own, or with a spouse at
        home the couple's less the (CPI-indexed) community spouse resource allowance."""
        rules = self.config.medicaid
        assets = self._countable_assets(self.person)
        spouse = self._community_spouse()
        if spouse is not None:
            cpi = self.model.economy.cumulative_inflation(self.model.year)
            assets += self._countable_assets(spouse) - rules.community_spouse_resource_allowance * cpi
        return assets <= rules.asset_limit

    def _monthly_income(self, person: Person) -> float:
        """The person's income this month counted toward the patient's share."""
        month = self.model.month
        total = 0.0
        for entry in person.income.entries:
            if entry.month != month:
                continue
            if entry.income_type == IncomeType.SS_BENEFIT:
                total += entry.gross
            elif entry.income_type in _PATIENT_INCOME_TYPES:
                total += entry.amount
        return total

    def patient_pay(self, cost: float, *, monthly_income: float, spouse_monthly_income: float | None) -> float:
        """The patient's share of a Medicaid care month: income above the personal needs allowance and
        above what a spouse at home keeps (topping their income up to the CPI-indexed minimum monthly
        maintenance needs allowance), at most the month's cost."""
        rules = self.config.medicaid
        share = monthly_income - rules.personal_needs_allowance_monthly
        if spouse_monthly_income is not None:
            cpi = self.model.economy.cumulative_inflation(self.model.year)
            share -= max(0.0, rules.minimum_monthly_maintenance_needs_allowance * cpi - spouse_monthly_income)
        return min(cost, max(0.0, share))

    # --- charging and claiming ---

    def _charge_care_month(self):
        """Charge this month's care cost (a twelfth of the setting's year) through the bill path, less
        what Medicaid pays."""
        setting = self.setting
        annual = self.config.annual_cost if setting.annual_cost is None else setting.annual_cost
        gross = annual * self._medical_inflation_factor() / 12
        charged = gross
        if self.medicaid and self.medicaid_eligible():
            spouse = self._community_spouse()
            spouse_income = self._last_spouse_income if spouse is not None else None
            charged = self.patient_pay(
                gross, monthly_income=self._last_month_income, spouse_monthly_income=spouse_income
            )
            paid = gross - charged
            if paid > 0 and self.medicaid_paid_this_year == 0:
                self.model.event_log.add(Event(f"Medicaid began paying {self.person.name}'s long-term care"))
            self.medicaid_paid_this_year = snap_money(self.medicaid_paid_this_year + paid)
        self.care_months_total += 1
        self._charged_period = self.model.period
        self._months_this_year.append((self.care_months_total, charged))
        self._gross_charged_total += charged
        self.stat_medical_costs = snap_money(self.stat_medical_costs + charged)
        if charged > 0:
            self.person.spending.add_expense(charged, category="long_term_care")
        self.care_months_remaining -= 1
        if self.care_months_remaining <= 0:
            self.in_care = False
            self.model.event_log.add(Event(f"{self.person.name} left long-term care at age {self.person.age}"))

    def _claim_care_year(self):
        """Claim the year's care months against active LTC policies.

        The cost was already charged through the bill path, so the claim only credits the payout
        (``charge_loss=False``). Each policy covers the months after its elimination period, up to its
        benefit for the year and its remaining lifetime maximum; a deductible reduces the payout per
        the claim machinery's single-deductible convention.
        """
        months, self._months_this_year = self._months_this_year, []
        if not months:
            return
        payout = 0.0
        for policy in self.model.registries.general_insurance_policies.get_items(self.person):
            if policy.insurance_type != InsuranceType.LONG_TERM_CARE or not policy.is_coverage_active:
                continue
            eligible = sum(charged for number, charged in months if number > policy.elimination_months)
            claimable = min(eligible, policy.claim_limit, policy.lifetime_benefit_remaining)
            if claimable <= 0:
                continue
            claim = policy.file_claim(claimable, "Long-term care", charge_loss=False)
            if claim is not None:
                payout += claim.payout_amount
        self.stat_medical_costs = max(0.0, self.stat_medical_costs - payout)

    def settle_at_death(self) -> None:
        """Claim the year's care months before the estate is valued (the agent is then retired). A death in
        pre_step comes after this month's charge, which dies unpaid with the person's bills: it is not
        claimed."""
        if self._charged_period == self.model.period and self._months_this_year:
            _, charged = self._months_this_year.pop()
            self._gross_charged_total -= charged
            self.stat_medical_costs = max(0.0, self.stat_medical_costs - charged)
        self._claim_care_year()

    # --- stages ---

    def on_year_start(self):
        self._months_this_year = []
        self.medicaid_paid_this_year = 0.0

    def pre_step(self):
        if self.person.is_deceased:
            return
        if not self.in_care:
            age = self.person.age
            if age >= self.config.start_age and self._rng.random() <= monthly_hazard(self._annual_hazard(age)):
                self.start_episode()
            else:
                return
        self._charge_care_month()

    def post_step(self):
        if self.person.is_deceased or not self.medicaid:
            return
        self._last_month_income = self._monthly_income(self.person)
        spouse = self.person.spouse
        self._last_spouse_income = self._monthly_income(spouse) if spouse is not None else 0.0

    def on_year_end(self):
        if self.person.is_deceased:
            return
        self._claim_care_year()

    def _repr_html_(self):
        return (
            "<b>Long-Term Care</b><ul>"
            f"<li>Person: {self.person.name}</li>"
            f"<li>In care: {self.in_care}</li>"
            f"<li>Episodes: {self.episodes_started}</li>"
            f"<li>This year's net cost: ${self.stat_medical_costs:,.0f}</li>"
            "</ul>"
        )
