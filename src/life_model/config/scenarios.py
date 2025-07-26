# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""
Predefined scenario configurations for common economic and regulatory conditions.
These scenarios allow users to easily adjust multiple configuration parameters
to model different economic environments without manually changing individual values.
"""

import yaml
from pathlib import Path
from typing import Dict, Any


def _load_scenario_from_yaml(filename: str) -> Dict[str, Any]:
    """Load a scenario configuration from a YAML file

    Args:
        filename: Name of the YAML file (without path)

    Returns:
        Dictionary containing scenario configuration
    """
    # Try multiple potential locations for scenario files
    potential_paths = [
        Path('config/scenarios') / filename,  # From project root
        Path(__file__).parent.parent.parent.parent / 'config' / 'scenarios' / filename,  # Relative to this file
        Path.cwd() / 'config' / 'scenarios' / filename,  # From current directory
    ]

    for path in potential_paths:
        if path.exists():
            with open(path, 'r') as f:
                return yaml.safe_load(f)

    # If file not found, return empty dict (will use embedded defaults)
    return {}


# For backward compatibility, maintain scenario definitions as lazy-loaded properties
def _get_recession_scenario() -> Dict[str, Any]:
    """Load recession scenario from YAML or use embedded defaults"""
    scenario = _load_scenario_from_yaml('recession.yaml')
    if scenario:
        return scenario

    # Embedded defaults as fallback
    return {
        'accounts': {
            'bank': {
                'default_interest_rate': 0.5  # Lower interest rates
            },
            'brokerage': {
                'default_growth_rate': 3.0  # Reduced market growth expectations
            }
        },
        'retirement': {
            'ira': {
                'default_growth_rate': 3.5  # Conservative growth in retirement accounts
            }
        },
        'insurance': {
            'life': {
                'default_cash_value_growth_rate': 1.0  # Lower returns on cash value
            }
        }
    }


def _get_high_inflation_scenario() -> Dict[str, Any]:
    """Load high inflation scenario from YAML or use embedded defaults"""
    scenario = _load_scenario_from_yaml('high_inflation.yaml')
    if scenario:
        return scenario

    # Embedded defaults as fallback
    return {
        'accounts': {
            'bank': {
                'default_interest_rate': 4.0  # Higher interest rates to combat inflation
            },
            'brokerage': {
                'default_growth_rate': 9.0  # Stocks may perform better during inflation
            }
        },
        'debt': {
            'credit_card': {
                'default_interest_rate': 25.0  # Credit card rates rise with inflation
            }
        }
    }


def _get_conservative_scenario() -> Dict[str, Any]:
    """Load conservative scenario from YAML or use embedded defaults"""
    scenario = _load_scenario_from_yaml('conservative.yaml')
    if scenario:
        return scenario

    # Embedded defaults as fallback
    return {
        'accounts': {
            'brokerage': {
                'default_growth_rate': 5.0  # Conservative investment growth
            }
        },
        'retirement': {
            'ira': {
                'default_growth_rate': 5.5  # Conservative retirement growth
            }
        },
        'insurance': {
            'life': {
                'default_cash_value_growth_rate': 2.0  # Conservative cash value growth
            }
        }
    }


def _get_aggressive_scenario() -> Dict[str, Any]:
    """Load aggressive scenario from YAML or use embedded defaults"""
    scenario = _load_scenario_from_yaml('aggressive.yaml')
    if scenario:
        return scenario

    # Embedded defaults as fallback
    return {
        'accounts': {
            'brokerage': {
                'default_growth_rate': 10.0  # Aggressive investment growth
            }
        },
        'retirement': {
            'ira': {
                'default_growth_rate': 10.5  # Aggressive retirement growth
            }
        },
        'insurance': {
            'life': {
                'default_cash_value_growth_rate': 4.0  # Higher cash value growth
            }
        }
    }


def _get_tax_reform_scenario() -> Dict[str, Any]:
    """Load tax reform scenario from YAML or use embedded defaults"""
    scenario = _load_scenario_from_yaml('tax_reform.yaml')
    if scenario:
        return scenario

    # Embedded defaults as fallback
    return {
        'tax': {
            'federal': {
                'standard_deduction': {
                    'single': 15000,  # Increased standard deduction
                    'married_filing_jointly': 30000
                },
                'tax_brackets': {
                    'single': [
                        [0, 12000, 10],      # Expanded 10% bracket
                        [12001, 45000, 12],  # Adjusted middle brackets
                        [45001, 95000, 22],
                        [95001, 180000, 24],
                        [180001, 250000, 32],
                        [250001, 600000, 35],
                        [600001, float('inf'), 39],  # Higher top rate
                    ]
                }
            },
            'state': {
                'tax_rate': 7.5  # Increased state tax rate
            }
        }
    }


def _get_low_tax_scenario() -> Dict[str, Any]:
    """Load low tax scenario from YAML or use embedded defaults"""
    scenario = _load_scenario_from_yaml('low_tax.yaml')
    if scenario:
        return scenario

    # Embedded defaults as fallback
    return {
        'tax': {
            'federal': {
                'tax_brackets': {
                    'single': [
                        [0, 15000, 8],       # Lower initial rate
                        [15001, 50000, 10],  # Reduced middle rates
                        [50001, 100000, 18],
                        [100001, 200000, 20],
                        [200001, 500000, 28],
                        [500001, float('inf'), 32],  # Lower top rate
                    ]
                }
            },
            'state': {
                'tax_rate': 3.0  # Reduced state tax rate
            }
        }
    }


def _get_boom_scenario() -> Dict[str, Any]:
    """Load boom scenario from YAML"""
    return _load_scenario_from_yaml('boom.yaml')


def _get_deflation_scenario() -> Dict[str, Any]:
    """Load deflation scenario from YAML"""
    return _load_scenario_from_yaml('deflation.yaml')


def _get_high_tax_scenario() -> Dict[str, Any]:
    """Load high tax scenario from YAML"""
    return _load_scenario_from_yaml('high_tax.yaml')


def get_scenario(name: str) -> Dict[str, Any]:
    """Get a predefined scenario by name

    Args:
        name: Name of the scenario

    Returns:
        Dictionary of configuration overrides for the scenario

    Raises:
        KeyError: If scenario name is not found
    """
    # Map of scenario names to their loader functions
    scenario_loaders = {
        'recession': _get_recession_scenario,
        'high_inflation': _get_high_inflation_scenario,
        'conservative': _get_conservative_scenario,
        'aggressive': _get_aggressive_scenario,
        'tax_reform': _get_tax_reform_scenario,
        'low_tax': _get_low_tax_scenario,
        'boom': _get_boom_scenario,
        'deflation': _get_deflation_scenario,
        'high_tax': _get_high_tax_scenario,
    }

    if name not in scenario_loaders:
        available = ', '.join(scenario_loaders.keys())
        raise KeyError(f"Scenario '{name}' not found. Available scenarios: {available}")

    return scenario_loaders[name]()


def list_scenarios() -> list:
    """Get a list of all available predefined scenarios"""
    # Always include the embedded scenarios
    scenarios = ['recession', 'high_inflation', 'conservative', 'aggressive', 'tax_reform', 'low_tax']

    # Add any additional scenarios from YAML files
    scenario_dir_paths = [
        Path('config/scenarios'),
        Path(__file__).parent.parent.parent.parent / 'config' / 'scenarios',
        Path.cwd() / 'config' / 'scenarios',
    ]

    for path in scenario_dir_paths:
        if path.exists() and path.is_dir():
            for yaml_file in path.glob('*.yaml'):
                scenario_name = yaml_file.stem
                if scenario_name not in scenarios:
                    scenarios.append(scenario_name)
            break

    return scenarios


# For backward compatibility, maintain the old constants
RECESSION_SCENARIO = _get_recession_scenario()
HIGH_INFLATION_SCENARIO = _get_high_inflation_scenario()
CONSERVATIVE_SCENARIO = _get_conservative_scenario()
AGGRESSIVE_SCENARIO = _get_aggressive_scenario()
TAX_REFORM_SCENARIO = _get_tax_reform_scenario()
LOW_TAX_SCENARIO = _get_low_tax_scenario()

# Legacy PREDEFINED_SCENARIOS dict
PREDEFINED_SCENARIOS = {
    'recession': RECESSION_SCENARIO,
    'high_inflation': HIGH_INFLATION_SCENARIO,
    'conservative': CONSERVATIVE_SCENARIO,
    'aggressive': AGGRESSIVE_SCENARIO,
    'tax_reform': TAX_REFORM_SCENARIO,
    'low_tax': LOW_TAX_SCENARIO,
}
