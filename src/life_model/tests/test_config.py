# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from ..config.base_config import ConfigurationManager, ScenarioConfig
from ..config.financial_config import FinancialConfig
from ..config.config_manager import GlobalConfigManager
from ..tax.federal import FilingStatus


class TestConfigurationManager(unittest.TestCase):
    """Test the base configuration manager"""

    def setUp(self):
        class TestConfig(ConfigurationManager):
            def _initialize_defaults(self):
                self._config_data = {
                    'test': {
                        'value1': 100,
                        'value2': 'hello'
                    },
                    'simple': 42
                }

        self.config = TestConfig()

    def test_get_simple_value(self):
        """Test getting a simple configuration value"""
        self.assertEqual(self.config.get('simple'), 42)

    def test_get_nested_value(self):
        """Test getting a nested configuration value"""
        self.assertEqual(self.config.get('test.value1'), 100)
        self.assertEqual(self.config.get('test.value2'), 'hello')

    def test_get_nonexistent_value(self):
        """Test getting a non-existent value returns default"""
        self.assertIsNone(self.config.get('nonexistent'))
        self.assertEqual(self.config.get('nonexistent', 'default'), 'default')

    def test_set_simple_value(self):
        """Test setting a simple configuration value"""
        self.config.set('new_value', 123)
        self.assertEqual(self.config.get('new_value'), 123)

    def test_set_nested_value(self):
        """Test setting a nested configuration value"""
        self.config.set('nested.new.value', 456)
        self.assertEqual(self.config.get('nested.new.value'), 456)

    def test_update_config(self):
        """Test updating configuration with a dictionary"""
        updates = {
            'test': {'value3': 'new'},
            'another': {'nested': {'deep': 789}}
        }
        self.config.update(updates)

        self.assertEqual(self.config.get('test.value1'), 100)  # Should still exist
        self.assertEqual(self.config.get('test.value3'), 'new')  # Should be added
        self.assertEqual(self.config.get('another.nested.deep'), 789)

    def test_reset_to_defaults(self):
        """Test resetting configuration to defaults"""
        self.config.set('new_value', 999)
        self.assertEqual(self.config.get('new_value'), 999)

        self.config.reset_to_defaults()
        self.assertIsNone(self.config.get('new_value'))
        self.assertEqual(self.config.get('simple'), 42)  # Default should be restored


class TestScenarioConfig(unittest.TestCase):
    """Test scenario-specific configuration"""

    def setUp(self):
        class TestScenarioConfig(ScenarioConfig):
            def _initialize_defaults(self):
                self._config_data = {
                    'base_value': 100,
                    'scenario_value': 200
                }

        self.config = TestScenarioConfig()

    def test_apply_scenario(self):
        """Test applying scenario-specific overrides"""
        overrides = {
            'scenario_value': 300,
            'new_value': 400
        }

        self.config.apply_scenario('test_scenario', overrides)

        self.assertEqual(self.config.scenario, 'test_scenario')
        self.assertEqual(self.config.get('base_value'), 100)  # Unchanged
        self.assertEqual(self.config.get('scenario_value'), 300)  # Overridden
        self.assertEqual(self.config.get('new_value'), 400)  # Added


class TestFinancialConfig(unittest.TestCase):
    """Test financial configuration"""

    def setUp(self):
        self.config = FinancialConfig()

    def test_default_values(self):
        """Test that default financial values are properly initialized"""
        # Test tax values
        self.assertEqual(self.config.get('tax.state.tax_rate'), 6.0)
        self.assertEqual(self.config.get('tax.fica.social_security_rate'), 6.2)

        # Test retirement values
        self.assertEqual(self.config.get('retirement.federal_retirement_age'), 59.5)
        self.assertEqual(self.config.get('retirement.ira.contribution_limit'), 6500)

        # Test account values
        self.assertEqual(self.config.get('accounts.bank.compound_rate'), 12)

    def test_get_federal_standard_deduction(self):
        """Test getting federal standard deduction"""
        single_deduction = self.config.get_federal_standard_deduction(FilingStatus.SINGLE)
        mfj_deduction = self.config.get_federal_standard_deduction(FilingStatus.MARRIED_FILING_JOINTLY)

        self.assertEqual(single_deduction, 13850)
        self.assertEqual(mfj_deduction, 27700)

    def test_get_federal_tax_brackets(self):
        """Test getting federal tax brackets"""
        single_brackets = self.config.get_federal_tax_brackets(FilingStatus.SINGLE)

        self.assertIsInstance(single_brackets, list)
        self.assertEqual(len(single_brackets), 7)
        self.assertEqual(single_brackets[0], [0, 10275, 10])  # First bracket
        self.assertEqual(single_brackets[-1][2], 37)  # Highest rate

    def test_get_job_401k_contrib_limit(self):
        """Test getting 401k contribution limits"""
        # Under 50
        limit_under_50 = self.config.get_job_401k_contrib_limit(40)
        self.assertEqual(limit_under_50, 20500)

        # 50 and over (catch-up)
        limit_over_50 = self.config.get_job_401k_contrib_limit(55)
        self.assertEqual(limit_over_50, 27000)  # 20500 + 6500

    def test_get_max_tax_rate(self):
        """Test getting maximum tax rate"""
        max_rate = self.config.get_max_tax_rate(FilingStatus.SINGLE)
        self.assertEqual(max_rate, 37.0)

    def test_scenario_override(self):
        """Test scenario-specific configuration overrides"""
        # Test high tax scenario
        high_tax_overrides = {
            'tax': {
                'federal': {
                    'tax_brackets': {
                        'single': [
                            [0, 10000, 15],  # Higher rates
                            [10001, 50000, 25],
                            [50001, float('inf'), 45]
                        ]
                    }
                },
                'state': {
                    'tax_rate': 10.0  # Higher state tax
                }
            }
        }

        self.config.apply_scenario('high_tax', high_tax_overrides)

        # Check that overrides are applied
        self.assertEqual(self.config.get('tax.state.tax_rate'), 10.0)
        brackets = self.config.get_federal_tax_brackets(FilingStatus.SINGLE)
        self.assertEqual(brackets[0][2], 15)  # Higher first bracket rate
        self.assertEqual(self.config.get_max_tax_rate(FilingStatus.SINGLE), 45.0)


class TestGlobalConfigManager(unittest.TestCase):
    """Test global configuration manager"""

    def test_singleton_behavior(self):
        """Test that GlobalConfigManager is a singleton"""
        config1 = GlobalConfigManager()
        config2 = GlobalConfigManager()

        self.assertIs(config1, config2)

    def test_financial_config_access(self):
        """Test accessing financial configuration"""
        config_manager = GlobalConfigManager()

        self.assertIsInstance(config_manager.financial, FinancialConfig)

        # Test that we can get values through the manager
        rate = config_manager.financial.get('tax.state.tax_rate')
        self.assertEqual(rate, 6.0)

    def test_apply_scenario(self):
        """Test applying scenarios through global manager"""
        config_manager = GlobalConfigManager()

        # Apply a scenario
        recession_overrides = {
            'accounts': {
                'bank': {
                    'default_interest_rate': 0.1  # Lower interest rates
                },
                'brokerage': {
                    'default_growth_rate': 3.0  # Lower growth expectations
                }
            }
        }

        config_manager.apply_scenario('recession', recession_overrides)

        self.assertEqual(config_manager.get_current_scenario(), 'recession')
        self.assertEqual(config_manager.financial.get('accounts.bank.default_interest_rate'), 0.1)
        self.assertEqual(config_manager.financial.get('accounts.brokerage.default_growth_rate'), 3.0)

    def test_reset_to_defaults(self):
        """Test resetting to default values"""
        config_manager = GlobalConfigManager()

        # Apply overrides - need to use nested structure
        config_manager.apply_scenario('test', {'tax': {'state': {'tax_rate': 99.0}}})
        self.assertEqual(config_manager.financial.get('tax.state.tax_rate'), 99.0)

        # Reset to defaults
        config_manager.reset_to_defaults()
        self.assertEqual(config_manager.financial.get('tax.state.tax_rate'), 6.0)
        self.assertIsNone(config_manager.get_current_scenario())


class TestConfigurationIntegration(unittest.TestCase):
    """Test integration with existing code"""

    def test_federal_tax_functions_use_config(self):
        """Test that federal tax functions use configuration values"""
        from ..tax.federal import get_federal_standard_deduction, get_federal_tax_brackets

        # These should return the same values as direct config access
        deduction = get_federal_standard_deduction(FilingStatus.SINGLE)
        self.assertEqual(deduction, 13850)

        brackets = get_federal_tax_brackets(FilingStatus.SINGLE)
        self.assertIsInstance(brackets, list)
        self.assertEqual(len(brackets), 7)

    def test_limits_functions_use_config(self):
        """Test that limits functions use configuration values"""
        from ..limits import job_401k_contrib_limit, federal_retirement_age

        # Test 401k limits
        self.assertEqual(job_401k_contrib_limit(40), 20500)
        self.assertEqual(job_401k_contrib_limit(55), 27000)

        # Test retirement age
        self.assertEqual(federal_retirement_age(), 59.5)


if __name__ == '__main__':
    unittest.main()
