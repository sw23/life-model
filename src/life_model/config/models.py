# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import Dict, List, Union

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


class TaxBracketsConfig(StrictModel):
    single: List[List[Union[int, float]]]
    married_filing_jointly: List[List[Union[int, float]]]


class FederalTaxConfig(StrictModel):
    standard_deduction: StandardDeductionConfig
    tax_brackets: TaxBracketsConfig
    # Itemized-deduction limits (defaults let existing configs load without these keys).
    # vintage: 2026, source: IRC §163(h)(3) TCJA acquisition-debt limit; §164(b)(6) SALT cap (OBBBA).
    mortgage_interest_debt_limit: int = Field(default=750000, ge=0)
    salt_deduction_cap: int = Field(default=40000, ge=0)


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
    # 415(c) overall annual-additions limit (employee + employer, per employer plan).
    annual_additions_limit: int = Field(ge=0)


class IRAConfig(StrictModel):
    contribution_limit: int = Field(ge=0)
    default_growth_rate: float = Field(ge=0)


class RetirementConfig(StrictModel):
    federal_retirement_age: float = Field(ge=0)
    job_401k_contrib_limit: Job401kContribLimitConfig
    ira: IRAConfig
    rmd_distribution_periods: List[List[float]]


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

    # Historical data tables
    avg_wage_index: Dict[int, float]
    cost_of_living_adj: Dict[int, float]
    bend_points: Dict[int, List[int]]


class BankAccountConfig(StrictModel):
    default_interest_rate: float = Field(ge=0)
    compound_rate: int = Field(ge=1)


class BrokerageAccountConfig(StrictModel):
    default_growth_rate: float


class HSAAccountConfig(StrictModel):
    contribution_limit: int = Field(ge=0)
    catch_up_age: int = Field(ge=0)
    catch_up_amount: int = Field(ge=0)
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


class InsuranceConfig(StrictModel):
    life: LifeInsuranceConfig


class CreditCardConfig(StrictModel):
    default_interest_rate: float = Field(ge=0)
    default_minimum_payment_percent: float = Field(ge=0, le=100)


class DebtConfig(StrictModel):
    credit_card: CreditCardConfig


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


class FinancialConfigModel(StrictModel):
    """Complete financial configuration model with validation"""

    tax: TaxConfig
    retirement: RetirementConfig
    social_security: SocialSecurityConfig
    accounts: AccountsConfig
    insurance: InsuranceConfig
    debt: DebtConfig
    tax_years: Dict[int, YearlyTaxParameters]
