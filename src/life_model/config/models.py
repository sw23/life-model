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
    """AGI limit on deductible cash gifts to public charities (incl. donor-advised funds)."""

    # vintage: statutory, source: IRC §170(b)(1)(G) 60% cash limit (made permanent by OBBBA);
    # §170(d)(1) five-year carryover of the excess
    cash_agi_limit_percent: float = Field(default=60.0, ge=0, le=100)
    carryforward_years: int = Field(default=5, ge=0)


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
    salt_deduction_cap: int = Field(default=40000, ge=0)
    senior_deduction: SeniorDeductionConfig = Field(default_factory=SeniorDeductionConfig)
    charitable: CharitableConfig = Field(default_factory=CharitableConfig)
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

    Annual payment = ``rate_step_percent``% x AGI for each full ``income_step`` of AGI, capped at
    ``max_rate_percent``% (1% for $10,001-20,000 ... 10% above $100,000), with ``minimum_annual``
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
    ctc_qualifying_age_max: int = Field(default=17, ge=0)
    ctc_phaseout_start: CTCPhaseoutStartConfig = Field(default_factory=CTCPhaseoutStartConfig)
    # Credit reduction as a percentage of modified AGI over the threshold ($50 per $1,000).
    ctc_phaseout_rate: float = Field(default=5.0, ge=0, le=100)


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
