# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest

from ..config.base_config import ConfigurationManager, ScenarioConfig
from ..config.config_manager import GlobalConfigManager
from ..config.financial_config import FinancialConfig
from ..tax.federal import FilingStatus


class TestConfigurationManager(unittest.TestCase):
    """Test the base configuration manager"""

    def setUp(self):
        class TestConfig(ConfigurationManager):
            def _initialize_defaults(self):
                self._config_data = {"test": {"value1": 100, "value2": "hello"}, "simple": 42}

        self.config = TestConfig()

    def test_get_simple_value(self):
        """Test getting a simple configuration value"""
        self.assertEqual(self.config.get("simple"), 42)

    def test_get_nested_value(self):
        """Test getting a nested configuration value"""
        self.assertEqual(self.config.get("test.value1"), 100)
        self.assertEqual(self.config.get("test.value2"), "hello")

    def test_get_nonexistent_value(self):
        """Test getting a non-existent value returns default"""
        self.assertIsNone(self.config.get("nonexistent"))
        self.assertEqual(self.config.get("nonexistent", "default"), "default")

    def test_set_simple_value(self):
        """Test setting a simple configuration value"""
        self.config.set("new_value", 123)
        self.assertEqual(self.config.get("new_value"), 123)

    def test_set_nested_value(self):
        """Test setting a nested configuration value"""
        self.config.set("nested.new.value", 456)
        self.assertEqual(self.config.get("nested.new.value"), 456)

    def test_update_config(self):
        """Test updating configuration with a dictionary"""
        updates = {"test": {"value3": "new"}, "another": {"nested": {"deep": 789}}}
        self.config.update(updates)

        self.assertEqual(self.config.get("test.value1"), 100)  # Should still exist
        self.assertEqual(self.config.get("test.value3"), "new")  # Should be added
        self.assertEqual(self.config.get("another.nested.deep"), 789)

    def test_reset_to_defaults(self):
        """Test resetting configuration to defaults"""
        self.config.set("new_value", 999)
        self.assertEqual(self.config.get("new_value"), 999)

        self.config.reset_to_defaults()
        self.assertIsNone(self.config.get("new_value"))
        self.assertEqual(self.config.get("simple"), 42)  # Default should be restored


class TestScenarioConfig(unittest.TestCase):
    """Test scenario-specific configuration"""

    def setUp(self):
        class TestScenarioConfig(ScenarioConfig):
            def _initialize_defaults(self):
                self._config_data = {"base_value": 100, "scenario_value": 200}

        self.config = TestScenarioConfig()

    def test_apply_scenario(self):
        """Test applying scenario-specific overrides"""
        overrides = {"scenario_value": 300, "new_value": 400}

        self.config.apply_scenario("test_scenario", overrides)

        self.assertEqual(self.config.scenario, "test_scenario")
        self.assertEqual(self.config.get("base_value"), 100)  # Unchanged
        self.assertEqual(self.config.get("scenario_value"), 300)  # Overridden
        self.assertEqual(self.config.get("new_value"), 400)  # Added


class TestFinancialConfig(unittest.TestCase):
    """Test financial configuration"""

    def setUp(self):
        self.config = FinancialConfig()

    def test_default_values(self):
        """Test that default financial values are properly initialized"""
        # Test tax values
        self.assertEqual(self.config.get("tax.state.tax_rate"), 6.0)
        self.assertEqual(self.config.get("tax.fica.social_security_rate"), 6.2)

        # Test retirement values
        self.assertEqual(self.config.get("retirement.federal_retirement_age"), 59.5)
        self.assertEqual(self.config.get("retirement.ira.contribution_limit"), 7500)

        # Test account values
        self.assertEqual(self.config.get("accounts.bank.compound_rate"), 12)

    def test_get_federal_standard_deduction(self):
        """Test getting federal standard deduction"""
        single_deduction = self.config.get_federal_standard_deduction(FilingStatus.SINGLE)
        mfj_deduction = self.config.get_federal_standard_deduction(FilingStatus.MARRIED_FILING_JOINTLY)

        self.assertEqual(single_deduction, 16100)
        self.assertEqual(mfj_deduction, 32200)

    def test_get_federal_tax_brackets(self):
        """Test getting federal tax brackets"""
        single_brackets = self.config.get_federal_tax_brackets(FilingStatus.SINGLE)

        self.assertIsInstance(single_brackets, list)
        self.assertEqual(len(single_brackets), 7)
        self.assertEqual(single_brackets[0], [0, 12400, 10])  # First bracket
        self.assertEqual(single_brackets[-1][2], 37)  # Highest rate

    def test_get_job_401k_contrib_limit(self):
        """Test getting 401k contribution limits"""
        # Under 50
        limit_under_50 = self.config.get_job_401k_contrib_limit(40)
        self.assertEqual(limit_under_50, 24500)

        # 50 and over (catch-up)
        limit_over_50 = self.config.get_job_401k_contrib_limit(55)
        self.assertEqual(limit_over_50, 32500)  # 24500 + 8000

    def test_get_max_tax_rate(self):
        """Test getting maximum tax rate"""
        max_rate = self.config.get_max_tax_rate(FilingStatus.SINGLE)
        self.assertEqual(max_rate, 37.0)

    def test_scenario_override(self):
        """Test scenario-specific configuration overrides"""
        # Test high tax scenario
        high_tax_overrides = {
            "tax": {
                "federal": {
                    "tax_brackets": {
                        "single": [
                            [0, 10000, 15],  # Higher rates
                            [10001, 50000, 25],
                            [50001, float("inf"), 45],
                        ]
                    }
                },
                "state": {
                    "tax_rate": 10.0  # Higher state tax
                },
            }
        }

        self.config.apply_scenario("high_tax", high_tax_overrides)

        # Check that overrides are applied
        self.assertEqual(self.config.get("tax.state.tax_rate"), 10.0)
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
        rate = config_manager.financial.get("tax.state.tax_rate")
        self.assertEqual(rate, 6.0)

    def test_apply_scenario(self):
        """Test applying scenarios through global manager"""
        config_manager = GlobalConfigManager()

        # Apply a scenario
        recession_overrides = {
            "accounts": {
                "bank": {
                    "default_interest_rate": 0.1  # Lower interest rates
                },
                "brokerage": {
                    "default_growth_rate": 3.0  # Lower growth expectations
                },
            }
        }

        config_manager.apply_scenario("recession", recession_overrides)

        self.assertEqual(config_manager.get_current_scenario(), "recession")
        self.assertEqual(config_manager.financial.get("accounts.bank.default_interest_rate"), 0.1)
        self.assertEqual(config_manager.financial.get("accounts.brokerage.default_growth_rate"), 3.0)

    def test_reset_to_defaults(self):
        """Test resetting to default values"""
        config_manager = GlobalConfigManager()

        # Apply overrides - need to use nested structure
        config_manager.apply_scenario("test", {"tax": {"state": {"tax_rate": 99.0}}})
        self.assertEqual(config_manager.financial.get("tax.state.tax_rate"), 99.0)

        # Reset to defaults
        config_manager.reset_to_defaults()
        self.assertEqual(config_manager.financial.get("tax.state.tax_rate"), 6.0)
        self.assertIsNone(config_manager.get_current_scenario())


class TestConfigurationIntegration(unittest.TestCase):
    """Test integration with existing code"""

    def test_federal_tax_functions_use_config(self):
        """Test that federal tax functions use configuration values"""
        from ..tax.federal import get_federal_standard_deduction, get_federal_tax_brackets

        # These should return the same values as direct config access
        deduction = get_federal_standard_deduction(FilingStatus.SINGLE)
        self.assertEqual(deduction, 16100)

        brackets = get_federal_tax_brackets(FilingStatus.SINGLE)
        self.assertIsInstance(brackets, list)
        self.assertEqual(len(brackets), 7)

    def test_limits_functions_use_config(self):
        """Test that limits functions use configuration values"""
        from ..limits import federal_retirement_age, job_401k_contrib_limit

        # Test 401k limits
        self.assertEqual(job_401k_contrib_limit(40), 24500)
        self.assertEqual(job_401k_contrib_limit(55), 32500)

        # Test retirement age
        self.assertEqual(federal_retirement_age(), 59.5)


class TestPerModelConfig(unittest.TestCase):
    """Two models with different scenarios coexist in one process."""

    def test_scenarios_coexist_with_different_tax_results(self):
        from ..model import LifeModel
        from ..tax.tax import get_income_taxes_due

        model_high = LifeModel(scenario="high_tax")
        model_default = LifeModel()

        # The two models hold independent configs.
        self.assertEqual(model_high.config.tax.state.tax_rate, 10.0)
        self.assertEqual(model_default.config.tax.state.tax_rate, 6.0)

        taxes_high = get_income_taxes_due(100000, 0, FilingStatus.SINGLE, model_high.config)
        taxes_default = get_income_taxes_due(100000, 0, FilingStatus.SINGLE, model_default.config)
        self.assertGreater(taxes_high.total, taxes_default.total)

    def test_explicit_config_object(self):
        from ..model import LifeModel

        cfg = FinancialConfig()
        cfg.apply_scenario("low_tax", {"tax": {"state": {"tax_rate": 1.0}}})
        model = LifeModel(config=cfg)
        self.assertEqual(model.config.tax.state.tax_rate, 1.0)
        # A default model is unaffected.
        self.assertEqual(LifeModel().config.tax.state.tax_rate, 6.0)


class TestScenarioValidation(unittest.TestCase):
    """Scenario overrides are re-validated through Pydantic."""

    def test_misspelled_key_raises(self):
        config = FinancialConfig()
        with self.assertRaises(ValueError):
            config.apply_scenario("bad", {"tax": {"state": {"tax_rate_typo": 5.0}}})

    def test_out_of_range_value_raises(self):
        config = FinancialConfig()
        with self.assertRaises(ValueError):
            config.apply_scenario("bad", {"tax": {"state": {"tax_rate": 150.0}}})

    def test_all_packaged_scenarios_map_to_schema_fields(self):
        from ..config.models import FinancialConfigModel
        from ..config.scenarios import get_scenario, list_scenarios

        for name in list_scenarios():
            overrides = get_scenario(name)
            # Applying re-validates through Pydantic (extra='forbid'), so an unknown
            # key would raise here.
            FinancialConfig().apply_scenario(name, overrides)
            # And every key path corresponds to a validated schema field.
            self._assert_keys_in_model(overrides, FinancialConfigModel, name)

    def _assert_keys_in_model(self, data, model_cls, scenario):
        from pydantic import BaseModel

        for key, value in data.items():
            self.assertIn(
                key, model_cls.model_fields, msg=f"Scenario '{scenario}' key '{key}' not in {model_cls.__name__}"
            )
            annotation = model_cls.model_fields[key].annotation
            if isinstance(value, dict) and isinstance(annotation, type) and issubclass(annotation, BaseModel):
                self._assert_keys_in_model(value, annotation, scenario)


class TestYearIndexedTax(unittest.TestCase):
    """Year-indexed tax parameters and the projection rule."""

    def setUp(self):
        self.config = FinancialConfig()

    def test_published_years(self):
        self.assertEqual(self.config.tax_year(2022).standard_deduction.single, 12950)
        self.assertEqual(self.config.tax_year(2026).standard_deduction.single, 16100)
        self.assertEqual(self.config.tax_year(2026).ss_wage_base, 184500)

    def test_future_year_frozen_at_latest(self):
        projected = self.config.tax_year(2035)
        self.assertEqual(projected.year, 2035)
        self.assertEqual(projected.standard_deduction.single, 16100)  # frozen at 2026

    def test_prior_year_uses_earliest(self):
        projected = self.config.tax_year(2000)
        self.assertEqual(projected.year, 2000)
        self.assertEqual(projected.standard_deduction.single, 12950)  # earliest (2022)


class TestPlan529ConfigFlows(unittest.TestCase):
    """Regression: the accounts.plan_529 block is validated and reaches consumers."""

    def test_plan_529_defaults_present(self):
        config = FinancialConfig()
        self.assertEqual(config.accounts.plan_529.annual_contribution_limit, 19000)
        self.assertEqual(config.accounts.plan_529.qualified_expense_penalty, 10.0)

    def test_plan_529_scenario_override_flows(self):
        config = FinancialConfig()
        config.apply_scenario("edu", {"accounts": {"plan_529": {"annual_contribution_limit": 25000}}})
        self.assertEqual(config.accounts.plan_529.annual_contribution_limit, 25000)


class TestNoImportTimeFileIO(unittest.TestCase):
    """Importing life_model must not read the config YAML."""

    def test_no_config_load_on_import(self):
        import subprocess
        import sys

        code = (
            "import life_model\n"
            "from life_model.config.config_manager import config\n"
            "assert config._financial_config is None, 'config loaded at import time'\n"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
