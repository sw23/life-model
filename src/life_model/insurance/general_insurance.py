# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html
from enum import Enum
from typing import cast

from ..deprecated_names import deprecated_arguments
from ..ledger import FlowKind
from ..model import Event, LifeModel, LifeModelAgent, month_index, snap_money
from ..people.person import Person
from ..tax.income import IncomeType


class InsuranceType(Enum):
    """Types of insurance coverage"""

    AUTO = "Auto"
    HOME = "Home"
    HEALTH = "Health"
    DISABILITY = "Disability"
    UMBRELLA = "Umbrella"
    RENTERS = "Renters"
    FLOOD = "Flood"
    EARTHQUAKE = "Earthquake"
    LONG_TERM_CARE = "Long Term Care"


class ClaimStatus(Enum):
    """Status of insurance claims"""

    PENDING = "Pending"
    APPROVED = "Approved"
    DENIED = "Denied"
    SETTLED = "Settled"


class InsuranceClaim:
    """Represents an insurance claim"""

    def __init__(self, claim_id: str, amount: float, description: str, claim_date: int, deductible: float = 0.0):
        self.claim_id = claim_id
        self.amount = amount
        self.description = description
        self.claim_date = claim_date
        self.deductible = deductible
        self.status = ClaimStatus.PENDING
        self.payout_amount = 0.0
        self.settlement_date: int | None = None


class Insurance(LifeModelAgent):
    @deprecated_arguments(
        {"person": "owner", "annual_premium": "premium_annual", "premium_increase_rate": "premium_increase_pct"}
    )
    def __init__(
        self,
        owner: Person,
        insurance_type: InsuranceType,
        company: str,
        premium_annual: float,
        coverage_amount: float,
        deductible: float = 0,
        coverage_start_age: int | None = None,
        coverage_end_age: int | None = None,
        premium_increase_pct: float | None = None,
        max_claims_per_year: int | None = None,
        *,
        oop_max_annual: float | None = None,
        coinsurance_pct: float | None = None,
        benefit_pct: float | None = None,
        benefit_max_monthly: float | None = None,
        elimination_months: int = 3,
        benefit_end_age: float | None = None,
        benefits_taxable: bool = False,
        marketplace=None,
    ):
        """Models insurance coverage for a person

        Args:
            owner: The person who owns this insurance (``person=`` is deprecated)
            insurance_type: Type of insurance
            company: Insurance company name
            premium_annual: Annual premium cost (``annual_premium=`` is deprecated)
            coverage_amount: Coverage amount/limit
            deductible: Insurance deductible amount
            coverage_start_age: Age when coverage starts (None for immediate)
            coverage_end_age: Age when coverage ends (None for lifetime)
            premium_increase_pct: Annual premium increase percentage. Configured default if None
                (``premium_increase_rate=`` is deprecated).
            max_claims_per_year: Maximum claims allowed per year. Configured default if None.
            oop_max_annual: HEALTH: the out-of-pocket maximum per year (keyword-only; Plan 27 D9). With
                it or ``coinsurance_pct`` the policy caps the person's ``MedicalCosts``: they pay the
                year's costs up to ``deductible``, then ``coinsurance_pct`` of the rest, at most
                ``oop_max_annual``.
            coinsurance_pct: HEALTH: the person's share of costs above the deductible (100 when unset).
            benefit_pct: DISABILITY: the share of pre-disability pay replaced (Plan 27; e.g. 60).
            benefit_max_monthly: DISABILITY: the monthly benefit cap.
            elimination_months: DISABILITY: months from the disability before benefits start.
            benefit_end_age: DISABILITY: age benefits stop (``coverage_end_age``, else 65, when unset).
            benefits_taxable: DISABILITY: True when the premiums were paid by the employer or pre-tax
                (benefits are then taxable income, IRC §104(a)(3), §105(a)); False (default): an
                individually paid policy, whose benefits are tax-free.
            marketplace: HEALTH bought on the ACA marketplace
                (:class:`~life_model.tax.ptc.MarketplaceCoverage`; keyword-only, Plan 31 task 6): the premium
                is paid a twelfth a month while coverage is active, net of any advance premium tax credit,
                and the year's premium tax credit is figured on the return (Form 8962).
        """
        person, annual_premium, premium_increase_rate = owner, premium_annual, premium_increase_pct
        super().__init__(cast(LifeModel, person.model))
        self.model: LifeModel = cast("LifeModel", self.model)
        general_config = self.model.config.insurance.general
        if premium_increase_rate is None:
            premium_increase_rate = general_config.default_premium_increase_rate
        if max_claims_per_year is None:
            max_claims_per_year = general_config.default_max_claims_per_year
        self.person = person
        self.insurance_type = insurance_type
        self.company = company
        self.annual_premium = annual_premium
        self.base_annual_premium = annual_premium
        self.coverage_amount = coverage_amount
        self.deductible = deductible
        self.coverage_start_age = coverage_start_age or person.age
        self.coverage_end_age = coverage_end_age
        self.premium_increase_rate = premium_increase_rate
        self.max_claims_per_year = max_claims_per_year

        # State tracking
        self.is_active = True
        self.policy_start_year = self.model.year
        self.claims_history: list[InsuranceClaim] = []
        self.claims_this_year = 0

        # Statistics tracking
        self.stat_premiums_paid = 0.0
        self.stat_claims_filed = 0
        self.stat_claims_paid_out = 0.0
        self.stat_deductibles_paid = 0.0

        self.oop_max_annual = oop_max_annual
        self.coinsurance_pct = coinsurance_pct
        self.benefit_pct = benefit_pct
        self.benefit_max_monthly = benefit_max_monthly
        self.elimination_months = elimination_months
        self.benefit_end_age = benefit_end_age
        self.benefits_taxable = benefits_taxable
        #: DISABILITY: the claim's ``(month index it pays from, monthly benefit)`` once disabled.
        self.disability_claim: tuple[int, float] | None = None
        self.stat_disability_benefits = 0.0
        if marketplace is not None and insurance_type != InsuranceType.HEALTH:
            raise ValueError("marketplace coverage is a HEALTH policy")
        self.marketplace = marketplace
        #: This year's covered months: ``(enrollment premium, SLCSP premium, advance credit)`` (Form 1095-A).
        self.ptc_months: list[tuple[float, float, float]] = []
        self._advance_estimate: tuple[int, float] | None = None

        # Register with model
        self.model.registries.general_insurance_policies.register(person, self)

    @property
    def is_coverage_active(self) -> bool:
        """Check if coverage is currently active based on age"""
        if not self.is_active:
            return False
        if self.person.age < self.coverage_start_age:
            return False
        return not (self.coverage_end_age and self.person.age > self.coverage_end_age)

    @property
    def years_active(self) -> int:
        """Years the policy has been active"""
        return self.model.year - self.policy_start_year

    # --- health: cost sharing (Plan 27 D9) ---

    @property
    def caps_medical_costs(self) -> bool:
        """Whether this is a HEALTH policy with cost sharing that limits the person's medical costs."""
        return self.insurance_type == InsuranceType.HEALTH and (
            self.oop_max_annual is not None or self.coinsurance_pct is not None
        )

    def out_of_pocket(self, gross: float) -> float:
        """The person's share of ``gross`` covered costs in a year: the deductible, then coinsurance,
        capped at the out-of-pocket maximum."""
        share = 1.0 if self.coinsurance_pct is None else self.coinsurance_pct / 100
        paid = min(gross, self.deductible) + share * max(0.0, gross - self.deductible)
        return paid if self.oop_max_annual is None else min(paid, self.oop_max_annual)

    # --- disability: income replacement ---

    def start_disability_claim(self, monthly_pay: float | None = None) -> float:
        """Open a disability claim now: the benefit (``benefit_pct`` of ``monthly_pay``, default the
        person's current base pay, up to ``benefit_max_monthly``) is paid monthly from the end of the
        elimination period. Returns the monthly benefit (0 when the policy is not disability income)."""
        if self.insurance_type != InsuranceType.DISABILITY or not self.benefit_pct or not self.is_coverage_active:
            return 0.0
        if monthly_pay is None:
            monthly_pay = sum(job.salary.base for job in self.person.jobs if not job.retired) / 12
        benefit = monthly_pay * self.benefit_pct / 100
        if self.benefit_max_monthly is not None:
            benefit = min(benefit, self.benefit_max_monthly)
        self.disability_claim = (month_index(self.model.year, self.model.month) + self.elimination_months, benefit)
        self.model.event_log.add(
            Event(
                f"{self.person.name} filed a disability claim with {self.company}: ${benefit:,.0f}/month after "
                f"{self.elimination_months} months"
            )
        )
        return benefit

    def _pay_disability_benefit(self) -> None:
        if self.disability_claim is None or self.person.is_deceased:
            return
        start, benefit = self.disability_claim
        end_age = self.benefit_end_age if self.benefit_end_age is not None else (self.coverage_end_age or 65)
        if month_index(self.model.year, self.model.month) < start or self.person.age_years_fractional >= end_age:
            return
        if self.benefits_taxable:
            self.person.income.add(IncomeType.ORDINARY, benefit, source="disability_benefits")
        self.person.receive_cash(
            benefit, source=f"{self.company} (disability insurance)", kind=FlowKind.BENEFIT, cause="disability benefit"
        )
        self.stat_disability_benefits = snap_money(self.stat_disability_benefits + benefit)

    def pay_premium(self) -> bool:
        """Charge the annual premium through the tax unit's bill path (once a year, in the first
        month of the year).

        The premium is added to the person's spending (``spending.add_expense``) so it is paid with
        that month's bills through the household waterfall — a cash-poor retiree draws a 401k to
        cover it — and it is reflected in ``stat_money_spent``.

        Solvency is resolved at settlement: a unit-wide shortfall becomes debt (as with any other
        bill). A single missed payment does not lapse the policy — an always-paid-if-solvent
        simplification (documented).

        Returns True when the premium was charged (coverage active), else False.
        """
        if not self.is_coverage_active:
            return False

        self.person.spending.add_expense(self.annual_premium, category="insurance_premium")
        self.stat_premiums_paid += self.annual_premium
        self.premium_paid_year = (self.model.year, self.annual_premium)
        return True

    def file_claim(self, claim_amount: float, description: str, *, charge_loss: bool = True) -> InsuranceClaim | None:
        """File an insurance claim.

        Args:
            claim_amount: The size of the covered loss being claimed.
            description: Description of the claim.
            charge_loss: When True (default) the person incurs the loss from their bank at claim
                time (single-deductible convention). Pass False when the loss has already been
                charged elsewhere (e.g. LTC care costs routed through the bill path)
                so only the payout is credited.
        """
        if not self.is_coverage_active:
            return None

        if self.claims_this_year >= self.max_claims_per_year:
            self.model.event_log.add(
                Event(f"{self.person.name} cannot file more claims this year ({self.insurance_type.value})")
            )
            return None

        # Create claim
        claim_id = f"{self.insurance_type.value}_{self.model.year}_{len(self.claims_history) + 1}"
        claim = InsuranceClaim(
            claim_id=claim_id,
            amount=claim_amount,
            description=description,
            claim_date=self.model.year,
            deductible=self.deductible,
        )

        self.claims_history.append(claim)
        self.claims_this_year += 1
        self.stat_claims_filed += 1

        # Process claim automatically (simplified)
        self.process_claim(claim, charge_loss=charge_loss)

        self.model.event_log.add(
            Event(f"{self.person.name} filed {self.insurance_type.value} claim for ${claim_amount:,.0f}")
        )
        return claim

    def process_claim(self, claim: InsuranceClaim, *, charge_loss: bool = True) -> bool:
        """Process an insurance claim (see :meth:`file_claim` for ``charge_loss``)."""
        if claim.status != ClaimStatus.PENDING:
            return False

        # Check if claim is within coverage limits
        if claim.amount > self.coverage_amount:
            claim.status = ClaimStatus.DENIED
            self.model.event_log.add(Event(f"{self.person.name}'s claim denied - exceeds coverage limit"))
            return False

        # Calculate payout (simplified approval logic)
        if claim.amount > claim.deductible:
            claim.payout_amount = min(claim.amount - claim.deductible, self.coverage_amount)
            claim.status = ClaimStatus.APPROVED
            claim.settlement_date = self.model.year

            # Single-deductible convention: the person incurs the loss (the full claim amount)
            # and the insurer reimburses it net of the deductible. The net cash effect on the
            # person is therefore exactly the deductible. When the loss was already charged
            # through another path (charge_loss=False), only the payout is credited.
            if charge_loss:
                self.person.deduct_from_bank_accounts(
                    claim.amount,
                    kind=FlowKind.SPENDING,
                    sink=f"insured loss: {claim.description}",
                    cause=f"{self.insurance_type.value} claim",
                )
            self.person.receive_cash(
                claim.payout_amount,
                source=f"{self.company} ({self.insurance_type.value} insurance)",
                kind=FlowKind.BENEFIT,
                cause=f"{self.insurance_type.value} claim payout",
            )
            self.stat_deductibles_paid += claim.deductible
            self.stat_claims_paid_out += claim.payout_amount

            self.model.event_log.add(Event(f"{self.person.name} received ${claim.payout_amount:,.0f} insurance payout"))
            return True
        else:
            claim.status = ClaimStatus.DENIED
            self.model.event_log.add(Event(f"{self.person.name}'s claim denied - below deductible"))
            return False

    def cancel_policy(self):
        """Cancel the insurance policy"""
        self.is_active = False
        self.model.event_log.add(Event(f"{self.person.name} cancelled {self.insurance_type.value} insurance"))

    def update_coverage(self, new_coverage_amount: float, new_deductible: float | None = None):
        """Update coverage amount and optionally deductible"""
        old_coverage = self.coverage_amount
        self.coverage_amount = new_coverage_amount

        if new_deductible is not None:
            self.deductible = new_deductible

        # Adjust premium based on coverage change. Scale the *current* premium (which may have
        # compounded from step() increases) rather than the base, so accumulated increases are
        # preserved.
        coverage_ratio = new_coverage_amount / old_coverage
        self.annual_premium *= coverage_ratio
        self.base_annual_premium *= coverage_ratio

        self.model.event_log.add(
            Event(f"{self.person.name} updated {self.insurance_type.value} coverage to ${new_coverage_amount:,.0f}")
        )

    def get_claim_history(self, year: int | None = None) -> list[InsuranceClaim]:
        """Get claims history, optionally filtered by year"""
        if year is None:
            return self.claims_history.copy()
        return [claim for claim in self.claims_history if claim.claim_date == year]

    def get_total_claims_amount(self, year: int | None = None) -> float:
        """Get total amount of claims filed, optionally for a specific year"""
        claims = self.get_claim_history(year)
        return sum(claim.amount for claim in claims)

    def get_total_payouts(self, year: int | None = None) -> float:
        """Get total payouts received, optionally for a specific year"""
        claims = self.get_claim_history(year)
        return sum(claim.payout_amount for claim in claims if claim.status == ClaimStatus.APPROVED)

    def on_year_end(self):
        """Year end: reset the year's claim count and apply the premium increase for next year."""
        if not self.is_active:
            return

        # Reset yearly claim counter
        self.claims_this_year = 0

        # Apply premium increases
        if self.years_active > 0:
            self.annual_premium *= 1 + self.premium_increase_rate / 100

    def pre_step(self):
        """Pay the annual premium in the first month of each year (January, or the start month); a
        disability claim's monthly benefit (premiums are waived while it is open). Marketplace coverage pays
        a twelfth of the premium each covered month, net of the advance premium tax credit."""
        if self.marketplace is not None:
            self._marketplace_month()
            return
        if self.model.is_year_start and self.is_coverage_active and self.disability_claim is None:
            self.pay_premium()
        self._pay_disability_benefit()

    def _marketplace_month(self) -> None:
        if self.model.is_year_start:
            self.ptc_months = []
        if self.person.is_deceased or not self.is_coverage_active:
            return
        premium = self.annual_premium / 12
        growth = self.annual_premium / self.base_annual_premium if self.base_annual_premium else 1.0
        slcsp = self.marketplace.slcsp_monthly * growth
        advance = self._advance_monthly(premium, slcsp)
        self.ptc_months.append((premium, slcsp, advance))
        self.person.spending.add_expense(premium - advance, category="insurance_premium")
        self.stat_premiums_paid += premium - advance

    def _advance_monthly(self, premium: float, slcsp: float) -> float:
        """This month's advance premium tax credit (1095-A column C)."""
        advance = self.marketplace.advance_monthly
        if advance is None:
            return 0.0
        if advance != "estimate":
            return min(float(advance), premium)
        year = self.model.year
        if self._advance_estimate is None or self._advance_estimate[0] != year:
            self._advance_estimate = (year, self._estimate_advance(premium, slcsp))
        return self._advance_estimate[1]

    def _estimate_advance(self, premium: float, slcsp: float) -> float:
        """The marketplace's estimate: the monthly credit last year's household income would earn (no
        estimate without a prior return)."""
        from ..people.tax_unit import TaxUnit
        from ..tax.household import dependent_counts
        from ..tax.ptc import estimated_advance_monthly

        params = self.model.year_config.tax.federal.premium_tax_credit
        income = self.person.agi_history.get(self.model.year - 1)
        if params is None or income is None:
            return 0.0
        unit = TaxUnit.for_member(self.person)
        counts = dependent_counts(unit)
        size = (2 if unit.filing_status.name == "MARRIED_FILING_JOINTLY" else 1) + counts["ctc"] + counts["other"]
        return estimated_advance_monthly(income, size, premium, slcsp, unit.filing_status, params)

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Type: {self.insurance_type.value}</li>"
        desc += f"<li>Company: {html.escape(self.company)}</li>"
        desc += f"<li>Annual Premium: ${self.annual_premium:,.2f}</li>"
        desc += f"<li>Coverage: ${self.coverage_amount:,.2f}</li>"
        desc += f"<li>Deductible: ${self.deductible:,.2f}</li>"
        desc += f"<li>Status: {'Active' if self.is_coverage_active else 'Inactive'}</li>"
        desc += f"<li>Claims Filed: {self.stat_claims_filed}</li>"
        desc += f"<li>Total Payouts: ${self.stat_claims_paid_out:,.2f}</li>"
        desc += "</ul>"
        return desc
