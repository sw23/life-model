# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from pydantic import BaseModel, Field, ConfigDict
from typing import List, Union, Dict


class StandardDeductionConfig(BaseModel):
    single: int
    married_filing_jointly: int


class TaxBracketsConfig(BaseModel):
    single: List[List[Union[int, float]]]
    married_filing_jointly: List[List[Union[int, float]]]


class FederalTaxConfig(BaseModel):
    standard_deduction: StandardDeductionConfig
    tax_brackets: TaxBracketsConfig


class StateTaxConfig(BaseModel):
    tax_rate: float = Field(ge=0, le=100)


class MedicareThresholdConfig(BaseModel):
    single: int
    married_filing_jointly: int


class FICATaxConfig(BaseModel):
    social_security_rate: float = Field(ge=0, le=100)
    social_security_max_income: int
    medicare_rate: float = Field(ge=0, le=100)
    medicare_additional_rate: float = Field(ge=0, le=100)
    medicare_additional_rate_threshold: MedicareThresholdConfig


class TaxConfig(BaseModel):
    federal: FederalTaxConfig
    state: StateTaxConfig
    fica: FICATaxConfig


class Job401kContribLimitConfig(BaseModel):
    base: int
    catch_up_age: int
    catch_up_amount: int


class IRAConfig(BaseModel):
    contribution_limit: int
    default_growth_rate: float = Field(ge=0)


class RetirementConfig(BaseModel):
    federal_retirement_age: float
    job_401k_contrib_limit: Job401kContribLimitConfig
    ira: IRAConfig
    rmd_distribution_periods: List[List[float]]


class SocialSecurityConfig(BaseModel):
    min_eligible_credits: int
    max_credits_per_year: int
    max_years_of_income: int
    min_early_retirement_age: int
    normal_retirement_age: int
    max_delayed_retirement_credit_age: int
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


class BankAccountConfig(BaseModel):
    default_interest_rate: float = Field(ge=0)
    compound_rate: int = Field(ge=1)


class BrokerageAccountConfig(BaseModel):
    default_growth_rate: float


class HSAAccountConfig(BaseModel):
    contribution_limit: int
    default_employer_contribution: int = Field(ge=0)


class AccountsConfig(BaseModel):
    bank: BankAccountConfig
    brokerage: BrokerageAccountConfig
    hsa: HSAAccountConfig


class SurrenderPercentagesConfig(BaseModel):
    early: float = Field(ge=0, le=1)
    standard: float = Field(ge=0, le=1)


class LifeInsuranceConfig(BaseModel):
    default_loan_interest_rate: float = Field(ge=0)
    default_cash_value_growth_rate: float = Field(ge=0)
    default_max_missed_payments: int = Field(ge=0)
    surrender_percentages: SurrenderPercentagesConfig


class InsuranceConfig(BaseModel):
    life: LifeInsuranceConfig


class CreditCardConfig(BaseModel):
    default_interest_rate: float = Field(ge=0)
    default_minimum_payment_percent: float = Field(ge=0, le=100)


class DebtConfig(BaseModel):
    credit_card: CreditCardConfig


class FinancialConfigModel(BaseModel):
    """Complete financial configuration model with validation"""
    model_config = ConfigDict(extra='forbid')

    tax: TaxConfig
    retirement: RetirementConfig
    social_security: SocialSecurityConfig
    accounts: AccountsConfig
    insurance: InsuranceConfig
    debt: DebtConfig
