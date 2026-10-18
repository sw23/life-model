# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base for all configuration models.

    ``extra='forbid'`` on every nested model means a misspelled or unknown key
    anywhere in the defaults or in a scenario override raises a ``ValidationError``
    at load time instead of being silently dropped.
    """

    model_config = ConfigDict(extra="forbid")


class StandardDeductionConfig(StrictModel):
    single: int = Field(ge=0)
    married_filing_jointly: int = Field(ge=0)
    # Optional: HEAD_OF_HOUSEHOLD falls back to `single` when absent, so existing scenarios and
    # the frozen test fixture load unchanged.
    head_of_household: int | None = Field(default=None, ge=0)
    # Optional: MARRIED_FILING_SEPARATELY defaults to half the joint amount (IRC §63(c)(2)).
    married_filing_separately: int | None = Field(default=None, ge=0)


class TaxBracketsConfig(StrictModel):
    single: list[list[int | float]]
    married_filing_jointly: list[list[int | float]]
    # Optional: HEAD_OF_HOUSEHOLD falls back to `single` when absent.
    head_of_household: list[list[int | float]] | None = None
    # Optional: MARRIED_FILING_SEPARATELY defaults to the joint brackets with every threshold halved,
    # which is how the separate-return table is defined (IRC §1(d)); 2026's published separate
    # table (Rev. Proc. 2025-32: 37% above $384,350 = $768,700 / 2) matches.
    married_filing_separately: list[list[int | float]] | None = None


class NIITConfig(StrictModel):
    """Net investment income surtax (IRC §1411).

    The thresholds are written into the statute and have never been inflation-indexed, so they are
    deliberately kept out of the yearly ``tax_years`` projection path — indexing them would erase
    the real fiscal drag the statute produces.
    """

    # vintage: statutory, source: IRC §1411 (rate and thresholds; not inflation-indexed)
    rate: float = Field(default=3.8, ge=0, le=100)
    single: int = Field(default=200000, ge=0)
    married_filing_jointly: int = Field(default=250000, ge=0)
    head_of_household: int = Field(default=200000, ge=0)
    married_filing_separately: int = Field(default=125000, ge=0)

    def threshold_for(self, filing_status) -> int:
        """MAGI threshold above which the surtax applies, for a filing status."""
        if filing_status.value == 2:
            return self.married_filing_jointly
        if filing_status.value == 3:
            return self.head_of_household
        if filing_status.value == 4:
            return self.married_filing_separately
        return self.single


def _default_capital_gains_brackets() -> "TaxBracketsConfig":
    """Long-term capital gains / qualified dividend brackets, used when a config omits them.

    Keeping these as a default (rather than a required key) is what lets every existing config
    file and scenario continue to load unchanged.
    """
    # vintage: 2026, source: IRS Rev. Proc. 2025-32 §3.03
    return TaxBracketsConfig(
        single=[[0, 49450, 0], [49451, 545500, 15], [545501, float("inf"), 20]],
        married_filing_jointly=[[0, 98900, 0], [98901, 613700, 15], [613701, float("inf"), 20]],
        head_of_household=[[0, 66200, 0], [66201, 579600, 15], [579601, float("inf"), 20]],
    )


class SeniorDeductionConfig(StrictModel):
    """OBBBA's temporary deduction for people 65 and older (taken whether or not one itemizes).

    Each eligible individual gets ``amount``, reduced by ``phaseout_rate`` percent of the return's
    MAGI above the filing-status threshold. Married couples must file jointly to claim it.
    """

    # vintage: statutory, source: OBBBA §70103 (IRC §151(d)(5)(C)); tax years 2025-2028
    amount: int = Field(default=6000, ge=0)
    age: int = Field(default=65, ge=0)
    first_year: int = 2025
    last_year: int = 2028
    phaseout_rate: float = Field(default=6.0, ge=0, le=100)
    phaseout_start_single: int = Field(default=75000, ge=0)
    phaseout_start_married_filing_jointly: int = Field(default=150000, ge=0)


class CharitableConfig(StrictModel):
    """Charitable deduction limits: the AGI limits on cash and appreciated property, and the OBBBA
    changes from 2026 (the non-itemizer deduction, the 0.5%-of-AGI floor and the 2/37 limit on
    itemized deductions). Every field is statutory (not inflation-indexed)."""

    # vintage: statutory, source: IRC §170(b)(1)(G) 60% cash limit (made permanent by OBBBA);
    # §170(d)(1) five-year carryover of the excess
    cash_agi_limit_percent: float = Field(default=60.0, ge=0, le=100)
    carryforward_years: int = Field(default=5, ge=0)
    # vintage: statutory, source: IRC §170(b)(1)(C)(i): long-term capital gain property given to a
    # public charity (deducted at fair market value) is limited to 30% of AGI; §170(b)(1)(C)(ii) carryover.
    property_agi_limit_percent: float = Field(default=30.0, ge=0, le=100)
    # vintage: statutory, source: OBBBA (P.L. 119-21) §70424, IRC §170(p): non-itemizers deduct cash gifts to
    # public charities (not donor-advised funds) up to $1,000 ($2,000 joint), tax years after 2025. None: off.
    non_itemizer_first_year: int | None = None
    non_itemizer_limit_single: float = Field(default=1000, ge=0)
    non_itemizer_limit_joint: float = Field(default=2000, ge=0)
    # vintage: statutory, source: OBBBA §70425, IRC §170(b)(1)(I): itemized charitable deductions are
    # allowed only to the extent they exceed 0.5% of the contribution base (AGI), tax years after 2025.
    floor_first_year: int | None = None
    floor_percent: float = Field(default=0.5, ge=0, le=100)
    # vintage: statutory, source: OBBBA §70111, IRC §68: itemized deductions are reduced by 2/37 of the
    # lesser of the deductions or the taxable income (plus the deductions) above the 37% bracket start,
    # tax years after 2025. None: off.
    itemized_limit_first_year: int | None = None


class SaltCapStatuteConfig(StrictModel):
    """How the SALT cap moves after the last published ``tax_years`` entry: statutory, not indexed to
    inflation. OBBBA §70120 (IRC §164(b)(7)): the cap and the phase-down threshold grow 1% a year
    through 2029; from 2030 the cap reverts to $10,000 with no phase-down."""

    # vintage: statutory, source: OBBBA (P.L. 119-21) §70120, IRC §164(b)(7)
    annual_increase_percent: float = Field(default=1.0, ge=0)
    increase_through_year: int = 2029
    reversion_year: int = 2030
    reversion_cap: float = Field(default=10000, ge=0)


class SaltCapYear(StrictModel):
    """One year's SALT cap (§164(b)(6)/(7)); see ``FederalTaxConfig.salt_deduction_cap``."""

    cap: float = Field(ge=0)
    phaseout_threshold: float | None = Field(default=None, ge=0)


class AdditionalStandardDeduction(StrictModel):
    """IRC §63(f) additional standard deduction per condition (age 65+; blindness is not modeled):
    ``married`` on a joint or separate return, ``unmarried`` for single and head of household."""

    married: int = Field(ge=0)
    unmarried: int = Field(ge=0)


class Phaseout(StrictModel):
    """A MAGI range over which a benefit phases out linearly: full below ``start``, none from ``end``."""

    start: float = Field(ge=0)
    end: float = Field(ge=0)

    def fraction_allowed(self, magi: float) -> float:
        """Share of the benefit left at ``magi`` (1 below ``start``, 0 from ``end``)."""
        if magi <= self.start:
            return 1.0
        if magi >= self.end or self.end <= self.start:
            return 0.0
        return (self.end - magi) / (self.end - self.start)


class EITCYear(StrictModel):
    """Earned income credit (IRC §32) for 0, 1, 2 and 3+ qualifying children (four-element lists).

    The dollar amounts are the year's published table (Rev. Proc. §32(b) table); the percentages are
    statutory (§32(b)(1)). ``phaseout_start`` is for every status but joint (``phaseout_start_joint``).
    """

    earned_income_amount: list[float] = Field(min_length=4, max_length=4)
    max_credit: list[float] = Field(min_length=4, max_length=4)
    phaseout_start: list[float] = Field(min_length=4, max_length=4)
    phaseout_start_joint: list[float] = Field(min_length=4, max_length=4)
    investment_income_limit: float = Field(ge=0)
    # vintage: statutory, source: IRC §32(b)(1)
    credit_percent: list[float] = Field(default=[7.65, 34.0, 40.0, 45.0], min_length=4, max_length=4)
    phaseout_percent: list[float] = Field(default=[7.65, 15.98, 21.06, 21.06], min_length=4, max_length=4)


class DependentCareYear(StrictModel):
    """Child and dependent care credit (IRC §21) and the dependent care assistance exclusion (§129).

    The credit rate starts at ``max_rate`` and drops one point per ``step`` (or fraction) of AGI over
    ``first_start``, not below ``first_floor``; from 2026 (OBBBA §70405) it then drops one more point
    per ``second_step`` (``second_step_joint``) over ``second_start`` (``second_start_joint``), not
    below ``second_floor``. Not inflation-indexed.
    """

    exclusion_limit: float = Field(ge=0)  # §129(a)(2)(A); half on a separate return
    expense_limit_one: float = Field(default=3000, ge=0)  # §21(c)(1)
    expense_limit_two: float = Field(default=6000, ge=0)  # §21(c)(2)
    max_rate: float = Field(ge=0, le=100)
    first_floor: float = Field(ge=0, le=100)
    first_start: float = Field(default=15000, ge=0)
    step: float = Field(default=2000, gt=0)
    second_start: float | None = None
    second_start_joint: float | None = None
    second_step: float = Field(default=2000, gt=0)
    second_step_joint: float = Field(default=4000, gt=0)
    second_floor: float = Field(default=20.0, ge=0, le=100)


class SaversCreditYear(StrictModel):
    """Retirement savings contributions credit (IRC §25B): AGI ceilings of the 50%, 20% and 10% tiers by
    filing status; ``rates`` and ``max_contribution`` (per person) are statutory."""

    joint: list[float] = Field(min_length=3, max_length=3)
    head_of_household: list[float] = Field(min_length=3, max_length=3)
    other: list[float] = Field(min_length=3, max_length=3)
    rates: list[float] = Field(default=[50.0, 20.0, 10.0], min_length=3, max_length=3)
    max_contribution: float = Field(default=2000, ge=0)


class IRAPhaseoutsYear(StrictModel):
    """Traditional IRA deduction (§219(g)) and Roth IRA contribution (§408A(c)(3)) MAGI phase-outs.

    ``traditional_*`` apply to an active participant in a workplace plan (single/HoH, joint) and to a
    non-participant whose spouse participates (``traditional_spouse_covered``). A separate return
    phases out over ``separate`` (statutory $0-$10,000) for both.
    """

    traditional_single: Phaseout
    traditional_joint: Phaseout
    traditional_spouse_covered: Phaseout
    roth_single: Phaseout
    roth_joint: Phaseout
    separate: Phaseout = Field(default_factory=lambda: Phaseout(start=0, end=10000))


class StudentLoanPhaseoutYear(StrictModel):
    """Student loan interest deduction (§221(b)(2)) MAGI phase-out by filing status (not allowed on a
    separate return)."""

    single: Phaseout
    joint: Phaseout


class AMTYear(StrictModel):
    """Alternative minimum tax (IRC §55): exemption, its phase-out (``phaseout_rate`` percent of AMTI
    over the threshold: 25%, 50% from 2026 under OBBBA §70107), and the 26%/28% breakpoint."""

    exemption_single: float = Field(ge=0)
    exemption_joint: float = Field(ge=0)
    exemption_separate: float = Field(ge=0)
    phaseout_start_single: float = Field(ge=0)
    phaseout_start_joint: float = Field(ge=0)
    phaseout_start_separate: float = Field(ge=0)
    phaseout_rate: float = Field(default=25.0, ge=0, le=100)
    breakpoint: float = Field(ge=0)
    breakpoint_separate: float = Field(ge=0)
    # vintage: statutory, source: IRC §55(b)(1)(A)
    low_rate: float = Field(default=26.0, ge=0, le=100)
    high_rate: float = Field(default=28.0, ge=0, le=100)


class QBIYear(StrictModel):
    """Qualified business income deduction (IRC §199A): taxable-income thresholds and phase-in range
    widths (50k/100k through 2025; 75k/150k from 2026, OBBBA §70105), and the 2026+ minimum deduction
    for at least ``minimum_qbi`` of active QBI."""

    threshold_single: float = Field(ge=0)
    threshold_joint: float = Field(ge=0)
    threshold_separate: float = Field(ge=0)
    phase_in_single: float = Field(ge=0)
    phase_in_joint: float = Field(ge=0)
    rate: float = Field(default=20.0, ge=0, le=100)
    minimum_deduction: float = Field(default=0.0, ge=0)
    minimum_qbi: float = Field(default=1000.0, ge=0)


class KiddieTaxYear(StrictModel):
    """Kiddie tax (IRC §1(g)) amounts: ``base_amount`` is the §1(g)(4)(A)(ii)(I) amount ($1,300 in 2024).
    Form 8814 (the parents' election, §1(g)(7)) excludes the first ``base_amount`` of the child's interest
    and dividends, taxes the next ``base_amount`` at 10%, and adds the rest to the parents' income; it
    is open while the child's gross income is under 10 x ``base_amount``."""

    base_amount: float = Field(ge=0)


class LTCPremiumLimit(StrictModel):
    """§213(d)(10) eligible long-term care premium limit for an attained age up to ``max_age``."""

    max_age: int = Field(ge=0)
    limit: float = Field(ge=0)


class EducationCreditsConfig(StrictModel):
    """American opportunity and lifetime learning credits (IRC §25A). Statutory and no longer indexed
    (P.L. 116-260 §104 repealed §25A(h))."""

    # vintage: statutory, source: IRC §25A(b)(1), (b)(2)(C), (i)(5)-(6)
    aotc_full_expenses: float = Field(default=2000, ge=0)  # 100% of the first $2,000
    aotc_partial_expenses: float = Field(default=2000, ge=0)  # 25% of the next $2,000
    aotc_partial_rate: float = Field(default=25.0, ge=0, le=100)
    aotc_refundable_percent: float = Field(default=40.0, ge=0, le=100)
    aotc_max_years: int = Field(default=4, ge=0)
    # vintage: statutory, source: IRC §25A(c)(1)
    llc_expense_limit: float = Field(default=10000, ge=0)
    llc_rate: float = Field(default=20.0, ge=0, le=100)
    # vintage: statutory, source: IRC §25A(d) (both credits; not indexed since 2021)
    phaseout_single: Phaseout = Field(default_factory=lambda: Phaseout(start=80000, end=90000))
    phaseout_joint: Phaseout = Field(default_factory=lambda: Phaseout(start=160000, end=180000))


class CreditStatuteConfig(StrictModel):
    """Statutory switches of the credits computed in ``tax/credits.py``."""

    # vintage: statutory, source: SECURE 2.0 Act (P.L. 117-328) §103(e)-(f): from tax year 2027 the §25B
    # credit covers only ABLE contributions (the Saver's Match, §6433, replaces it; not modeled).
    savers_credit_last_year: int = 2026
    # vintage: statutory, source: IRC §32(c)(1)(A)(ii)(II): a worker without a qualifying child must be at
    # least 25 and under 65.
    eitc_min_age_no_children: int = 25
    eitc_max_age_no_children: int = 64
    # vintage: statutory, source: IRC §25B(c)(1): at least 18 (and not a dependent or full-time student).
    savers_credit_min_age: int = 18
    # None (a config without it, such as the frozen test fixture) leaves the education credits off.
    education: EducationCreditsConfig | None = None


class SelfEmploymentTaxConfig(StrictModel):
    """Self-employment tax (IRC §1401-1402, Schedule SE) and the SEP / solo 401(k) employer limit."""

    # vintage: statutory, source: IRC §1402(a)(12) (Schedule SE line 4a: 92.35%); §1401(a)-(b) rates;
    # §1402(b)(2) $400 minimum
    net_earnings_percent: float = Field(default=92.35, ge=0, le=100)
    social_security_rate: float = Field(default=12.4, ge=0, le=100)
    medicare_rate: float = Field(default=2.9, ge=0, le=100)
    minimum_net_earnings: float = Field(default=400, ge=0)
    # vintage: statutory, source: IRC §404(h)(1)(C), §402(h)(2)(A): SEP contributions up to 25% of
    # compensation (for a self-employed person, net earnings after the SE-tax deduction and the
    # contribution itself: Pub. 560 rate table, 25% -> 20%)
    max_plan_rate: float = Field(default=25.0, ge=0, le=100)


class FederalTaxConfig(StrictModel):
    standard_deduction: StandardDeductionConfig
    tax_brackets: TaxBracketsConfig
    # Preferential rate schedule for long-term capital gains and qualified dividends. Shares the
    # ordinary ``[lower, upper, rate]`` bracket shape so the same marginal engine applies.
    capital_gains: TaxBracketsConfig = Field(default_factory=_default_capital_gains_brackets)
    niit: NIITConfig = Field(default_factory=NIITConfig)
    # Capital loss deductible against ordinary income each year; the remainder carries forward.
    # vintage: statutory, source: IRC §1211(b) / IRS Topic 409 (not inflation-indexed since 1978)
    capital_loss_ordinary_offset: int = Field(default=3000, ge=0)
    # Itemized-deduction limits (defaults let existing configs load without these keys).
    # vintage: 2026, source: IRC §163(h)(3) TCJA acquisition-debt limit; §164(b)(6) SALT cap (OBBBA).
    mortgage_interest_debt_limit: int = Field(default=750000, ge=0)
    # SALT cap per return (§164(b)(6)/(7)). Simulated years read the year's values from ``tax_years``
    # (``salt``): the cap, and from 2025 (OBBBA) its phase-down by ``salt_phaseout_rate`` percent of
    # MAGI over ``salt_phaseout_threshold``, not below ``salt_cap_floor``. A separate return gets
    # half of the cap, the threshold and the floor. None threshold: no phase-down.
    salt_deduction_cap: float = Field(default=40000, ge=0)
    salt_phaseout_threshold: float | None = Field(default=None, ge=0)
    salt_phaseout_rate: float = Field(default=30.0, ge=0, le=100)
    salt_cap_floor: float = Field(default=10000, ge=0)
    salt_cap_statute: SaltCapStatuteConfig = Field(default_factory=SaltCapStatuteConfig)
    senior_deduction: SeniorDeductionConfig = Field(default_factory=SeniorDeductionConfig)
    charitable: CharitableConfig = Field(default_factory=CharitableConfig)
    credits: CreditStatuteConfig = Field(default_factory=CreditStatuteConfig)
    # Year-indexed parameters of the Plan 31 credits, deductions and regimes. They live in ``tax_years``
    # only (no static mirror): simulated years read them through ``model.year_config``, where
    # ``FinancialConfig.year_view`` copies the year's values in. None (a config without them, such as the
    # frozen test fixture) leaves the feature off.
    additional_standard_deduction: AdditionalStandardDeduction | None = None
    eitc: EITCYear | None = None
    dependent_care: DependentCareYear | None = None
    savers_credit: SaversCreditYear | None = None
    ira_phaseouts: IRAPhaseoutsYear | None = None
    student_loan_phaseout: StudentLoanPhaseoutYear | None = None
    amt: AMTYear | None = None
    qbi: QBIYear | None = None
    kiddie_tax: KiddieTaxYear | None = None
    qcd_limit: float | None = Field(default=None, ge=0)
    ltc_premium_limits: list[LTCPremiumLimit] | None = None
    #: §401(a)(17) compensation limit (caps the pay a SEP / solo 401(k) contribution is figured on).
    compensation_limit: float | None = Field(default=None, ge=0)
    # Estate transfer parameters (defaults let existing configs load without these keys).
    # The unified exemption shelters estate value below it; transfers to a surviving spouse are
    # fully sheltered by the unlimited marital deduction regardless of the exemption.
    # vintage: 2026, source: IRC §2010 unified credit (post-OBBBA ~$15M); §2001(c) top rate 40%.
    estate_tax_exemption: int = Field(default=15000000, ge=0)
    estate_tax_rate: float = Field(default=40.0, ge=0, le=100)


# Two-letter USPS codes for the 50 states + DC. Pack keys must be one of these or ``DEFAULT``;
# an unknown code fails validation at load (unknown state → ValidationError).
US_STATE_CODES = frozenset(
    {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
        "DC",
    }
)

DEFAULT_STATE_KEY = "DEFAULT"


class StateStandardDeductionConfig(StrictModel):
    """State standard deduction by filing status (defaults to 0 — no deduction)."""

    single: int = Field(default=0, ge=0)
    married_filing_jointly: int = Field(default=0, ge=0)


class StateTaxPack(StrictModel):
    """State income-tax parameters for a single state.

    Exactly one of ``flat_rate`` or ``brackets`` must be set. ``flat_rate`` of ``0`` models a
    no-income-tax state (TX/FL/WA). ``brackets`` mirrors the federal ``[lower, upper, rate]`` shape,
    keyed by filing status (``single`` required; other statuses fall back to ``single``).
    """

    flat_rate: float | None = Field(default=None, ge=0, le=100)
    brackets: dict[str, list[list[int | float]]] | None = None
    standard_deduction: StateStandardDeductionConfig = Field(default_factory=StateStandardDeductionConfig)
    # Whether pre-tax retirement distributions (401k/IRA withdrawals, RMDs) are taxed by the state.
    # PA and IL exempt them.
    retirement_income_taxable: bool = True
    # Whether Social Security benefits are taxed by the state. Most states exempt them.
    ss_taxable: bool = False
    # Whether capital gains and qualified dividends are taxed by the state. The large majority of
    # states tax them as ordinary income, so this defaults to True and only the exceptions set it.
    capital_gains_taxable: bool = True

    @model_validator(mode="after")
    def _validate_pack(self) -> "StateTaxPack":
        if self.flat_rate is not None and self.brackets is not None:
            raise ValueError("StateTaxPack: set exactly one of 'flat_rate' or 'brackets', not both")
        if self.flat_rate is None and self.brackets is None:
            raise ValueError("StateTaxPack: one of 'flat_rate' or 'brackets' must be set (use flat_rate: 0 for no tax)")
        if self.brackets is not None:
            if "single" not in self.brackets:
                raise ValueError("StateTaxPack.brackets must define at least the 'single' filing status")
            valid_statuses = {"single", "married_filing_jointly", "head_of_household"}
            for status, rows in self.brackets.items():
                if status not in valid_statuses:
                    raise ValueError(f"StateTaxPack.brackets: unknown filing status '{status}'")
                self._validate_brackets(status, rows)
        return self

    @staticmethod
    def _validate_brackets(status: str, rows: "list[list[int | float]]") -> None:
        """Reject malformed or gapped brackets.

        Rows follow the federal ``[lower, upper, rate]`` convention where each row's ``lower`` is
        the previous row's ``upper`` + 1 (the half-open marginal engine keys off ``upper``). The
        first row must start at 0 and each subsequent row must be contiguous with the previous.
        """
        if not rows:
            raise ValueError(f"StateTaxPack.brackets['{status}'] must have at least one row")
        prev_upper: float | None = None
        for row in rows:
            if len(row) != 3:
                raise ValueError(f"StateTaxPack.brackets['{status}'] rows must be [lower, upper, rate]")
            lower, upper, rate = row
            if not (0 <= rate <= 100):
                raise ValueError(f"StateTaxPack.brackets['{status}'] rate {rate} out of range [0, 100]")
            if upper <= lower:
                raise ValueError(f"StateTaxPack.brackets['{status}'] row upper {upper} must exceed lower {lower}")
            if prev_upper is None:
                if lower != 0:
                    raise ValueError(f"StateTaxPack.brackets['{status}'] first row must start at lower=0")
            elif lower != prev_upper + 1:
                raise ValueError(
                    f"StateTaxPack.brackets['{status}'] gap: row lower {lower} != previous upper {prev_upper} + 1"
                )
            prev_upper = upper


class StateTaxConfig(StrictModel):
    """State tax configuration: a set of per-state packs plus the resident default.

    The scalar ``tax_rate`` key is supported: when present it synthesizes the ``DEFAULT`` pack as
    a flat rate, so a YAML/scenario that sets only ``tax_rate`` loads as a single flat-rate pack.
    ``tax_rate`` remains readable for callers that want the flat rate directly.
    """

    tax_rate: float | None = Field(default=6.0, ge=0, le=100)
    default_state: str = DEFAULT_STATE_KEY
    packs: dict[str, StateTaxPack] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _synthesize_and_validate(self) -> "StateTaxConfig":
        # The scalar tax_rate is the authoritative source for the DEFAULT flat pack.
        if self.tax_rate is not None:
            self.packs[DEFAULT_STATE_KEY] = StateTaxPack(flat_rate=self.tax_rate)
        for code in self.packs:
            if code != DEFAULT_STATE_KEY and code not in US_STATE_CODES:
                raise ValueError(f"StateTaxConfig: unknown state code '{code}' in packs")
        if self.default_state not in self.packs:
            raise ValueError(
                f"StateTaxConfig.default_state '{self.default_state}' has no matching pack "
                f"(available: {sorted(self.packs)})"
            )
        return self

    def get_pack(self, state: str | None) -> "StateTaxPack":
        """Resolve the pack for a resident.

        Uses the resident's ``state`` when a matching pack exists, otherwise ``default_state``,
        otherwise ``DEFAULT``. Never raises: an unknown residency falls back to the default pack.
        """
        if state and state in self.packs:
            return self.packs[state]
        if self.default_state in self.packs:
            return self.packs[self.default_state]
        return self.packs[DEFAULT_STATE_KEY]

    def resolve_state_code(self, state: str | None) -> str:
        """Return the pack key a resident resolves to (see :meth:`get_pack`)."""
        if state and state in self.packs:
            return state
        if self.default_state in self.packs:
            return self.default_state
        return DEFAULT_STATE_KEY


class MedicareThresholdConfig(StrictModel):
    single: int = Field(ge=0)
    married_filing_jointly: int = Field(ge=0)
    # vintage: statutory, source: IRC §3101(b)(2)(B) (not inflation-indexed)
    married_filing_separately: int = Field(default=125000, ge=0)


class FICATaxConfig(StrictModel):
    social_security_rate: float = Field(ge=0, le=100)
    social_security_max_income: int = Field(ge=0)
    medicare_rate: float = Field(ge=0, le=100)
    medicare_additional_rate: float = Field(ge=0, le=100)
    medicare_additional_rate_threshold: MedicareThresholdConfig


class TaxConfig(StrictModel):
    federal: FederalTaxConfig
    state: StateTaxConfig
    fica: FICATaxConfig
    self_employment: SelfEmploymentTaxConfig = Field(default_factory=SelfEmploymentTaxConfig)


class Job401kContribLimitConfig(StrictModel):
    base: int = Field(ge=0)
    catch_up_age: int = Field(ge=0)
    catch_up_amount: int = Field(ge=0)
    # 415(c) overall annual-additions limit (employee + employer, per employer plan).
    annual_additions_limit: int = Field(ge=0)


class IRAConfig(StrictModel):
    contribution_limit: int = Field(ge=0)
    default_growth_rate: float = Field(ge=0)


class RetirementConfig(StrictModel):
    federal_retirement_age: float = Field(ge=0)
    # Additional tax on early (pre-``federal_retirement_age``) distributions from pre-tax accounts and
    # on non-qualified Roth IRA earnings (IRC §72(t)). Statutory, unindexed.
    early_withdrawal_penalty_rate: float = Field(default=10.0, ge=0, le=100)
    job_401k_contrib_limit: Job401kContribLimitConfig
    ira: IRAConfig
    rmd_distribution_periods: list[list[float]]


class SocialSecurityBenefitTaxationConfig(StrictModel):
    """Statutory (non-indexed) provisional-income thresholds for taxing benefits.

    See IRS Pub. 915. Thresholds have been fixed in statute since 1984/1994.
    """

    lower_threshold_single: int = Field(ge=0)
    upper_threshold_single: int = Field(ge=0)
    lower_threshold_married_filing_jointly: int = Field(ge=0)
    upper_threshold_married_filing_jointly: int = Field(ge=0)
    # A separate filer who lived with their spouse has a base amount of zero (IRC §86(c)(1)(C)(ii)),
    # so benefits are taxable from the first dollar of provisional income.
    lower_threshold_married_filing_separately: int = Field(default=0, ge=0)
    upper_threshold_married_filing_separately: int = Field(default=0, ge=0)
    lower_inclusion_rate: float = Field(ge=0, le=1)
    upper_inclusion_rate: float = Field(ge=0, le=1)


class SocialSecurityConfig(StrictModel):
    min_eligible_credits: int = Field(ge=0)
    max_credits_per_year: int = Field(ge=0)
    max_years_of_income: int = Field(ge=0)
    min_early_retirement_age: int = Field(ge=0)
    normal_retirement_age: int = Field(ge=0)
    max_delayed_retirement_credit_age: int = Field(ge=0)
    delayed_retirement_credit: float = Field(ge=0)

    # QC amount calculation base values
    qc_credit_amount_1978: float
    qc_avg_wage_index_1976: float

    # Configuration for extrapolation beyond available data
    last_avg_wage_index_year: int
    last_avg_wage_index_increase: float
    last_cost_of_living_adj_year: int
    last_bend_points_year: int
    # Long-run assumptions applied for years beyond the published tables.
    long_run_cost_of_living_adj: float = Field(ge=0)
    long_run_bend_point_increase: float = Field(ge=0)

    # Historical data tables
    avg_wage_index: dict[int, float]
    cost_of_living_adj: dict[int, float]
    bend_points: dict[int, list[int]]

    # Provisional-income taxation of benefits
    benefit_taxation: SocialSecurityBenefitTaxationConfig


class BankAccountConfig(StrictModel):
    default_interest_rate: float = Field(ge=0)
    compound_rate: int = Field(ge=1)


class BrokerageAccountConfig(StrictModel):
    default_growth_rate: float
    # Share of the growth rate paid out as qualified dividends rather than accruing as untaxed
    # price appreciation. Defaults to 0 so accounts are pure-appreciation unless opted in.
    dividend_yield: float = Field(default=0.0, ge=0)


class HSAAccountConfig(StrictModel):
    contribution_limit: int = Field(ge=0)
    catch_up_age: int = Field(ge=0)
    catch_up_amount: int = Field(ge=0)
    contribution_limit_family: int = Field(ge=0)
    default_employer_contribution: int = Field(ge=0)
    # Non-medical distributions are ordinary income plus this additional tax below the penalty age
    # (IRC §223(f)(2), (f)(4)). Statutory, unindexed.
    non_medical_penalty_rate: float = Field(default=20.0, ge=0, le=100)
    non_medical_penalty_age: int = Field(default=65, ge=0)


class Plan529Config(StrictModel):
    annual_contribution_limit: int = Field(ge=0)
    lifetime_contribution_limit: int = Field(ge=0)
    default_growth_rate: float = Field(ge=0)
    qualified_expense_penalty: float = Field(ge=0, le=100)


class AccountsConfig(StrictModel):
    bank: BankAccountConfig
    brokerage: BrokerageAccountConfig
    hsa: HSAAccountConfig
    plan_529: Plan529Config


class SurrenderPercentagesConfig(StrictModel):
    early: float = Field(ge=0, le=1)
    standard: float = Field(ge=0, le=1)


class LifeInsuranceConfig(StrictModel):
    default_loan_interest_rate: float = Field(ge=0)
    default_cash_value_growth_rate: float = Field(ge=0)
    default_max_missed_payments: int = Field(ge=0)
    surrender_percentages: SurrenderPercentagesConfig
    # Fraction of the yearly premium that funds cash value for whole-life policies.
    cash_value_premium_fraction_first_year: float = Field(ge=0, le=1)
    cash_value_premium_fraction_later: float = Field(ge=0, le=1)
    # Maximum fraction of available cash value that can be borrowed against.
    loan_to_value_ratio: float = Field(ge=0, le=1)
    # Default term-life premium multipliers by attained age (premium = base x multiplier, linearly
    # interpolated between ages). A modeling assumption shaped like level-term rate curves, not a
    # published table.
    term_age_multipliers: dict[int, float] = Field(
        default_factory=lambda: {
            20: 1.0,
            25: 1.1,
            30: 1.3,
            35: 1.6,
            40: 2.1,
            45: 2.8,
            50: 3.8,
            55: 5.2,
            60: 7.1,
            65: 10.0,
            70: 15.0,
            75: 23.0,
            80: 35.0,
            85: 55.0,
        }
    )


class AnnuityConfig(StrictModel):
    default_interest_rate: float = Field(ge=0)
    default_payout_start_age: int = Field(ge=0)
    default_surrender_charge_years: int = Field(ge=0)
    default_surrender_charge_rate: float = Field(ge=0)
    default_period_certain_years: int = Field(ge=0)
    # Actuarial projection horizon and survival cutoff used by the annuity-factor integration.
    max_projection_age: int = Field(ge=0)
    survival_probability_cutoff: float = Field(gt=0, le=1)


class GeneralInsuranceConfig(StrictModel):
    default_premium_increase_rate: float = Field(ge=0)
    default_max_claims_per_year: int = Field(ge=0)


class InsuranceConfig(StrictModel):
    life: LifeInsuranceConfig
    annuity: AnnuityConfig
    general: GeneralInsuranceConfig


class CreditCardConfig(StrictModel):
    default_interest_rate: float = Field(ge=0)
    default_minimum_payment_percent: float = Field(ge=0, le=100)
    # Dollar floor on the monthly minimum payment (defaults keep existing configs loadable).
    default_minimum_payment_floor: float = Field(default=25.0, ge=0)


class RepaymentAssistancePlanConfig(StrictModel):
    """The Repayment Assistance Plan (RAP), the income-driven plan for federal loans from July 2026.

    Annual payment = ``rate_step_percent`` percent x AGI for each full ``income_step`` of AGI, capped at
    ``max_rate_percent`` percent (1% for $10,001-20,000 ... 10% above $100,000), with ``minimum_annual``
    at or below the first step; less ``dependent_credit_monthly`` per dependent per month, floored
    at ``minimum_monthly``. Interest the payment doesn't cover is waived; if principal falls by less
    than ``principal_match_monthly`` in a month, the government makes up the difference (up to the
    payment). The balance left after ``forgiveness_years`` of payments is forgiven.
    """

    # vintage: 2026, source: One Big Beautiful Bill Act (Repayment Assistance Plan), studentaid.gov
    income_step: int = Field(default=10000, gt=0)
    rate_step_percent: float = Field(default=1.0, ge=0)
    max_rate_percent: float = Field(default=10.0, ge=0, le=100)
    minimum_annual: float = Field(default=120.0, ge=0)
    minimum_monthly: float = Field(default=10.0, ge=0)
    dependent_credit_monthly: float = Field(default=50.0, ge=0)
    principal_match_monthly: float = Field(default=50.0, ge=0)
    forgiveness_years: int = Field(default=30, ge=0)
    # The American Rescue Plan exclusion of forgiven student debt covered discharges before 2026
    # (ARPA §9675); IDR forgiveness after that is ordinary income.
    forgiveness_taxable: bool = True


class StudentLoanConfig(StrictModel):
    # Above-the-line student-loan interest deduction (IRC §221). The MAGI phase-out is not
    # modeled; this is a flat cap. vintage: 2025, source: IRC §221 (statutory, unindexed cap).
    interest_deduction_limit: float = Field(default=2500.0, ge=0)
    repayment_assistance_plan: RepaymentAssistancePlanConfig = Field(default_factory=RepaymentAssistancePlanConfig)


class DebtConfig(StrictModel):
    credit_card: CreditCardConfig
    student_loan: StudentLoanConfig = Field(default_factory=StudentLoanConfig)
    # Annual interest (percent) on bills a household could not pay, carried into the next year as
    # ``Person.debt``. None means the credit-card rate: an unpaid shortfall is effectively financed
    # on a card.
    unpaid_balance_interest_rate: float | None = Field(default=None, ge=0)

    @property
    def effective_unpaid_balance_interest_rate(self) -> float:
        """The configured unpaid-balance rate, or the credit-card rate when unset."""
        if self.unpaid_balance_interest_rate is not None:
            return self.unpaid_balance_interest_rate
        return self.credit_card.default_interest_rate


class Section121ExclusionConfig(StrictModel):
    single: int = Field(default=250000, ge=0)
    married_filing_jointly: int = Field(default=500000, ge=0)


class EstateConfig(StrictModel):
    """Estate-settlement parameters.

    ``inherited_pretax_mode`` controls how a non-spouse beneficiary receives inherited pre-tax
    retirement balances:

    * ``"ten_year"`` (default) — the SECURE Act 10-year rule: the balance moves into an
      :class:`~life_model.account.inherited.InheritedPretaxAccount` that keeps growing and pays out
      an even slice each year over ten years, spreading (and deferring) the beneficiary's tax.
    * ``"lump_sum"`` — the lump-sum simplification: the whole pre-tax balance is distributed to the
      beneficiary and taxed in the death year. Retained for comparability with older frames.
    """

    inherited_pretax_mode: Literal["ten_year", "lump_sum"] = "ten_year"


class HousingConfig(StrictModel):
    """Housing parameters (PMI, transaction costs, capital-gains exclusion).

    All fields have defaults so existing configs without a ``housing`` section still load.
    """

    # PMI: charged yearly as a percentage of the loan balance while loan-to-value exceeds the
    # threshold, then automatically dropped. vintage: 2026, source: typical private-MI rates.
    pmi_rate: float = Field(default=0.5, ge=0)  # percent of loan balance per year
    pmi_ltv_threshold: float = Field(default=80.0, ge=0, le=100)  # percent LTV
    closing_cost_percent: float = Field(default=2.0, ge=0)  # percent of purchase price at buy
    selling_cost_percent: float = Field(default=6.0, ge=0)  # percent of sale price at sell
    # vintage: IRC §121 primary-residence capital-gains exclusion (statutory, unindexed).
    section_121_exclusion: Section121ExclusionConfig = Field(default_factory=Section121ExclusionConfig)


class CTCPhaseoutStartConfig(StrictModel):
    """Modified-AGI thresholds at which the Child Tax Credit begins to phase out, by filing status.

    Statutory and not inflation-indexed (IRC §24(h)(3)). Head of household shares the single
    threshold.
    """

    single: int = Field(default=200000, ge=0)
    married_filing_jointly: int = Field(default=400000, ge=0)
    head_of_household: int = Field(default=200000, ge=0)


class DependentsConfig(StrictModel):
    """Costs of raising children and the child-related tax credits.

    Every field has a default so existing configs/scenarios without a ``dependents`` section
    still load. Cost figures are representative national estimates; credit parameters are
    verified against primary sources (see the YAML vintage comments).
    """

    # Age-banded annual cost of a child (nominal; grown by cumulative inflation in Child.pre_step).
    # vintage: 2024, source: Child Care Aware of America (childcare); USDA/Brookings child-rearing
    # estimates (school age); College Board Trends in College Pricing (college) — representative
    # placeholders, TODO(verify) against a primary cost survey.
    childcare_annual_cost: float = Field(default=12000.0, ge=0)
    school_age_annual_cost: float = Field(default=8000.0, ge=0)
    college_annual_cost: float = Field(default=28000.0, ge=0)
    college_start_age: int = Field(default=18, ge=0)
    college_years: int = Field(default=4, ge=0)
    adult_age: int = Field(default=18, ge=0)

    # Child Tax Credit (IRC §24 as amended by the One Big Beautiful Bill Act).
    # vintage: 2026, source: IRC §24(h) (OBBBA); Rev. Proc. 2025-32.
    ctc_per_child: float = Field(default=2200.0, ge=0)
    ctc_refundable_max: float = Field(default=1700.0, ge=0)
    # Oldest age (inclusive) of a qualifying child: under 17 at year end (IRC §24(c)(1)).
    ctc_qualifying_age_max: int = Field(default=16, ge=0)
    ctc_phaseout_start: CTCPhaseoutStartConfig = Field(default_factory=CTCPhaseoutStartConfig)
    # Credit reduction as a percentage of modified AGI over the threshold ($50 per $1,000).
    ctc_phaseout_rate: float = Field(default=5.0, ge=0, le=100)
    # Credit for other dependents ($500 per dependent who is not a CTC-qualifying child: a child aged 17-18,
    # or a full-time student under 24), phased out with the CTC. None (the default) leaves it off so a
    # config without it is unchanged. vintage: statutory, source: IRC §24(h)(4) (made permanent by OBBBA).
    odc_per_dependent: float | None = Field(default=None, ge=0)
    # Additional child tax credit (Schedule 8812 Part II-A): 15% of earned income over $2,500, up to the
    # refundable maximum per child. None keeps the legacy approximation (no earned-income limit).
    # vintage: statutory, source: IRC §24(d)(1)(B)(i), §24(h)(6).
    actc_earned_income_threshold: float | None = Field(default=None, ge=0)
    actc_rate: float = Field(default=15.0, ge=0, le=100)
    # Dependency age limits (IRC §152(c)(3)): under 19, or under 24 for a full-time student.
    # vintage: statutory, source: IRC §152(c)(3)(A)
    dependent_age_limit: int = Field(default=19, ge=0)
    student_dependent_age_limit: int = Field(default=24, ge=0)


class YearlyTaxParameters(StrictModel):
    """Tax parameters that vary year-over-year.

    A table of published years (see ``tax_years`` in the YAML) lets a multi-decade
    simulation apply the parameters in effect for each simulated year instead of a
    single frozen snapshot. ``year`` is stamped by ``FinancialConfig.tax_year`` and
    is not stored in the YAML (it is the table key).
    """

    year: int = 0
    standard_deduction: StandardDeductionConfig
    tax_brackets: TaxBracketsConfig
    ss_wage_base: int = Field(ge=0)
    limit_401k_base: int = Field(ge=0)
    limit_401k_catch_up: int = Field(ge=0)
    limit_ira: int = Field(ge=0)
    limit_ira_catch_up: int = Field(ge=0)
    limit_hsa_self: int = Field(ge=0)
    limit_hsa_family: int = Field(ge=0)
    gift_exclusion: int = Field(ge=0)
    rmd_start_age: int = Field(ge=0)
    #: IRC §415(c)(1)(A) annual-additions limit for defined contribution plans (employee + employer
    #: money per plan). Optional so older tables still load; None keeps the static
    #: ``retirement.job_401k_contrib_limit.annual_additions_limit``.
    limit_415c: int | None = Field(default=None, ge=0)
    # Plan 29 task 3: year-varying parameters that used to be static. Each is optional (None keeps
    # the static value) so older tables and the frozen test fixture still load unchanged.
    #: Long-term capital gains / qualified dividend brackets (§1(h); thresholds indexed).
    capital_gains: TaxBracketsConfig | None = None
    #: Child Tax Credit per child and the refundable (additional child tax credit) maximum per child.
    ctc_per_child: float | None = Field(default=None, ge=0)
    ctc_refundable_max: float | None = Field(default=None, ge=0)
    #: SALT cap (and its OBBBA phase-down threshold).
    salt: SaltCapYear | None = None
    #: OBBBA senior deduction per person 65+ (0 outside 2025-2028; statutory, not indexed).
    senior_deduction_amount: float | None = Field(default=None, ge=0)
    #: Net investment income tax thresholds (statutory, never indexed).
    niit: NIITConfig | None = None
    #: §63(f) additional standard deduction per person 65+ (Plan 31).
    additional_standard_deduction: AdditionalStandardDeduction | None = None
    # Plan 31: year-indexed parameters of the credits, deductions and regimes (see the same-named fields
    # of ``FederalTaxConfig``, where ``year_view`` copies them). Each optional: None leaves it off.
    eitc: EITCYear | None = None
    dependent_care: DependentCareYear | None = None
    savers_credit: SaversCreditYear | None = None
    ira_phaseouts: IRAPhaseoutsYear | None = None
    student_loan_phaseout: StudentLoanPhaseoutYear | None = None
    amt: AMTYear | None = None
    qbi: QBIYear | None = None
    kiddie_tax: KiddieTaxYear | None = None
    qcd_limit: float | None = Field(default=None, ge=0)
    ltc_premium_limits: list[LTCPremiumLimit] | None = None
    compensation_limit: float | None = Field(default=None, ge=0)


class StochasticEconomyConfig(StrictModel):
    """Distribution parameters for the ``stochastic`` economy mode.

    Annual returns are drawn as correlated normals (equity/bond/inflation share a
    correlation matrix); the remaining series are drawn independently. All values are
    percentages. Defaults reproduce the ``fixed``-mode means with historically typical
    volatilities.
    """

    equity_mean: float = 7.0
    equity_vol: float = Field(default=15.0, ge=0)
    bond_mean: float = 3.0
    bond_vol: float = Field(default=5.0, ge=0)
    inflation_mean: float = 3.0
    inflation_vol: float = Field(default=1.5, ge=0)
    cash_yield_mean: float = 0.0
    cash_yield_vol: float = Field(default=0.5, ge=0)
    home_appreciation_mean: float = 4.0
    home_appreciation_vol: float = Field(default=6.0, ge=0)
    wage_growth_mean: float = 3.0
    wage_growth_vol: float = Field(default=1.0, ge=0)
    equity_bond_correlation: float = Field(default=0.1, ge=-1, le=1)
    equity_inflation_correlation: float = Field(default=-0.1, ge=-1, le=1)
    bond_inflation_correlation: float = Field(default=-0.2, ge=-1, le=1)


class EconomyConfig(StrictModel):
    """Economy-wide rates that drive account returns, wage growth, and inflation.

    A single :class:`~life_model.economy.EconomyModel` per simulation reads this section
    and answers per-year rate queries. In ``fixed`` mode every year returns these constants;
    in ``path`` mode the ``paths`` table overrides individual years; in ``stochastic`` mode
    rates are drawn from ``stochastic``. All rates are percentages. The defaults reproduce
    the pre-economy per-account constants, so a fixed economy leaves simulation output
    unchanged.
    """

    mode: Literal["fixed", "path", "stochastic"] = "fixed"
    inflation: float = 3.0
    wage_growth: float = 3.0
    equity_return: float = 7.0
    bond_return: float = 3.0
    cash_yield: float = 0.0
    home_appreciation: float = 4.0
    # PATH mode: per-rate, per-year overrides, e.g. {"equity_return": {2027: -10.0, 2028: -4.0}}.
    # Years absent from a rate's table fall back to that rate's fixed constant above.
    paths: dict[str, dict[int, float]] = Field(default_factory=dict)
    stochastic: StochasticEconomyConfig = Field(default_factory=StochasticEconomyConfig)


class MedicalCostBandConfig(StrictModel):
    """One age band of the out-of-pocket medical-cost curve.

    ``max_age`` is the inclusive upper bound of the band (use a large sentinel for the top band);
    ``annual_cost`` is the real (start-year-dollar) out-of-pocket medical spend for a person in the
    band before inflation indexing.
    """

    max_age: int = Field(ge=0)
    annual_cost: float = Field(ge=0)


class MedicareIRMAATierConfig(StrictModel):
    """One IRMAA tier: the MAGI lower bounds and the resulting monthly premiums.

    The tier applies when two-year-lookback MAGI *exceeds* the filing-status lower bound. The base
    tier uses a lower bound of 0 and carries the standard (unsurcharged) Part B premium.
    """

    magi_min_single: float = Field(ge=0)
    magi_min_married_filing_jointly: float = Field(ge=0)
    part_b_monthly: float = Field(ge=0)
    part_d_monthly_surcharge: float = Field(ge=0)


class MedicareConfig(StrictModel):
    eligibility_age: int = Field(default=65, ge=0)
    # A separate filer who lived with their spouse skips the middle IRMAA tiers: above the first
    # single threshold they pay the second-highest tier, and the highest tier from this MAGI.
    # vintage: 2026, source: SSA POMS HI 01101.020 / CMS 2026 Part B premiums ($391,000)
    irmaa_mfs_top_threshold: float = Field(default=391000, ge=0)
    # Part A is premium-free for people with sufficient work history (documented simplification).
    part_b_base_monthly_premium: float = Field(default=202.90, ge=0)
    part_d_base_monthly_premium: float = Field(default=34.50, ge=0)
    irmaa_tiers: list[MedicareIRMAATierConfig] = Field(
        default_factory=lambda: [
            # vintage: 2026, source: CMS 2026 Parts B Premiums fact sheet; Part D IRMAA (SSA).
            MedicareIRMAATierConfig(
                magi_min_single=0,
                magi_min_married_filing_jointly=0,
                part_b_monthly=202.90,
                part_d_monthly_surcharge=0.0,
            ),
            MedicareIRMAATierConfig(
                magi_min_single=109000,
                magi_min_married_filing_jointly=218000,
                part_b_monthly=284.06,
                part_d_monthly_surcharge=14.50,
            ),
            MedicareIRMAATierConfig(
                magi_min_single=137000,
                magi_min_married_filing_jointly=274000,
                part_b_monthly=405.80,
                part_d_monthly_surcharge=37.50,
            ),
            MedicareIRMAATierConfig(
                magi_min_single=171000,
                magi_min_married_filing_jointly=342000,
                part_b_monthly=527.54,
                part_d_monthly_surcharge=60.40,
            ),
            MedicareIRMAATierConfig(
                magi_min_single=205000,
                magi_min_married_filing_jointly=410000,
                part_b_monthly=649.28,
                part_d_monthly_surcharge=83.30,
            ),
            MedicareIRMAATierConfig(
                magi_min_single=500000,
                magi_min_married_filing_jointly=750000,
                part_b_monthly=690.06,
                part_d_monthly_surcharge=91.00,
            ),
        ]
    )


class LTCHazardBandConfig(StrictModel):
    """One age band of the annual long-term-care onset hazard."""

    max_age: int = Field(ge=0)
    annual_hazard: float = Field(ge=0, le=1)


class LongTermCareConfig(StrictModel):
    start_age: int = Field(default=65, ge=0)
    # Annual hazard of entering a care episode, by age band (TODO(verify): calibrated to ASPE
    # lifetime-risk data, not a published annual-incidence table).
    hazard_bands: list[LTCHazardBandConfig] = Field(
        default_factory=lambda: [
            LTCHazardBandConfig(max_age=74, annual_hazard=0.005),
            LTCHazardBandConfig(max_age=84, annual_hazard=0.02),
            LTCHazardBandConfig(max_age=200, annual_hazard=0.06),
        ]
    )
    # vintage: 2024, source: Genworth/CareScout Cost of Care (semi-private nursing home, median).
    annual_cost: float = Field(default=111325, ge=0)
    # vintage: 2024, source: ASPE (mean paid nursing-home episode ~2.3 years).
    mean_duration_years: float = Field(default=2.3, gt=0)


class HealthcareConfig(StrictModel):
    """Healthcare, Medicare, and long-term-care parameters.

    Every field has a default so existing YAML without a ``healthcare`` section still loads.
    """

    # Age-banded out-of-pocket medical-cost curve (real start-year dollars).
    # vintage: 2024, source: CMS NHE / MEPS out-of-pocket by age — TODO(verify) exact per-band OOP.
    medical_cost_bands: list[MedicalCostBandConfig] = Field(
        default_factory=lambda: [
            MedicalCostBandConfig(max_age=39, annual_cost=1500),
            MedicalCostBandConfig(max_age=64, annual_cost=3000),
            MedicalCostBandConfig(max_age=74, annual_cost=6000),
            MedicalCostBandConfig(max_age=84, annual_cost=9000),
            MedicalCostBandConfig(max_age=200, annual_cost=12000),
        ]
    )
    # Percentage points that medical inflation runs above CPI.
    # vintage: 2024, source: CMS National Health Expenditure projections — TODO(verify).
    medical_inflation_premium: float = Field(default=2.0, ge=0)
    medicare: MedicareConfig = Field(default_factory=MedicareConfig)
    long_term_care: LongTermCareConfig = Field(default_factory=LongTermCareConfig)
    # vintage: 2023, source: NFDA median cost of a funeral with viewing and burial ($8,300).
    funeral_cost: float = Field(default=8300, ge=0)
    # Final-year medical spend as a multiple of the person's current-year medical cost.
    # vintage: 2024, source: end-of-life spending is elevated — TODO(verify) exact multiplier.
    final_year_medical_multiplier: float = Field(default=2.0, ge=0)
    # AGI floor (percent) above which unreimbursed medical is deductible (IRC §213(a)).
    medical_deduction_agi_floor: float = Field(default=7.5, ge=0, le=100)


class EquityCompConfig(StrictModel):
    """Defaults for stock compensation.

    These are modeling conventions rather than published figures, so they carry no ``vintage``
    stamp. Every field is defaulted so configs that omit the section still load.
    """

    # Named preset used when a stock plan does not specify a vesting schedule.
    default_schedule: str = "four_year"
    # Vesting length used to build an even schedule when ``default_schedule`` is "even".
    default_vesting_years: int = Field(default=4, ge=1)


class FinancialConfigModel(StrictModel):
    """Complete financial configuration model with validation"""

    tax: TaxConfig
    retirement: RetirementConfig
    social_security: SocialSecurityConfig
    accounts: AccountsConfig
    insurance: InsuranceConfig
    debt: DebtConfig
    housing: HousingConfig = Field(default_factory=HousingConfig)
    estate: EstateConfig = Field(default_factory=EstateConfig)
    economy: EconomyConfig = Field(default_factory=EconomyConfig)
    healthcare: HealthcareConfig = Field(default_factory=HealthcareConfig)
    dependents: DependentsConfig = Field(default_factory=DependentsConfig)
    equity_comp: EquityCompConfig = Field(default_factory=EquityCompConfig)
    tax_years: dict[int, YearlyTaxParameters]
    # How simulated years after the last published ``tax_years`` entry are treated: indexed by the
    # economy's realized inflation (IRS-style rounding), or frozen at the last published values.
    tax_years_projection: Literal["inflation_indexed", "frozen"] = "inflation_indexed"
