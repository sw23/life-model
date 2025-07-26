# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""
Predefined scenario configurations for common economic and regulatory conditions.
These scenarios allow users to easily adjust multiple configuration parameters
to model different economic environments without manually changing individual values.
"""

from typing import Dict, Any


# Economic recession scenario - lower growth, higher taxes
RECESSION_SCENARIO: Dict[str, Any] = {
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


# High inflation scenario - higher rates across the board
HIGH_INFLATION_SCENARIO: Dict[str, Any] = {
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


# Conservative scenario - lower risk, lower returns
CONSERVATIVE_SCENARIO: Dict[str, Any] = {
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


# Aggressive growth scenario - higher risk, higher returns
AGGRESSIVE_SCENARIO: Dict[str, Any] = {
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


# Tax reform scenario - simulates potential tax changes
TAX_REFORM_SCENARIO: Dict[str, Any] = {
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


# Low tax scenario - favorable tax environment
LOW_TAX_SCENARIO: Dict[str, Any] = {
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


# All predefined scenarios
PREDEFINED_SCENARIOS = {
    'recession': RECESSION_SCENARIO,
    'high_inflation': HIGH_INFLATION_SCENARIO,
    'conservative': CONSERVATIVE_SCENARIO,
    'aggressive': AGGRESSIVE_SCENARIO,
    'tax_reform': TAX_REFORM_SCENARIO,
    'low_tax': LOW_TAX_SCENARIO,
}


def get_scenario(name: str) -> Dict[str, Any]:
    """Get a predefined scenario by name

    Args:
        name: Name of the scenario

    Returns:
        Dictionary of configuration overrides for the scenario

    Raises:
        KeyError: If scenario name is not found
    """
    if name not in PREDEFINED_SCENARIOS:
        available = ', '.join(PREDEFINED_SCENARIOS.keys())
        raise KeyError(f"Scenario '{name}' not found. Available scenarios: {available}")

    return PREDEFINED_SCENARIOS[name].copy()


def list_scenarios() -> list:
    """Get a list of all available predefined scenarios"""
    return list(PREDEFINED_SCENARIOS.keys())
