# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import yaml
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from .base_config import ScenarioConfig
from .models import FinancialConfigModel
from pydantic import ValidationError

if TYPE_CHECKING:
    from ..tax.federal import FilingStatus


class FinancialConfig(ScenarioConfig):
    """Configuration for financial parameters, limits, and rates"""

    def __init__(self, config_file: Optional[str] = None):
        """Initialize financial configuration from YAML file

        Args:
            config_file: Path to configuration file. If None, uses default location.
        """
        self.config_file = config_file
        super().__init__()

    def _initialize_defaults(self) -> None:
        """Initialize default financial configuration values from YAML file"""
        # Determine config file path
        if self.config_file is None:
            # Look for config file relative to the project root
            # Try multiple potential locations
            potential_paths = [
                Path('config/financial_defaults.yaml'),  # From project root
                # Relative to this file
                Path(__file__).parent.parent.parent.parent / 'config' / 'financial_defaults.yaml',
                Path.cwd() / 'config' / 'financial_defaults.yaml',  # From current directory
            ]

            for path in potential_paths:
                if path.exists():
                    self.config_file = str(path)
                    break
            else:
                # If no config file found, fall back to embedded defaults
                self._use_embedded_defaults()
                return

        try:
            # Load YAML configuration
            with open(self.config_file, 'r') as f:
                raw_config = yaml.safe_load(f)

            # Validate with Pydantic model
            validated_config = FinancialConfigModel(**raw_config)
            self._config_data = validated_config.model_dump()

        except (FileNotFoundError, yaml.YAMLError, ValidationError) as e:
            # If loading fails, fall back to embedded defaults
            print(f"Warning: Failed to load configuration from {self.config_file}: {e}")
            print("Using embedded defaults")
            self._use_embedded_defaults()

    def _use_embedded_defaults(self) -> None:
        """Use embedded default configuration as fallback"""
        self._config_data = {
            # Tax Configuration
            'tax': {
                'federal': {
                    'standard_deduction': {
                        'single': 13850,
                        'married_filing_jointly': 27700
                    },
                    'tax_brackets': {
                        'single': [
                            [0, 10275, 10],
                            [10276, 41775, 12],
                            [41776, 89075, 22],
                            [89076, 170050, 24],
                            [170051, 215950, 32],
                            [215951, 539900, 35],
                            [539901, float('inf'), 37],
                        ],
                        'married_filing_jointly': [
                            [0, 20550, 10],
                            [20551, 83550, 12],
                            [83551, 178150, 22],
                            [178151, 340100, 24],
                            [340101, 431900, 32],
                            [431901, 647850, 35],
                            [647851, float('inf'), 37],
                        ]
                    }
                },
                'state': {
                    'tax_rate': 6.0  # percentage
                },
                'fica': {
                    'social_security_rate': 6.2,  # percentage
                    'social_security_max_income': 160200,
                    'medicare_rate': 1.45,  # percentage
                    'medicare_additional_rate': 0.9,  # percentage
                    'medicare_additional_rate_threshold': {
                        'single': 200000,
                        'married_filing_jointly': 250000
                    }
                }
            },

            # Retirement Configuration
            'retirement': {
                'federal_retirement_age': 59.5,
                'job_401k_contrib_limit': {
                    'base': 20500,
                    'catch_up_age': 50,
                    'catch_up_amount': 6500
                },
                'ira': {
                    'contribution_limit': 6500,
                    'default_growth_rate': 7.0  # percentage
                },
                'rmd_distribution_periods': [
                    [70, 27.4], [71, 26.5], [72, 25.6], [73, 24.7], [74, 23.8],
                    [75, 22.9], [76, 22], [77, 21.2], [78, 20.3], [79, 19.5],
                    [80, 18.7], [81, 17.9], [82, 17.1], [83, 16.3], [84, 15.5],
                    [85, 14.8], [86, 14.1], [87, 13.4], [88, 12.7], [89, 12],
                    [90, 11.4], [91, 10.8], [92, 10.2], [93, 9.6], [94, 9.1],
                    [95, 8.6], [96, 8.1], [97, 7.6], [98, 7.1], [99, 6.7],
                    [100, 6.3], [101, 5.9], [102, 5.5], [103, 5.2], [104, 4.9],
                    [105, 4.5], [106, 4.2], [107, 3.9], [108, 3.7], [109, 3.4],
                    [110, 3.1], [111, 2.9], [112, 2.6], [113, 2.4], [114, 2.1], [115, 1.9]
                ]
            },

            # Social Security Configuration
            'social_security': {
                'min_eligible_credits': 40,
                'max_credits_per_year': 4,
                'max_years_of_income': 35,
                'min_early_retirement_age': 62,
                'max_delayed_retirement_credit_age': 70
            },

            # Account Configuration
            'accounts': {
                'bank': {
                    'default_interest_rate': 0.0,
                    'compound_rate': 12  # monthly compounding
                },
                'brokerage': {
                    'default_growth_rate': 7.0  # percentage
                },
                'hsa': {
                    'contribution_limit': 4150,
                    'default_employer_contribution': 0
                }
            },

            # Insurance Configuration
            'insurance': {
                'life': {
                    'default_loan_interest_rate': 6.0,  # percentage
                    'default_cash_value_growth_rate': 0.0,
                    'default_max_missed_payments': 3,
                    'surrender_percentages': {
                        'early': 0.5,  # less than 3 years
                        'standard': 0.8  # 3+ years
                    }
                }
            },

            # Debt Configuration
            'debt': {
                'credit_card': {
                    'default_interest_rate': 18.0,  # percentage
                    'default_minimum_payment_percent': 2.0  # percentage
                }
            }
        }

    # Convenience methods for commonly accessed values
    def get_federal_standard_deduction(self, filing_status: 'FilingStatus') -> float:
        """Get federal standard deduction for filing status"""
        # Use integer comparison to avoid importing FilingStatus
        key = 'single' if filing_status.value == 1 else 'married_filing_jointly'
        return self.get(f'tax.federal.standard_deduction.{key}')

    def get_federal_tax_brackets(self, filing_status: 'FilingStatus') -> list:
        """Get federal tax brackets for filing status"""
        # Use integer comparison to avoid importing FilingStatus
        key = 'single' if filing_status.value == 1 else 'married_filing_jointly'
        return self.get(f'tax.federal.tax_brackets.{key}')

    def get_job_401k_contrib_limit(self, age: int) -> int:
        """Get 401k contribution limit based on age"""
        base = self.get('retirement.job_401k_contrib_limit.base')
        catch_up_age = self.get('retirement.job_401k_contrib_limit.catch_up_age')
        catch_up_amount = self.get('retirement.job_401k_contrib_limit.catch_up_amount')

        return base + (catch_up_amount if age >= catch_up_age else 0)

    def get_max_tax_rate(self, filing_status: 'FilingStatus') -> float:
        """Get maximum tax rate for filing status"""
        brackets = self.get_federal_tax_brackets(filing_status)
        return brackets[-1][2] if brackets else 0.0
