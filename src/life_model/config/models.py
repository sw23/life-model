# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


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
    head_of_household: Optional[int] = Field(default=None, ge=0)


class TaxBracketsConfig(StrictModel):
    single: List[List[Union[int, float]]]
    married_filing_jointly: List[List[Union[int, float]]]
    # Optional: HEAD_OF_HOUSEHOLD falls back to `single` when absent.
    head_of_household: Optional[List[List[Union[int, float]]]] = None


class FederalTaxConfig(StrictModel):
    standard_deduction: StandardDeductionConfig
    tax_brackets: TaxBracketsConfig
    # Itemized-deduction limits (defaults let existing configs load without these keys).
    # vintage: 2026, source: IRC §163(h)(3) TCJA acquisition-debt limit; §164(b)(6) SALT cap (OBBBA).
    mortgage_interest_debt_limit: int = Field(default=750000, ge=0)
    salt_deduction_cap: int = Field(default=40000, ge=0)
    # Estate transfer parameters (defaults let existing configs load without these keys).
    # The unified exemption shelters estate value below it; transfers to a surviving spouse are
    # fully sheltered by the unlimited marital deduction regardless of the exemption.
    # vintage: 2026, source: IRC §2010 unified credit (post-OBBBA ~$15M); §2001(c) top rate 40%.
    estate_tax_exemption: int = Field(default=15000000, ge=0)
    estate_tax_rate: float = Field(default=40.0, ge=0, le=100)


class StateTaxConfig(StrictModel):
    tax_rate: float = Field(ge=0, le=100)


class MedicareThresholdConfig(StrictModel):
    single: int = Field(ge=0)
    married_filing_jointly: int = Field(ge=0)


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


class IRAConfig(StrictModel):
    contribution_limit: int = Field(ge=0)
    default_growth_rate: float = Field(ge=0)


class RetirementConfig(StrictModel):
    federal_retirement_age: float = Field(ge=0)
    job_401k_contrib_limit: Job401kContribLimitConfig
    ira: IRAConfig
    rmd_distribution_periods: List[List[float]]


class SocialSecurityBenefitTaxationConfig(StrictModel):
    """Statutory (non-indexed) provisional-income thresholds for taxing benefits.

    See IRS Pub. 915. Thresholds have been fixed in statute since 1984/1994.
    """

    lower_threshold_single: int = Field(ge=0)
    upper_threshold_single: int = Field(ge=0)
    lower_threshold_married_filing_jointly: int = Field(ge=0)
    upper_threshold_married_filing_jointly: int = Field(ge=0)
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
    avg_wage_index: Dict[int, float]
    cost_of_living_adj: Dict[int, float]
    bend_points: Dict[int, List[int]]

    # Provisional-income taxation of benefits
    benefit_taxation: SocialSecurityBenefitTaxationConfig


class BankAccountConfig(StrictModel):
    default_interest_rate: float = Field(ge=0)
    compound_rate: int = Field(ge=1)


class BrokerageAccountConfig(StrictModel):
    default_growth_rate: float


class HSAAccountConfig(StrictModel):
    contribution_limit: int = Field(ge=0)
    contribution_limit_family: int = Field(ge=0)
    default_employer_contribution: int = Field(ge=0)


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


class StudentLoanConfig(StrictModel):
    # Above-the-line student-loan interest deduction (IRC §221). The MAGI phase-out is not
    # modeled; this is a flat cap. vintage: 2025, source: IRC §221 (statutory, unindexed cap).
    interest_deduction_limit: float = Field(default=2500.0, ge=0)


class DebtConfig(StrictModel):
    credit_card: CreditCardConfig
    student_loan: StudentLoanConfig = Field(default_factory=StudentLoanConfig)


class Section121ExclusionConfig(StrictModel):
    single: int = Field(default=250000, ge=0)
    married_filing_jointly: int = Field(default=500000, ge=0)


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
    paths: Dict[str, Dict[int, float]] = Field(default_factory=dict)
    stochastic: StochasticEconomyConfig = Field(default_factory=StochasticEconomyConfig)


class FinancialConfigModel(StrictModel):
    """Complete financial configuration model with validation"""

    tax: TaxConfig
    retirement: RetirementConfig
    social_security: SocialSecurityConfig
    accounts: AccountsConfig
    insurance: InsuranceConfig
    debt: DebtConfig
    housing: HousingConfig = Field(default_factory=HousingConfig)
    economy: EconomyConfig = Field(default_factory=EconomyConfig)
    dependents: DependentsConfig = Field(default_factory=DependentsConfig)
    tax_years: Dict[int, YearlyTaxParameters]
